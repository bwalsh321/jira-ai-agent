#!/usr/bin/env python3
"""
Development runner for Jira AI Agent
Quick way to start the server with proper logging
"""

import uvicorn
from config import get_config, Config
from utils.logger import setup_logger


def _jira_auth_mode(cfg: Config) -> str:
    """Return a human-readable auth mode for logs."""
    has_cloud = bool(cfg.jira_email and cfg.jira_api_token)
    has_bearer = bool(cfg.jira_bearer_token)
    if has_cloud:
        return "cloud-basic"
    if has_bearer:
        return "bearer"
    return "none"


def main():
    """Start the Jira AI Agent server"""
    # Setup logging
    logger = setup_logger("jira_ai_agent", level="INFO")

    # Load config
    config = get_config()

    logger.info("🚀 Starting Jira AI Agent...")
    logger.info(f"📊 Configuration: {config}")  # __str__ already hides secrets

    # Validate critical components
    if not config.webhook_secret or config.webhook_secret == "changeme":
        logger.warning("⚠️  WARNING: Using default webhook secret - set WEBHOOK_SECRET in production!")

    # New auth checks (replace old config.jira_token logic)
    has_cloud = bool(config.jira_email and config.jira_api_token)
    has_bearer = bool(config.jira_bearer_token)
    auth_mode = _jira_auth_mode(config)

    if not (has_cloud or has_bearer):
        logger.warning(
            "⚠️  WARNING: No Jira credentials detected "
            "(set JIRA_EMAIL + JIRA_API_TOKEN for Jira Cloud, "
            "or JIRA_BEARER_TOKEN for Server/Data Center)."
        )
        logger.info("   Create a Cloud API token at: https://id.atlassian.com/manage-profile/security/api-tokens")
    else:
        logger.info(f"🔐 Jira auth mode: {auth_mode}")

    # Start server
    try:
        uvicorn.run(
            "main:app",
            host="127.0.0.1",
            port=8001,
            reload=not config.production,
            access_log=not config.production,
            log_level="info" if not config.production else "warning",
        )
    except KeyboardInterrupt:
        logger.info("👋 Shutting down Jira AI Agent...")
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
