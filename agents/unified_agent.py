"""
Unified Jira Agent - Combines all your existing agents into one autonomous system
Uses your existing GenericJiraAPI and adds dynamic tool discovery
"""

from typing import Dict, List, Any, Optional
import json
import inspect
from datetime import datetime

from config import Config
from jira.api import JiraAPI
from ai.ollama_client import call_ollama
from utils.logger import get_logger

logger = get_logger(__name__)

class UnifiedJiraAgent:
    """Single agent that can perform any Jira operation by dynamically discovering available tools"""
    
    def __init__(self, config: Config):
        self.config = config
        self.jira_api = JiraAPI(config)
        
        # Always initialize as empty dict first
        self.available_tools = {}
        
        # Discover all available Jira operations
        try:
            discovered_tools = self._discover_jira_tools()
            if discovered_tools and isinstance(discovered_tools, dict):
                self.available_tools = discovered_tools
                logger.info(f"Successfully discovered {len(self.available_tools)} tools")
            else:
                logger.error("Tool discovery returned None or invalid data")
        except Exception as e:
            logger.error(f"Failed to discover Jira tools: {e}")
            
        # System prompt that uses your existing concrete API knowledge
        tool_count = len(self.available_tools) if self.available_tools else 0
        self.system_prompt = f"""You are an autonomous Jira agent with access to {tool_count} proven API operations.

AVAILABLE TOOLS:
{self._format_tools_for_prompt()}

You can chain multiple tool calls to complete complex tasks. For example:
1. Search for existing fields → Create field if needed → Add to screen → Update ticket
2. Check for duplicates → Query knowledge base → Update ticket with resolution
3. Analyze ticket → Apply governance rules → Send notifications

IMPORTANT RULES:
- Use get_issue first if you need more details about a ticket
- Always check for duplicates before creating fields
- Post comments to keep users informed of progress
- Chain operations logically (create → configure → test → notify)

Return this JSON structure:
{{
  "understanding": "What you understood from the request",
  "plan": [
    {{
      "step": 1,
      "tool": "tool_name",
      "description": "What this accomplishes", 
      "args": {{"param": "value"}}
    }}
  ],
  "expected_outcome": "What will be accomplished"
}}

Focus on the business logic. All tool calls are proven to work."""
    
    def _discover_jira_tools(self) -> Dict[str, Dict]:
        """Discover available JiraAPI methods as tools"""
        tools = {}
        
        # Explicitly list the methods we want to expose as tools
        desired_methods = [
            'test_connection', 'get_issue', 'update_issue', 'add_comment',
            'get_all_custom_fields', 'check_duplicate_field', 'create_custom_field',
            'add_field_options'
        ]
        
        try:
            logger.info(f"Discovering JiraAPI tools...")
            
            for method_name in desired_methods:
                if hasattr(self.jira_api, method_name):
                    method = getattr(self.jira_api, method_name)
                    
                    try:
                        # Get method signature
                        sig = inspect.signature(method)
                        doc = method.__doc__ or f"Execute {method_name} operation"
                        
                        # Build parameter info
                        params = {}
                        for param_name, param in sig.parameters.items():
                            if param_name == 'self':
                                continue
                            params[param_name] = {
                                "type": str(param.annotation) if param.annotation != param.empty else "str",
                                "required": param.default == param.empty
                            }
                        
                        tools[method_name] = {
                            "method": method,
                            "description": doc.split('\n')[0],
                            "parameters": params
                        }
                        
                        logger.debug(f"Registered tool: {method_name}")
                        
                    except Exception as e:
                        logger.error(f"Failed to process method {method_name}: {e}")
                else:
                    logger.warning(f"Method {method_name} not found in JiraAPI")
            
            logger.info(f"Successfully discovered {len(tools)} Jira API tools")
            return tools
            
        except Exception as e:
            logger.error(f"Error during tool discovery: {e}")
            return {}
        
    def _format_tools_for_prompt(self) -> str:
        """Format available tools for the system prompt"""
        if not self.available_tools:
            return "No tools available - using fallback mode"
            
        tool_descriptions = []
        for name, info in self.available_tools.items():
            try:
                params = ", ".join([f"{p}: {details['type']}" for p, details in info['parameters'].items()])
                tool_descriptions.append(f"- {name}({params}): {info['description']}")
            except Exception as e:
                logger.error(f"Error formatting tool {name}: {e}")
                tool_descriptions.append(f"- {name}(): {info.get('description', 'No description')}")
        
        return "\n".join(tool_descriptions)
 
    def process(self, issue_data: Dict) -> Dict:
        """Process any Jira request using available tools"""
        if not issue_data:
            return {"error": "No issue data provided", "timestamp": datetime.now().isoformat()}
            
        issue_key = issue_data.get("key")
        fields = issue_data.get("fields", {})
        
        # Check if we have any tools available
        if not self.available_tools:
            logger.error("No tools available - cannot process request")
            return {
                "error": "No Jira API tools available - check JiraAPI initialization",
                "issueKey": issue_key,
                "timestamp": datetime.now().isoformat()
            }
        
        summary = fields.get("summary", "")
        description = self._extract_description_text(fields.get("description"))
        
        # Build context with issue details
        context = f"""
Issue: {issue_key}
Summary: {summary}
Description: {description}

Current Status: {fields.get('status', {}).get('name', 'Unknown')}
Assignee: {fields.get('assignee', {}).get('displayName', 'Unassigned')}
Labels: {', '.join(fields.get('labels', []))}
"""
        
        logger.info(f"Processing unified request: {issue_key}")
        
        try:
            # Get AI plan
            ai_response = call_ollama(context, self.system_prompt, self.config)
            
            if not isinstance(ai_response, dict) or "plan" not in ai_response:
                return self._handle_ai_failure(issue_key, ai_response)
            
            logger.info(f"AI Understanding: {ai_response.get('understanding')}")
            logger.info(f"Plan has {len(ai_response.get('plan', []))} steps")
            
            # Execute the plan
            execution_results = []
            context_data = {"issue_key": issue_key}  # Start with issue key
            
            for step in ai_response.get("plan", []):
                step_num = step.get("step", len(execution_results) + 1)
                tool_name = step.get("tool")
                description = step.get("description", "")
                args = step.get("args", {})
                
                logger.info(f"Step {step_num}: {description} (using {tool_name})")
                
                # Execute the tool
                result = self._execute_tool(tool_name, args, context_data)
                
                # Store results for next steps
                if result.get("success"):
                    data = result.get("data", {})
                    context_data[f"step_{step_num}_result"] = data
                    
                    # Common fields for chaining
                    if "id" in data:
                        context_data[f"step_{step_num}_id"] = data["id"]
                    if "key" in data:
                        context_data[f"step_{step_num}_key"] = data["key"]
                
                execution_results.append({
                    "step": step_num,
                    "tool": tool_name,
                    "description": description,
                    "success": result.get("success", False),
                    "result": result
                })
                
                # Stop on failure
                if not result.get("success"):
                    logger.error(f"Step {step_num} failed: {result.get('error')}")
                    break
            
            # Post summary comment
            self._post_summary_comment(issue_key, ai_response, execution_results)
            
            return {
                "received": True,
                "issueKey": issue_key,
                "mode_detected": "unified_agent",
                "ai_understanding": ai_response.get("understanding"),
                "plan": ai_response.get("plan"),
                "execution_results": execution_results,
                "steps_completed": len([r for r in execution_results if r.get("success")]),
                "total_steps": len(ai_response.get("plan", [])),
                "expected_outcome": ai_response.get("expected_outcome"),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error in unified processing: {e}")
            return {"error": str(e), "issueKey": issue_key}
    
    def _execute_tool(self, tool_name: str, args: Dict, context_data: Dict) -> Dict:
        """Execute a discovered tool with the given arguments"""
        if tool_name not in self.available_tools:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}
        
        tool_info = self.available_tools[tool_name]
        method = tool_info["method"]
        
        try:
            # Substitute context variables in args
            resolved_args = self._resolve_context_variables(args, context_data)
            
            # Call the method
            logger.debug(f"Calling {tool_name} with args: {resolved_args}")
            result = method(**resolved_args)
            
            # Standardize response format
            if isinstance(result, dict):
                if "error" in result:
                    return {"success": False, "error": result["error"], "data": result}
                else:
                    return {"success": True, "data": result}
            else:
                return {"success": True, "data": {"result": result}}
                
        except Exception as e:
            logger.error(f"Tool execution failed for {tool_name}: {e}")
            return {"success": False, "error": str(e)}
    
    def _resolve_context_variables(self, args: Dict, context_data: Dict) -> Dict:
        """Resolve context variables like {{step_1_id}} in arguments"""
        resolved = {}
        
        for key, value in args.items():
            if isinstance(value, str) and "{{" in value and "}}" in value:
                for ctx_key, ctx_value in context_data.items():
                    placeholder = "{{" + ctx_key + "}}"
                    if placeholder in value:
                        if value.strip() == placeholder:
                            value = ctx_value
                        else:
                            value = value.replace(placeholder, str(ctx_value))
            resolved[key] = value
        
        return resolved
    
    def _extract_description_text(self, description_obj: Any) -> str:
        """Extract plain text from Jira description object"""
        if not description_obj:
            return ""
        if isinstance(description_obj, str):
            return description_obj
        if isinstance(description_obj, dict):
            text = []
            for block in (description_obj.get("content", []) or []):
                if block.get("type") == "paragraph":
                    for item in (block.get("content", []) or []):
                        if item.get("type") == "text":
                            text.append(item.get("text", ""))
            return " ".join(text)
        return str(description_obj)
    
    def _handle_ai_failure(self, issue_key: str, ai_response: Any) -> Dict:
        """Handle cases where AI fails to generate a valid plan"""
        logger.error(f"AI failed to generate valid plan for {issue_key}")
        
        # Post a helpful comment
        try:
            self.jira_api.add_comment(
                issue_key, 
                "AI agent encountered an issue processing this request. "
                "The request has been queued for manual review. "
                "Please ensure your request includes specific details about what you need."
            )
        except:
            pass
        
        return {
            "received": True,
            "issueKey": issue_key,
            "error": "AI failed to generate execution plan",
            "raw_response": str(ai_response),
            "timestamp": datetime.now().isoformat()
        }
    
    def _post_summary_comment(self, issue_key: str, ai_response: Dict, execution_results: List[Dict]):
        """Post a summary of what was accomplished"""
        try:
            successful_steps = len([r for r in execution_results if r.get("success")])
            total_steps = len(execution_results)
            
            comment = f"**Autonomous Jira Agent - Task Complete**\n\n"
            comment += f"**Understanding:** {ai_response.get('understanding', 'N/A')}\n\n"
            comment += f"**Results:** {successful_steps}/{total_steps} steps completed\n\n"
            
            for result in execution_results:
                step_num = result.get("step")
                tool = result.get("tool")
                desc = result.get("description") 
                success = result.get("success", False)
                
                status = "✅" if success else "❌"
                comment += f"{status} Step {step_num}: {desc} (via {tool})\n"
                
                if not success:
                    error = result.get("result", {}).get("error", "Unknown error")
                    comment += f"   Error: {error}\n"
            
            if ai_response.get("expected_outcome"):
                comment += f"\n**Expected Result:** {ai_response['expected_outcome']}"
            
            self.jira_api.add_comment(issue_key, comment)
            
        except Exception as e:
            logger.error(f"Failed to post summary comment: {e}")

# Integration point - replace your existing agent routing
def create_unified_agent(config: Config) -> UnifiedJiraAgent:
    """Factory function to create the unified agent"""
    return UnifiedJiraAgent(config)
