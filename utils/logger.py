"""
Logging configuration for Jira AI Agent
Privacy-safe logging with no sensitive data
"""

import logging
import sys
from typing import Optional

def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Setup privacy-safe logger with emojis for easy scanning"""
    
    logger = logging.getLogger(name)
    
    # Don't add handlers if already configured
    if logger.handlers:
        return logger
    
    # Set level
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }
    logger.setLevel(level_map.get(level.upper(), logging.INFO))
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logger.level)
    
    # Create privacy-safe formatter with emojis
    formatter = PrivacySafeFormatter(
        fmt='%(asctime)s | %(emoji)s %(levelname)s | %(name)s | %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    
    # Prevent propagation to avoid duplicate logs
    logger.propagate = False
    
    return logger

def get_logger(name: str) -> logging.Logger:
    """Get existing logger or create new one"""
    return logging.getLogger(name)

class PrivacySafeFormatter(logging.Formatter):
    """Custom formatter that adds emojis and ensures no sensitive data is logged"""
    
    EMOJI_MAP = {
        logging.DEBUG: "🔍",
        logging.INFO: "ℹ️",
        logging.WARNING: "⚠️",
        logging.ERROR: "❌",
        logging.CRITICAL: "🚨"
    }
    
    def format(self, record):
        # Add emoji based on log level
        record.emoji = self.EMOJI_MAP.get(record.levelno, "📝")
        
        # Format the message
        formatted = super().format(record)
        
        # Privacy check - scan for potential sensitive data patterns
        formatted = self._sanitize_message(formatted)
        
        return formatted
    
    def _sanitize_message(self, message: str) -> str:
        """Remove or mask potential sensitive data from log messages"""
        import re
        
        # Mask potential API tokens (keep first few chars for debugging)
        message = re.sub(r'\b([A-Za-z0-9]{10,})\b', lambda m: m.group(1)[:6] + "..." if len(m.group(1)) > 10 else m.group(1), message)
        
        # Mask email addresses (keep domain for debugging)
        message = re.sub(r'\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b', r'***@\1', message)
        
        # Mask potential passwords or secrets in key=value patterns
        message = re.sub(r'(password|secret|token|key)=[^\s]+', r'\1=***', message, flags=re.IGNORECASE)
        
        return message

# Configure root logger to be quiet
logging.getLogger().setLevel(logging.WARNING)

# Silence noisy third-party loggers
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('uvicorn.access').setLevel(logging.WARNING)