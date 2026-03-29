# Primary Memory

This file stores long-term facts, decisions, and important information that should persist across sessions.

## System Information

### Hardware Configuration
- **GPU**: NVIDIA RTX 5090
- **Use Case**: Local LLM inference (Ollama) and embedding generation (sentence-transformers)
- **Performance**: ~2-3 second response time with Qwen2.5:32b

### Software Stack Decisions

#### 2026-02-13: Python vs TypeScript
**Decision**: Chose Python as primary language
**Rationale**:
- Better local AI library ecosystem (transformers, sentence-transformers, etc.)
- Easier GPU integration with PyTorch and CUDA
- Simpler setup for local-first operation
- More mature ML tooling

**Trade-offs**:
- TypeScript would allow direct OpenClaw fork
- Python async can be less elegant than Node.js
- Type safety requires mypy discipline

#### 2026-02-13: Qdrant vs SQLite for Vector DB
**Decision**: Chose Qdrant
**Rationale**:
- Better performance for vector similarity search
- Easier to scale if needed
- Excellent Python SDK
- Embedded mode runs in-process — no server, no containers required
- Production-grade features (snapshots, clustering)

**Trade-offs**:
- Slightly higher resource usage than SQLite
- Embedded storage path must be managed (auto-resets on corruption)

#### 2026-02-13: LiteLLM as LLM Router
**Decision**: Use LiteLLM for unified LLM interface
**Rationale**:
- Supports 100+ providers with consistent API
- Built-in fallback chains
- Cost tracking
- Async support
- Active development

**Configuration**:
```yaml
Primary: ollama/qwen2.5:32b (local)
Fallback 1: anthropic/claude-3-opus-20240229
Fallback 2: openai/gpt-4-turbo
```

## Project Architecture

### Memory System Design
- **Vector DB**: Qdrant embedded (in-process, persisted to `DATA_DIR`)
- **Embedding Model**: all-mpnet-base-v2 (768 dimensions, GPU-accelerated)
- **Search Strategy**: Hybrid (70% vector, 30% keyword)
- **Chunk Size**: 400 tokens with 80 token overlap
- **Storage**:
  - SOUL.md: Agent identity and values
  - USER.md: User profile and preferences
  - MEMORY.md: This file - long-term facts
  - memory/YYYY-MM-DD.md: Daily session logs
  - long_memory/: Archive for old important data

### Heartbeat System
- **Interval**: 30 minutes during active hours (08:00-22:00)
- **Scheduler**: APScheduler with cron and interval support
- **Integrations**:
  - Gmail: Check every 2 hours for urgent emails
  - Google Calendar: Check hourly, warn 2 hours ahead
  - Custom: Extensible for future sources

### Channel Architecture
- **Primary**: Telegram (for alerts and quick chat)
- **Secondary**: Discord (for project discussions)
- **Tertiary**: Terminal (for focused deep work)
- **API**: FastAPI backend for remote access

## Technical Learnings

### Ollama Optimization
- Qwen2.5:32b runs efficiently on RTX 5090
- Average response time: 2-3 seconds for conversational queries
- GPU utilization: ~60% during inference
- Context window: 128k tokens (though 8k is more efficient)

### Qdrant Best Practices
- Use HNSW index for fast approximate nearest neighbor search
- Batch upserts for better performance (32 vectors at a time)
- gRPC interface is faster than HTTP for high-throughput scenarios
- Keep collection size under 1M vectors for optimal performance on consumer hardware

### Embedding Generation
- sentence-transformers with all-mpnet-base-v2 gives good balance of quality and speed
- GPU acceleration essential for large document sets
- Batch size of 32 works well for RTX 5090
- Cache embeddings to avoid recomputation

## Important Contacts & Accounts

### API Keys & Tokens
- Telegram Bot: Stored in .env as TELEGRAM_BOT_TOKEN
- Discord Bot: Stored in .env as DISCORD_BOT_TOKEN
- Claude API: Stored in .env as ANTHROPIC_API_KEY (fallback only)
- OpenAI API: Stored in .env as OPENAI_API_KEY (fallback only)

### Service Accounts
- Gmail: Configured with OAuth2 for email monitoring
- Google Calendar: Same OAuth2 token for calendar access

## Recurring Tasks & Automations

### Daily
- **02:00**: Backup memory to Google Drive (encrypted)
- **08:00**: Morning briefing (email summary, calendar for today)
- **12:00**: Email check (urgent only)
- **18:00**: Email check (urgent only)

### Weekly
- **Sunday 00:00**: Memory consolidation (archive old daily logs)
- **Friday 18:00**: Weekly review and skill cleanup

### Monthly
- **1st of month**: Backup integrity check
- **15th of month**: Dependency updates check

## Code Patterns & Snippets

### Memory Search Pattern
```python
results = await agent.memory.search(
    query="What did we decide about vector databases?",
    top_k=6,
    min_score=0.35
)
for result in results:
    print(f"Score: {result['score']:.2f}")
    print(f"Source: {result['source']}")
    print(f"Text: {result['text'][:200]}...")
```

### LLM Call with Fallback
```python
response = await agent.llm.complete_with_fallback(
    prompt="Your prompt here",
    models=[
        "ollama/qwen2.5:32b",
        "anthropic/claude-3-opus-20240229"
    ],
    temperature=0.7
)
```

### Heartbeat Task Registration
```python
scheduler.add_job(
    check_urgent_emails,
    CronTrigger(hour='*/2'),  # Every 2 hours
    id='email_check'
)
```

## Future Improvements

### Planned Enhancements
- [ ] Skill auto-generation: Agent creates skills for itself
- [ ] Second brain dashboard: Web UI for memory exploration
- [ ] Obsidian integration: Sync memory to Obsidian vault
- [ ] Advanced MCP integrations: More MCP servers for specialized tools
- [ ] Voice interface: Whisper for transcription, TTS for responses

### Under Consideration
- Multi-agent collaboration (spawn specialized agents for complex tasks)
- RAG over external documentation (auto-index project docs)
- Proactive skill suggestions (agent recommends new skills based on usage)

## References & Resources

### Documentation
- [LiteLLM Docs](https://docs.litellm.ai/)
- [Qdrant Docs](https://qdrant.tech/documentation/)
- [sentence-transformers](https://www.sbert.net/)
- [Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md)

### Useful Repositories
- [OpenClaw](https://github.com/openclaw/openclaw) - Original inspiration
- [MCP Servers](https://github.com/modelcontextprotocol/servers) - Official MCP servers

### Learning Resources
- Local-first software principles
- Vector database performance tuning
- GPU optimization for transformers

---

**Version**: 1.0
**Created**: 2026-02-13
**Last Updated**: 2026-02-13

**Index**: decisions, architecture, technical-learnings, code-patterns
