# Quick Start Guide

Get your local AI agent running in minutes!

## Prerequisites Check

```bash
# 1. Check Python version (need 3.11+)
python --version

# 2. Check Ollama is installed
ollama --version

# 3. Check Docker is running
docker ps

# 4. Check GPU is available (optional but recommended)
nvidia-smi
```

## Installation Steps

### 1. Pull LLM Model

```bash
# Pull Qwen2.5:32b (will use ~20GB disk space)
ollama pull qwen2.5:32b

# Test it works
ollama run qwen2.5:32b "Hello, who are you?"
```

### 2. Set Up Python Environment

**Option A: Using UV (Recommended - faster)**
```bash
# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment
uv venv

# Activate
source .venv/bin/activate  # Linux/Mac
# OR
.venv\Scripts\activate  # Windows

# Install dependencies
uv pip install -r requirements.txt
```

**Option B: Using pip**
```bash
# Create virtual environment
python -m venv .venv

# Activate
source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 3. Start Qdrant Vector Database

```bash
# Start Qdrant with Docker Compose
docker-compose up -d

# Verify it's running
curl http://localhost:6333

# You should see: {"title":"qdrant - vector search engine"...}
```

### 4. Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit with your tokens
nano .env  # or use your preferred editor

# Minimum required for testing:
# - Leave Ollama as default (http://localhost:11434)
# - Set TELEGRAM_BOT_TOKEN if you want Telegram (optional for testing)
# - Set API_TOKEN to any random string for API access
```

### 5. Copy Configuration

```bash
# Copy example config
cp config/settings.yaml.example config/settings.yaml

# Review and adjust if needed (defaults are fine for testing)
nano config/settings.yaml
```

### 6. Download Embedding Model

```bash
# This will download the model to cache (~400MB)
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-mpnet-base-v2')"
```

## First Test Run

### Test 1: Terminal Chat (Minimal Setup)

Create a simple test script:

```bash
# Create test_basic.py
cat > test_basic.py << 'EOF'
import asyncio
from litellm import completion

async def test_ollama():
    response = completion(
        model="ollama/qwen2.5:32b",
        messages=[{"role": "user", "content": "Hello! Say hi back in one sentence."}],
        api_base="http://localhost:11434"
    )
    print(response.choices[0].message.content)

asyncio.run(test_ollama())
EOF

# Run it
python test_basic.py
```

If you see a response, Ollama integration works! ✅

### Test 2: Qdrant Memory

```bash
cat > test_memory.py << 'EOF'
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import numpy as np

# Connect to Qdrant
client = QdrantClient(host="localhost", port=6333)

# Create test collection
client.recreate_collection(
    collection_name="test_collection",
    vectors_config=VectorParams(size=4, distance=Distance.COSINE)
)

# Insert test vector
client.upsert(
    collection_name="test_collection",
    points=[
        PointStruct(
            id=1,
            vector=[0.1, 0.2, 0.3, 0.4],
            payload={"text": "Hello world"}
        )
    ]
)

# Search
results = client.search(
    collection_name="test_collection",
    query_vector=[0.1, 0.2, 0.3, 0.4],
    limit=1
)

print(f"Found: {results[0].payload['text']}")
print("Qdrant works! ✅")
EOF

python test_memory.py
```

### Test 3: Embeddings on GPU

```bash
cat > test_embeddings.py << 'EOF'
from sentence_transformers import SentenceTransformer
import torch

print(f"CUDA available: {torch.cuda.is_available()}")
print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None'}")

# Load model (will use GPU if available)
model = SentenceTransformer('all-mpnet-base-v2')
model.to('cuda' if torch.cuda.is_available() else 'cpu')

# Generate embedding
embedding = model.encode("This is a test sentence")
print(f"Embedding shape: {embedding.shape}")
print(f"Device: {model.device}")
print("Embeddings work! ✅")
EOF

python test_embeddings.py
```

## Next Steps

### Phase 1: Core Agent (You are here!)

1. **Create core agent implementation**:
   ```bash
   # Copy starter implementation (will be provided)
   # or build from scratch following REVERSE_ENGINEERING_ANALYSIS.md
   ```

2. **Test memory storage**:
   - Add some facts to MEMORY.md
   - Test hybrid search
   - Verify citations work

3. **Test LLM fallback**:
   - Try local model (Ollama)
   - Simulate failure
   - Verify fallback to Claude/GPT

### Phase 2: Add Channels

1. **Telegram Bot**:
   ```bash
   # Get token from @BotFather on Telegram
   # Add to .env
   # Test with: python -m channels.telegram
   ```

2. **Discord Bot**:
   ```bash
   # Create bot on Discord Developer Portal
   # Add to .env
   # Test with: python -m channels.discord
   ```

3. **Terminal Interface**:
   ```bash
   # Polish CLI with rich formatting
   # Add history and autocomplete
   # Test with: python -m channels.terminal
   ```

### Phase 3: Heartbeat & Automation

1. **Gmail Integration**:
   - Set up Google Cloud project
   - Enable Gmail API
   - Get OAuth credentials
   - Test email monitoring

2. **Calendar Integration**:
   - Use same Google Cloud project
   - Enable Calendar API
   - Test event reminders

3. **Heartbeat Loop**:
   - Configure APScheduler
   - Test 30-minute interval
   - Verify notifications

### Phase 4: Skills & Tools

1. **MCP Integration**:
   - Install MCP Python SDK
   - Configure MCP servers
   - Test tool calling

2. **Skill System**:
   - Create first custom skill
   - Test skill discovery
   - Implement skill generator

### Phase 5: Second Brain

1. **FastAPI Backend**:
   - Set up API routes
   - Add WebSocket support
   - Test remote access

2. **Dashboard**:
   - Build React UI (or Streamlit)
   - Add note-taking interface
   - Add memory search

3. **Backup System**:
   - Configure Rclone
   - Set up Google Drive sync
   - Test backup/restore

## Troubleshooting

### Ollama not responding

```bash
# Check if Ollama is running
systemctl status ollama  # Linux
brew services list  # Mac

# Check logs
journalctl -u ollama -f  # Linux
ollama serve  # Manual start to see logs

# Restart
systemctl restart ollama  # Linux
brew services restart ollama  # Mac
```

### Qdrant connection error

```bash
# Check Docker container
docker ps | grep qdrant

# View logs
docker logs qdrant

# Restart
docker-compose restart qdrant

# Or rebuild
docker-compose down
docker-compose up -d
```

### GPU not detected

```bash
# Check NVIDIA driver
nvidia-smi

# Check PyTorch CUDA
python -c "import torch; print(torch.cuda.is_available())"

# Reinstall PyTorch with CUDA
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### Import errors

```bash
# Make sure virtual environment is activated
which python  # Should show .venv/bin/python

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

## Recommended Development Workflow

### 1. Start with Terminal Chat

Build a simple terminal interface first:
- Load SOUL.md and USER.md
- Implement basic memory search
- Test LLM responses
- Add conversation history

### 2. Add Memory Persistence

Once chat works:
- Store conversations in Qdrant
- Implement hybrid search
- Test memory retrieval
- Add daily log rotation

### 3. Add First Channel

Pick Telegram or Discord:
- Implement channel adapter
- Test bidirectional communication
- Add session isolation
- Test notifications

### 4. Add Heartbeat

Start simple:
- 30-minute timer
- Load HEARTBEAT.md
- Send "heartbeat" message
- Gradually add integrations

### 5. Iterate and Expand

- Add more channels
- Add more integrations
- Build dashboard
- Optimize performance

## Getting Help

### Documentation
- Read `REVERSE_ENGINEERING_ANALYSIS.md` for architecture details
- Check `README.md` for comprehensive guide
- Review OpenClaw docs at https://docs.openclaw.ai/

### Resources
- LiteLLM: https://docs.litellm.ai/
- Qdrant: https://qdrant.tech/documentation/
- sentence-transformers: https://www.sbert.net/
- Ollama: https://ollama.ai/

### Common Issues

**"Model not found"**
- Run `ollama list` to see installed models
- Pull model: `ollama pull qwen2.5:32b`

**"CUDA out of memory"**
- Reduce batch size in config
- Use smaller model (qwen2.5:14b)
- Monitor with `nvidia-smi`

**"Qdrant connection refused"**
- Check Docker: `docker ps`
- Check port: `curl http://localhost:6333`
- Restart: `docker-compose restart qdrant`

## What's Next?

You now have the foundation. Next steps:

1. ✅ **Review** `REVERSE_ENGINEERING_ANALYSIS.md` to understand architecture
2. ✅ **Test** basic components (Ollama, Qdrant, embeddings)
3. 🔨 **Build** core agent implementation
4. 🔨 **Add** your first channel (Telegram recommended)
5. 🔨 **Implement** heartbeat system
6. 🔨 **Create** skills and tools
7. 🔨 **Build** second brain dashboard

Good luck! 🚀
