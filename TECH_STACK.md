# My Local-First Agent: Technology Stack

This document details the complete technology choices and framework decisions made to build the `my-local-agent` architecture. The framework was engineered from scratch specifically for a secure, local-first ecosystem (optimized around an RTX 5090 running Ollama).

---

## 🏗️ 1. Core Framework & Orchestration

### Python 3.11+
The entire agent is written in strictly typed Python.
*   **Why?** Python has the absolute undisputed best ecosystem for local AI, embeddings, and data integration. Features like `asyncio` are used constantly for concurrent operations, keeping the backend non-blocking. Enforcing strict typing (via `mypy`) ensures robust enterprise-grade code predictability.

### LiteLLM (`litellm`)
An abstraction layer for standardizing LLM API calls.
*   **Why?** Instead of hardcoding `ollama` or `openai` client libraries, LiteLLM allows the agent backend to format a single identical prompt payload regardless of the underlying engine. This enables our powerful Fallback Logic: if local Ollama times out, the `LLMGateway` can instantly pivot the same prompt to Claude or GPT-4 without rewriting request schemas.

### Ollama (Primary Engine)
The local LLM runner managing the models, loaded with `Qwen2.5:32b`.
*   **Why?** The RTX 5090 is an exceptionally powerful GPU. Ollama ensures that your entire text-generation layer never leaves your hardware, operating with extremely low latency, zero cloud costs, and high privacy.

### Pydantic & Pydantic-Settings
Data validation and settings management layer.
*   **Why?** Passing unstructured text to a local LLM to execute tools is dangerous. Pydantic is used to enforce strict `JSON Schemas` structure for Tool implementations (`SkillRegistry`). If the LLM generates a malformed tool call, Pydantic catches it immediately before executing the code. `Pydantic-Settings` guarantees `.env` configurations are type-checked at boot.

---

## 🧠 2. Memory & Context Engine

### Qdrant (`qdrant-client`)
A high-performance Vector Search Database (running locally).
*   **Why?** We implemented a dual-memory system (Episodic memory for exact chat logs, Semantic memory for user facts). Qdrant allows us to run extremely fast queries comparing the "meaning" of the user's prompt against millions of past memories locally on your filesystem. 

### Sentence-Transformers (`sentence-transformers`)
The locally-running PyTorch embedding model.
*   **Why?** To use a Vector Database, text must be converted to float vectors. Rather than spending money on OpenAI's `text-embedding-3-small`, we use Microsoft's `all-MiniLM-L6-v2`. It downloads straight to your cache and generates 384-dimensional embeddings in milliseconds using your GPU/CPU for zero cost.

### SQLite (`aiosqlite`)
Asynchronous SQL database utilized by the observability system.
*   **Why?** We needed a lightweight, completely local file-based database capable of handling highly concurrent writes without blocking the event loop. This stores the raw `events`, `metrics`, and `traces` collected from the EventBus.

---

## 📡 3. Telemetry & Observability Backend

### AsyncIO Queues (`EventBus`)
The non-blocking nervous system of the agent.
*   **Why?** We decoupled tracing and metric-recording from the main execution thread. Instead of writing directly to a database mid-chat, components "fire and forget" an `Event` object onto an `asyncio.Queue`. A background worker (`EventCollector`) drains this queue sequentially.

### ContextVars (`contextvars`)
Native Python library to manage context state.
*   **Why?** Used to implement `Trace IDs`. Because an LLM request bounces through API routers, memory managers, embeddings, and tool executors asynchronously, we use context variables to tag every single logged event with a universal UUID so they can be visually stitched back together (request waterfalls) in the future React dashboard.

---

## 🕹️ 4. Automation & Interfaces

### FastAPI & Uvicorn (`fastapi`, `uvicorn`)
Modern, high-performance web framework.
*   **Why?** Serves as the primary background API for the agent. Exposes both REST endpoints (for standard queries) and WebSockets (allowing the future React dashboard to subscribe to a live, low-latency stream of every `Event` the agent emits in real-time).

### APScheduler (`apscheduler`)
Advanced Python task scheduling library.
*   **Why?** Powers the `HeartbeatSystem`. The agent needs to be "proactive"—not just responding to chats, but waking up independently. We run an `AsyncIOScheduler` inside the FastAPI `lifespan` block to trigger self-reflection, cron jobs, and email checks automatically.

### Prompt Toolkit & Rich (`prompt_toolkit`, `rich`)
Advanced command-line rendering libraries.
*   **Why?** The default Terminal interface. Provides syntax highlighting, markdown rendering, and interactive non-blocking prompt inputs when interacting with the agent directly through your CLI.
