# Quick Start Guide

Get your local AI agent running in minutes.

## Prerequisites

```bash
# 1. Check Python version (need 3.11+)
python --version

# 2. Check Ollama is installed
ollama --version

# 3. Check GPU is available (optional but recommended)
nvidia-smi
```

No Docker required. Qdrant runs embedded inside the Python process.

---

## Installation

### 1. Pull LLM Model

```bash
# Pull Qwen2.5:32b (~20GB disk space)
ollama pull qwen2.5:32b

# Test it works
ollama run qwen2.5:32b "Hello, who are you?"
```

### 2. Set Up Python Environment

**Option A: UV (Recommended)**
```bash
# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create and activate virtual environment
uv venv
source .venv/bin/activate        # Linux/Mac
# OR
.venv\Scripts\activate           # Windows

# Install dependencies
uv pip install -r requirements.txt
```

**Option B: pip**
```bash
python -m venv .venv
source .venv/bin/activate        # Linux/Mac

pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit with your tokens
nano .env
```

Minimum required:
```
PRIMARY_MODEL=ollama/qwen2.5:32b
OLLAMA_API_BASE=http://localhost:11434
DATA_DIR=data/qdrant_storage
```

- `DATA_DIR` is a local path — Qdrant runs embedded, no server needed.
- `TELEGRAM_BOT_TOKEN` and `DISCORD_BOT_TOKEN` are optional (leave commented out unless you want those channels).
- `API_TOKEN` is unused and can be omitted.

### 4. Download Embedding Model

```bash
# Downloads ~400MB to cache
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-mpnet-base-v2')"
```

### 5. Run dolOS

**Option A: Direct (development)**
```bash
python main.py
```

**Option B: systemd service (production)**

```bash
# 1. Copy or symlink the repo to /opt/dolOS
sudo ln -s /root/dolOS /opt/dolOS

# 2. Ensure /opt/dolOS/.env exists and is configured

# 3. Install the service
sudo cp deploy/dolOS.service /etc/systemd/system/
sudo systemctl daemon-reload

# 4. (Optional) Create a dedicated user instead of running as root:
#    sudo useradd -r -s /bin/false -d /opt/dolOS dolos
#    sudo chown -R dolos:dolos /opt/dolOS
#    Then uncomment User=dolos and Group=dolos in the service file.

# 5. Enable and start
sudo systemctl enable --now dolOS
journalctl -u dolOS -f
```

---

## How Storage Works

| `DATA_DIR` value       | Qdrant mode               |
|------------------------|---------------------------|
| `data/qdrant_storage`  | Embedded, persisted to disk |
| `:memory:`             | Embedded, in-memory only  |

Everything runs in-process — no external database server, no containers.

---

## Verification Tests

### Test 1: Ollama

```bash
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

python test_basic.py
```

### Test 2: Embedded Qdrant Memory

```bash
cat > test_memory.py << 'EOF'
from memory.vector_store import VectorStore
from qdrant_client.http.models import Distance

store = VectorStore(location="data/test_qdrant")
store.create_collection("test", vector_size=4, distance=Distance.COSINE)
store.upsert("test", vectors=[[0.1, 0.2, 0.3, 0.4]], payloads=[{"text": "Hello world"}], ids=[1])
results = store.query("test", query_vector=[0.1, 0.2, 0.3, 0.4], limit=1)
print(f"Found: {results[0].payload['text']}")
print("Qdrant embedded works!")
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

model = SentenceTransformer('all-mpnet-base-v2')
embedding = model.encode("This is a test sentence")
print(f"Embedding shape: {embedding.shape}")
print("Embeddings work!")
EOF

python test_embeddings.py
```

---

## Troubleshooting

### Ollama not responding

```bash
# Check status
systemctl status ollama        # Linux
brew services list             # Mac

# Restart
systemctl restart ollama       # Linux
brew services restart ollama   # Mac

# Start manually to see logs
ollama serve
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
# Confirm virtual environment is active
which python    # Should show .venv/bin/python

# Reinstall
pip install -r requirements.txt --force-reinstall
```

### Qdrant storage corrupted

The `VectorStore` automatically detects and resets corrupted storage on startup. If you want to manually clear it:

```bash
rm -rf data/qdrant_storage
# Restart the agent — it will recreate the storage fresh
```

### dolOS service not starting

```bash
# View service logs
journalctl -u dolOS -f

# Check .env is present and configured
cat /opt/dolOS/.env

# Test manually first
cd /opt/dolOS && python main.py
```

---

## Roadmap

### Phase 1: Core Agent
- Review `REVERSE_ENGINEERING_ANALYSIS.md` for architecture
- Test components (Ollama, embedded Qdrant, embeddings)
- Build core agent

### Phase 2: Channels
- Telegram (`TELEGRAM_BOT_TOKEN` in `.env`)
- Discord (`DISCORD_BOT_TOKEN` in `.env`)

### Phase 3: Heartbeat & Automation
- Gmail OAuth integration
- Google Calendar integration
- APScheduler heartbeat loop

### Phase 4: Skills & Tools
- MCP integration
- Custom skill authoring
- Skill auto-generation

### Phase 5: Second Brain Dashboard
- FastAPI backend + WebSocket
- React UI for memory exploration
- Backup via Rclone / Google Drive
