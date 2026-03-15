# Implementation Plan: Memory System Foundation

## Task 1: Vector Store Setup
- **Objective:** Create a wrapper around `qdrant-client` to manage collections, upsert vectors, and query with metadata filtering.
- **Files:**
  - `tests/memory/test_vector_store.py`
  - `memory/vector_store.py`
- **Steps:**
  1. Write failing tests in `tests/memory/test_vector_store.py` testing collection creation, point upsertion, and querying (with and without metadata filters).
  2. Implement `VectorStore` in `memory/vector_store.py` using `qdrant_client.QdrantClient`. Default to `location=":memory:"`.
  3. Run `pytest tests/memory/test_vector_store.py -v` to ensure tests pass.
  4. Refactor if necessary.

## Task 2: Embedding Search
- **Objective:** Set up `sentence-transformers` locally to convert text to embeddings.
- **Files:**
  - `tests/memory/test_search.py`
  - `memory/search.py`
- **Steps:**
  1. Write failing tests in `tests/memory/test_search.py` for an `EmbeddingService` that generates embeddings from text. Mock the model for fast execution in tests.
  2. Implement `EmbeddingService` in `memory/search.py` using `sentence_transformers.SentenceTransformer`. Use a small model like `all-MiniLM-L6-v2` by default.
  3. Run `pytest tests/memory/test_search.py -v` to ensure tests pass.

## Task 3: Memory Manager and Telemetry
- **Objective:** Orchestrate episodic and semantic memory collections, score results (similarity + recency + importance), and emit telemetry events.
- **Files:**
  - `tests/memory/test_memory_manager.py`
  - `memory/memory_manager.py`
- **Steps:**
  1. Write failing tests in `tests/memory/test_memory_manager.py` testing `MemoryManager` initialization (creates "episodic" and "semantic" collections), adding memories, retrieving memories with scoring (combining similarity, recency, and importance), and emitting `MEMORY_QUERY`, `MEMORY_HIT`, and `MEMORY_MISS` telemetry events.
  2. Implement `MemoryManager` in `memory/memory_manager.py`. It should coordinate `VectorStore`, `EmbeddingService`, and `core.telemetry.EventBus`.
  3. Run `pytest tests/memory/test_memory_manager.py -v` to ensure tests pass.
  4. Verify the entire memory suite: `pytest tests/memory -v`.

## Final Verification
Run type checking and linting across the entire module.
- `ruff check memory/ tests/memory/`
- `mypy memory/ tests/memory/`
