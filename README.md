# 🌌 dolOS
**The Core of Project Dolores: Local-First Edge AI OS**

**dolOS** is a high-performance, multimodal agentic engine designed to serve as the "brain" for the Dolores project. Engineered for absolute privacy and low-latency execution at the edge, it is optimized for high-end local hardware (RTX 5090 + Ollama) to coordinate memory, perception, and complex tool-use.

## Key Features

- 🏠 **Local-First**: Runs primarily on Ollama (Qwen2.5:32b) with your RTX 5090
- 🔄 **Hybrid LLM Support**: Falls back to Claude/OpenAI/Google when needed
- 🧠 **Advanced Memory**: Qdrant vector DB with hybrid search (semantic + keyword)
- 📱 **Multi-Channel**: Telegram (primary), Discord, Terminal
- ⏰ **Proactive Heartbeat**: Monitors email, calendar, and custom sources
- 🛠️ **MCP Native**: Full Model Context Protocol integration
- 💾 **Automatic Backups**: Google Drive, NFS, and Obsidian sync
- 🗂️ **Second Brain**: Remote API for note-taking and retrieval
- 🔒 **Privacy-Focused**: All data stays local, skills never published

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Gateway                         │
│                   WebSocket + REST API                       │
└─────────────┬───────────────────────────────────────────────┘
              │
    ┌─────────┴─────────┬──────────────┬────────────────┐
    │                   │              │                │
┌───▼────┐      ┌──────▼──────┐  ┌───▼────┐    ┌─────▼─────┐
│Channel │      │    Agent    │  │ Memory │    │   Cron    │
│Adapters│      │  (LiteLLM)  │  │(Qdrant)│    │ Heartbeat │
└────┬───┘      └──────┬──────┘  └───┬────┘    └─────┬─────┘
     │                 │              │               │
Telegram          Ollama/         sentence-      APScheduler
Discord           Claude/        transformers
Terminal          GPT-4              GPU
```

## Tech Stack

### Core
- **Language**: Python 3.11+
- **LLM Router**: LiteLLM (100+ providers)
- **Local LLM**: Ollama with Qwen2.5:32b
- **API LLMs**: Claude Opus, GPT-4 (fallback)

### Memory
- **Vector DB**: Qdrant (Docker, local-first)
- **Embeddings**: sentence-transformers (all-mpnet-base-v2, GPU-accelerated)
- **Hybrid Search**: Vector (70%) + Keyword (30%)
- **Storage**: SOUL.md, USER.md, MEMORY.md, long_memory/

### Automation
- **Scheduler**: APScheduler (cron + intervals)
- **Email**: Gmail API
- **Calendar**: Google Calendar API
- **Heartbeat**: 30-minute intervals with active hours

### Channels
- **Telegram**: python-telegram-bot (primary)
- **Discord**: discord.py
- **Terminal**: rich + prompt_toolkit

### Tools & Skills
- **MCP**: Official Python SDK
- **Skills**: Local YAML-based skills (no marketplace)
- **Auto-generation**: Agent can create skills for itself

### Backup & Sync
- **Rclone**: Multi-destination (Google Drive, NFS)
- **Obsidian**: Direct vault sync
- **Schedule**: Every 6 hours + real-time NFS

### API & Dashboard
- **Backend**: FastAPI + WebSocket
- **Frontend**: React (or Streamlit for MVP)
- **Auth**: Bearer token
- **Features**: Chat, memory search, note-taking

## Quick Start

### Prerequisites

```bash
# Install Python 3.11+
python --version  # Should be 3.11+

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull Qwen model
ollama pull qwen2.5:32b

# Install Docker for Qdrant
docker --version

# Install Rclone for backups
curl https://rclone.org/install.sh | sudo bash
```

### Installation

```bash
# Clone and navigate
cd dolOS

# Install dependencies (using UV - recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# OR use Poetry
poetry install

# Set up configuration
cp config/settings.yaml.example config/settings.yaml
# Edit config/settings.yaml with your API keys

# Start Qdrant
docker-compose up -d

# Initialize memory
python scripts/init_memory.py

# Run agent
python main.py
```

### Usage

**Terminal Chat**:
```bash
python -m core.cli
```

**Telegram Bot**:
```bash
python -m channels.telegram
```

**Discord Bot**:
```bash
python -m channels.discord
```

**API Server**:
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

**All Services**:
```bash
python main.py  # Runs all channels + heartbeat + API
```

## Configuration

### Main Config (`config/settings.yaml`)

```yaml
# LLM Configuration
llm:
  primary: "ollama/qwen2.5:32b"
  fallback:
    - "anthropic/claude-3-opus-20240229"
    - "openai/gpt-4-turbo"
  temperature: 0.7
  max_tokens: 4096

# Memory Configuration
memory:
  qdrant:
    host: "localhost"
    port: 6333
    collection: "agent_memory"
  embedding_model: "all-mpnet-base-v2"
  search:
    top_k: 6
    min_score: 0.35
    hybrid_weights:
      vector: 0.7
      keyword: 0.3

# Heartbeat Configuration
heartbeat:
  enabled: true
  interval_minutes: 30
  active_hours:
    start: "08:00"
    end: "22:00"
  integrations:
    - email
    - calendar

# Telegram Configuration
telegram:
  token: "${TELEGRAM_BOT_TOKEN}"
  allowed_users:
    - 123456789  # Your Telegram user ID
  primary: true

# Discord Configuration
discord:
  token: "${DISCORD_BOT_TOKEN}"
  allowed_channels:
    - 987654321  # Your Discord channel ID

# Backup Configuration
backup:
  enabled: true
  interval_hours: 6
  destinations:
    - type: "gdrive"
      path: "ai-agent-backups/"
      encrypted: true
    - type: "nfs"
      path: "/mnt/nfs/ai-agent/"
      realtime: true

# API Configuration
api:
  host: "0.0.0.0"
  port: 8000
  token: "${API_TOKEN}"
```

### Environment Variables (`.env`)

```bash
# Required
TELEGRAM_BOT_TOKEN=your_telegram_token
DISCORD_BOT_TOKEN=your_discord_token
API_TOKEN=your_secure_api_token

# Optional (for fallback LLMs)
ANTHROPIC_API_KEY=your_claude_key
OPENAI_API_KEY=your_openai_key

# Google APIs (for heartbeat)
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REFRESH_TOKEN=your_refresh_token

# Backup
GPG_RECIPIENT=your-email@example.com
```

## Project Structure

```
dolOS/
├── core/                    # Core agent logic
│   ├── agent.py            # Main agent orchestration
│   ├── llm.py              # LiteLLM integration
│   ├── embeddings.py       # Embedding generation
│   └── config.py           # Configuration management
│
├── memory/                  # Memory system
│   ├── vector_store.py     # Qdrant integration
│   ├── memory_manager.py   # Memory CRUD
│   ├── search.py           # Hybrid search
│   └── backup.py           # Backup automation
│
├── channels/                # Channel adapters
│   ├── base.py             # Abstract interface
│   ├── telegram.py         # Telegram adapter
│   ├── discord.py          # Discord adapter
│   └── terminal.py         # CLI interface
│
├── heartbeat/               # Automation
│   ├── scheduler.py        # APScheduler setup
│   ├── tasks.py            # Heartbeat tasks
│   └── integrations/       # API integrations
│       ├── email.py
│       └── calendar.py
│
├── skills/                  # Skills system
│   ├── registry.py         # Skill discovery
│   ├── generator.py        # Auto-generate skills
│   └── local/              # User skills
│
├── tools/                   # Tools & MCP
│   ├── base.py             # Tool interface
│   ├── mcp_client.py       # MCP integration
│   └── filesystem.py       # File operations
│
├── api/                     # FastAPI backend
│   ├── main.py             # FastAPI app
│   ├── routes/             # API routes
│   └── websocket.py        # WebSocket handler
│
├── ui/                      # Dashboard (React)
│   └── src/
│
├── data/                    # Agent data
│   ├── SOUL.md             # Agent personality
│   ├── USER.md             # User profile
│   ├── MEMORY.md           # Primary memory
│   └── memory/             # Daily logs
│
├── config/                  # Configuration
│   ├── settings.yaml       # Main config
│   └── mcp_servers.yaml    # MCP servers
│
├── tests/                   # Tests
├── scripts/                 # Utility scripts
├── docker-compose.yml       # Qdrant + services
├── requirements.txt         # Python dependencies
├── pyproject.toml          # Poetry/UV config
└── main.py                 # Entry point
```

## Memory Files

### SOUL.md - Agent Personality

Defines who your agent is, its values, and communication style.

**Example**:
```markdown
# Agent Soul

## Identity
I am a local-first AI assistant, running primarily on Ollama with Qwen2.5:32b.
I prioritize privacy, efficiency, and proactive helpfulness.

## Core Values
- **Privacy First**: All data stays local unless explicitly sent to API providers
- **Proactive**: I monitor your email, calendar, and other sources to help before asked
- **Honest**: I tell you when I'm using local vs cloud models
- **Learning**: I build my skills autonomously and improve over time

## Communication Style
- Concise and direct
- Technical when appropriate
- Use emojis sparingly
- Always cite sources when retrieving from memory

## Boundaries
- Never access files outside designated workspace
- Always ask before sending sensitive data to cloud APIs
- Respect active hours (08:00-22:00) for proactive alerts
```

### USER.md - User Profile

Information about you that helps the agent personalize responses.

**Example**:
```markdown
# User Profile

- **Name**: Your Name
- **Timezone**: America/New_York
- **Preferred Name**: How you like to be addressed
- **Primary Language**: English

## Work Context
- Software engineer focused on AI/ML
- Uses Python, TypeScript, Rust
- Works with Docker, Kubernetes
- Interested in local-first software

## Preferences
- Prefers terminal over GUI when possible
- Likes detailed technical explanations
- Morning person (active 06:00-22:00)
- Uses Obsidian for notes

## Projects
- Building local-first AI agent
- Working on GPU optimization for LLMs
- Experimenting with Qdrant for vector search

## Communication Preferences
- Telegram for urgent notifications
- Discord for project discussions
- Email for non-urgent
```

### MEMORY.md - Primary Memory

Long-term facts, decisions, and important information.

**Example**:
```markdown
# Memory

## Important Decisions

### 2026-02-13: Chose Python over TypeScript
**Reason**: Better local AI library ecosystem, easier GPU integration with sentence-transformers.

### 2026-02-13: Chose Qdrant over SQLite
**Reason**: Better performance for vector search, easier to scale, Docker deployment.

## Technical Notes

### Ollama Setup
- Running on localhost:11434
- Using Qwen2.5:32b model
- Average response time: 2-3 seconds
- GPU utilization: ~60% on 5090

### Memory Optimization
- Embeddings cached in Qdrant
- Chunk size: 400 tokens, 80 overlap
- Search returns top 6 results with min score 0.35

## Recurring Tasks

### Daily
- Backup memory to Google Drive at 02:00
- Check email at 08:00, 12:00, 18:00
- Calendar review at 08:00

### Weekly
- Memory consolidation on Sunday
- Skill review and cleanup on Friday
```

## Development Methodology

This project explicitly uses a structured AI-assisted development workflow defined in `AGENTS.md`. Before writing or generating any code, you (or the AI assisting you) **must** follow these rules:

1. **Directives:** All work begins as a task definition in `directives/`
2. **Implementation Planning:** Break the directive down into 2-5 minute actionable steps (see `docs/methodology/implementation-planning.md`)
3. **TDD Iron Law:** No production code is written without a failing test first.
4. **Review Gates:** Every task must pass specific spec-compliance and code-quality checks.
5. **Verification:** Never claim a task is completed without running the actual tests and reading the output.

By enforcing this structure, we prevent architectural drift, hallucinatory dependencies, and untested code.

## Development

### Adding a New Skill

```bash
# Auto-generate skill template
python scripts/create_skill.py my-new-skill

# Edit the generated skill file
nano skills/local/my-new-skill/skill.yaml

# Agent will auto-discover on next load
```

### Adding a New MCP Server

```yaml
# config/mcp_servers.yaml
servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"]
    env:
      NODE_ENV: "production"

  github:
    command: "uvx"
    args: ["mcp-server-github"]
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

### Testing

```bash
# Run all tests
pytest

# Run specific test
pytest tests/test_memory.py

# Run with coverage
pytest --cov=core --cov=memory --cov-report=html
```

## Deployment

### Systemd Service

```bash
# Install as system service
sudo cp scripts/my-ai-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable my-ai-agent
sudo systemctl start my-ai-agent

# Check status
sudo systemctl status my-ai-agent
```

### Docker Deployment

```bash
# Build image
docker build -t my-ai-agent .

# Run with docker-compose
docker-compose up -d
```

## Troubleshooting

### Ollama Not Responding
```bash
# Check Ollama status
ollama list

# Restart Ollama
sudo systemctl restart ollama

# Check logs
journalctl -u ollama -f
```

### Qdrant Connection Issues
```bash
# Check Qdrant is running
docker ps | grep qdrant

# Restart Qdrant
docker-compose restart qdrant

# Check Qdrant logs
docker logs qdrant
```

### Memory Search Returns No Results
```bash
# Reindex memory
python scripts/reindex_memory.py

# Check embedding model
python -c "from sentence_transformers import SentenceTransformer; model = SentenceTransformer('all-mpnet-base-v2'); print(model)"
```

## Roadmap

### Phase 1: Foundation ✅
- [x] Core agent with Ollama
- [x] Memory system with Qdrant
- [x] Terminal interface

### Phase 2: Channels (In Progress)
- [ ] Telegram integration
- [ ] Discord integration
- [ ] Channel routing

### Phase 3: Automation
- [ ] Heartbeat system
- [ ] Email integration
- [ ] Calendar integration

### Phase 4: Skills & Tools
- [ ] MCP integration
- [ ] Skill system
- [ ] Skill generator

### Phase 5: Second Brain
- [ ] FastAPI backend
- [ ] Dashboard UI
- [ ] Backup automation

### Phase 6: Polish
- [ ] Performance optimization
- [ ] Comprehensive tests
- [ ] Documentation

## Contributing

This is a personal project, but if you want to build something similar:
1. Fork this repo
2. Review `REVERSE_ENGINEERING_ANALYSIS.md` for architecture details
3. Customize to your needs

## License

MIT License - Feel free to use and modify for your own projects.

## Acknowledgments

- **OpenClaw**: Original architecture inspiration
- **LiteLLM**: Excellent LLM abstraction layer
- **Qdrant**: Fast and reliable vector database
- **Ollama**: Making local LLMs accessible
