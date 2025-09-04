"""
Governance Bot Agent - Maintains Jira hygiene and enforces conventions
"""

from typing import Dict, List, Any
import json
from datetime import datetime, timedelta

from config import Config
from jira.api import JiraAPI
from ai.ollama_client import call_ollama
from utils.logger import get_logger

logger = get_logger(__name__)

class GovernanceBot:
    """AI agent that maintains Jira hygiene and enforces organizational conventions"""
    
    def __init__(self, config: Config):
        self.config = config
        # ✅ Cloud Basic OR Server/DC Bearer
        has_jira_creds = bool(
            (config.jira_email and config.jira_api_token) or config.jira_bearer_token
        )
        self.jira = JiraAPI(config) if has_jira_creds else None
        
        # System prompt for governance
        self.system_prompt = """You maintain Jira hygiene and enforce conventions automatically.

INPUT: JQL search results or specific tickets that need cleanup
OUTPUT: Actions to fix governance violations

You handle:
- Stale tickets (no updates >7 days) - add nudging comments
- Missing required fields (estimates, labels, assignees)  
- Incorrect labeling or component assignments
- Policy violations (naming conventions, workflow states)
- Orphaned or misconfigured items

Be helpful but firm about governance. Explain why standards matter.

Format: Return ONLY valid JSON:
{
  "actions": [
    {"type": "update_issue", "issueKey": "PROJ-123", "fields": {"labels": ["updated-label"]}},
    {"type": "add_comment", "issueKey": "PROJ-123", "comment": "Governance reminder message"}
  ],
  "summary": "What was fixed and why",
  "marker": "<!--governance-bot-->"
}"""
    
    def process(self, issue_data: Dict) -> Dict:
        """Main processing method for governance checks"""
        issue_key = issue_data["key"]
        fields = issue_data["fields"]
        
        logger.info(f"🏛️  Processing governance check for issue: {issue_key}")
        
        try:
            # Analyze governance violations
            violations = self._analyze_governance_violations(fields)
            logger.info(f"📊 Found {len(violations)} governance violations")
            
            if not violations:
                logger.info("✅ No governance violations found")
                return {
                    "received": True,
                    "action": "governance_check",
                    "issueKey": issue_key,
                    "mode_detected": "governance_bot",
                    "violations_found": 0,
                    "actions_taken": 0,
                    "status": "compliant",
                    "timestamp": datetime.now().isoformat()
                }
            
            # Build governance context
            governance_context = self._build_governance_context(issue_key, fields, violations)
            
            # Get AI recommendations
            ai_result = call_ollama(governance_context, self.system_prompt, self.config)
            
            if "error" in ai_result:
                logger.error(f"❌ AI governance analysis failed: {ai_result['error']}")
                return self._create_error_response(issue_key, ai_result["error"])
            
            logger.info(f"✅ AI governance analysis complete!")
            
            # Execute governance actions
            actions_executed = 0
            action_results = []
            
            if self.jira and ai_result.get("actions"):
                for action in ai_result["actions"]:
                    result = self._execute_governance_action(action)
                    action_results.append(result)
                    if result.get("success"):
                        actions_executed += 1
            
            logger.info(f"🔧 Executed {actions_executed}/{len(ai_result.get('actions', []))} governance actions")
            
            # Return comprehensive result
            return {
                "received": True,
                "action": "governance_check",
                "issueKey": issue_key,
                "mode_detected": "governance_bot",
                "violations_found": len(violations),
                "actions_taken": actions_executed,
                "violations": violations,
                "ai_response": ai_result,
                "action_results": action_results,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error processing governance check: {e}")
            return self._create_error_response(issue_key, str(e))
    
    def _analyze_governance_violations(self, fields: Dict) -> List[Dict]:
        """Analyze fields for governance violations"""
        violations = []
        
        # Check for missing assignee
        if not fields.get("assignee"):
            violations.append({
                "type": "missing_assignee",
                "severity": "medium",
                "description": "Ticket has no assignee",
                "recommendation": "Assign to appropriate team member"
            })
        
        # Check for missing labels
        labels = fields.get("labels", [])
        if not labels:
            violations.append({
                "type": "missing_labels",
                "severity": "low",
                "description": "Ticket has no labels",
                "recommendation": "Add categorization labels"
            })
        
        # Check for missing components
        if not fields.get("components"):
            violations.append({
                "type": "missing_components",
                "severity": "medium",
                "description": "Ticket has no components assigned",
                "recommendation": "Tag with relevant component"
            })
        
        # Check for missing description
        description = self._extract_description_text(fields.get("description"))
        if not description or len(description) < 20:
            violations.append({
                "type": "minimal_description",
                "severity": "high",
                "description": "Ticket has minimal or missing description",
                "recommendation": "Add detailed requirements and context"
            })
        
        # Check for missing priority
        priority = fields.get("priority", {}).get("name", "").lower()
        if not priority or priority == "none":
            violations.append({
                "type": "missing_priority",
                "severity": "medium",
                "description": "Ticket has no priority set",
                "recommendation": "Set appropriate priority level"
            })
        
        # Check summary quality
        summary = fields.get("summary", "")
        if len(summary) < 10:
            violations.append({
                "type": "poor_summary",
                "severity": "high",
                "description": "Summary is too short or unclear",
                "recommendation": "Write a clear, descriptive summary"
            })
        
        # Check for vague language in summary
        vague_words = ["fix", "issue", "problem", "bug", "update", "change"]
        if any(word in summary.lower() for word in vague_words) and len(summary) < 30:
            violations.append({
                "type": "vague_summary",
                "severity": "medium",
                "description": "Summary uses vague language",
                "recommendation": "Be more specific about what needs to be done"
            })
        
        return violations
    
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
    
    def _build_governance_context(self, issue_key: str, fields: Dict, violations: List[Dict]) -> str:
        """Build context for AI governance analysis"""
        
        # Extract issue details
        summary = fields.get("summary", "")
        description = self._extract_description_text(fields.get("description"))
        issue_type = fields.get("issuetype", {}).get("name", "Task")
        status = fields.get("status", {}).get("name", "Unknown")
        project_key = fields.get("project", {}).get("key", "UNKNOWN")
        
        # Format violations
        violations_text = ""
        for violation in violations:
            violations_text += f"• {violation['type'].upper()}: {violation['description']} (Severity: {violation['severity']})\n"
            violations_text += f"  Recommendation: {violation['recommendation']}\n\n"
        
        context = f"""GOVERNANCE ANALYSIS:
Issue: {issue_key}
Project: {project_key}
Type: {issue_type}
Status: {status}
Summary: {summary}
Description: {description[:200]}...

VIOLATIONS FOUND:
{violations_text}

TASK: Create governance actions to fix these violations. Consider:
1. What fields need to be updated?
2. What reminders or comments should be added?
3. How to educate the team about standards?
4. Prioritize high-severity violations first

Be helpful but firm about maintaining standards. Explain why governance matters for team productivity.
"""
        
        return context
    
    def _execute_governance_action(self, action: Dict) -> Dict:
        """Execute a single governance action"""
        action_type = action.get("type")
        issue_key = action.get("issueKey")
        
        try:
            if action_type == "update_issue":
                fields = action.get("fields", {})
                result = self.jira.update_issue(issue_key, fields)
                if "error" not in result:
                    logger.info(f"✅ Updated {issue_key} with fields: {list(fields.keys())}")
                    return {"success": True, "action": action_type, "issueKey": issue_key}
                else:
                    logger.error(f"❌ Failed to update {issue_key}: {result['error']}")
                    return {"success": False, "action": action_type, "issueKey": issue_key, "error": result["error"]}
            
            elif action_type == "add_comment":
                comment = action.get("comment", "")
                result = self.jira.add_comment(issue_key, comment)
                if "error" not in result:
                    logger.info(f"✅ Added governance comment to {issue_key}")
                    return {"success": True, "action": action_type, "issueKey": issue_key}
                else:
                    logger.error(f"❌ Failed to comment on {issue_key}: {result['error']}")
                    return {"success": False, "action": action_type, "issueKey": issue_key, "error": result["error"]}
            
            else:
                logger.warning(f"⚠️  Unknown action type: {action_type}")
                return {"success": False, "action": action_type, "error": "Unknown action type"}
                
        except Exception as e:
            logger.error(f"❌ Error executing action {action_type}: {e}")
            return {"success": False, "action": action_type, "error": str(e)}
    
    def _create_error_response(self, issue_key: str, error: str) -> Dict:
        """Create standardized error response"""
        return {
            "received": True,
            "action": "governance_check",
            "issueKey": issue_key,
            "mode_detected": "governance_bot",
            "error": error,
            "timestamp": datetime.now().isoformat()
        }
