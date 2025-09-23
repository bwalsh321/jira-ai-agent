#!/usr/bin/env python3
"""
Jira AI Agent - Complete Multi-Agent System
Each agent gets its own endpoint, standardized interface
"""

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import queue
import threading
import time
import hmac
import os
import json
from datetime import datetime
from typing import Dict, Any, Optional

# Import your existing modules
from config import get_config
from jira.api import JiraAPI
from utils.logger import setup_logger

# Import available agents
from agents.l1_triage_bot import L1TriageBot
from agents.admin_validator import UnrestrictedJiraAgent
from agents.pm_enhancer import PMEnhancer
from agents.governance_bot import GovernanceBot
# Note: planner.py has functions, not a class - we'll skip it for now

# Initialize config and logger
config = get_config()
logger = setup_logger(__name__)

# FastAPI app
app = FastAPI(
    title="Jira AI Agent Toolkit",
    description="Direct routing to specialized Jira agents",
    version="3.2.0",
    docs_url=None if config.production else "/docs",
    redoc_url=None if config.production else "/redoc"
)

# Background job queue
jobs = queue.Queue()

# Initialize available agents
available_agents = {}

# Initialize all agents with error handling
agent_configs = [
    ("l1_triage", L1TriageBot, "L1 Triage Agent"),
    ("admin_validator", UnrestrictedJiraAgent, "Admin Validator Agent"),
    ("pm_enhancer", PMEnhancer, "PM Enhancer Agent"),
    ("governance_bot", GovernanceBot, "Governance Bot Agent")
]

for agent_key, agent_class, agent_name in agent_configs:
    try:
        logger.info(f"Initializing {agent_name}...")
        available_agents[agent_key] = agent_class(config)
        logger.info(f"{agent_name} initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize {agent_name}: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")

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
    issue: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None

def verify_webhook_secret(request: Request):
    """Verify webhook secret header"""
    provided_secret = request.headers.get("x-webhook-secret", "")
    expected_secret = config.webhook_secret
    
    if not hmac.compare_digest(provided_secret, expected_secret):
        logger.warning(f"Invalid secret provided")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

def build_full_issue_context(payload: WebhookPayload) -> Dict:
    """Build complete issue context from webhook payload"""
    
    # If we have full issue data in the payload, use it
    if payload.issue:
        return {"issue": payload.issue}
    
    # If we have raw_data with issue, use that
    if payload.raw_data and payload.raw_data.get("issue"):
        return {"issue": payload.raw_data["issue"]}
    
    # Otherwise build minimal issue data from webhook fields
    issue_data = {
        "key": payload.issueKey,
        "fields": {
            "summary": payload.summary or "",
            "issuetype": {"name": payload.issueType or "Task"},
            "project": {"key": payload.issueKey.split("-")[0] if payload.issueKey and "-" in payload.issueKey else "UNKNOWN"},
            "assignee": None,
            "labels": [],
            "status": {"name": "To Do"},
            "reporter": {"displayName": "Unknown"},
            "created": datetime.now().isoformat()
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
    
    return {"issue": issue_data}

def process_with_agent(agent_name: str, payload: WebhookPayload) -> Dict:
    """Process webhook with specific agent"""
    
    if agent_name not in available_agents:
        return {
            "error": f"Agent '{agent_name}' not available",
            "available_agents": list(available_agents.keys()),
            "issueKey": payload.issueKey
        }
    
    try:
        # Build full issue context
        context = build_full_issue_context(payload)
        
        # Try process_ticket first (newer interface), fallback to process
        agent = available_agents[agent_name]
        try:
            if hasattr(agent, 'process_ticket'):
                result = agent.process_ticket(payload.issueKey, context)
            elif hasattr(agent, 'process'):
                result = agent.process(context)
            else:
                return {
                    "error": f"Agent {agent_name} has no process method",
                    "issueKey": payload.issueKey
                }
        except AttributeError:
            # Fallback for older agents
            result = agent.process(context)
        
        logger.info(f"Agent {agent_name} processed {payload.issueKey}: {result.get('result', 'unknown')}")
        return result
        
    except Exception as e:
        logger.error(f"Agent {agent_name} failed processing {payload.issueKey}: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
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
                logger.info(f"Job completed: {agent_name} -> {result.get('result', 'unknown')}")
            
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

# ========================= HELPER FUNCTION FOR WEBHOOK DATA =========================

def extract_webhook_data(body: Dict) -> Dict:
    """Extract standardized webhook data from Jira webhook body"""
    webhook_data = {}
    
    if "issue" in body:
        # Jira webhook format
        issue = body["issue"]
        webhook_data = {
            "issueKey": issue["key"],
            "summary": issue["fields"]["summary"],
            "issueType": issue["fields"]["issuetype"]["name"],
            "issue": issue,
            "raw_data": body
        }
        
        # Extract description
        desc_obj = issue["fields"].get("description")
        if desc_obj and isinstance(desc_obj, dict) and "content" in desc_obj:
            description = ""
            for block in desc_obj.get("content", []):
                if block.get("type") == "paragraph":
                    for content in block.get("content", []):
                        if content.get("type") == "text":
                            description += content.get("text", "")
            webhook_data["description"] = description
        
        # Extract request type if available
        request_type_field = issue["fields"].get("customfield_10010")
        if request_type_field and isinstance(request_type_field, dict):
            webhook_data["requestType"] = request_type_field.get("requestType", {}).get("name", "")
    else:
        # Direct payload format
        webhook_data = body
    
    return webhook_data

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
        
        webhook_data = extract_webhook_data(body)
        payload = WebhookPayload(**webhook_data)
        
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
        
        webhook_data = extract_webhook_data(body)
        payload = WebhookPayload(**webhook_data)
        
        jobs.put({
            "agent_name": "admin_validator",
            "payload": payload.dict()
        })
        
        return {
            "received": True,
            "agent": "admin_validator",
            "issueKey": payload.issueKey,
            "queued": True,
            "queue_size": jobs.qsize()
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
        
        webhook_data = extract_webhook_data(body)
        payload = WebhookPayload(**webhook_data)
        
        jobs.put({
            "agent_name": "pm_enhancer",
            "payload": payload.dict()
        })
        
        return {
            "received": True,
            "agent": "pm_enhancer",
            "issueKey": payload.issueKey,
            "queued": True,
            "queue_size": jobs.qsize()
        }
        
    except Exception as e:
        logger.error(f"PM enhancer webhook error: {e}")
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
        
        webhook_data = extract_webhook_data(body)
        payload = WebhookPayload(**webhook_data)
        
        jobs.put({
            "agent_name": "governance_bot",
            "payload": payload.dict()
        })
        
        return {
            "received": True,
            "agent": "governance_bot",
            "issueKey": payload.issueKey,
            "queued": True,
            "queue_size": jobs.qsize()
        }
        
    except Exception as e:
        logger.error(f"Governance bot webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/agents/planner")
async def planner_webhook(request: Request):
    """Smart Planner Agent
    
    Use this for:
    - Auto-routing complex requests
    - Multi-step workflow planning
    """
    verify_webhook_secret(request)
    
    try:
        body = await request.json()
        logger.info(f"Planner webhook received")
        
        webhook_data = extract_webhook_data(body)
        payload = WebhookPayload(**webhook_data)
        
        jobs.put({
            "agent_name": "planner",
            "payload": payload.dict()
        })
        
        return {
            "received": True,
            "agent": "planner",
            "issueKey": payload.issueKey,
            "queued": True,
            "queue_size": jobs.qsize()
        }
        
    except Exception as e:
        logger.error(f"Planner webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ========================= INFO ENDPOINTS =========================

@app.get("/")
async def root():
    """Root endpoint with available agents"""
    return {
        "service": "Jira AI Agent Toolkit",
        "version": "3.2.0", 
        "architecture": "direct_routing",
        "available_agents": {
            "l1_triage": {
                "endpoint": "/agents/l1-triage",
                "status": "active" if "l1_triage" in available_agents else "inactive",
                "description": "Incident triage and troubleshooting guidance"
            },
            "custom_field_creator": {
                "endpoint": "/agents/custom-field-creator",
                "status": "active" if "admin_validator" in available_agents else "inactive",
                "description": "Custom field validation and creation"
            },
            "pm_enhancer": {
                "endpoint": "/agents/pm-enhancer",
                "status": "active" if "pm_enhancer" in available_agents else "inactive",
                "description": "Ticket enhancement and user story creation"
            },
            "governance_bot": {
                "endpoint": "/agents/governance-bot",
                "status": "active" if "governance_bot" in available_agents else "inactive",
                "description": "Housekeeping and policy enforcement"
            },
            "planner": {
                "endpoint": "/agents/planner",
                "status": "inactive",
                "description": "Smart routing and workflow planning (not implemented yet)"
            }
        },
        "total_active_agents": len(available_agents)
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Test Jira connection if configured
    jira_status = "not_configured"
    
    try:
        if hasattr(config, 'jira_email') and hasattr(config, 'jira_api_token'):
            has_cloud = bool(config.jira_email and config.jira_api_token)
        else:
            has_cloud = False
            
        if hasattr(config, 'jira_bearer_token'):
            has_bearer = bool(config.jira_bearer_token)
        else:
            has_bearer = False
        
        if has_cloud or has_bearer:
            jira = JiraAPI(config)
            conn_test = jira.test_connection()
            jira_status = "connected" if "error" not in conn_test else "failed"
    except Exception as e:
        jira_status = f"failed: {e}"
    
    return {
        "status": "healthy",
        "version": "3.2.0",
        "active_agents": len(available_agents),
        "agent_list": list(available_agents.keys()),
        "queue_size": jobs.qsize(),
        "jira_status": jira_status,
        "model": config.model,
        "environment": "production" if hasattr(config, 'production') and config.production else "development"
    }

@app.get("/test/l1-triage")
async def test_l1_triage():
    """Test the L1 triage agent"""
    if hasattr(config, 'production') and config.production:
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

@app.get("/test/all-agents")
async def test_all_agents():
    """Test all available agents"""
    if hasattr(config, 'production') and config.production:
        raise HTTPException(status_code=404, detail="Not found")
    
    test_payload = WebhookPayload(
        issueKey="TEST-123",
        summary="Test ticket for all agents",
        description="This is a test ticket to verify all agents are working properly.",
        issueType="Task"
    )
    
    results = {}
    for agent_name in available_agents:
        try:
            result = process_with_agent(agent_name, test_payload)
            results[agent_name] = {"status": "success" if "error" not in result else "failed", "result": result}
        except Exception as e:
            results[agent_name] = {"status": "failed", "error": str(e)}
    
    return {
        "test_summary": f"{len(available_agents)} agents tested",
        "results": results
    }

if __name__ == "__main__":
    import uvicorn
    
    logger.info("Starting Jira AI Agent Toolkit (Complete Multi-Agent System)...")
    logger.info(f"Active agents: {list(available_agents.keys())}")
    logger.info(f"Endpoints available: /agents/{{l1-triage,custom-field-creator,pm-enhancer,governance-bot,planner}}")
    
    uvicorn.run(
        "main:app",
        host="127.0.0.1", 
        port=8001,
        reload=not (hasattr(config, 'production') and config.production),
        access_log=not (hasattr(config, 'production') and config.production)
    )