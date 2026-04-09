"""Tests for Phase D — semantic skill routing.

Covers:
- set_embedder() backfills embeddings for all already-registered skills
- Skills registered AFTER set_embedder() are embedded immediately
- get_relevant_schemas() ranks by semantic similarity when embedder available
- Paraphrase of a skill description returns the correct skill
- Fallback to keyword-only when embedder absent
- Generated skills ranked correctly via semantic score
"""

from __future__ import annotations

import math

from skills.registry import SkillRegistry, _cosine_similarity

# ---------------------------------------------------------------------------
# Minimal mock embedder
# ---------------------------------------------------------------------------

class _VectorEmbedder:
    """Deterministic mock embedder for testing.

    Maps exact text strings to predetermined 3-D vectors.  Any text not in
    the mapping returns a zero vector so it scores 0 against everything.
    """

    def __init__(self, mapping: dict[str, list[float]]) -> None:
        self._mapping = mapping

    def encode(self, text: str) -> list[float]:
        return list(self._mapping.get(text, [0.0, 0.0, 0.0]))


def _norm(v: list[float]) -> list[float]:
    """Return the unit-normalised version of *v*."""
    mag = math.sqrt(sum(x * x for x in v))
    if mag == 0:
        return v
    return [x / mag for x in v]


# Pre-set unit vectors used across tests
_V_GITHUB  = _norm([1.0, 0.0, 0.0])
_V_EMAIL   = _norm([0.0, 1.0, 0.0])
_V_WEATHER = _norm([0.0, 0.0, 1.0])
_V_QUERY_GITHUB  = _norm([0.95, 0.05, 0.0])  # close to _V_GITHUB
_V_QUERY_WEATHER = _norm([0.05, 0.0, 0.95])  # close to _V_WEATHER


def _make_embedder() -> _VectorEmbedder:
    return _VectorEmbedder({
        # Skill descriptions
        "Fetch and summarize GitHub pull requests": _V_GITHUB,
        "Send an email to a recipient":             _V_EMAIL,
        "Get the current weather forecast":         _V_WEATHER,
        # Query strings
        "pull request summary":     _V_QUERY_GITHUB,
        "what is the weather like": _V_QUERY_WEATHER,
    })


def _make_large_registry(embedder=None) -> SkillRegistry:
    """11 filler skills + 3 target skills → routing threshold exceeded."""
    reg = SkillRegistry()
    if embedder:
        reg.set_embedder(embedder)

    # Filler — neutral descriptions get zero vector from mock embedder
    for i in range(11):
        def _fn(**kwargs): return ""
        reg.register(f"filler_{i}", f"Filler skill number {i}", _fn)

    # Targets
    def _gh(**kwargs): return ""
    def _em(**kwargs): return ""
    def _wt(**kwargs): return ""
    reg.register("github_pr", "Fetch and summarize GitHub pull requests", _gh)
    reg.register("send_email", "Send an email to a recipient", _em)
    reg.register("get_weather", "Get the current weather forecast", _wt)
    return reg


# ---------------------------------------------------------------------------
# _cosine_similarity unit tests
# ---------------------------------------------------------------------------

def test_cosine_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert abs(_cosine_similarity(v, v) - 1.0) < 1e-9


def test_cosine_orthogonal_vectors():
    assert abs(_cosine_similarity([1, 0, 0], [0, 1, 0])) < 1e-9


def test_cosine_zero_vector_returns_zero():
    assert _cosine_similarity([0.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# set_embedder() backfill
# ---------------------------------------------------------------------------

def test_set_embedder_backfills_existing_skills():
    """Skills registered before set_embedder() must receive embeddings on the call."""
    reg = SkillRegistry()

    def _fn(**kwargs): return ""
    reg.register("github_pr", "Fetch and summarize GitHub pull requests", _fn)
    reg.register("send_email", "Send an email to a recipient", _fn)

    # No embedder yet
    assert reg.get_registration("github_pr").description_embedding is None
    assert reg.get_registration("send_email").description_embedding is None

    reg.set_embedder(_make_embedder())

    assert reg.get_registration("github_pr").description_embedding == _V_GITHUB
    assert reg.get_registration("send_email").description_embedding == _V_EMAIL


def test_set_embedder_embeds_skills_registered_after():
    """Skills registered AFTER set_embedder() are embedded immediately."""
    reg = SkillRegistry()
    reg.set_embedder(_make_embedder())

    def _fn(**kwargs): return ""
    reg.register("get_weather", "Get the current weather forecast", _fn)

    assert reg.get_registration("get_weather").description_embedding == _V_WEATHER


def test_set_embedder_handles_unknown_description_gracefully():
    """A description not in the mock mapping gets a zero vector, not an exception."""
    reg = SkillRegistry()
    reg.set_embedder(_make_embedder())

    def _fn(**kwargs): return ""
    reg.register("unknown_skill", "Some completely unmapped description text", _fn)

    # Mock returns [0,0,0] for unknown text — should not raise
    emb = reg.get_registration("unknown_skill").description_embedding
    assert emb is not None
    assert all(v == 0.0 for v in emb)


# ---------------------------------------------------------------------------
# Semantic routing — correct skill selected for paraphrase query
# ---------------------------------------------------------------------------

def test_semantic_routing_paraphrase_github():
    """Query 'pull request summary' (paraphrase) should rank github_pr first."""
    reg = _make_large_registry(embedder=_make_embedder())
    results = reg.get_relevant_schemas("pull request summary", max_tools=3)
    names = [s["name"] for s in results]
    assert "github_pr" in names, f"Expected github_pr in top-3, got: {names}"
    assert names[0] == "github_pr", f"Expected github_pr ranked first, got: {names}"


def test_semantic_routing_paraphrase_weather():
    """Query 'what is the weather like' should rank get_weather first."""
    reg = _make_large_registry(embedder=_make_embedder())
    results = reg.get_relevant_schemas("what is the weather like", max_tools=3)
    names = [s["name"] for s in results]
    assert "get_weather" in names, f"Expected get_weather in top-3, got: {names}"
    assert names[0] == "get_weather", f"Expected get_weather ranked first, got: {names}"


def test_semantic_routing_works_for_skills_registered_at_import_time():
    """Skills registered before set_embedder() are correctly ranked after backfill."""
    reg = SkillRegistry()

    # Register first (simulates import-time registration like built-in skills)
    def _fn(**kwargs): return ""
    for i in range(11):
        reg.register(f"filler_{i}", f"Filler skill number {i}", _fn)
    reg.register("github_pr", "Fetch and summarize GitHub pull requests", _fn)
    reg.register("get_weather", "Get the current weather forecast", _fn)

    # Embedder injected later (simulates main.py wiring after memory init)
    reg.set_embedder(_make_embedder())

    results = reg.get_relevant_schemas("pull request summary", max_tools=3)
    names = [s["name"] for s in results]
    assert "github_pr" in names
    assert names[0] == "github_pr"


# ---------------------------------------------------------------------------
# Fallback to keyword-only when no embedder
# ---------------------------------------------------------------------------

def test_keyword_fallback_when_no_embedder():
    """Without an embedder, routing still works via keyword overlap."""
    reg = SkillRegistry()

    def _fn(**kwargs): return ""
    for i in range(11):
        reg.register(f"filler_{i}", f"Filler skill number {i}", _fn)
    reg.register("read_file", "Read file contents from disk", _fn)

    # No embedder set
    results = reg.get_relevant_schemas("read file from disk", max_tools=5)
    names = [s["name"] for s in results]
    assert "read_file" in names


def test_keyword_fallback_when_embedder_encode_fails():
    """If embedder.encode raises, routing falls back to keyword silently."""
    class _BrokenEmbedder:
        def encode(self, text: str) -> list[float]:
            raise RuntimeError("embedding service down")

    reg = SkillRegistry()

    def _fn(**kwargs): return ""
    for i in range(11):
        reg.register(f"filler_{i}", f"Filler skill number {i}", _fn)
    reg.register("bash_exec", "Execute a bash shell command", _fn)

    reg.set_embedder(_BrokenEmbedder())

    # Should not raise; keyword fallback handles it
    results = reg.get_relevant_schemas("bash shell command", max_tools=5)
    names = [s["name"] for s in results]
    assert "bash_exec" in names


# ---------------------------------------------------------------------------
# Small registry (≤ 10) — routing still skipped
# ---------------------------------------------------------------------------

def test_small_registry_returns_all_even_with_embedder():
    """With ≤ 10 skills, all schemas are returned regardless of embedder."""
    reg = SkillRegistry()
    reg.set_embedder(_make_embedder())

    def _fn(**kwargs): return ""
    for i in range(5):
        reg.register(f"skill_{i}", f"Description {i}", _fn)

    results = reg.get_relevant_schemas("anything", max_tools=10)
    assert len(results) == 5
