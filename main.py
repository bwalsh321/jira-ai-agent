#!/usr/bin/env python3
"""
Jira AI Agent - Main Entry Point
Professional modular architecture with webhook processing
"""

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import queue
import threading
import time
import hmac
from datetime import datetime
from typing import Dict, Any, Optional

from config import get_config
from agents.admin_validator import AdminValidator
from agents.pm_enhancer import PMEnhancer
from agents.governance_bot import GovernanceBot
from jira.api import JiraAPI
from utils.logger import setup_logger

# Initialize config and logger
config = get_config()
logger = setup_logger(__name__)

# FastAPI app
app = FastAPI(
    title="Jira AI Agent",
    description="AI-powered Jira automation and enhancement",
    version="2.0.0",
    docs_url=None if config.production else "/docs",
    redoc_url=None if config.production else "/redoc"
)

# Background job queue
jobs = queue.Queue()

# Initialize agents
admin_validator = AdminValidator(config)
pm_enhancer = PMEnhancer(config) 
governance_bot = GovernanceBot(config)

class WebhookPayload(BaseModel):
    """Webhook payload structure"""
    issueKey: Optional[str] = None
    ruleId: Optional[str] = None
    eventType: Optional[str] = None
    issue: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    issueType: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None

# ========================= AUTO-DETECTION =========================

def detect_ai_mode(issue_data: Dict) -> str:
    """Auto-detect which AI agent should handle this request"""
    fields = issue_data.get("fields", {})
    summary = (fields.get("summary") or "").lower()
    
    # Extract description text
    description = ""
    desc_obj = fields.get("description")
    if desc_obj and isinstance(desc_obj, dict):
        content = desc_obj.get("content", [])
        for block in content:
            if block.get("type") == "paragraph":
                for item in block.get("content", []):
                    if item.get("type") == "text":
                        description += item.get("text", "")
    description = description.lower()
    
    # Admin request detection
    admin_keywords = [
        "custom field", "field", "workflow", "permission", "scheme", 
        "configuration", "admin", "create field", "add field", "new field", 
        "screen", "role", "user management", "project settings"
    ]
    
    if any(keyword in summary + " " + description for keyword in admin_keywords):
        return "admin_validator"
    
    # Meeting notes / enhancement detection
    enhancement_keywords = [
        "meeting notes", "transcript", "brain dump", "requirements gathering",
        "unclear", "needs improvement", "enhance", "rewrite"
    ]
    
    if any(keyword in summary + " " + description for keyword in enhancement_keywords):
        return "pm_enhancer"
    
    # Governance issues (stale, missing fields, etc.)
    governance_keywords = [
        "stale", "cleanup", "governance", "missing", "violation", 
        "standard", "convention", "policy"
    ]
    
    if any(keyword in summary + " " + description for keyword in governance_keywords):
        return "governance_bot"
    
    # Default based on content length and complexity
    if len(description) > 500 or "acceptance criteria" in description:
        return "pm_enhancer"
    
    return "pm_enhancer"  # Safe default

def build_issue_from_webhook(webhook_data: Dict) -> Dict:
    """Build proper issue structure from webhook data"""
    issue_key = webhook_data.get("issueKey")
    
    # If we already have full issue data, use it
    if webhook_data.get("issue") and webhook_data["issue"].get("fields"):
        return webhook_data["issue"]
    
    # Build minimal issue structure
    issue_data = {
        "key": issue_key,
        "fields": {
            "summary": webhook_data.get("summary", ""),
            "issuetype": {"name": webhook_data.get("issueType", "Task")},
            "project": {
                "key": issue_key.split("-")[0] if issue_key and "-" in issue_key else "UNKNOWN"
            },
            "assignee": None,
            "labels": [],
            "status": {"name": "To Do"}
        }
    }
    
    # Add description if provided
    description_text = webhook_data.get("description", "")
    if description_text:
        issue_data["fields"]["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": description_text
                        }
                    ]
                }
            ]
        }
    
    return issue_data

# ========================= PROCESSING =========================

def process_webhook(webhook_data: Dict) -> Dict:
    """Main webhook processing logic"""
    issue_key = webhook_data.get("issueKey") or webhook_data.get("issue", {}).get("key")
    
    if not issue_key:
        logger.error("No issue key provided in webhook")
        return {"error": "No issue key provided"}
    
    logger.info(f"🚀 Processing webhook for issue: {issue_key}")
    
    # Build issue data
    issue_data = build_issue_from_webhook(webhook_data)
    
    # If we don't have summary and we have API access, fetch from Jira
    if not issue_data.get("fields", {}).get("summary") and config.jira_token:
        logger.info("⚠️  No summary in webhook data, fetching from API...")
        try:
            jira = JiraAPI(config)
            api_data = jira.get_issue(issue_key)
            
            if "error" not in api_data:
                logger.info("✅ Successfully fetched issue data from API")
                issue_data = api_data
            else:
                logger.warning(f"❌ API fetch failed: {api_data['error']}")
        except Exception as e:
            logger.error(f"Failed to fetch issue from API: {e}")
    
    # Detect which AI agent should handle this
    ai_mode = detect_ai_mode(issue_data)
    logger.info(f"🤖 Auto-detected mode: {ai_mode} for {issue_key}")
    
    # Route to appropriate agent
    try:
        if ai_mode == "admin_validator":
            logger.info("🛡️  Routing to Admin Validator...")
            return admin_validator.process(issue_data)
        
        elif ai_mode == "pm_enhancer":
            logger.info("✨ Routing to PM Enhancer...")
            return pm_enhancer.process(issue_data)
        
        elif ai_mode == "governance_bot":
            logger.info("🏛️  Routing to Governance Bot...")
            return governance_bot.process(issue_data)
        
        else:
            logger.warning(f"Unknown AI mode: {ai_mode}")
            return {
                "error": f"Unknown AI mode: {ai_mode}",
                "mode_detected": ai_mode,
                "issueKey": issue_key
            }
            
    except Exception as e:
        logger.error(f"Error processing with {ai_mode}: {e}")
        return {
            "error": str(e),
            "mode_detected": ai_mode,
            "issueKey": issue_key
        }

# ========================= BACKGROUND WORKER =========================

def worker_loop():
    """Background worker that processes jobs from the queue"""
    logger.info("🔄 Background worker started")
    
    while True:
        try:
            # Get job from queue (blocking with timeout)
            job = jobs.get(timeout=1)
            
            # Process the webhook
            result = process_webhook(job)
            
            # Log result
            if "error" in result:
                logger.error(f"Job failed: {result['error']}")
            else:
                logger.info(f"Job completed: {result.get('mode_detected', 'unknown')} mode")
            
            jobs.task_done()
            
        except queue.Empty:
            # No jobs to process, continue
            continue
        except Exception as e:
            logger.error(f"Worker error: {type(e).__name__}: {e}")
            try:
                jobs.task_done()
            except:
                pass
            time.sleep(0.1)

# Start background worker
threading.Thread(target=worker_loop, daemon=True).start()

# ========================= API ENDPOINTS =========================

@app.post("/jira-hook")
async def jira_hook(request: Request):
    """Main webhook endpoint - receives requests from Jira Automation"""
    
    # Verify webhook secret
    provided_secret = request.headers.get("x-webhook-secret", "")
    expected_secret = config.webhook_secret
    
    if not hmac.compare_digest(provided_secret, expected_secret):
        logger.warning(f"❌ Invalid secret provided: {provided_secret[:10]}...")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    
    logger.info("✅ Valid secret provided")
    
    try:
        # Parse webhook body
        body = await request.json()
        
        # Extract issue key
        issue_key = None
        if "issue" in body and "key" in body["issue"]:
            issue_key = body["issue"]["key"]
        elif "issueKey" in body:
            issue_key = body["issueKey"]
        
        logger.info(f"📨 Received webhook for issue: {issue_key or 'Unknown'}")
        
        # Normalize webhook data
        webhook_payload = WebhookPayload(
            issueKey=issue_key,
            issue=body.get("issue", {}),
            eventType=body.get("webhookEvent", "unknown"),
            summary=body.get("summary", ""),
            description=body.get("description", ""),
            issueType=body.get("issueType", ""),
            ruleId=body.get("ruleId"),
            raw_data=body
        )
        
    except Exception as e:
        logger.error(f"❌ Invalid webhook data: {e}")
        raise HTTPException(status_code=400, detail="Invalid webhook data")
    
    # Queue for background processing
    jobs.put(webhook_payload.dict())
    logger.info(f"📋 Job queued for background processing (queue size: {jobs.qsize()})")
    
    # Return immediate response to keep Jira happy
    return {
        "received": True,
        "issueKey": issue_key,
        "queued": True,
        "queue_size": jobs.qsize(),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Test Jira connection if configured
    jira_status = "not_configured"
    if config.jira_token:
        try:
            jira = JiraAPI(config)
            conn_test = jira.test_connection()
            jira_status = "connected" if "error" not in conn_test else "failed"
        except:
            jira_status = "failed"
    
    return {
        "status": "healthy",
        "version": "2.0.0",
        "queue_size": jobs.qsize(),
        "jira_status": jira_status,
        "model": config.model,
        "environment": "production" if config.production else "development",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/debug/config")
async def debug_config():
    """Debug configuration (development only)"""
    if config.production:
        raise HTTPException(status_code=404, detail="Not found")
    
    return {
        "jira_configured": bool(config.jira_token),
        "jira_base_url": config.jira_base_url,
        "model": config.model,
        "ollama_url": config.ollama_url,
        "production": config.production
    }

@app.get("/debug/extraction")
async def debug_extraction():
    """Debug field extraction (development only)"""
    if config.production:
        raise HTTPException(status_code=404, detail="Not found")
    
    from jira.field_extractor import extract_field_details
    
    # Test with sample data
    summary = "Create custom field called Banana Ripeness Level"
    description = "Need a select list with Unripe, Ripe, Overripe options for our fruit tracking project"
    
    result = extract_field_details(summary, description)
    return result

@app.get("/test/ollama")
async def test_ollama():
    """Test Ollama connection and performance"""
    if config.production:
        raise HTTPException(status_code=404, detail="Not found")
    
    from ai.ollama_client import test_ollama_connection
    
    try:
        result = test_ollama_connection(config)
        return result
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "suggestion": "Check if Ollama is running: ollama serve"
        }

if __name__ == "__main__":
    import uvicorn
    
    logger.info("🚀 Starting Jira AI Agent...")
    logger.info(f"📊 Configuration: {config}")
    
    # Run with development settings
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=not config.production,
        access_log=not config.production
    )