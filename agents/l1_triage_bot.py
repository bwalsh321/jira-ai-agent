# L1 Triage Bot with REAL Trend Detection
# Looks at tickets from last 30 minutes, finds commonalities, alerts on trends

import json
import logging
import re
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(name)s | %(message)s')
logger = logging.getLogger(__name__)

class L1TriageBot:
    def __init__(self, config):
        self.config = config
        self.ollama_url = "http://127.0.0.1:11434/api/generate"
        self.model = config.model

        self.system_prompt = """You are an expert L1 support agent who triages IT/software tickets for immediate action.
Your job is to analyze tickets and provide:
1. Assessment of complexity level (L1 doable vs escalation needed)
2. Immediate action steps OR information needed
3. Priority recommendation
4. Estimated effort

CRITICAL: Always respond with valid JSON only. No markdown, no explanations outside JSON.

Response format:
{
  "triage_level": "l1_doable|needs_info|escalate",
  "summary": "Brief assessment",
  "priority_suggestion": "high|medium|low",
  "estimated_effort": "5 minutes|30 minutes|2 hours|complex",
  "incident_risk": "high|medium|low",
  "next_steps": ["Step 1", "Step 2", "Step 3"],
  "missing_info": ["Info needed 1", "Info needed 2"],
  "escalation_reason": "Why this needs L2/L3",
  "confidence": 0.85
}

Examples of L1 doable issues:
- Password resets
- Account lockouts
- Basic access requests
- Simple software installs
- Standard configuration changes
- Known error patterns

Escalate when:
- Security incidents
- Database/server issues
- Complex integrations
- Network/infrastructure problems
- Custom development needed
- Regulatory/compliance matters

Be concise but helpful. Focus on actionable next steps."""

        logger.info("L1TriageBot initialized")

    def process_ticket(self, issue_key: str, context: Dict) -> Dict:
        """Main processing method - analyze ticket and detect trends"""
        try:
            logger.info(f"L1 Triage processing: {issue_key}")
            
            # Extract issue context
            issue_context = self._extract_issue_context(context)
            
            if not issue_context:
                logger.error(f"Could not extract issue context for {issue_key}")
                return {"result": "l1_triage_failed", "error": "No context"}
            
            logger.info(f"Extracted context for {issue_key} ({len(str(issue_context))} chars)")
            
            # STEP 1: Detect trends (boss's original request)
            trend_analysis = self._detect_trends(issue_key, issue_context)
            
            # STEP 2: Perform L1 triage
            triage_result = self._analyze_with_ai(issue_context, trend_analysis)
            
            if "error" in triage_result:
                logger.error(f"AI analysis failed for {issue_key}: {triage_result['error']}")
                return {"result": "l1_triage_failed", "error": triage_result["error"]}
            
            # STEP 3: Post comprehensive comment
            comment_posted = self._post_triage_comment(issue_key, triage_result, trend_analysis)
            
            logger.info(f"Triage complete for {issue_key}")
            logger.info(f"   Level: {triage_result.get('triage_level', 'unknown')}")
            logger.info(f"   Confidence: {triage_result.get('confidence', 0)}")
            
            return {
                "result": "l1_triage_complete",
                "triage_level": triage_result.get("triage_level"),
                "confidence": triage_result.get("confidence"),
                "trends_detected": trend_analysis.get("trends_detected", False),
                "comment_posted": comment_posted
            }
            
        except Exception as e:
            logger.error(f"L1 Triage processing failed for {issue_key}: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return {"result": "l1_triage_failed", "error": str(e)}

    def _extract_issue_context(self, context: Dict) -> Optional[str]:
        """Extract and format issue context for AI analysis"""
        try:
            issue = context.get("issue", {})
            fields = issue.get("fields", {})
            
            # Get basic fields
            summary = fields.get("summary", "")
            issue_type = fields.get("issuetype", {}).get("name", "")
            priority = fields.get("priority", {}).get("name", "")
            project = fields.get("project", {}).get("key", "")
            
            # Extract description
            description = ""
            desc_obj = fields.get("description")
            if desc_obj:
                if isinstance(desc_obj, dict) and "content" in desc_obj:
                    # ADF format
                    for block in desc_obj.get("content", []):
                        if block.get("type") == "paragraph":
                            for content in block.get("content", []):
                                if content.get("type") == "text":
                                    description += content.get("text", "")
                elif isinstance(desc_obj, str):
                    description = desc_obj
            
            # Get reporter info
            reporter = fields.get("reporter", {}).get("displayName", "Unknown")
            
            # Format context
            context_text = f"""TICKET: {issue.get('key', 'UNKNOWN')}
PROJECT: {project}
TYPE: {issue_type}
PRIORITY: {priority}
REPORTER: {reporter}

SUMMARY: {summary}

DESCRIPTION:
{description}

STATUS: {fields.get('status', {}).get('name', 'Unknown')}
CREATED: {fields.get('created', '')}"""

            return context_text
            
        except Exception as e:
            logger.error(f"Error extracting issue context: {e}")
            return None

    def _detect_trends(self, current_issue_key: str, current_context: str) -> Dict:
        """REAL trend detection - boss's original request implementation"""
        try:
            logger.info("Starting trend detection analysis...")
            
            # Search for recent tickets (last 30 minutes as requested)
            recent_tickets = self._search_recent_tickets(minutes=30)
            
            if len(recent_tickets) < 2:
                logger.info(f"Only {len(recent_tickets)} recent tickets found - insufficient for trend analysis")
                return {
                    "trends_detected": False,
                    "analysis_timeframe": "last 30 minutes",
                    "tickets_analyzed": len(recent_tickets),
                    "reason": "Insufficient recent tickets for pattern analysis"
                }
            
            logger.info(f"Analyzing {len(recent_tickets)} recent tickets for trends...")
            
            # Extract keywords from current ticket
            current_keywords = self._extract_keywords_from_context(current_context)
            
            # Find similar tickets
            similar_tickets = []
            trending_patterns = {}
            
            for ticket in recent_tickets:
                if ticket.get("key") == current_issue_key:
                    continue  # Skip the current ticket
                
                ticket_keywords = self._extract_keywords_from_text(
                    f"{ticket.get('summary', '')} {ticket.get('description', '')}"
                )
                
                # Calculate similarity
                common_keywords = set(current_keywords).intersection(set(ticket_keywords))
                
                if len(common_keywords) >= 2:  # At least 2 common keywords = similar
                    similar_tickets.append({
                        "key": ticket.get("key"),
                        "summary": ticket.get("summary", ""),
                        "common_keywords": list(common_keywords),
                        "similarity_score": len(common_keywords) / len(set(current_keywords).union(set(ticket_keywords)))
                    })
                
                # Track trending patterns
                for keyword in ticket_keywords:
                    if keyword in current_keywords:
                        trending_patterns[keyword] = trending_patterns.get(keyword, 0) + 1
            
            # Determine if trends detected
            trends_detected = len(similar_tickets) >= 1 or any(count >= 2 for count in trending_patterns.values())
            
            result = {
                "trends_detected": trends_detected,
                "analysis_timeframe": "last 30 minutes",
                "tickets_analyzed": len(recent_tickets),
                "similar_tickets": similar_tickets[:5],  # Top 5 most similar
                "trending_patterns": {k: v for k, v in trending_patterns.items() if v >= 2},
                "current_keywords": current_keywords[:10]  # For debugging
            }
            
            if trends_detected:
                logger.info(f"🚨 TRENDS DETECTED: {len(similar_tickets)} similar tickets, {len(result['trending_patterns'])} trending patterns")
            else:
                logger.info("No significant trends detected")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in trend detection: {e}")
            return {
                "trends_detected": False,
                "error": str(e),
                "analysis_timeframe": "last 30 minutes"
            }

    def _search_recent_tickets(self, minutes: int = 30) -> List[Dict]:
        """Search for tickets created/updated in last N minutes"""
        try:
            # Import your JiraAPI here to avoid circular imports
            from jira.api import JiraAPI
            
            # Use your existing JiraAPI class
            jira = JiraAPI(self.config)
            
            # Build JQL for recent tickets
            jql = f"created >= '-{minutes}m' OR updated >= '-{minutes}m' ORDER BY created DESC"
            
            logger.info(f"Searching for tickets in last {minutes} minutes: {jql}")
            
            # Search tickets using your existing search method
            search_result = jira.search_issues(jql, max_results=50)
            
            if "error" in search_result:
                logger.error(f"JQL search failed: {search_result['error']}")
                return []
            
            tickets = []
            for issue in search_result.get("issues", []):
                fields = issue.get("fields", {})
                
                # Extract description
                description = ""
                desc_obj = fields.get("description")
                if desc_obj and isinstance(desc_obj, dict) and "content" in desc_obj:
                    for block in desc_obj.get("content", []):
                        if block.get("type") == "paragraph":
                            for content in block.get("content", []):
                                if content.get("type") == "text":
                                    description += content.get("text", "")
                
                tickets.append({
                    "key": issue.get("key"),
                    "summary": fields.get("summary", ""),
                    "description": description,
                    "issue_type": fields.get("issuetype", {}).get("name", ""),
                    "priority": fields.get("priority", {}).get("name", ""),
                    "created": fields.get("created", "")
                })
            
            logger.info(f"Found {len(tickets)} recent tickets for trend analysis")
            return tickets
            
        except Exception as e:
            logger.error(f"Error searching recent tickets: {e}")
            return []

    def _extract_keywords_from_context(self, context: str) -> List[str]:
        """Extract meaningful keywords from issue context"""
        # Get summary and description lines
        lines = context.split('\n')
        summary_line = next((line for line in lines if line.startswith('SUMMARY:')), '')
        description_start = next((i for i, line in enumerate(lines) if line.startswith('DESCRIPTION:')), -1)
        
        summary_text = summary_line.replace('SUMMARY:', '').strip()
        
        description_text = ""
        if description_start >= 0:
            for line in lines[description_start+1:]:
                if line.startswith('STATUS:') or line.startswith('CREATED:'):
                    break
                description_text += line + " "
        
        combined_text = f"{summary_text} {description_text}".strip()
        return self._extract_keywords_from_text(combined_text)

    def _extract_keywords_from_text(self, text: str) -> List[str]:
        """Extract meaningful keywords from text"""
        if not text:
            return []
        
        # Convert to lowercase and clean
        text = text.lower()
        
        # Remove common stop words
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
            'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
            'will', 'would', 'could', 'should', 'can', 'may', 'might', 'this', 'that', 'these', 'those',
            'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my', 'your',
            'his', 'our', 'their', 'please', 'need', 'needs', 'unable', 'issue', 'problem', 'help'
        }
        
        # Extract words (alphanumeric, 3+ chars)
        words = re.findall(r'\b[a-zA-Z0-9]{3,}\b', text)
        
        # Filter meaningful keywords
        keywords = []
        for word in words:
            if (word not in stop_words and 
                not word.isdigit() and 
                len(word) >= 3):
                keywords.append(word)
        
        # Return unique keywords, preserving order
        seen = set()
        unique_keywords = []
        for keyword in keywords:
            if keyword not in seen:
                seen.add(keyword)
                unique_keywords.append(keyword)
        
        return unique_keywords[:20]  # Limit to top 20 keywords

    def _analyze_with_ai(self, issue_context: str, trend_analysis: Dict) -> Dict:
        """Analyze ticket with AI including trend context"""
        try:
            # Build enhanced prompt with trend info
            prompt = f"""Analyze this support ticket for L1 triage:

{issue_context}

TREND ANALYSIS:
- Trends detected: {trend_analysis.get('trends_detected', False)}
- Similar tickets in last 30 min: {len(trend_analysis.get('similar_tickets', []))}
- Trending patterns: {list(trend_analysis.get('trending_patterns', {}).keys())[:3]}

If trends are detected, consider this may be part of a larger incident requiring higher priority/escalation.

Respond with JSON only:"""

            logger.info(f"Calling AI model: {self.model}")
            
            response = requests.post(self.ollama_url, json={
                "model": self.model,
                "prompt": f"{self.system_prompt}\n\n{prompt}",
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "num_predict": 800,
                    "num_ctx": 4096
                }
            }, timeout=120)
            
            response.raise_for_status()
            result = response.json()
            ai_text = result.get("response", "").strip()
            
            logger.info(f"Raw AI response length: {len(ai_text)} chars")
            
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                logger.info(f"Extracted JSON string: {json_str[:100]}...")
                
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                    return self._get_fallback_triage()
            else:
                logger.error("No JSON found in AI response")
                return self._get_fallback_triage()
                
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return {"error": str(e)}

    def _get_fallback_triage(self) -> Dict:
        """Fallback triage when AI fails"""
        return {
            "triage_level": "needs_info",
            "summary": "AI analysis temporarily unavailable - manual review required",
            "priority_suggestion": "medium",
            "estimated_effort": "unknown",
            "incident_risk": "low",
            "next_steps": ["Review ticket manually", "Gather additional information", "Assign to appropriate agent"],
            "missing_info": ["AI triage service needs attention"],
            "confidence": 0.3
        }

    def _post_triage_comment(self, issue_key: str, triage_result: Dict, trend_analysis: Dict) -> bool:
        """Post comprehensive triage comment to Jira ticket using ADF format"""
        try:
            from jira.api import JiraAPI
            
            jira = JiraAPI(self.config)
            
            # Build formatted triage comment using ADF
            triage_level = triage_result.get('triage_level', 'unknown')
            triage_emoji = "🟢" if triage_level == 'l1_doable' else "🟡" if triage_level == 'needs_info' else "🔴"
            
            # Add trend alert emoji if trends detected
            if trend_analysis.get("trends_detected"):
                triage_emoji += "🚨"
            
            # Build ADF document structure
            content_blocks = []
            
            # Header
            content_blocks.append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "🤖 ", "marks": []},
                    {"type": "text", "text": "L1 Triage Bot", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": f" {triage_emoji}", "marks": []}
                ]
            })
            
            # Assessment
            content_blocks.append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Assessment: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": triage_result.get('summary', 'Analysis complete'), "marks": []}
                ]
            })
            
            # Triage Level
            content_blocks.append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Triage Level: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": triage_level.replace('_', ' ').title(), "marks": []}
                ]
            })
            
            # Estimated Effort
            content_blocks.append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Estimated Effort: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": triage_result.get('estimated_effort', 'unknown'), "marks": []}
                ]
            })
            
            # Suggested Priority
            content_blocks.append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Suggested Priority: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": triage_result.get('priority_suggestion', 'medium').title(), "marks": []}
                ]
            })
            
            # Add incident risk if elevated
            if triage_result.get('incident_risk', 'low') != 'low':
                content_blocks.append({
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Incident Risk: ", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": triage_result.get('incident_risk', 'unknown').title(), "marks": []}
                    ]
                })
            
            # TREND ANALYSIS SECTION
            if trend_analysis.get("trends_detected"):
                content_blocks.append({
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "🚨 ", "marks": []},
                        {"type": "text", "text": "TREND ALERT", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": " - Similar Pattern Detected!", "marks": []}
                    ]
                })
                
                similar_count = len(trend_analysis.get("similar_tickets", []))
                content_blocks.append({
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": f"Found ", "marks": []},
                        {"type": "text", "text": f"{similar_count} similar tickets", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": " in the last 30 minutes:", "marks": []}
                    ]
                })
                
                # Add similar tickets as bullet list
                if trend_analysis.get("similar_tickets"):
                    bullet_items = []
                    for ticket in trend_analysis.get("similar_tickets", [])[:3]:
                        bullet_items.append({
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": f"{ticket['key']}: {ticket['summary'][:60]}...", "marks": []}
                                    ]
                                }
                            ]
                        })
                    
                    content_blocks.append({
                        "type": "bulletList",
                        "content": bullet_items
                    })
                
                # Trending patterns
                if trend_analysis.get("trending_patterns"):
                    top_patterns = sorted(trend_analysis["trending_patterns"].items(), 
                                        key=lambda x: x[1], reverse=True)[:3]
                    pattern_text = ', '.join([f'{pattern} ({count}x)' for pattern, count in top_patterns])
                    
                    content_blocks.append({
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Trending Keywords: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": pattern_text, "marks": []}
                        ]
                    })
                
                # Escalation warning
                content_blocks.append({
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "⚠️ ", "marks": []},
                        {"type": "text", "text": "This may indicate a system-wide issue requiring immediate escalation!", "marks": [{"type": "strong"}]}
                    ]
                })
            
            # Action steps
            if triage_result.get('next_steps'):
                content_blocks.append({
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Recommended Next Steps:", "marks": [{"type": "strong"}]}
                    ]
                })
                
                step_items = []
                for i, step in enumerate(triage_result['next_steps'], 1):
                    step_items.append({
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": step, "marks": []}
                                ]
                            }
                        ]
                    })
                
                content_blocks.append({
                    "type": "orderedList",
                    "content": step_items
                })
            
            # Missing information
            if triage_result.get('missing_info'):
                content_blocks.append({
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Information Needed:", "marks": [{"type": "strong"}]}
                    ]
                })
                
                info_items = []
                for info in triage_result['missing_info']:
                    info_items.append({
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": info, "marks": []}
                                ]
                            }
                        ]
                    })
                
                content_blocks.append({
                    "type": "bulletList",
                    "content": info_items
                })
            
            # Escalation reason
            if triage_result.get('escalation_reason'):
                content_blocks.append({
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Escalation Note: ", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": triage_result['escalation_reason'], "marks": []}
                    ]
                })
            
            # Footer
            confidence_pct = int(triage_result.get('confidence', 0) * 100)
            footer_text = f"Confidence: {confidence_pct}% | Auto-generated at {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            content_blocks.append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": footer_text, "marks": [{"type": "em"}]}
                ]
            })
            
            # Build final ADF payload
            adf_payload = {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": content_blocks
                }
            }
            
            # Post the comment using ADF format
            comment_result = jira.add_comment(issue_key, adf_payload)
            
            if "error" in comment_result:
                logger.error(f"Failed to post triage comment to {issue_key}: {comment_result['error']}")
                return False
            else:
                logger.info(f"Posted L1 triage comment to {issue_key}")
                return True
                
        except Exception as e:
            logger.error(f"Error posting triage comment to {issue_key}: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False