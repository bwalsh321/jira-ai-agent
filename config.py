"""
Configuration management for Jira AI Agent
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Configuration settings"""
    
    def __init__(self):
        # Jira settings
        self.jira_base_url = os.getenv("JIRA_BASE_URL", "")
        self.jira_token = os.getenv("JIRA_TOKEN", "")
        self.jira_email = os.getenv("JIRA_EMAIL", "")
        
        # Security
        self.webhook_secret = os.getenv("WEBHOOK_SECRET", "default-secret-change-me")
        
        # AI settings
        self.ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
        self.ai_model = os.getenv("AI_MODEL", "gpt-oss:20b")
        
        # Environment
        self.environment = os.getenv("ENVIRONMENT", "development")
        
        # Validation
        self._validate()
    
    def _validate(self):
        """Validate critical settings"""
        if not self.jira_base_url:
            print("WARNING: JIRA_BASE_URL not set")
        if not self.jira_token:
            print("WARNING: JIRA_TOKEN not set - running in read-only mode")
        if self.webhook_secret == "default-secret-change-me":
            print("WARNING: Using default webhook secret - change this!")
    
    def __str__(self):
        return f"Config(jira={bool(self.jira_token)}, model={self.ai_model})"