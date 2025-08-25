"""
Admin Validator Agent - Validates and auto-creates Jira custom fields
Migrated from monolithic script with enhancements
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
    """AI agent that validates admin requests and can auto-create approved fields"""
    
    def __init__(self, config: Config):
        self.config = config

        # ✅ New auth check: Cloud Basic OR Server/DC Bearer
        has_jira_creds = bool(
            (config.jira_email and config.jira_api_token) or config.jira_bearer_token
        )
        self.jira = JiraAPI(config) if has_jira_creds else None
        
        # System prompt for AI validation
        self.system_prompt = """You are a Jira admin who validates field requests and can auto-create approved fields.

INPUT: Field creation request with duplicate check results and extracted details
OUTPUT: Validation decision with optional auto-creation

You check for:
- Real duplicate conflicts (based on actual Jira data provided)
- Naming convention compliance 
- Missing required information for implementation
- Security or compliance concerns

When request is APPROVED and has all needed info, you can auto-create the field.
When REJECTED or NEEDS_INFO, explain what's missing.

Format: Return ONLY valid JSON:
{
  "status": "approved|rejected|needs_info",
  "auto_create": true|false,
  "field_name": "Cleaned up field name",
  "field_type": "select|text|textarea|number|date|multiselect",
  "field_description": "Professional description for the field",
  "field_options": ["Option1", "Option2", "Option3"],
  "issues": ["List of problems found"],
  "suggestions": ["Alternative approaches or improvements"],
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
                logger.info(f"🎚️  Options: {field_details.get('field_options', [])}")
            else:
                logger.warning("❌ Could not extract field name from request")
            
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
            
            # Step 3: Get AI validation
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
                comment_text = self._build_comment(ai_result, field_creation_result, duplicate_check)
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
        
        result = f"""REAL DUPLICATE CHECK RESULTS - THIS IS ACTUAL DATA FROM YOUR JIRA INSTANCE:
✅ Checked {total_checked} existing custom fields in Jira
🎯 Exact duplicates found: {len(duplicates)}
🔍 Similar fields found: {len(similar)}

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
            result += "✅ CONFIRMED: No duplicates or similar fields found - field name appears unique!\n"
            result += "✅ Safe to proceed with field creation.\n\n"
        
        return result
    
    def _build_validation_context(self, summary: str, description: str, 
                                field_details: Dict, duplicate_results: str) -> str:
        """Build context for AI validation"""
        return f"""ADMIN REQUEST ANALYSIS:
Request Summary: {summary}
Request Description: {description}

EXTRACTED FIELD DETAILS:
Field Name: {field_details.get('field_name', 'Could not extract')}
Field Type: {field_details.get('field_type', 'unknown')}
Field Options: {field_details.get('field_options', [])}

{duplicate_results}

CRITICAL INSTRUCTIONS:
- Use ONLY the real duplicate check results above
- Do NOT assume or guess about duplicates
- If the duplicate check shows "No duplicates found", then there are NO duplicates
- Only flag duplicate issues if actual duplicates were found in the real data above
- If no real duplicates found and request has sufficient detail, APPROVE it

TASK: Validate this admin request using ONLY the real duplicate check results above. 
If APPROVED and you have all needed info, set auto_create=true to create the field automatically.
"""
    
    def _auto_create_field(self, ai_result: Dict) -> Optional[Dict]:
        """Auto-create the custom field based on AI validation"""
        try:
            return self.jira.create_custom_field(
                field_name=ai_result["field_name"],
                field_type=ai_result.get("field_type", "text"),
                description=ai_result.get("field_description", f"Auto-created: {ai_result['field_name']}"),
                options=ai_result.get("field_options", []),
            )
        except Exception as e:
            logger.error(f"❌ Field creation error: {e}")
            return {"error": str(e)}
    
    def _build_comment(self, ai_result: Dict, field_creation_result: Optional[Dict], 
                      duplicate_check: Dict) -> str:
        """Build comprehensive comment for Jira ticket"""
        status_emoji = {
            "approved": "✅",
            "needs_info": "⚠️",
            "rejected": "❌"
        }.get(ai_result.get("status", ""), "❓")
        
        comment_text = f"{ai_result.get('marker', '<!--admin-validation-->')}\n\n"
        comment_text += f"**🤖 AI Admin Validation {status_emoji}**\n\n"
        comment_text += f"**Status:** {ai_result.get('status', 'unknown').title()}\n\n"
        
        # Add duplicate check summary
        if duplicate_check and "error" not in duplicate_check:
            total_checked = duplicate_check.get("total_checked", 0)
            duplicates_count = len(duplicate_check.get("duplicates", []))
            similar_count = len(duplicate_check.get("similar", []))
            comment_text += f"**Duplicate Check:** Scanned {total_checked} existing fields - "
            comment_text += f"{duplicates_count} exact, {similar_count} similar matches\n\n"
        
        # Add field creation result
        if field_creation_result:
            if "error" not in field_creation_result:
                field_id = field_creation_result["field"]["id"]
                comment_text += f"**✅ FIELD CREATED AUTOMATICALLY!**\n"
                comment_text += f"Field ID: `{field_id}`\n"
                comment_text += f"Field Name: {ai_result.get('field_name')}\n"
                comment_text += f"Field Type: {ai_result.get('field_type', 'text')}\n"
                if ai_result.get('field_options'):
                    comment_text += f"Options: {', '.join(ai_result['field_options'])}\n"
                comment_text += f"\n"
            else:
                comment_text += f"**❌ Auto-creation attempted but failed:**\n{field_creation_result['error']}\n\n"
        
        # Add AI comment
        comment_text += ai_result['comment']
        
        # Add issues and suggestions
        if ai_result.get("issues"):
            comment_text += f"\n\n**Issues Found:**\n"
            for issue in ai_result["issues"]:
                comment_text += f"• {issue}\n"
        
        if ai_result.get("suggestions"):
            comment_text += f"\n**Suggestions:**\n"
            for suggestion in ai_result["suggestions"]:
                comment_text += f"• {suggestion}\n"
        
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
