"""
Generic Jira API Executor - Let the LLM call any API it knows about
"""

from typing import Dict, List, Optional, Any
import json
import requests
import copy
from datetime import datetime

from config import Config
from ai.ollama_client import call_ollama
from utils.logger import get_logger

logger = get_logger(__name__)

class GenericJiraAPI:
    """Generic Jira API that can execute any REST call the LLM requests"""
    
    def __init__(self, config: Config):
        self.base_url = config.jira_base_url.rstrip("/")
        self.session = requests.Session()
        
        if config.jira_email and config.jira_api_token:
            import base64
            credentials = base64.b64encode(f"{config.jira_email}:{config.jira_api_token}".encode()).decode()
            self.session.headers.update({
                "Authorization": f"Basic {credentials}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            })
        elif config.jira_bearer_token:
            self.session.headers.update({
                "Authorization": f"Bearer {config.jira_bearer_token}",
                "Accept": "application/json", 
                "Content-Type": "application/json",
            })
    
    def execute_api_call(self, method: str, endpoint: str, payload: Dict = None, params: Dict = None) -> Dict:
        """Execute arbitrary Jira REST API calls"""
        try:
            # Construct full URL
            if endpoint.startswith('http'):
                url = endpoint
            else:
                url = f"{self.base_url}{endpoint}"
            
            logger.info(f"API Call: {method} {endpoint}")
            if payload:
                logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
            
            # Make the API call
            response = self.session.request(
                method=method.upper(),
                url=url,
                json=payload if payload else None,
                params=params if params else None
            )
            
            logger.info(f"Response: {response.status_code}")
            
            # Return structured response
            try:
                response_data = response.json() if response.text else {}
            except:
                response_data = {"raw_response": response.text}
            
            return {
                "success": response.status_code < 400,
                "status_code": response.status_code,
                "data": response_data,
                "headers": dict(response.headers)
            }
            
        except Exception as e:
            logger.error(f"API call failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }

class UnrestrictedJiraAgent:
    """AI agent with unrestricted access to Jira APIs"""
    
    def __init__(self, config: Config):
        self.config = config
        self.jira = GenericJiraAPI(config)
        
        # System prompt with concrete API examples to prevent reasoning loops
        self.system_prompt = """You are a Jira administrator with access to tested API endpoints. Use ONLY these endpoints:

CUSTOM FIELDS:
- GET /rest/api/3/field (list all fields)
- POST /rest/api/3/field (create custom field)
  Required: {"name": "Field Name", "type": "FIELD_TYPE", "description": "Description"}
  Types: "com.atlassian.jira.plugin.system.customfieldtypes:select" (dropdown)
         "com.atlassian.jira.plugin.system.customfieldtypes:textfield" (text)
         "com.atlassian.jira.plugin.system.customfieldtypes:textarea" (paragraph)

SCREENS:
- GET /rest/api/3/screens (list all screens)
- GET /rest/api/3/screens/{screenId} (get screen details)
- PUT /rest/api/3/screens/{screenId}/addToDefault/{fieldId} (add field to default screen)

FIELD OPTIONS (for select fields):
- GET /rest/api/3/field/{fieldId}/contexts (get field contexts)
- POST /rest/api/3/field/{fieldId}/context/{contextId}/option (add options)
  Body: {"options": [{"value": "Option Name"}]}

WORKFLOWS:
- GET /rest/api/3/workflow (list workflows)

PROJECTS:  
- GET /rest/api/3/project (list projects)

When you receive a request:
1. Understand what needs to be done
2. Plan the API calls in order
3. Use context variables {{step_N_id}} for values from previous steps

Return this EXACT JSON structure:
{
  "understanding": "Clear description of what you understood",
  "plan": [
    {
      "step": 1,
      "description": "What this step accomplishes",
      "api_call": {
        "method": "POST",
        "endpoint": "/rest/api/3/field",
        "payload": {"name": "Priority Level", "type": "com.atlassian.jira.plugin.system.customfieldtypes:select", "description": "Priority classification"}
      }
    },
    {
      "step": 2,
      "description": "Add options to the select field",
      "api_call": {
        "method": "GET",
        "endpoint": "/rest/api/3/field/{{step_1_id}}/contexts"
      }
    }
  ],
  "safety_checks": ["Any warnings or confirmations needed"],
  "expected_outcome": "What will be accomplished"
}

Focus on business logic. Don't question the API endpoints - they work. Keep plans under 5 steps when possible."""

    def process(self, issue_data: Dict) -> Dict:
        """Process any admin request with full API access"""
        issue_key = issue_data["key"]
        fields = issue_data.get("fields") or {}
        
        summary = fields.get("summary") or ""
        description = self._extract_description_text(fields.get("description"))
        full_request = f"{summary}\n\n{description}".strip()
        
        logger.info(f"Processing unrestricted request: {issue_key}")
        logger.info(f"Request: {full_request[:200]}...")
        
        try:
            # Get the AI's execution plan
            ai_response = call_ollama(full_request, self.system_prompt, self.config)
            
            if not isinstance(ai_response, dict) or "plan" not in ai_response:
                logger.error("AI failed to create valid execution plan")
                return {"error": "AI failed to create execution plan", "raw_response": ai_response}
            
            logger.info(f"AI Understanding: {ai_response.get('understanding')}")
            logger.info(f"Plan has {len(ai_response.get('plan', []))} steps")
            
            # Check for safety concerns
            safety_checks = ai_response.get("safety_checks", [])
            if safety_checks:
                logger.warning(f"Safety checks needed: {safety_checks}")
                # Block DELETE operations without confirmation
                for step in ai_response.get("plan", []):
                    if step.get("api_call", {}).get("method") == "DELETE":
                        return {
                            "status": "blocked",
                            "reason": "DELETE operation requires explicit confirmation",
                            "safety_checks": safety_checks,
                            "plan": ai_response.get("plan")
                        }
            
            # Execute the plan
            execution_results = []
            context = {}  # Store values between steps (like field IDs)
            
            for step in ai_response.get("plan", []):
                step_num = step.get("step", len(execution_results) + 1)
                logger.info(f"Executing step {step_num}: {step.get('description')}")
                
                api_call = step.get("api_call", {})
                
                # Replace any context variables in the API call
                api_call = self._substitute_context_variables(api_call, context)
                
                # Execute the API call
                result = self.jira.execute_api_call(
                    method=api_call.get("method", "GET"),
                    endpoint=api_call.get("endpoint", ""),
                    payload=api_call.get("payload"),
                    params=api_call.get("params")
                )
                
                # Store important values in context for next steps
                if result.get("success"):
                    data = result.get("data", {})
                    if "id" in data:
                        context[f"step_{step_num}_id"] = data["id"]
                    if "key" in data:
                        context[f"step_{step_num}_key"] = data["key"]
                    # Store the whole result for complex references
                    context[f"step_{step_num}_result"] = data
                    
                    logger.info(f"Step {step_num} successful, stored context: {list(context.keys())}")
                
                execution_results.append({
                    "step": step_num,
                    "description": step.get("description"),
                    "success": result.get("success", False),
                    "result": result
                })
                
                # Stop on first failure
                if not result.get("success"):
                    logger.error(f"Step {step_num} failed: {result.get('error')}")
                    break
            
            # Post results comment
            self._post_results_comment(issue_key, ai_response, execution_results)
            
            return {
                "received": True,
                "issueKey": issue_key,
                "ai_understanding": ai_response.get("understanding"),
                "plan": ai_response.get("plan"),
                "execution_results": execution_results,
                "steps_completed": len([r for r in execution_results if r.get("success")]),
                "total_steps": len(ai_response.get("plan", [])),
                "expected_outcome": ai_response.get("expected_outcome"),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error in unrestricted processing: {e}")
            return {"error": str(e), "issueKey": issue_key}
    
    def _substitute_context_variables(self, api_call: Dict, context: Dict) -> Dict:
        """Replace context variables like {{step_1_id}} with actual values"""
        if not context:
            return api_call
            
        result = copy.deepcopy(api_call)
        
        def replace_in_value(value):
            if isinstance(value, str) and "{{" in value and "}}" in value:
                for key, ctx_value in context.items():
                    placeholder = "{{" + key + "}}"
                    if placeholder in value:
                        # Replace the entire string if it's just the placeholder
                        if value.strip() == placeholder:
                            return ctx_value
                        else:
                            value = value.replace(placeholder, str(ctx_value))
                return value
            elif isinstance(value, dict):
                return {k: replace_in_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [replace_in_value(item) for item in value]
            return value
        
        return replace_in_value(result)
    
    def _extract_description_text(self, description_obj: Any) -> str:
        """Extract plain text from Jira description"""
        if not description_obj:
            return ""
        if isinstance(description_obj, str):
            return description_obj
        if isinstance(description_obj, dict):
            text = []
            for block in (description_obj.get("content") or []):
                if block.get("type") == "paragraph":
                    for item in (block.get("content") or []):
                        if item.get("type") == "text":
                            text.append(item.get("text", ""))
            return "".join(text)
        return str(description_obj)
    
    def _post_results_comment(self, issue_key: str, ai_response: Dict, execution_results: List[Dict]):
        """Post a comment showing what was accomplished"""
        try:
            successful_steps = len([r for r in execution_results if r.get("success")])
            total_steps = len(execution_results)
            
            comment = f"Admin request completed: {successful_steps}/{total_steps} steps successful\n\n"
            comment += f"**Understanding:** {ai_response.get('understanding', 'N/A')}\n\n"
            
            for result in execution_results:
                step_num = result.get("step")
                desc = result.get("description")
                success = result.get("success", False)
                
                status = "✅" if success else "❌"
                comment += f"{status} Step {step_num}: {desc}\n"
                
                if not success:
                    error = result.get("result", {}).get("error", "Unknown error")
                    comment += f"   Error: {error}\n"
            
            if ai_response.get("expected_outcome"):
                comment += f"\n**Expected Result:** {ai_response['expected_outcome']}"
            
            # Post the comment
            self.jira.execute_api_call(
                method="POST",
                endpoint=f"/rest/api/3/issue/{issue_key}/comment",
                payload={
                    "body": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": comment}]
                            }
                        ]
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to post results comment: {e}")