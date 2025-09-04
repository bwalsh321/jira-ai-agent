"""
PM Enhancer Agent - Transforms messy tickets into professional user stories
"""

from typing import Dict, Any, List, Optional
import json
import re
import logging
from datetime import datetime

from config import Config
from jira.api import JiraAPI
from ai.ollama_client import call_ollama
from utils.logger import get_logger

logger = get_logger(__name__)
log = logging.getLogger(__name__)

# -------------------- Robust parsing helpers --------------------

EXPECTED_KEYS = {
    "new_summary", "new_description", "acceptance_criteria",
    "estimate", "labels", "subtasks", "comment", "marker"
}

def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
    """Return a dict parsed from the last {...} block in text; else None."""
    if not text or not isinstance(text, str):
        return None
    m = re.search(r"\{.*\}\s*$", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def _normalize_ai_result(ai_result: Any) -> Optional[Dict[str, Any]]:
    """
    Accepts whatever call_ollama returned and tries to normalize into the expected dict.
    Supports:
      - dict already containing expected keys
      - dict with 'response'/'text' containing JSON
      - raw string with JSON or prose + JSON
    """
    # already a dict with expected keys
    if isinstance(ai_result, dict):
        if any(k in ai_result for k in EXPECTED_KEYS):
            return ai_result
        txt = ai_result.get("response") or ai_result.get("text") or ai_result.get("message")
        parsed = _extract_json_block(txt) if isinstance(txt, str) else None
        return parsed if isinstance(parsed, dict) else None

    # raw string
    if isinstance(ai_result, str):
        parsed = _extract_json_block(ai_result)
        return parsed if isinstance(parsed, dict) else None

    return None

def _extract_description_text(description_obj: Any) -> str:
    """Extract plain text from Jira description object (ADF-safe)."""
    if not description_obj:
        return ""
    if isinstance(description_obj, str):
        return description_obj
    if isinstance(description_obj, dict):
        text = []
        content = description_obj.get("content", []) or []
        for block in content:
            if block.get("type") == "paragraph":
                for item in (block.get("content") or []):
                    if item.get("type") == "text":
                        text.append(item.get("text", ""))
        return "".join(text)
    return str(description_obj)

# -------------------- Agent --------------------

class PMEnhancer:
    """AI agent that transforms meeting notes and messy ticket descriptions into professional user stories"""

    def __init__(self, config: Config):
        self.config = config
        # ✅ Cloud Basic OR Server/DC Bearer
        has_jira_creds = bool(
            (config.jira_email and config.jira_api_token) or config.jira_bearer_token
        )
        self.jira = JiraAPI(config) if has_jira_creds else None

        # System prompt for PM enhancement
        self.system_prompt = """You transform meeting notes, brain dumps, and messy ticket descriptions into professional Jira stories.

INPUT: Raw meeting transcripts, scattered notes, or unclear requirements
OUTPUT: Clean JSON with proper ticket structure

You excel at:
- Extracting actionable requirements from rambling meeting discussions  
- Breaking complex ideas into clear, implementable user stories
- Adding missing context that dev teams need (technical details, edge cases)
- Creating realistic acceptance criteria from vague requirements
- Suggesting story point estimates based on complexity
- Identifying when something should be split into multiple tickets

CRITICAL: Never invent features not mentioned. If key info is missing, note it in comments.
CRITICAL: Return ONLY one valid JSON object matching this structure. No prose, no Markdown, no code fences.
{
  "new_summary": "Clear, action-oriented summary",
  "new_description": "Professional description with context and technical details", 
  "acceptance_criteria": ["Given X when Y then Z", "Given A when B then C"],
  "estimate": 5.0,
  "labels": ["backend", "api"],
  "subtasks": [{"summary": "Task name", "description": "Detailed task description"}],
  "comment": "What I improved and any questions for the team",
  "marker": "<!--pm-ai-->"
}"""

    def process(self, issue_data: Dict) -> Dict:
        """Main processing method for PM enhancement requests"""
        issue_key = issue_data.get("key", "UNKNOWN")
        fields = issue_data.get("fields") or {}

        logger.info(f"✨ Processing PM enhancement for issue: {issue_key}")

        # Extract basic info
        summary = fields.get("summary") or ""
        description = _extract_description_text(fields.get("description"))

        logger.info(f"📝 Original summary: {summary}")
        logger.info(f"📄 Description length: {len(description)} characters")

        try:
            # Analyze ticket health first
            health_info = self._analyze_ticket_health(fields)
            logger.info(f"📊 Ticket health score: {health_info['health_score']}/10")

            # Build enhancement context
            enhancement_context = self._build_enhancement_context(
                summary, description, health_info, fields
            )

            # Get AI enhancement (robust handling)
            raw_ai = call_ollama(enhancement_context, self.system_prompt, self.config)

            if raw_ai is None:
                logger.error("❌ AI enhancement failed: model returned None")
                return self._create_error_response(issue_key, "Model returned no output")

            if isinstance(raw_ai, Dict) and "error" in raw_ai:
                logger.error(f"❌ AI enhancement failed: {raw_ai['error']}")
                return self._create_error_response(issue_key, raw_ai["error"])

            ai_result = _normalize_ai_result(raw_ai)
            if not isinstance(ai_result, dict):
                # Don’t crash; leave a friendly comment and exit cleanly
                logger.error("❌ AI enhancement parse failed: could not extract JSON spec")
                if self.jira:
                    try:
                        self.jira.add_comment(
                            issue_key,
                            "<!--pm-ai-->\n\n**🤖 PM Enhancer Needs Info**\n\n"
                            "I couldn't parse a valid JSON enhancement from the model output. "
                            "Please re-run or provide more details (e.g., acceptance criteria, labels, components)."
                        )
                    except Exception:
                        pass
                return self._create_error_response(issue_key, "AI output not parseable as JSON")

            logger.info("✅ AI enhancement complete!")
            logger.info(f"📋 New summary: {(ai_result.get('new_summary') or 'N/A')[:50]}...")

            # Apply enhancements to Jira if configured
            update_applied = False
            if self.jira and ai_result.get("new_summary"):
                update_result = self._apply_enhancements(issue_key, ai_result)
                update_applied = bool(update_result.get("success"))
                if update_applied:
                    logger.info("✅ Successfully applied enhancements to Jira!")
                else:
                    logger.error(f"❌ Failed to apply enhancements: {update_result.get('error')}")

            # Post enhancement comment
            comment_posted = False
            if self.jira and ai_result.get("comment"):
                comment_text = self._build_enhancement_comment(ai_result, health_info)
                comment_result = self.jira.add_comment(issue_key, comment_text)
                if "error" not in comment_result:
                    logger.info("✅ Successfully posted enhancement comment!")
                    comment_posted = True
                else:
                    logger.error(f"❌ Failed to post comment: {comment_result['error']}")

            # Return comprehensive result
            return {
                "received": True,
                "action": "pm_enhancement",
                "issueKey": issue_key,
                "mode_detected": "pm_enhancer",
                "health_score": health_info["health_score"],
                "enhancements_applied": update_applied,
                "comment_posted": comment_posted,
                "improvements": self._summarize_improvements(ai_result),
                "ai_response": ai_result,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"❌ Error processing PM enhancement: {e}")
            return self._create_error_response(issue_key, str(e))

    # -------------------- internals (unchanged logic) --------------------

    def _analyze_ticket_health(self, fields: Dict) -> Dict:
        """Analyze ticket health and identify issues"""
        health_issues = []
        suggestions = []

        # Check assignee
        if not fields.get("assignee"):
            health_issues.append("No assignee")
            suggestions.append("Assign to appropriate team member")

        # Check description quality
        description = _extract_description_text(fields.get("description"))
        if not description or len(description) < 50:
            health_issues.append("Missing or minimal description")
            suggestions.append("Add detailed requirements and context")

        # Check components
        if not fields.get("components"):
            health_issues.append("No components assigned")
            suggestions.append("Tag with relevant component")

        # Check labels
        if not fields.get("labels"):
            health_issues.append("No labels")
            suggestions.append("Add categorization labels")

        # Check for acceptance criteria
        if description and "acceptance criteria" not in description.lower():
            health_issues.append("No acceptance criteria")
            suggestions.append("Define clear acceptance criteria")

        # Check priority
        priority = (fields.get("priority") or {}).get("name", "").lower()
        if not priority or priority == "none":
            health_issues.append("No priority set")
            suggestions.append("Set appropriate priority level")

        return {
            "issues": health_issues,
            "suggestions": suggestions,
            "health_score": max(0, 10 - len(health_issues) * 1.5)
        }

    def _build_enhancement_context(self, summary: str, description: str,
                                   health_info: Dict, fields: Dict) -> str:
        """Build context for AI enhancement"""
        issue_type = (fields.get("issuetype") or {}).get("name", "Task")
        project_key = (fields.get("project") or {}).get("key", "UNKNOWN")
        assignee = (fields.get("assignee") or {}).get("displayName", "Unassigned")

        context = f"""TICKET ENHANCEMENT REQUEST:
Project: {project_key}
Issue Type: {issue_type}
Assignee: {assignee}

CURRENT CONTENT:
Summary: {summary}
Description: {description}

HEALTH ANALYSIS:
Health Score: {health_info['health_score']}/10
Issues Found: {', '.join(health_info['issues']) if health_info['issues'] else 'None'}
Suggestions: {', '.join(health_info['suggestions']) if health_info['suggestions'] else 'None'}

TASK: Transform this into a professional, actionable user story with:
1. Clear, specific summary that describes the user goal
2. Detailed description with context and technical requirements
3. Realistic acceptance criteria in Given/When/Then format
4. Appropriate story point estimate (1, 2, 3, 5, 8, 13, 21)
5. Relevant labels for categorization
6. Subtasks if the work should be broken down
7. Comment explaining what you improved

Focus on clarity, actionability, and completeness. If critical information is missing, note it in your comment.
"""
        return context

    def _apply_enhancements(self, issue_key: str, ai_result: Dict) -> Dict:
        """Apply AI enhancements to the Jira ticket"""
        try:
            update_fields: Dict[str, Any] = {}

            # Update summary
            if ai_result.get("new_summary"):
                update_fields["summary"] = ai_result["new_summary"]

            # Update description
            if ai_result.get("new_description"):
                update_fields["description"] = {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": ai_result["new_description"]}]
                        }
                    ]
                }
                # Acceptance criteria
                if ai_result.get("acceptance_criteria"):
                    update_fields["description"]["content"].append({
                        "type": "paragraph",
                        "content": [{
                            "type": "text",
                            "text": "\n\nAcceptance Criteria:",
                            "marks": [{"type": "strong"}]
                        }]
                    })
                    for criterion in ai_result["acceptance_criteria"]:
                        update_fields["description"]["content"].append({
                            "type": "paragraph",
                            "content": [{"type": "text", "text": f"• {criterion}"}]
                        })

            # Labels
            if ai_result.get("labels"):
                update_fields["labels"] = ai_result["labels"]

            if update_fields:
                return self.jira.update_issue(issue_key, update_fields)
            return {"success": True, "message": "No updates to apply"}

        except Exception as e:
            logger.error(f"❌ Error applying enhancements: {e}")
            return {"error": str(e)}

    def _build_enhancement_comment(self, ai_result: Dict, health_info: Dict) -> str:
        """Build enhancement comment for Jira ticket"""
        comment_text = f"{ai_result.get('marker', '<!--pm-ai-->')}\n\n"
        comment_text += f"**🤖 AI Enhancement Applied ✨**\n\n"
        comment_text += f"**Health Score Improvement:** {health_info['health_score']}/10\n\n"

        # Improvements
        improvements = []
        if ai_result.get("new_summary"):
            improvements.append("Summary rewritten for clarity")
        if ai_result.get("new_description"):
            improvements.append("Description enhanced with context")
        if ai_result.get("acceptance_criteria"):
            improvements.append(f"Added {len(ai_result['acceptance_criteria'])} acceptance criteria")
        if ai_result.get("labels"):
            improvements.append(f"Suggested labels: {', '.join(ai_result['labels'])}")
        if ai_result.get("estimate"):
            improvements.append(f"Estimated effort: {ai_result['estimate']} story points")

        if improvements:
            comment_text += f"**Improvements Made:**\n"
            for improvement in improvements:
                comment_text += f"• {improvement}\n"
            comment_text += "\n"

        comment_text += ai_result.get('comment', 'Ticket enhanced by AI')

        # Subtasks
        if ai_result.get("subtasks"):
            comment_text += f"\n\n**Suggested Subtasks:**\n"
            for subtask in ai_result["subtasks"]:
                comment_text += f"• **{subtask.get('summary', 'Untitled')}**: {subtask.get('description', 'No description')}\n"

        return comment_text

    def _summarize_improvements(self, ai_result: Dict) -> Dict:
        """Summarize what improvements were made"""
        return {
            "summary_updated": bool(ai_result.get("new_summary")),
            "description_enhanced": bool(ai_result.get("new_description")),
            "acceptance_criteria_added": len(ai_result.get("acceptance_criteria", [])),
            "labels_suggested": len(ai_result.get("labels", [])),
            "estimate_provided": bool(ai_result.get("estimate")),
            "subtasks_suggested": len(ai_result.get("subtasks", []))
        }

    def _create_error_response(self, issue_key: str, error: str) -> Dict:
        """Create standardized error response"""
        return {
            "received": True,
            "action": "pm_enhancement",
            "issueKey": issue_key,
            "mode_detected": "pm_enhancer",
            "error": error,
            "timestamp": datetime.now().isoformat()
        }
