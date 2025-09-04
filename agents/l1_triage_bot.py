"""
L1 Triage Agent - Provides immediate triage analysis and trend detection
"""

import json
import requests
import re
from typing import Dict, List
from datetime import datetime

from utils.logger import setup_logger

logger = setup_logger(__name__)

class L1TriageAgent:
    """L1 Support Triage Agent with trend detection"""
    
    def __init__(self, config):
        self.config = config
        self.description = "Analyzes tickets for L1 triage guidance and detects incident trends"
        logger.info("L1TriageAgent initialized")
    
    def process(self, issue_data: Dict) -> Dict:
        """Main processing method - analyze ticket and provide triage guidance"""
        issue_key = issue_data.get("key")
        logger.info(f"L1 Triage processing: {issue_key}")
        
        try:
            # Check if we should triage this ticket
            should_triage, reason = self._should_triage_ticket(issue_data)
            if not should_triage:
                logger.info(f"Skipping triage for {issue_key}: {reason}")
                return {
                    "received": True,
                    "skipped": True,
                    "reason": reason,
                    "issueKey": issue_key,
                    "action": "l1_triage_skipped"
                }
            
            # Extract context for AI analysis
            ticket_context = self._extract_ticket_context(issue_data)
            logger.info(f"Extracted context for {issue_key} ({len(ticket_context)} chars)")
            
            # Detect trends if Jira API is available
            trend_analysis = {}
            if self.config.jira_api_token or self.config.jira_bearer_token:
                trend_analysis = self._detect_trends(ticket_context)
                
                if trend_analysis.get("trends_detected"):
                    logger.warning(f"🚨 TREND DETECTED for {issue_key}!")
                    logger.info(f"   Similar tickets: {len(trend_analysis.get('similar_tickets', []))}")
                    logger.info(f"   Trending patterns: {list(trend_analysis.get('trending_patterns', {}).keys())}")
            
            # Enhance context with trend data
            enhanced_context = self._enhance_context_with_trends(ticket_context, trend_analysis)
            
            # Run AI triage analysis
            triage_result = self._call_ai_triage(enhanced_context)
            
            logger.info(f"Triage complete for {issue_key}")
            logger.info(f"   Level: {triage_result.get('triage_level', 'unknown')}")
            logger.info(f"   Confidence: {triage_result.get('confidence', 0)}")
            
            # Post comment to Jira if configured
            comment_posted = False
            has_cloud = bool(self.config.jira_email and self.config.jira_api_token)
            has_bearer = bool(self.config.jira_bearer_token)
            
            if has_cloud or has_bearer:
                comment_posted = self._post_triage_comment(issue_key, triage_result, trend_analysis)
            
            return {
                "received": True,
                "action": "l1_triage_completed",
                "issueKey": issue_key,
                "triage_level": triage_result.get("triage_level"),
                "confidence": triage_result.get("confidence"),
                "estimated_effort": triage_result.get("estimated_effort"),
                "incident_risk": triage_result.get("incident_risk"),
                "trends_detected": trend_analysis.get("trends_detected", False),
                "similar_tickets_count": len(trend_analysis.get("similar_tickets", [])),
                "comment_posted": comment_posted,
                "next_steps_count": len(triage_result.get("next_steps", [])),
                "missing_info_count": len(triage_result.get("missing_info", [])),
                "trend_analysis": trend_analysis,
                "triage_analysis": triage_result
            }
            
        except Exception as e:
            logger.error(f"L1 Triage processing failed for {issue_key}: {e}")
            return {
                "received": True,
                "action": "l1_triage_failed",
                "issueKey": issue_key,
                "error": str(e)
            }
    
    def _should_triage_ticket(self, issue_data: Dict) -> tuple[bool, str]:
        """Determine if ticket should be triaged"""
        fields = issue_data.get("fields", {})
        
        # Skip if in certain statuses
        status = fields.get("status", {}).get("name", "").lower()
        skip_statuses = ["done", "closed", "resolved", "cancelled"]
        if any(skip_status in status for skip_status in skip_statuses):
            return False, f"Status is {status}"
        
        # Skip if assigned to specific teams that don't need triage
        assignee = fields.get("assignee", {}).get("displayName", "") if fields.get("assignee") else ""
        if "admin" in assignee.lower() or "lead" in assignee.lower():
            return False, f"Assigned to {assignee}"
        
        # TODO: Skip if already has L1 triage comments (would need API call to check)
        
        return True, "Ready for triage"
    
    def _extract_ticket_context(self, issue_data: Dict) -> str:
        """Extract key context from ticket for AI analysis"""
        fields = issue_data.get("fields", {})
        
        # Basic info
        issue_key = issue_data.get("key", "Unknown")
        summary = fields.get("summary", "")
        issue_type = fields.get("issuetype", {}).get("name", "Unknown")
        priority = fields.get("priority", {}).get("name", "Unknown")
        project = fields.get("project", {}).get("key", "Unknown")
        
        # Extract description text
        description = ""
        desc_obj = fields.get("description")
        if desc_obj and isinstance(desc_obj, dict):
            content = desc_obj.get("content", [])
            for block in content:
                if block.get("type") == "paragraph":
                    for item in block.get("content", []):
                        if item.get("type") == "text":
                            description += item.get("text", "") + " "
        
        # Additional context
        assignee = fields.get("assignee", {}).get("displayName", "Unassigned") if fields.get("assignee") else "Unassigned"
        reporter = fields.get("reporter", {}).get("displayName", "Unknown") if fields.get("reporter") else "Unknown"
        labels = fields.get("labels", [])
        components = [c.get("name", "") for c in fields.get("components", [])]
        
        # Build context string
        context = f"""
TICKET: {issue_key}
PROJECT: {project}
TYPE: {issue_type}
PRIORITY: {priority}
ASSIGNEE: {assignee}
REPORTER: {reporter}
LABELS: {', '.join(labels) if labels else 'None'}
COMPONENTS: {', '.join(components) if components else 'None'}

SUMMARY: {summary}

DESCRIPTION:
{description.strip() if description.strip() else 'No description provided'}
""".strip()
        
        return context
    
    def _detect_trends(self, ticket_context: str) -> Dict:
        """Detect trends by analyzing recent tickets"""
        # For now, return empty trend analysis
        # This would need to be implemented with actual Jira API calls
        # Similar to the trend detection code from the standalone bot
        
        logger.info("Trend detection not yet implemented in agent version")
        return {
            "trends_detected": False,
            "similar_tickets": [],
            "trending_patterns": {},
            "total_recent_tickets": 0,
            "analysis_timeframe": "last 2 hours"
        }
    
    def _enhance_context_with_trends(self, ticket_context: str, trend_analysis: Dict) -> str:
        """Enhance ticket context with trend information"""
        enhanced_context = ticket_context
        
        if trend_analysis.get("trends_detected"):
            enhanced_context += f"\n\nTREND ANALYSIS - RECENT SIMILAR TICKETS:\n"
            
            similar_tickets = trend_analysis.get("similar_tickets", [])
            if similar_tickets:
                enhanced_context += f"Found {len(similar_tickets)} similar tickets in the last 2 hours:\n"
                for ticket in similar_tickets[:3]:  # Show top 3
                    enhanced_context += f"- {ticket['key']}: {ticket['summary']} (keywords: {', '.join(ticket['common_keywords'])})\n"
            
            trending_patterns = trend_analysis.get("trending_patterns", {})
            if trending_patterns:
                enhanced_context += f"\nTrending issue patterns:\n"
                for pattern, count in sorted(trending_patterns.items(), key=lambda x: x[1], reverse=True)[:5]:
                    enhanced_context += f"- '{pattern}' appears in {count} recent tickets\n"
            
            enhanced_context += f"\n⚠️ TREND ALERT: This may be part of a larger incident affecting multiple users!\n"
        
        return enhanced_context
    
    def _call_ai_triage(self, ticket_context: str) -> Dict:
        """Call AI for triage analysis"""
        
        system_prompt = """You are an expert L1 support analyst who provides immediate triage for Jira tickets AND detects incident trends.

Your job: Analyze the ticket, provide ACTIONABLE next steps, and identify if this ticket indicates a broader trend or incident.

ANALYZE FOR:
- Issue type and complexity (simple config vs complex troubleshooting)
- Information completeness (missing steps to reproduce, environment details, etc.)
- Common patterns you recognize from similar tickets
- Urgency/priority assessment
- Required expertise level (L1 doable vs needs escalation)
- TREND DETECTION: Does this ticket suggest a wider system issue?

OUTPUT FORMAT - Return ONLY valid JSON:
{
  "triage_level": "l1_doable|needs_escalation|needs_info",
  "confidence": 0.85,
  "summary": "One-line assessment of the issue",
  "next_steps": ["Step 1", "Step 2", "Step 3"],
  "missing_info": ["What environment?", "Steps to reproduce?"],
  "escalation_reason": "Why this needs L2/L3 if applicable",
  "estimated_effort": "15 minutes|2 hours|complex",
  "priority_suggestion": "low|medium|high|urgent",
  "similar_tickets": ["PROJ-123", "PROJ-456"],
  "trend_indicators": ["authentication_failure", "dashboard_loading", "api_timeout"],
  "incident_risk": "low|medium|high",
  "trend_analysis": "Description of potential trend if detected",
  "comment": "Professional comment for the ticket"
}

COMMON ISSUE PATTERNS TO RECOGNIZE:
- Permission/access issues → check groups, roles, project permissions
- Performance problems → gather metrics, check recent changes
- Integration failures → verify API keys, network connectivity
- User workflow questions → check configuration, provide documentation
- Data inconsistency → verify sync jobs, check for manual changes
- Custom field issues → check field configuration, screen schemes
- Workflow problems → verify transitions, conditions, validators
- Email/notification issues → check notification schemes, user preferences
- Dashboard/loading issues → check server resources, recent deployments
- Authentication problems → verify LDAP/SSO connections, check logs
- API/integration timeouts → check external service status, network issues

TREND DETECTION PATTERNS:
- Multiple users reporting same issue → potential system-wide problem
- Performance complaints → possible infrastructure issue
- Login/auth failures → SSO or LDAP problems
- Dashboard/UI problems → recent deployment or CDN issues
- API errors → third-party service outages
- Email/notification failures → SMTP or notification service issues

BE HELPFUL BUT REALISTIC:
- If you can guide through troubleshooting → provide clear steps
- If complex/specialized → recommend escalation with context
- If info is missing → ask specific questions
- If trend detected → suggest checking for similar recent tickets
- Always suggest realistic timeline estimates"""
        
        try:
            full_prompt = f"{system_prompt}\n\nANALYZE THIS TICKET:\n{ticket_context}\n\nReturn JSON analysis:"
            
            logger.info(f"Calling AI model: {self.config.model}")
            
            response = requests.post(self.config.ollama_url, json={
                "model": self.config.model,
                "prompt": full_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "num_predict": 800,
                    "num_ctx": 4096
                }
            }, timeout=45)
            
            response.raise_for_status()
            result = response.json()
            ai_response = result.get("response", "").strip()
            
            # Robust JSON extraction for thinking models
            logger.info(f"Raw AI response length: {len(ai_response)} chars")
            
            # Remove code fences first
            if "```json" in ai_response:
                start = ai_response.find("```json") + 7
                end = ai_response.find("```", start)
                if end != -1:
                    ai_response = ai_response[start:end].strip()
            elif ai_response.startswith("```"):
                lines = ai_response.split('\n')
                ai_response = '\n'.join(lines[1:-1]) if len(lines) > 2 else ai_response
            
            # Find the JSON object - look for first { and last }
            start = ai_response.find('{')
            if start == -1:
                raise json.JSONDecodeError("No JSON object found", ai_response, 0)
            
            # Find the matching closing brace
            brace_count = 0
            end = start
            for i, char in enumerate(ai_response[start:], start):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break
            
            json_str = ai_response[start:end]
            logger.info(f"Extracted JSON string: {json_str[:200]}...")
            
            return json.loads(json_str)
            
        except requests.exceptions.Timeout:
            logger.error("AI request timed out")
            return self._get_fallback_triage("timeout")
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return self._get_fallback_triage("json_error")
        except Exception as e:
            logger.error(f"AI call failed: {e}")
            return self._get_fallback_triage("error")
    
    def _get_fallback_triage(self, error_type: str) -> Dict:
        """Fallback response when AI fails"""
        return {
            "triage_level": "needs_info",
            "confidence": 0.3,
            "summary": "AI triage temporarily unavailable - manual review needed",
            "next_steps": [
                "Review ticket details manually",
                "Gather any missing information",
                "Assign to appropriate team member"
            ],
            "missing_info": ["AI analysis failed - please review manually"],
            "estimated_effort": "manual review",
            "priority_suggestion": "medium",
            "incident_risk": "unknown",
            "comment": f"🤖 **L1 Triage Bot** (temporarily unavailable due to {error_type})\n\nThis ticket requires manual triage. Please review the details and assign appropriately."
        }
    
    def _post_triage_comment(self, issue_key: str, triage_result: Dict, trend_analysis: Dict) -> bool:
        """Post triage comment to Jira ticket"""
        try:
            from jira.api import JiraAPI
            
            jira = JiraAPI(self.config)
            
            # Build formatted triage comment
            triage_emoji = "🟢" if triage_result.get('triage_level') == 'l1_doable' else "🟡" if triage_result.get('triage_level') == 'needs_info' else "🔴"
            
            # Add trend alert emoji if trends detected
            if trend_analysis.get("trends_detected"):
                triage_emoji += "🚨"
            
            comment_text = f"🤖 **L1 Triage Bot** {triage_emoji}\n\n"
            comment_text += f"**Assessment:** {triage_result.get('summary', 'Analysis complete')}\n"
            comment_text += f"**Triage Level:** {triage_result.get('triage_level', 'unknown').replace('_', ' ').title()}\n"
            comment_text += f"**Estimated Effort:** {triage_result.get('estimated_effort', 'unknown')}\n"
            comment_text += f"**Suggested Priority:** {triage_result.get('priority_suggestion', 'medium').title()}\n"
            
            # Add incident risk if detected
            if triage_result.get('incident_risk', 'low') != 'low':
                comment_text += f"**Incident Risk:** {triage_result.get('incident_risk', 'unknown').title()}\n"
            
            # TREND ANALYSIS SECTION
            if trend_analysis.get("trends_detected"):
                comment_text += f"\n🚨 **TREND ALERT** - Similar Pattern Detected!\n"
                similar_count = len(trend_analysis.get("similar_tickets", []))
                comment_text += f"Found **{similar_count} similar tickets** in the last 2 hours:\n"
                
                for ticket in trend_analysis.get("similar_tickets", [])[:3]:
                    comment_text += f"• {ticket['key']}: {ticket['summary'][:60]}...\n"
                
                if trend_analysis.get("trending_patterns"):
                    top_patterns = sorted(trend_analysis["trending_patterns"].items(), key=lambda x: x[1], reverse=True)[:3]
                    comment_text += f"\n**Trending Keywords:** {', '.join([f'{pattern} ({count}x)' for pattern, count in top_patterns])}\n"
                
                comment_text += f"\n⚠️ **This may indicate a system-wide issue requiring immediate escalation!**\n"
            
            comment_text += f"\n"
            
            if triage_result.get('next_steps'):
                comment_text += "**Recommended Next Steps:**\n"
                for i, step in enumerate(triage_result['next_steps'], 1):
                    comment_text += f"{i}. {step}\n"
                comment_text += "\n"
            
            if triage_result.get('missing_info'):
                comment_text += "**Information Needed:**\n"
                for info in triage_result['missing_info']:
                    comment_text += f"• {info}\n"
                comment_text += "\n"
            
            if triage_result.get('escalation_reason'):
                comment_text += f"**Escalation Note:** {triage_result['escalation_reason']}\n\n"
            
            comment_text += f"*Confidence: {triage_result.get('confidence', 0):.0%} | Auto-generated at {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
            
            # Post the comment
            comment_result = jira.add_comment(issue_key, comment_text)
            
            if "error" in comment_result:
                logger.error(f"Failed to post triage comment to {issue_key}: {comment_result['error']}")
                return False
            else:
                logger.info(f"Posted L1 triage comment to {issue_key}")
                return True
                
        except Exception as e:
            logger.error(f"Error posting triage comment to {issue_key}: {e}")
            return False