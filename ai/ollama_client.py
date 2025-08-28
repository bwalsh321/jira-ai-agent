"""
Ollama Client - Handles local LLM communication
Migrated from monolithic script with error handling improvements
"""

import requests
import json
import time
import re
from typing import Dict, Any

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

def call_ollama(prompt: str, system_prompt: str, config: Config) -> Dict:
    """Call local Ollama with improved timeout and fallback"""
    try:
        # Build full prompt
        full_prompt = f"{system_prompt}\n\nAnalyze this request and return ONLY valid JSON:\n{prompt}"
        
        logger.info(f"Calling Ollama model: {config.model}")
        logger.debug(f"Prompt length: {len(full_prompt)} chars")
        
        # Optimized parameters for speed vs quality
        payload = {
            "model": config.model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
                "top_k": 20,
                "num_predict": 1500,  # Reduced from 2000 to prevent rambling
                "num_ctx": 4096,
                "stop": ["\n\n\n", "```"]  # Stop on excessive newlines or code blocks
            }
        }
        
        # Call Ollama with timeout
        start_time = time.time()
        response = requests.post(config.ollama_url, json=payload, timeout=60)
        elapsed = time.time() - start_time
        
        response.raise_for_status()
        result = response.json()
        text = result.get("response", "").strip()
        
        logger.info(f"Ollama responded in {elapsed:.1f}s with {len(text)} characters")
        
        if not text or len(text.strip()) < 10:
            logger.warning("Model returned very short response, using fallback")
            return _get_structured_fallback(prompt, "empty_response")
        
        # Clean up response text
        cleaned_text = _clean_response_text(text)
        logger.debug(f"Cleaned response length: {len(cleaned_text)}")
        
        # Parse JSON with validation
        try:
            parsed = json.loads(cleaned_text)
            
            # Validate structure for admin requests
            if "field" in prompt.lower() or "admin" in prompt.lower():
                if not isinstance(parsed, dict) or "plan" not in parsed:
                    logger.warning("Invalid JSON structure for admin request")
                    return _get_structured_fallback(prompt, "invalid_structure")
                    
                if not parsed.get("plan") or not isinstance(parsed["plan"], list):
                    logger.warning("Missing or invalid plan in response")
                    return _get_structured_fallback(prompt, "missing_plan")
            
            return parsed
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from AI: {e}")
            logger.debug(f"Raw response: {cleaned_text[:500]}")
            return _get_structured_fallback(prompt, "invalid_json", cleaned_text)
        
    except requests.exceptions.Timeout:
        logger.error(f"Ollama timeout after 60s - model might be too slow")
        return _get_structured_fallback(prompt, "timeout")
    
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to Ollama at {config.ollama_url}")
        return _get_structured_fallback(prompt, "connection_error")
    
    except Exception as e:
        logger.error(f"AI call failed: {e}")
        return _get_structured_fallback(prompt, "error", str(e))

def _clean_response_text(text: str) -> str:
    """Clean up AI response text to extract valid JSON"""
    # Strip code fences if model added them
    if text.startswith("```"):
        lines = text.split('\n')
        if len(lines) > 1:
            # Remove first line (```json or ```)
            text = '\n'.join(lines[1:])
    
    if text.endswith("```"):
        lines = text.split('\n')
        if len(lines) > 1:
            # Remove last line (```)
            text = '\n'.join(lines[:-1])
    
    # Remove common prefixes that models add
    prefixes_to_remove = [
        "Here's the JSON response:",
        "Here is the JSON:",
        "JSON response:",
        "Response:",
        "Here's what I found:",
        "Based on the request:",
    ]
    
    for prefix in prefixes_to_remove:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
    
    # Find JSON object if response has extra text
    text = text.strip()
    if not text.startswith('{'):
        start = text.find('{')
        if start != -1:
            text = text[start:]
    
    # Find end of JSON object (balance braces)
    if text.startswith('{'):
        brace_count = 0
        for i, char in enumerate(text):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    text = text[:i+1]
                    break
    
    return text.strip()

def _get_structured_fallback(prompt: str, error_type: str, details: str = "") -> Dict:
    """Generate a structured fallback response when AI fails"""
    
    prompt_lower = prompt.lower()
    
    # Admin validation fallback with proper structure
    if any(word in prompt_lower for word in ["field", "custom", "admin", "create", "configuration"]):
        return {
            "understanding": f"AI service temporarily unavailable ({error_type}). Admin request detected for manual review.",
            "plan": [
                {
                    "step": 1,
                    "description": "Manual review required - AI service unavailable",
                    "api_call": {
                        "method": "POST",
                        "endpoint": "/rest/api/3/issue/{issueKey}/comment",
                        "payload": {
                            "body": {
                                "type": "doc",
                                "version": 1,
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": f"AI validation temporarily unavailable ({error_type}). This admin request requires manual review."
                                            }
                                        ]
                                    }
                                ]
                            }
                        }
                    }
                }
            ],
            "safety_checks": [
                f"AI validation service error: {error_type}",
                "Manual review required for this admin request"
            ],
            "expected_outcome": "Comment posted requesting manual review",
            "fallback_reason": error_type
        }
    
    # PM enhancement fallback
    elif any(word in prompt_lower for word in ["enhance", "improve", "meeting", "notes", "story"]):
        return {
            "new_summary": "AI Enhancement Pending",
            "new_description": f"This ticket is queued for AI enhancement but the service is temporarily unavailable ({error_type}). Manual review recommended.",
            "comment": f"AI enhancement temporarily unavailable ({error_type}). Ticket marked for manual review.",
            "marker": f"<!--pm-ai-fallback-{error_type}-->",
            "fallback_reason": error_type
        }
    
    # Governance bot fallback
    elif any(word in prompt_lower for word in ["governance", "violation", "cleanup", "standard"]):
        return {
            "actions": [],
            "summary": f"Governance analysis temporarily unavailable ({error_type}). Manual review recommended.",
            "marker": f"<!--governance-bot-fallback-{error_type}-->",
            "fallback_reason": error_type
        }
    
    # Generic fallback
    return {
        "error": f"AI service temporarily unavailable ({error_type})",
        "details": details,
        "suggestion": "Please try again later or contact support if the issue persists",
        "marker": f"<!--ai-fallback-{error_type}-->",
        "fallback_reason": error_type
    }

def test_ollama_connection(config: Config) -> Dict:
    """Test Ollama connection and performance"""
    try:
        start_time = time.time()
        
        # Simple test prompt
        test_payload = {
            "model": config.model,
            "prompt": "Return this exact JSON: {\"status\": \"OK\", \"test\": true}",
            "stream": False,
            "options": {
                "num_predict": 50,
                "temperature": 0.1
            }
        }
        
        response = requests.post(config.ollama_url, json=test_payload, timeout=30)
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            response_text = result.get("response", "")
            
            # Try to parse the JSON response
            try:
                parsed_response = json.loads(_clean_response_text(response_text))
                json_valid = isinstance(parsed_response, dict) and parsed_response.get("status") == "OK"
            except:
                json_valid = False
            
            logger.info(f"Ollama test successful in {elapsed:.2f}s")
            
            return {
                "status": "success",
                "model": config.model,
                "response_time": f"{elapsed:.2f}s",
                "response": response_text[:200],
                "json_parsing": "valid" if json_valid else "failed",
                "url": config.ollama_url
            }
        else:
            logger.error(f"Ollama test failed: HTTP {response.status_code}")
            return {
                "status": "error", 
                "error": f"HTTP {response.status_code}",
                "response_time": f"{elapsed:.2f}s",
                "url": config.ollama_url
            }
            
    except requests.exceptions.Timeout:
        logger.error("Ollama test timeout")
        return {
            "status": "timeout",
            "error": "Ollama took longer than 30s to respond",
            "suggestion": "Try a smaller/faster model",
            "url": config.ollama_url
        }
        
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to Ollama at {config.ollama_url}")
        return {
            "status": "connection_error",
            "error": f"Cannot connect to {config.ollama_url}",
            "suggestion": "Check if Ollama is running: ollama serve",
            "url": config.ollama_url
        }
        
    except Exception as e:
        logger.error(f"Ollama test failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "suggestion": "Check Ollama installation and model availability",
            "url": config.ollama_url
        }