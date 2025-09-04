#!/usr/bin/env python3
"""
Jira AI Agent - Simplified Direct Routing
Each agent gets its own endpoint, no auto-detection nonsense
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
from jira.api import JiraAPI
from utils.logger import setup_logger

# Import available agents
from agents.l1_triage_bot import L1TriageAgent

# Initialize config and logger
config = get_config()
logger = setup_logger(__name__)

# FastAPI app
app = FastAPI(
    title="Jira AI Agent Toolkit",
    description="Direct routing to specialized Jira agents",
    version="3.1.0",
    docs_url=None if config.production else "/docs",
    redoc_url=None if config.production else "/redoc"
)

# Background job queue
jobs = queue.Queue()

# Initialize available agents
available_agents = {}

try:
    logger.info("Initializing L1 Triage Agent...")
    available_agents["l1_triage"] = L1TriageAgent(config)
    logger.info("L1 Triage Agent initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize L1 Triage Agent: {e}")

logger.info(f"Initialized {len(available_agents)} agents: {list(available_agents.keys())}")

class WebhookPayload(BaseModel):
    """Standard webhook payload structure"""
    issueKey: str
    summary: Optional[str] = None
    description: Optional[str] = None
    issueType: Optional[str] = None
    requestType: Optional[str] = None
    ruleId: Optional[str] = None
    timestamp: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None

def verify_webhook_secret(request: Request):
    """Verify webhook secret header"""
    provided_secret = request.headers.get("x-webhook-secret", "")
    expected_secret = config.webhook_secret
    
    if not hmac.compare_digest(provided_secret, expected_secret):
        logger.warning(f"Invalid secret provided")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

def build_issue_data(payload: WebhookPayload) -> Dict:
    """Build issue data structure from webhook payload"""
    
    # If we have full issue data in raw_data, use it
    if payload.raw_data and payload.raw_data.get("issue"):
        return payload.raw_data["issue"]
    
    # Otherwise build from webhook fields
    issue_data = {
        "key": payload.issueKey,
        "fields": {
            "summary": payload.summary or "",
            "issuetype": {"name": payload.issueType or "Task"},
            "project": {"key": payload.issueKey.split("-")[0] if payload.issueKey and "-" in payload.issueKey else "UNKNOWN"},
            "assignee": None,
            "labels": [],
            "status": {"name": "To Do"}
        }
    }
    
    # Add description if provided
    if payload.description:
        issue_data["fields"]["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": payload.description
                        }
                    ]
                }
            ]
        }
    
    return issue_data

def process_with_agent(agent_name: str, payload: WebhookPayload) -> Dict:
    """Process webhook with specific agent"""
    
    if agent_name not in available_agents:
        return {
            "error": f"Agent '{agent_name}' not available",
            "available_agents": list(available_agents.keys()),
            "issueKey": payload.issueKey
        }
    
    try:
        # Build issue data
        issue_data = build_issue_data(payload)
        
        # Process with agent
        agent = available_agents[agent_name]
        result = agent.process(issue_data)
        
        logger.info(f"Agent {agent_name} processed {payload.issueKey}: {result.get('action', 'unknown')}")
        return result
        
    except Exception as e:
        logger.error(f"Agent {agent_name} failed processing {payload.issueKey}: {e}")
        return {
            "error": str(e),
            "issueKey": payload.issueKey,
            "agent": agent_name
        }

# ========================= BACKGROUND WORKER =========================

def worker_loop():
    """Background worker processes jobs from the queue"""
    logger.info("Background worker started")
    
    while True:
        try:
            job = jobs.get(timeout=1)
            
            agent_name = job["agent_name"]
            payload_data = job["payload"]
            payload = WebhookPayload(**payload_data)
            
            result = process_with_agent(agent_name, payload)
            
            if "error" in result:
                logger.error(f"Job failed: {result['error']}")
            else:
                logger.info(f"Job completed: {agent_name} -> {result.get('action', 'unknown')}")
            
            jobs.task_done()
            
        except queue.Empty:
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

# ========================= AGENT ENDPOINTS =========================

@app.post("/agents/l1-triage")
async def l1_triage_webhook(request: Request):
    """L1 Incident Triage Agent
    
    Use this for:
    - Service desk incidents
    - Bug reports 
    - User issues needing troubleshooting
    """
    verify_webhook_secret(request)
    
    try:
        body = await request.json()
        logger.info(f"L1 Triage webhook received")
        
        payload = WebhookPayload(**body)
        
        # Queue for background processing
        jobs.put({
            "agent_name": "l1_triage",
            "payload": payload.dict()
        })
        
        return {
            "received": True,
            "agent": "l1_triage",
            "issueKey": payload.issueKey,
            "queued": True,
            "queue_size": jobs.qsize()
        }
        
    except Exception as e:
        logger.error(f"L1 triage webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/agents/custom-field-creator")
async def custom_field_creator_webhook(request: Request):
    """Custom Field Creation Agent
    
    Use this for:
    - "New Custom Field" requests
    - Field configuration requests
    """
    verify_webhook_secret(request)
    
    try:
        body = await request.json()
        logger.info(f"Custom Field Creator webhook received")
        
        # For now, just return not implemented
        # You'll build this agent later
        return {
            "received": True,
            "agent": "custom_field_creator",
            "status": "not_implemented",
            "message": "Custom Field Creator agent coming soon"
        }
        
    except Exception as e:
        logger.error(f"Custom field creator webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/agents/pm-enhancer")
async def pm_enhancer_webhook(request: Request):
    """PM Ticket Enhancement Agent
    
    Use this for:
    - Converting meeting notes to user stories
    - Adding acceptance criteria
    - Manual ticket cleanup
    """
    verify_webhook_secret(request)
    
    try:
        body = await request.json()
        logger.info(f"PM Enhancer webhook received")
        
        # For now, just return not implemented
        return {
            "received": True,
            "agent": "pm_enhancer", 
            "status": "not_implemented",
            "message": "PM Enhancer agent coming soon"
        }
        
    except Exception as e:
        logger.error(f"PM enhancer webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/agents/workflow-validator")
async def workflow_validator_webhook(request: Request):
    """Workflow Creation/Validation Agent
    
    Use this for:
    - "Create New Workflow" requests
    - Workflow configuration reviews
    """
    verify_webhook_secret(request)
    
    try:
        body = await request.json()
        logger.info(f"Workflow Validator webhook received")
        
        return {
            "received": True,
            "agent": "workflow_validator",
            "status": "not_implemented", 
            "message": "Workflow Validator agent coming soon"
        }
        
    except Exception as e:
        logger.error(f"Workflow validator webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/agents/governance-bot")
async def governance_bot_webhook(request: Request):
    """Governance/Housekeeping Agent
    
    Use this for:
    - Scheduled cleanup tasks
    - Stale ticket management
    - Policy enforcement
    """
    verify_webhook_secret(request)
    
    try:
        body = await request.json()
        logger.info(f"Governance Bot webhook received")
        
        return {
            "received": True,
            "agent": "governance_bot",
            "status": "not_implemented",
            "message": "Governance Bot agent coming soon"
        }
        
    except Exception as e:
        logger.error(f"Governance bot webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ========================= INFO ENDPOINTS =========================

@app.get("/")
async def root():
    """Root endpoint with available agents"""
    return {
        "service": "Jira AI Agent Toolkit",
        "version": "3.1.0", 
        "architecture": "direct_routing",
        "available_agents": {
            "l1_triage": {
                "endpoint": "/agents/l1-triage",
                "status": "active" if "l1_triage" in available_agents else "inactive",
                "description": "Incident triage and troubleshooting guidance"
            },
            "custom_field_creator": {
                "endpoint": "/agents/custom-field-creator",
                "status": "coming_soon",
                "description": "Custom field creation and validation"
            },
            "pm_enhancer": {
                "endpoint": "/agents/pm-enhancer", 
                "status": "coming_soon",
                "description": "Ticket enhancement and user story creation"
            },
            "workflow_validator": {
                "endpoint": "/agents/workflow-validator",
                "status": "coming_soon", 
                "description": "Workflow creation and validation"
            },
            "governance_bot": {
                "endpoint": "/agents/governance-bot",
                "status": "coming_soon",
                "description": "Governance and housekeeping automation"
            }
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Test Jira connection if configured
    jira_status = "not_configured"
    has_cloud = bool(config.jira_email and config.jira_api_token)
    has_bearer = bool(config.jira_bearer_token)
    
    if has_cloud or has_bearer:
        try:
            jira = JiraAPI(config)
            conn_test = jira.test_connection()
            jira_status = "connected" if "error" not in conn_test else "failed"
        except:
            jira_status = "failed"
    
    return {
        "status": "healthy",
        "version": "3.1.0",
        "active_agents": len(available_agents),
        "queue_size": jobs.qsize(),
        "jira_status": jira_status,
        "model": config.model,
        "environment": "production" if config.production else "development"
    }

@app.get("/test/l1-triage")
async def test_l1_triage():
    """Test the L1 triage agent"""
    if config.production:
        raise HTTPException(status_code=404, detail="Not found")
    
    if "l1_triage" not in available_agents:
        return {"error": "L1 Triage agent not available"}
    
    test_payload = WebhookPayload(
        issueKey="TEST-123",
        summary="Users cannot access dashboard after login",
        description="Multiple users report white screen after successful login. Started around 3 PM today. Browser: Chrome 120.",
        issueType="Bug",
        requestType="Incident"
    )
    
    result = process_with_agent("l1_triage", test_payload)
    
    return {
        "test": "l1_triage",
        "result": result
    }

if __name__ == "__main__":
    import uvicorn
    
    logger.info("Starting Jira AI Agent Toolkit (Direct Routing)...")
    logger.info(f"Active agents: {list(available_agents.keys())}")
    
    uvicorn.run(
        "main:app",
        host="127.0.0.1", 
        port=8001,
        reload=not config.production,
        access_log=not config.production
    )