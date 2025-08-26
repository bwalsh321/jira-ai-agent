"""
Admin Validator Agent - Updated with more practical validation approach
"""

from typing import Dict, List, Optional, Any
import json
from datetime import datetime

from config import Config
from jira.api import JiraAPI
from jira.field_extractor import extract_field_details
from ai.ollama_client import call_ollama
from utils.logger import get_logger

logger = get_logger(__name__)

class AdminValidator:
    """AI agent that validates admin requests with practical, workflow-aware approach"""
    
    def __init__(self, config: Config):
        self.config = config

        # Cloud Basic OR Server/DC Bearer
        has_jira_creds = bool(
            (config.jira_email and config.jira_api_token) or config.jira_bearer_token
        )
        self.jira = JiraAPI(config) if has_jira_creds else None
        
        # Updated system prompt - more practical and less rigid
        self.system_prompt = """You are a practical Jira admin who validates field requests efficiently and reasonably.

INPUT: Field creation request with duplicate check results and extracted details
OUTPUT: Validation decision with optional auto-creation

VALIDATION APPROACH - Be practical, not pedantic:

APPROVE AND AUTO-CREATE when:
- Simple field requests with clear names and no exact duplicates
- Basic text fields, even without detailed descriptions
- Reasonable field names that follow basic conventions
- Similar fields exist but serve different purposes

FLAG FOR REVIEW (needs_info) only when:
- Select fields requested without any options specified
- Field names are vague/unclear (like "Field1" or "Test")
- Potential security/compliance concerns
- Complex custom field types that need clarification

REJECT only when:
- Exact duplicate field already exists with same purpose
- Field name violates clear naming standards
- Request is genuinely inappropriate or nonsensical

PRACTICAL RULES:
- Missing descriptions are fine - generate reasonable ones
- Don't require extensive documentation for simple requests
- Trust the requester's judgment on field necessity
- Focus on preventing actual problems, not enforcing bureaucracy
- Auto-approve 80% of reasonable requests
- Keep humans in the loop for genuinely complex cases

Format: Return ONLY valid JSON:
{
  "status": "approved|needs_info|rejected",
  "auto_create": true|false,
  "field_name": "Cleaned field name",
  "field_type": "select|text|textarea|number|date|multiselect",
  "field_description": "Professional but concise description (auto-generate if missing)",
  "field_options": ["Option1", "Option2"] or [],
  "reasoning": "Brief explanation of decision",
  "workflow_note": "Any guidance for admin workflow",
  "comment": "Professional explanation for the requester",
  "marker": "<!--admin-validation-->"
}"""
    
    def process(self, issue_data: Dict) -> Dict:
        """Main processing method for admin validation requests"""
        issue_key = issue_data["key"]
        fields = issue_data["fields"]
        
        logger.info(f"🛡️  Processing admin validation for issue: {issue_key}")
        
        # Extract basic info
        summary = fields.get("summary", "")
        description = self._extract_description_text(fields.get("description"))
        
        logger.info(f"📝 Request: {summary}")
        
        try:
            # Step 1: Extract field details from the request
            field_details = extract_field_details(summary, description)
            field_name = field_details.get("field_name", "")
            
            if field_name:
                logger.info(f"✅ Extracted field name: '{field_name}'")
                logger.info(f"📋 Field type: {field_details.get('field_type', 'unknown')}")
                logger.info(f"🎯 Options: {field_details.get('field_options', [])}")
            else:
                logger.warning("⚠️ Could not extract field name from request")
            
            # Step 2: Check for duplicates if we have API access
            duplicate_check_results = ""
            duplicate_check = {}
            
            if self.jira and field_name:
                logger.info(f"🔍 Checking for duplicate field: '{field_name}'")
                duplicate_check = self.jira.check_duplicate_field(field_name)
                duplicate_check_results = self._format_duplicate_results(duplicate_check)
            else:
                duplicate_check_results = "⚠️ Cannot check for duplicates - no API access or field name not detected\n\n"
                logger.warning("⚠️ Skipping duplicate check - no API access or field name")
            
            # Step 3: Get AI validation with practical approach
            validation_context = self._build_validation_context(
                summary, description, field_details, duplicate_check_results
            )
            
            ai_result = call_ollama(validation_context, self.system_prompt, self.config)
            
            if "error" in ai_result:
                logger.error(f"❌ AI validation failed: {ai_result['error']}")
                return self._create_error_response(issue_key, ai_result["error"])
            
            logger.info(f"✅ AI validation complete!")
            logger.info(f"📊 Status: {ai_result.get('status', 'unknown')}")
            logger.info(f"🔧 Auto-create: {ai_result.get('auto_create', False)}")
            logger.info(f"💭 Reasoning: {ai_result.get('reasoning', 'N/A')}")
            
            # Step 4: Auto-create field if approved
            field_creation_result = None
            if (
                self.jira and 
                ai_result.get("status") == "approved" and 
                ai_result.get("auto_create") and
                ai_result.get("field_name")
            ):
                logger.info("🚀 Auto-creating field as requested by AI...")
                field_creation_result = self._auto_create_field(ai_result)
                
                if field_creation_result and "error" not in field_creation_result:
                    logger.info("🎉 Field successfully auto-created!")
                    ai_result["field_created"] = True
                    ai_result["field_id"] = field_creation_result["field"]["id"]
                else:
                    error_msg = field_creation_result.get("error", "Unknown error") if field_creation_result else "Creation failed"
                    logger.error(f"❌ Auto-creation failed: {error_msg}")
                    ai_result["field_created"] = False
                    ai_result["creation_error"] = error_msg
            
            # Step 5: Post comment to Jira
            comment_posted = False
            if self.jira and ai_result.get("comment"):
                comment_text = self._build_practical_comment(ai_result, field_creation_result, duplicate_check)
                comment_result = self.jira.add_comment(issue_key, comment_text)
                
                if "error" not in comment_result:
                    logger.info("✅ Successfully posted admin validation comment!")
                    comment_posted = True
                else:
                    logger.error(f"❌ Failed to post comment: {comment_result['error']}")
            
            # Return comprehensive result
            return {
                "received": True,
                "action": "admin_validation",
                "issueKey": issue_key,
                "mode_detected": "admin_validator",
                "validation_status": ai_result.get("status"),
                "field_name": field_name,
                "field_created": ai_result.get("field_created", False),
                "field_id": ai_result.get("field_id"),
                "comment_posted": comment_posted,
                "duplicates_found": len(duplicate_check.get("duplicates", [])) if duplicate_check else "unknown",
                "ai_response": ai_result,
                "creation_result": field_creation_result,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error processing admin validation: {e}")
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
    
    def _format_duplicate_results(self, duplicate_check: Dict) -> str:
        """Format duplicate check results for AI prompt"""
        if "error" in duplicate_check:
            return f"⚠️ Could not check for duplicates: {duplicate_check['error']}\n\n"
        
        duplicates = duplicate_check.get("duplicates", [])
        similar = duplicate_check.get("similar", [])
        total_checked = duplicate_check.get("total_checked", 0)
        
        logger.info(f"📊 Checked {total_checked} custom fields")
        logger.info(f"🎯 Found {len(duplicates)} exact duplicates")
        logger.info(f"🔍 Found {len(similar)} similar fields")
        
        result = f"""DUPLICATE CHECK RESULTS:
✅ Scanned {total_checked} existing custom fields
🎯 Exact duplicates: {len(duplicates)}
🔍 Similar fields: {len(similar)}

"""
        
        if duplicates:
            result += "EXACT DUPLICATES FOUND:\n"
            for dup in duplicates:
                result += f"• '{dup['name']}' (ID: {dup['id']})\n"
            result += "\n"
        
        if similar:
            result += "SIMILAR FIELDS FOUND:\n"
            for sim in similar:
                result += f"• '{sim['name']}' (ID: {sim['id']})\n"
            result += "\n"
        
        if not duplicates and not similar:
            result += "✅ No duplicates found - field name is unique\n\n"
        
        return result
    
    def _build_validation_context(self, summary: str, description: str, 
                                field_details: Dict, duplicate_results: str) -> str:
        """Build context for AI validation"""
        return f"""ADMIN REQUEST VALIDATION:

REQUEST DETAILS:
Summary: {summary}
Description: {description or 'No additional description provided'}

EXTRACTED FIELD INFO:
Field Name: {field_details.get('field_name', 'Could not extract')}
Field Type: {field_details.get('field_type', 'text')}
Field Options: {field_details.get('field_options', [])}

{duplicate_results}

VALIDATION TASK:
Evaluate this admin request using practical judgment. Focus on preventing real problems, not enforcing bureaucracy.

- Simple text field requests should generally be approved
- Missing descriptions are fine - generate reasonable ones  
- Only flag for review if genuinely unclear or problematic
- Only reject if there are actual conflicts or violations
- Remember: admins prefer efficiency over excessive validation

Be helpful and pragmatic, not rigid.
"""
    
    def _auto_create_field(self, ai_result: Dict) -> Optional[Dict]:
        """Auto-create the custom field based on AI validation"""
        try:
            return self.jira.create_custom_field(
                field_name=ai_result["field_name"],
                field_type=ai_result.get("field_type", "text"),
                description=ai_result.get("field_description", f"Custom field: {ai_result['field_name']}"),
                options=ai_result.get("field_options", []),
            )
        except Exception as e:
            logger.error(f"❌ Field creation error: {e}")
            return {"error": str(e)}
    
    def _build_practical_comment(self, ai_result: Dict, field_creation_result: Optional[Dict], 
                                duplicate_check: Dict) -> str:
        """Build practical, workflow-aware comment"""
        status_emoji = {
            "approved": "✅",
            "needs_info": "⚠️", 
            "rejected": "❌"
        }.get(ai_result.get("status", ""), "❓")
        
        comment_text = f"{ai_result.get('marker', '<!--admin-validation-->')}\n\n"
        comment_text += f"**🤖 AI Admin Validation {status_emoji}**\n\n"
        comment_text += f"**Status:** {ai_result.get('status', 'unknown').replace('_', ' ').title()}\n\n"
        
        # Add duplicate check summary if available
        if duplicate_check and "error" not in duplicate_check:
            total_checked = duplicate_check.get("total_checked", 0)
            duplicates_count = len(duplicate_check.get("duplicates", []))
            similar_count = len(duplicate_check.get("similar", []))
            comment_text += f"**Duplicate Check:** Scanned {total_checked} existing fields - {duplicates_count} exact, {similar_count} similar\n\n"
        
        # Field creation result
        if field_creation_result:
            if "error" not in field_creation_result:
                field_id = field_creation_result["field"]["id"]
                comment_text += f"**✅ FIELD CREATED SUCCESSFULLY**\n"
                comment_text += f"Field ID: `{field_id}`\n"
                comment_text += f"Name: {ai_result.get('field_name')}\n"
                comment_text += f"Type: {ai_result.get('field_type', 'text').title()}\n"
                if ai_result.get('field_options'):
                    comment_text += f"Options: {', '.join(ai_result['field_options'])}\n"
                comment_text += "\nField is now available for use in your project.\n\n"
            else:
                comment_text += f"**❌ Auto-creation failed:** {field_creation_result['error']}\n\n"
        
        # Main response
        comment_text += ai_result.get('comment', 'Request processed by AI admin assistant.')
        
        # Add reasoning if provided
        if ai_result.get("reasoning"):
            comment_text += f"\n\n**Reasoning:** {ai_result['reasoning']}"
        
        # Add workflow guidance if provided
        if ai_result.get("workflow_note"):
            comment_text += f"\n\n**Next Steps:** {ai_result['workflow_note']}"
        
        return comment_text
    
    def _create_error_response(self, issue_key: str, error: str) -> Dict:
        """Create standardized error response"""
        return {
            "received": True,
            "action": "admin_validation",
            "issueKey": issue_key,
            "mode_detected": "admin_validator",
            "error": error,
            "validation_status": "error",
            "timestamp": datetime.now().isoformat()
        }