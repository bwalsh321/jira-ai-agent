# Jira AI Agent 🤖

Professional AI-powered Jira automation and enhancement system. Transforms messy tickets into professional user stories, validates admin requests, and maintains governance automatically.

## ✨ Features

### 🛡️ Admin Validator
- **Smart field creation**: Validates custom field requests and auto-creates approved fields
- **Real duplicate checking**: Scans your entire Jira instance for conflicts
- **Governance enforcement**: Ensures naming conventions and best practices
- **Auto-configuration**: Adds field options, screen assignments, and descriptions

### ✨ PM Enhancer  
- **Ticket transformation**: Converts meeting notes and brain dumps into professional user stories
- **Acceptance criteria**: Automatically generates Given/When/Then acceptance criteria
- **Story point estimation**: AI-powered effort estimation based on complexity
- **Content enrichment**: Adds missing context, technical details, and structure

### 🏛️ Governance Bot
- **Hygiene maintenance**: Automatically fixes missing assignees, labels, components
- **Policy enforcement**: Ensures tickets meet organizational standards
- **Stale ticket management**: Nudges owners of abandoned work
- **Convention compliance**: Maintains consistent naming and categorization

## 🏗️ Architecture

```
jira-ai-agent/
├── main.py                 # FastAPI entry point
├── config.py              # Configuration management
├── run.py                 # Development runner
├── requirements.txt       # Dependencies
├── .env.example          # Environment template
├── agents/               # AI agent implementations
│   ├── __init__.py
│   ├── admin_validator.py
│   ├── pm_enhancer.py
│   └── governance_bot.py
├── jira/                 # Jira API integration
│   ├── __init__.py
│   ├── api.py
│   └── field_extractor.py
├── ai/                   # AI/LLM integration
│   ├── __init__.py
│   └── ollama_client.py
└── utils/                # Utilities
    ├── __init__.py
    └── logger.py
```

## 🚀 Quick Start

### 1. Clone and Setup
```bash
git clone https://github.com/bwalsh321/jira-ai-agent.git
cd jira-ai-agent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration
```bash
# Copy environment template
cp .env.example .env

# Edit .env with your settings
nano .env
```

Required environment variables:
```bash
# Jira Configuration
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_TOKEN=your_api_token_here
JIRA_EMAIL=your-email@domain.com

# Webhook Security
WEBHOOK_SECRET=your-strong-random-secret-here

# AI Configuration  
MODEL=gpt-oss:20b
OLLAMA_URL=http://127.0.0.1:11434/api/generate

# Environment
PRODUCTION=false
```

### 3. Start Ollama (if using local models)
```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull your model
ollama pull gpt-oss:20b

# Start Ollama server
ollama serve
```

### 4. Run the Agent
```bash
# Development mode with auto-reload
python run.py

# Or use uvicorn directly
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

#Start the cloudflare tunnel
cloudflare-tunnel --url http://localhost:8001

## 🔧 API Endpoints

### Main Webhook
```
POST /jira-hook
Headers: X-Webhook-Secret: your-secret
```

### Health & Diagnostics
```
GET /health              # System status
GET /debug/config        # Configuration (dev only)
GET /debug/extraction    # Test field extraction (dev only)
GET /test/ollama        # Test AI connection (dev only)
```

## 📋 Jira Automation Setup

### 1. Create Automation Rule
1. Go to **Project Settings → Automation**
2. Create rule with trigger: **Issue Created** or **Issue Updated**
3. Add condition: **Issue matches JQL** (optional filtering)
4. Add action: **Send web request**

### 2. Configure Web Request
- **URL**: `https://your-domain.com/jira-hook`
- **Method**: `POST`
- **Headers**: 
  ```
  X-Webhook-Secret: your-secret-here
  Content-Type: application/json
  ```
- **Body**: 
  ```json
  {
    "issueKey": "{{issue.key}}",
    "ruleId": "{{rule.id}}",
    "eventType": "{{webhookEvent}}",
    "issue": {{issue.asJsonADF}}
  }
  ```

## 🛠️ Development

### Project Structure
- **`main.py`**: FastAPI application and routing
- **`agents/`**: AI agent implementations for each use case
- **`jira/`**: Jira API client and field extraction logic
- **`ai/`**: LLM integration (Ollama, OpenAI, etc.)
- **`utils/`**: Logging, validation, and helper functions

### Adding New Agents
1. Create new agent class in `agents/`
2. Implement `process(issue_data: Dict) -> Dict` method
3. Add agent to main routing in `main.py`
4. Update auto-detection logic if needed

### Testing
```bash
# Test configuration
curl http://localhost:8000/debug/config

# Test Ollama connection
curl http://localhost:8000/test/ollama

# Test field extraction
curl http://localhost:8000/debug/extraction

# Health check
curl http://localhost:8000/health
```

## 🔒 Privacy & Security

### Data Handling
- **No persistence**: Webhook payloads processed in memory only
- **No training**: Local models don't send data to external services
- **Audit logs**: Optional minimal metadata only (no ticket content)
- **TLS required**: All webhook traffic must use HTTPS

### Hardening Checklist
- ✅ Strong webhook secret (32+ random characters)
- ✅ Access logs disabled (`--no-access-log`)
- ✅ Minimal environment variables
- ✅ Input validation on all endpoints
- ✅ Rate limiting on webhook endpoint
- ✅ No sensitive data in logs

## 📊 Monitoring

### Health Checks
The `/health` endpoint provides system status:
```json
{
  "status": "healthy",
  "version": "2.0.0",
  "queue_size": 0,
  "jira_status": "connected",
  "model": "gpt-oss:20b",
  "environment": "development"
}
```

### Logging
- Structured logging with emojis for easy scanning
- Privacy-safe (automatically masks tokens, emails)
- Configurable log levels
- No access logs in production mode

## 🚀 Deployment

### Production Setup
1. Set `PRODUCTION=true` in environment
2. Use strong secrets and TLS certificates
3. Configure reverse proxy (Nginx, Caddy)
4. Set up monitoring and alerting
5. Enable rate limiting and request validation

### Scaling
- **Single user**: RTX 3090 handles 20-30B models easily
- **Team usage**: Add more GPUs or use cloud inference
- **Enterprise**: Deploy multiple instances with load balancing

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

### Common Issues

**"Cannot connect to Ollama"**
- Ensure Ollama is running: `ollama serve`
- Check model is available: `ollama list`
- Verify URL in config: `http://127.0.0.1:11434/api/generate`

**"Invalid webhook secret"**
- Check `WEBHOOK_SECRET` environment variable
- Ensure Jira Automation sends correct header
- Verify no typos in secret value

**"Jira API errors"**
- Confirm `JIRA_TOKEN` is valid API token (not password)
- Check `JIRA_EMAIL` matches token owner
- Verify `JIRA_BASE_URL` format: `https://domain.atlassian.net`

### Getting Help
- 📧 Create GitHub issue for bugs
- 💬 Start GitHub discussion for questions
- 📚 Check documentation and examples
- 🔍 Enable debug logging for troubleshooting

---

**Built with ❤️ for Jira admins and project managers who want their tickets to be awesome** 🎯