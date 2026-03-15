# Directive 004: Memory System Foundation

## Objective
Build the memory and context retrieval system. The agent requires vector search (via Qdrant) and embedded documents (via `sentence-transformers`) to retrieve past interactions and knowledge. This directive separates episodic and semantic memory into distinct implementations.

## File Ownership & Boundaries (CRITICAL FOR PARALLEL EXECUTION)
**Allowed to modify/create:**
- `memory/vector_store.py` (Qdrant client wrapper)
- `memory/search.py` (Embedding and retrieval logic)
- `memory/memory_manager.py` (High-level memory orchestration)
- `tests/memory/test_vector_store.py`
- `tests/memory/test_search.py`
- `tests/memory/test_memory_manager.py`

**OFF-LIMITS (Do NOT modify):**
- `core/llm.py`
- `core/telemetry.py` (You may IMPORT it to emit events like `MEMORY_HIT`, but do not change it)
- `api/*`

## Acceptance Criteria
- [x] Setup `qdrant-client` local in-memory or file-based instance in `memory/vector_store.py`.
- [x] Implement a `VectorStore` class capable of creating collections, upserting vectors, and querying with metadata filtering.
- [x] Set up `sentence-transformers` locally to convert text to embeddings in `memory/search.py`.
- [x] Implement two distinct collection definitions: one for Episodic memory (conversations) and one for Semantic memory (facts/preferences).
- [x] The memory manager must score results based on similarity + recency + importance.
- [x] Emit `MEMORY_QUERY`, `MEMORY_HIT`, and `MEMORY_MISS` telemetry events.
- [x] Develop comprehensive tests for all logic, mocking Qdrant heavily if needed to ensure fast test execution.
- [x] No direct coupling to the LLM layer.

## Development Methodology Reminder
Follow the rules in `AGENTS.md` strictly:
1. Write an implementation plan first (`docs/plans/...`).
2. TDD Iron Law: NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
3. Verify via running the tests. Do not guess.
