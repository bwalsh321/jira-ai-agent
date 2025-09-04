"""
Configuration management for Jira AI Agent
Loads settings from environment variables with sensible defaults
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Configuration settings for the Jira AI Agent"""

    # Jira settings
    jira_base_url: str
    jira_email: Optional[str] = None
    # Cloud (Basic): email + API token
    jira_api_token: Optional[str] = None
    # Server/DC (Bearer PAT): explicit bearer token
    jira_bearer_token: Optional[str] = None

    # Webhook settings
    webhook_secret: str = "changeme"

    # AI settings
    model: str = "gpt-oss:20b"
    ollama_url: str = "http://127.0.0.1:11434/api/generate"

    # Environment settings
    production: bool = False
    environment: str = "development"

    def __str__(self) -> str:
        """String representation without sensitive data"""
        has_cloud = bool(self.jira_email and self.jira_api_token)
        has_bearer = bool(self.jira_bearer_token)
        mode = "cloud-basic" if has_cloud else ("bearer" if has_bearer else "none")
        return f"Config(jira_auth={mode}, model={self.model})"


def get_config() -> Config:
    """Load configuration from environment variables"""

    # Load environment variables
    jira_base_url = os.getenv("JIRA_BASE_URL", "").rstrip("/")
    jira_email = os.getenv("JIRA_EMAIL")

    # Preferred for Cloud:
    jira_api_token = os.getenv("JIRA_API_TOKEN")

    # Explicit for Server/DC:
    jira_bearer_token = os.getenv("JIRA_BEARER_TOKEN")

    # Legacy fallback (for backward-compat):
    # If only JIRA_TOKEN is set, treat it as an API token when JIRA_EMAIL exists (Cloud),
    # otherwise treat it as Bearer (Server/DC).
    legacy_token = os.getenv("JIRA_TOKEN")
    if not jira_api_token and legacy_token and jira_email:
        jira_api_token = legacy_token
    if not jira_bearer_token and legacy_token and not jira_email:
        jira_bearer_token = legacy_token

    webhook_secret = os.getenv("WEBHOOK_SECRET", "changeme")

    model = os.getenv("MODEL", "gpt-oss:20b")
    ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")

    # Environment settings
    production_str = os.getenv("PRODUCTION", "false").lower()
    production = production_str in ("true", "1", "yes", "on")

    environment = os.getenv("ENVIRONMENT", "development")
    if production:
        environment = "production"

    # Validation / helpful warnings
    if not jira_base_url:
        print("⚠️  WARNING: JIRA_BASE_URL not set")

    if not (jira_email and jira_api_token) and not jira_bearer_token:
        print("⚠️  WARNING: No Jira credentials detected "
              "(need JIRA_EMAIL+JIRA_API_TOKEN for Cloud, or JIRA_BEARER_TOKEN for Server/DC)")

    return Config(
        jira_base_url=jira_base_url,
        jira_email=jira_email,
        jira_api_token=jira_api_token,
        jira_bearer_token=jira_bearer_token,
        webhook_secret=webhook_secret,
        model=model,
        ollama_url=ollama_url,
        production=production,
        environment=environment,
    )
