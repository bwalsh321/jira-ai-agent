#!/usr/bin/env python3
"""
Jira AI Agent - Main Entry Point
Now using unified agent that can perform any Jira operation
"""

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import queue
import threading
import time
import hmac
from datetime import datetime
from typing import Dict, Any, Optional, List

from config import get_config
from agents.unified_agent import UnifiedJiraAgent
from jira.api import JiraAPI
from utils.logger import setup_logger

# Initialize config and logger
config = get_config()
logger = setup_logger(__name__)

# FastAPI app
app = FastAPI(
    title="Jira AI Agent",
    description="Autonomous AI-powered Jira agent with full API access",
    version="3.0.0",
    docs_url=None if config.production else "/docs",
    redoc_url=None if config.production else "/redoc"
)

# Background job queue
jobs = queue.Queue()

# Initialize unified agent with error handling
try:
    logger.info("Creating UnifiedJiraAgent...")
    unified_agent = UnifiedJiraAgent(config)
    logger.info(f"UnifiedJiraAgent created successfully with {len(unified_agent.available_tools)} tools")
except Exception as e:
    logger.error(f"Failed to create UnifiedJiraAgent: {e}")
    import traceback
    logger.error(f"Traceback: {traceback.format_exc()}")
    unified_agent = None

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

def build_issue_from_webhook(webhook_data: Dict) -> Dict:
    """Build proper issue structure from webhook data"""
    
    logger.info(f"build_issue_from_webhook received: {webhook_data}")
    logger.info(f"webhook_data keys: {list(webhook_data.keys()) if webhook_data else 'None'}")
    
    issue_key = webhook_data.get("issueKey")
    logger.info(f"Extracted issue_key: {issue_key}")
    
    if not issue_key:
        logger.error("No issue key found, returning None")
        return None
    
    # Build issue structure from flat webhook data
    issue_data = {
        "key": issue_key,
        "fields": {
            "summary": webhook_data.get("summary", ""),
            "issuetype": {"name": webhook_data.get("issueType", "Task")},
            "project": {"key": issue_key.split("-")[0] if issue_key and "-" in issue_key else "UNKNOWN"},
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
    
    # ADD THIS DEBUG LOG
    logger.info(f"Built issue_data: {issue_data}")
    logger.info(f"Returning issue_data with key: {issue_data.get('key')}")
    
    return issue_data

def process_webhook(webhook_data: Dict) -> Dict:
    """Process webhook using unified agent"""
    issue_key = webhook_data.get("issueKey") or webhook_data.get("issue", {}).get("key")
    
    if not issue_key:
        logger.error("No issue key provided in webhook")
        return {"error": "No issue key provided"}
    
    logger.info(f"Processing webhook with unified agent: {issue_key}")
    
    try:
        # Build issue data from webhook
        issue_data = build_issue_from_webhook(webhook_data)
        
        if not issue_data:
            logger.error("Failed to build issue data from webhook")
            return {"error": "Failed to build issue data", "issueKey": issue_key}
        
        # Process with unified agent
        logger.info("Routing to unified agent...")
        if unified_agent is None:
            logger.error("Unified agent not available")
            return {"error": "Unified agent initialization failed", "issueKey": issue_key}
        
        return unified_agent.process(issue_data)
            
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return {"error": str(e), "issueKey": issue_key}

# ========================= BACKGROUND WORKER =========================

def worker_loop():
    """Background worker that processes jobs from the queue"""
    logger.info("Background worker started")
    
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
                steps = result.get('steps_completed', 0)
                total = result.get('total_steps', 0)
                logger.info(f"Job completed: {steps}/{total} steps successful")
            
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
        logger.warning(f"Invalid secret provided: {provided_secret[:10]}...")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    
    logger.info("Valid secret provided")
    
    try:
        # Parse webhook body
        body = await request.json()
        
        # ADD DEBUG LOGGING HERE
        logger.info(f"Raw webhook body: {body}")
        
        # Extract issue key with debugging
        issue_key = None
        if "issue" in body and body["issue"] and "key" in body["issue"]:
            issue_key = body["issue"]["key"]
            logger.info(f"Found issue key in body.issue.key: {issue_key}")
        elif "issueKey" in body:
            issue_key = body["issueKey"]
            logger.info(f"Found issue key in body.issueKey: {issue_key}")
        
        logger.info(f"Final extracted issue key: {issue_key}")
        
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
        logger.error(f"Invalid webhook data: {e}")
        raise HTTPException(status_code=400, detail="Invalid webhook data")
    
    # Queue for background processing
    jobs.put(webhook_payload.dict())
    logger.info(f"Job queued for unified agent processing (queue size: {jobs.qsize()})")
    
    # Return immediate response to keep Jira happy
    available_tools_count = len(unified_agent.available_tools) if unified_agent else 0
    return {
        "received": True,
        "issueKey": issue_key,
        "queued": True,
        "agent_mode": "unified" if unified_agent else "failed",
        "available_tools": available_tools_count,
        "queue_size": jobs.qsize(),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/")
async def root():
    """Root endpoint"""
    available_tools_count = len(unified_agent.available_tools) if unified_agent else 0
    agent_status = "running" if unified_agent else "failed"
    
    return {
        "service": "Jira AI Agent", 
        "version": "3.0.0",
        "status": agent_status,
        "agent_mode": "unified" if unified_agent else "failed",
        "available_tools": available_tools_count,
        "endpoints": {
            "webhook": "/jira-hook",
            "health": "/health", 
            "tools": "/tools",
            "debug_config": "/debug/config",
            "test_ollama": "/test/ollama"
        }
    }

@app.get("/tools")
async def list_tools():
    """List all available tools the agent can use"""
    if config.production:
        raise HTTPException(status_code=404, detail="Not found")
    
    if unified_agent is None:
        return {"total_tools": 0, "tools": {}, "error": "Unified agent not initialized"}
    
    tools_info = {}
    for name, info in unified_agent.available_tools.items():
        tools_info[name] = {
            "description": info["description"],
            "parameters": info["parameters"]
        }
    
    return {
        "total_tools": len(tools_info),
        "tools": tools_info
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Test Jira connection if configured
    jira_status = "not_configured"
    if config.jira_api_token or config.jira_bearer_token:
        try:
            jira = JiraAPI(config)
            conn_test = jira.test_connection()
            jira_status = "connected" if "error" not in conn_test else "failed"
        except:
            jira_status = "failed"
    
    available_tools_count = len(unified_agent.available_tools) if unified_agent else 0
    
    return {
        "status": "healthy",
        "version": "3.0.0",
        "agent_mode": "unified" if unified_agent else "failed",
        "available_tools": available_tools_count,
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
    
    available_tools_count = len(unified_agent.available_tools) if unified_agent else 0
    tool_names = list(unified_agent.available_tools.keys()) if unified_agent else []
    
    return {
        "jira_configured": bool(config.jira_api_token or config.jira_bearer_token),
        "jira_base_url": config.jira_base_url,
        "model": config.model,
        "ollama_url": config.ollama_url,
        "production": config.production,
        "unified_agent_status": "initialized" if unified_agent else "failed",
        "available_tools": available_tools_count,
        "tool_names": tool_names
    }

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

@app.post("/test/unified")
async def test_unified_agent():
    """Test the unified agent with a sample request"""
    if config.production:
        raise HTTPException(status_code=404, detail="Not found")
    
    if unified_agent is None:
        return {
            "test_status": "failed",
            "error": "Unified agent not initialized"
        }
    
    # Test issue
    test_issue = {
        "key": "TEST-123",
        "fields": {
            "summary": "Test unified agent capabilities",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "This is a test to see what the unified agent can do with all available Jira tools."
                            }
                        ]
                    }
                ]
            },
            "status": {"name": "To Do"},
            "assignee": None,
            "labels": []
        }
    }
    
    try:
        result = unified_agent.process(test_issue)
        return {
            "test_status": "completed",
            "result": result
        }
    except Exception as e:
        return {
            "test_status": "failed", 
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    
    logger.info("Starting Unified Jira AI Agent...")
    logger.info(f"Configuration: {config}")
    logger.info(f"Discovered {len(unified_agent.available_tools)} Jira API tools")
    
    # Run with development settings
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=not config.production,
        access_log=not config.production
    )