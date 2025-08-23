"""
PM Enhancer Agent - Transforms messy tickets into professional user stories
"""

from typing import Dict, Any
import json
from datetime import datetime

from config import Config
from jira.api import JiraAPI
from ai.ollama_client import call_ollama
from utils.logger import get_logger

logger = get_logger(__name__)

class PMEnhancer:
    """AI agent that transforms meeting notes and messy tickets into professional user stories"""
    
    def __init__(self, config: Config):
        self.config = config
        self.jira = JiraAPI(config) if config.jira_token else None
        
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
Format: Return ONLY valid JSON matching this structure:
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
        issue_key = issue_data["key"]
        fields = issue_data["fields"]
        
        logger.info(f"✨ Processing PM enhancement for issue: {issue_key}")
        
        # Extract basic info
        summary = fields.get("summary", "")
        description = self._extract_description_text(fields.get("description"))
        
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
            
            # Get AI enhancement
            ai_result = call_ollama(enhancement_context, self.system_prompt, self.config)
            
            if "error" in ai_result:
                logger.error(f"❌ AI enhancement failed: {ai_result['error']}")
                return self._create_error_response(issue_key, ai_result["error"])
            
            logger.info(f"✅ AI enhancement complete!")
            logger.info(f"📋 New summary: {ai_result.get('new_summary', 'N/A')[:50]}...")
            
            # Apply enhancements to Jira if configured
            update_applied = False
            if self.jira and ai_result.get("new_summary"):
                update_result = self._apply_enhancements(issue_key, ai_result)
                update_applied = update_result.get("success", False)
                
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
    
    def _extract_description_text(self, description_obj: Any) -> str:
        """Extract plain text from Jira description object"""
        if not description_obj:
            return ""
        
        if isinstance(description_obj, str):
            return description_obj
        
        if isinstance(description_obj, dict):
            text = ""
            content = description_obj.get("content", [])
            for block in content:
                if block.get("type") == "paragraph":
                    for item in block.get("content", []):
                        if item.get("type") == "text":
                            text += item.get("text", "")
            return text
        
        return str(description_obj)
    
    def _analyze_ticket_health(self, fields: Dict) -> Dict:
        """Analyze ticket health and identify issues"""
        health_issues = []
        suggestions = []
        
        # Check assignee
        if not fields.get("assignee"):
            health_issues.append("No assignee")
            suggestions.append("Assign to appropriate team member")
        
        # Check description quality
        description = self._extract_description_text(fields.get("description"))
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
        priority = fields.get("priority", {}).get("name", "").lower()
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
        
        # Extract additional context
        issue_type = fields.get("issuetype", {}).get("name", "Task")
        project_key = fields.get("project", {}).get("key", "UNKNOWN")
        assignee = fields.get("assignee", {}).get("displayName", "Unassigned")
        
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
            update_fields = {}
            
            # Update summary if provided
            if ai_result.get("new_summary"):
                update_fields["summary"] = ai_result["new_summary"]
            
            # Update description if provided
            if ai_result.get("new_description"):
                # Convert to Atlassian Document Format
                update_fields["description"] = {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": ai_result["new_description"]
                                }
                            ]
                        }
                    ]
                }
                
                # Add acceptance criteria if provided
                if ai_result.get("acceptance_criteria"):
                    update_fields["description"]["content"].extend([
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "\n\nAcceptance Criteria:",
                                    "marks": [{"type": "strong"}]
                                }
                            ]
                        }
                    ])
                    
                    for criterion in ai_result["acceptance_criteria"]:
                        update_fields["description"]["content"].append({
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"• {criterion}"
                                }
                            ]
                        })
            
            # Update labels if provided
            if ai_result.get("labels"):
                update_fields["labels"] = ai_result["labels"]
            
            # Apply updates
            if update_fields:
                return self.jira.update_issue(issue_key, update_fields)
            else:
                return {"success": True, "message": "No updates to apply"}
                
        except Exception as e:
            logger.error(f"❌ Error applying enhancements: {e}")
            return {"error": str(e)}
    
    def _build_enhancement_comment(self, ai_result: Dict, health_info: Dict) -> str:
        """Build enhancement comment for Jira ticket"""
        comment_text = f"{ai_result.get('marker', '<!--pm-ai-->')}\n\n"
        comment_text += f"**🤖 AI Enhancement Applied ✨**\n\n"
        comment_text += f"**Health Score Improvement:** {health_info['health_score']}/10\n\n"
        
        # Add what was improved
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
        
        # Add AI comment
        comment_text += ai_result.get('comment', 'Ticket enhanced by AI')
        
        # Add subtasks if suggested
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