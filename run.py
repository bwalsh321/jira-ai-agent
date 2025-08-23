#!/usr/bin/env python3
"""
Development runner for Jira AI Agent
Quick way to start the server with proper logging
"""

import uvicorn
from config import get_config
from utils.logger import setup_logger

def main():
    """Start the Jira AI Agent server"""
    # Setup logging
    logger = setup_logger("jira_ai_agent", level="INFO")
    
    # Load config
    config = get_config()
    
    logger.info("🚀 Starting Jira AI Agent...")
    logger.info(f"📊 Configuration: {config}")
    
    # Validate critical components
    if not config.webhook_secret or config.webhook_secret == "changeme":
        logger.warning("⚠️  WARNING: Using default webhook secret - set WEBHOOK_SECRET in production!")
    
    if not config.jira_token:
        logger.warning("⚠️  WARNING: No JIRA_TOKEN set - running in read-only mode")
        logger.info("   Set JIRA_TOKEN environment variable to enable Jira updates")
        logger.info("   Get token from: https://id.atlassian.com/manage-profile/security/api-tokens")
    
    # Start server
    try:
        uvicorn.run(
            "main:app",
            host="127.0.0.1",
            port=8000,
            reload=not config.production,
            access_log=not config.production,
            log_level="info" if not config.production else "warning"
        )
    except KeyboardInterrupt:
        logger.info("👋 Shutting down Jira AI Agent...")
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())