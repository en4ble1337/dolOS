# Self-Improving Agent — Implementation Plan

**Goal:** Close the "gets better over time" gap between dolOS and Hermes Agent  
**Reference:** https://github.com/NousResearch/hermes-agent  
**Branch target:** `feature/self-improving` (branch off `main` after claw-gaps merge)  
**Date:** 2026-04-08

---

## Context & Motivation

Hermes Agent's primary differentiator is a **closed learning loop**:

> "The only agent that creates skills from experience, improves them during use, nudges itself to persist knowledge, searches its own past conversations, and builds a deepening model of who you are across sessions."

dolOS already has most of the *infrastructure* (skill writing, memory extractors, transcript store, lesson extractor). What it lacks is the *automation* — nothing triggers these systems from task outcomes. Every turn ends and the system moves on without asking: "What just happened that I should remember or codify?"

The loop we want to close:

```
Task completes
    → Was there a reusable pattern?   → write skill → future turns find & reuse it
    → Did something go wrong?         → auto-fix generated skill
    → What should I know long-term?   → already done (SemanticExtractor ✅)
    → What did the user prefer?       → already done (LessonExtractor ✅)
    → Who is this user, broadly?      → UserProfileExtractor (missing)
    → What happened in past sessions? → cross-session memory (already works ✅)
    → Can I find past transcripts?    → FTS5 index (missing)
```

**Hermes's Repo Structure (reference):**
- `agent/` — core loop + skill extraction trigger
- `skills/` — built-in skills; user skills at `~/.hermes/skills/`
- `gateway/` — multi-platform messaging
- `cron/` — scheduler
- `batch_runner.py` / `trajectory_compressor.py` — RL trajectory export

---

## Current State Inventory

| Capability | Status | File |
|---|---|---|
| Write new skills dynamically | ✅ Done | `skills/local/meta.py` — `create_skill`, `fix_skill` |
| Skill hot-load without restart | ✅ Done | `skills/local/meta.py` — `importlib` hot-reload |
| Skill execution with timeout | ✅ Done | `skills/executor.py` — `SkillExecutor.execute()` |
| Skill routing by keyword | ✅ Done | `skills/registry.py` — `get_relevant_schemas()` |
| Semantic fact extraction | ✅ Done | `memory/semantic_extractor.py` — per turn |
| Lesson / correction extraction | ✅ Done | `memory/lesson_extractor.py` — per turn |
| Lesson consolidation heartbeat | ✅ Done | `heartbeat/integrations/reflection_task.py` — every 5 min |
| Episodic + semantic memory search | ✅ Done | `memory/memory_manager.py` — vector similarity (no session filter) |
| Raw transcript store (JSONL) | ✅ Done | `data/transcripts/{session_id}.jsonl` |
| Episodic memory pruning heartbeat | ✅ Done | `heartbeat/integrations/memory_maintenance.py` — weekly TTL eviction |
| USER.md indexed into semantic memory | ✅ Done | `main.py:104` — `StaticFileLoader` at startup |
| Background tasks after each turn | ✅ Done | `core/agent.py:471` — `_schedule_background_tasks()` |
| **Skill auto-trigger from tasks** | ❌ Missing | No post-turn skill extraction trigger |
| **Skill self-improvement on failure** | ❌ Missing | `fix_skill` is manual only |
| **Generated skill safety metadata** | ❌ Missing | Auto-generated skills inherit `is_read_only=True, concurrency_safe=True` defaults — wrong for mutating skills |
| **Generated skill quarantine** | ❌ Missing | `create_skill()` writes + imports immediately; no quarantine/replay/promotion gate |
| **Full-text transcript search** | ❌ Missing | JSONL exists, no index |
| **Semantic skill routing** | ❌ Missing | Keyword overlap only; no backfill for skills registered before embedder is wired |
| **User behavioral profile** | ❌ Missing | Lessons capture corrections; no synthesized profile; USER.md exists but not updated at runtime |

> **Correction from original draft:** `memory.search()` is already called without `filter_metadata` in `core/agent.py:151-155` for both episodic and semantic. Cross-session retrieval already works. Phase A no longer needs to "remove the session filter" — it should instead define *scoping rules* and *principal boundaries* for multi-session or multi-channel deployments.

---

## Target Architecture

```
After every agent turn:
┌──────────────────────────────────────────────────┐
│  _schedule_background_tasks()  [core/agent.py]   │
│                                                  │
│  ├── CombinedTurnExtractor (existing)            │
│  │     facts → semantic memory                   │
│  │     corrections → lessons + semantic memory   │
│  │                                               │
│  ├── SkillExtractionTask (NEW — Phase B)         │
│  │     if tool_call_count >= 3:                  │
│  │       LLM: "Was there a reusable pattern?"    │
│  │       if yes → create_skill() autonomously   │
│  │                                               │
│  └── UserProfileExtractor (NEW — Phase E)        │
│        update persistent USER.md profile         │
└──────────────────────────────────────────────────┘

On skill execution failure (skills/executor.py):
┌──────────────────────────────────────────────────┐
│  if generated skill fails:                       │
│    → read source via fix_skill()                 │
│    → LLM diagnoses error                         │
│    → rewrite via create_skill()  (NEW — Phase C) │
└──────────────────────────────────────────────────┘

On memory search:
┌──────────────────────────────────────────────────┐
│  Session filter already absent — no change needed│
│  Add principal scoping for multi-channel use     │
│  Add SQLite FTS5 transcript search  (NEW — Phase F)│
└──────────────────────────────────────────────────┘

On generated skill execution:
┌──────────────────────────────────────────────────┐
│  Quarantine: write to generated/staging/ first   │
│  Replay validation: execute against test input   │
│  Promotion: move to generated/ only on success   │
│  (NEW — Phase B-safety gate)                     │
└──────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase A — Memory Scoping Model + Principal Boundaries

**Why first:** The original plan assumed cross-session retrieval was broken and needed fixing. It isn't — `core/agent.py:151-155` already calls `memory.search()` without any `filter_metadata` for both episodic and semantic. The real Phase A work is defining *scoping rules* so that as skills, profiles, and transcripts accumulate across multiple channels (Telegram, Discord, API), the system doesn't silently cross-contaminate sessions.

**Effort:** ~3 hours  
**Risk:** Low — metadata enrichment only; no read-path changes needed

#### A1. Establish `principal_id` in memory metadata

Define a `principal_id` convention for memory entries:
- Single-operator deployment (current): all entries share the same implicit principal, no change needed. Document this assumption explicitly.
- Multi-channel / multi-user: entries should carry `{"principal_id": <user_id>}` in `filter_metadata` so cross-session retrieval can be scoped per user.

**File:** `memory/memory_manager.py`

Add a `search_cross_session()` named alias that explicitly signals no session filter, for future call-site clarity:
```python
def search_cross_session(self, query, memory_type, limit=8, principal_id=None, ...):
    filter_md = {"principal_id": principal_id} if principal_id else None
    return self.search(query=query, memory_type=memory_type, limit=limit, filter_metadata=filter_md, ...)
```

Existing call sites in `core/agent.py` pass no filter — this is already correct for single-operator deployment. No changes needed there.

#### A2. Extend existing retention policy (do not duplicate)

**Do NOT create a new `memory/retention_policy.py`.** The weekly episodic eviction is already implemented in `heartbeat/integrations/memory_maintenance.py:18` (`MemoryMaintenanceTask`). Extend it instead:

- Add `max_semantic_count: int = 5000` param — when semantic collection exceeds this, evict lowest-importance entries
- Add `semantic_retention_days: int = 365` — semantic facts older than this and below threshold are pruned

This keeps one maintenance code path instead of two overlapping ones.

**Tests:** Extend `tests/heartbeat/test_memory_maintenance.py` for the new semantic eviction logic (do not create a separate test file)

---

### Phase A2 — Generated Skill Safety Gate (prerequisite for B and C)

**Why before B/C:** `skills/local/meta.py:67` writes and imports generated skills immediately. One bad extraction becomes durable behavior before it proves it works. Additionally, `skills/registry.py:25,28` defaults all skills to `is_read_only=True, concurrency_safe=True` — auto-generated skills that mutate state will be silently mislabeled and may be executed concurrently in `core/agent.py:333-344`.

**Effort:** ~half day  
**Risk:** Medium — touches `create_skill` and `executor`; existing manual create_skill flow also benefits

#### A2a. Explicit safety metadata in extraction contract

All generated skill LLM prompts (Phase B) must include `is_read_only` and `concurrency_safe` in the JSON schema:

```json
{
  "should_create": true,
  "name": "...",
  "description": "...",
  "code": "...",
  "is_read_only": false,        // ← required field; LLM must reason about this
  "concurrency_safe": false     // ← required field; default false for generated skills
}
```

**File:** `skills/local/meta.py` — `create_skill()` signature gains `is_read_only: bool = False, concurrency_safe: bool = False`. Generated skills default to **not** read-only and **not** concurrency-safe. This is the conservative, safe direction. Built-in skills keep their existing explicit declarations.

#### A2b. Quarantine + replay before promotion

**File:** `skills/local/meta.py`

New flow for auto-generated skills (manual `create_skill()` can bypass with `quarantine=False`):

1. Write to `skills/local/generated/staging/{name}.py` (not live)
2. Import into an isolated module namespace (don't register yet)
3. Execute against a synthetic no-op test input (`handler()` with empty kwargs, max 2s timeout)
4. If execution completes without exception → promote: move to `skills/local/generated/{name}.py` and register
5. If execution fails → log failure, leave in staging, surface to user but do not crash

This adds ~200ms to skill creation (only fires on new generated skills, not every turn).

**Tests:** `tests/skills/test_skill_auto_fix.py` should cover quarantine → staging, promotion, and staging-only failure path

**Why:** This is Hermes's headline feature. `create_skill` exists but nothing ever calls it without a human asking. Close the loop.

**Effort:** ~1 day  
**Risk:** Medium — LLM call per turn (only when tool_count >= threshold)

#### B1. SkillExtractionTask

**File:** `memory/skill_extractor.py` (new)

```python
class SkillExtractionTask:
    """Post-turn task that evaluates whether a reusable skill should be written.
    
    Fires when a turn used >= MIN_TOOL_CALLS tools (default: 3).
    Single LLM call with structured JSON output.
    If a skill is identified, calls create_skill() autonomously.
    Deduplication: checks existing skill names + descriptions before writing.
    """
    
    MIN_TOOL_CALLS = 3  # don't fire on trivial turns
    
    async def evaluate_and_extract(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        tool_calls_made: list[str],  # list of tool names called this turn
        trace_id: str,
    ) -> int:  # returns count of skills created
```

**Prompt structure** (reference Hermes's approach — skills created after "complex tasks"):
```
You just completed a task using these tools: {tool_calls_made}

User asked: {user_message}
You responded: {assistant_response[:500]}

Evaluate: Was there a REUSABLE multi-step pattern here that would benefit from a dedicated skill?

A good skill candidate:
- Combines 3+ tool calls in a non-obvious way
- Would be needed again for similar requests
- Is self-contained (no session-specific context needed)
- Is not already covered by existing skills: {existing_skill_names}

Return JSON:
{
  "should_create": true/false,
  "reason": "...",
  "name": "snake_case_name",          // only if should_create=true
  "description": "one sentence",       // only if should_create=true  
  "code": "async def handler(**kwargs): ...",  // only if should_create=true
  "is_read_only": false,              // required — true ONLY if skill reads but never writes/deletes/sends
  "concurrency_safe": false           // required — true ONLY if safe to run in parallel with itself
}

If no skill should be created, return {"should_create": false, "reason": "..."}.

> **Note:** `is_read_only` and `concurrency_safe` must be explicit in every extraction. Default to `false` for both. The LLM should reason about the skill's effects to determine correctness.
```

**Deduplication:** Before writing, embed the proposed description and check similarity against existing skill descriptions in registry. If similarity > 0.85, skip.

**File:** `core/agent.py` — `_schedule_background_tasks()`

Add after existing extractors:
```python
if self.skill_extractor and len(tool_calls_made_this_turn) >= SkillExtractionTask.MIN_TOOL_CALLS:
    asyncio.create_task(
        self.skill_extractor.evaluate_and_extract(
            session_id=session_id,
            user_message=user_message,
            assistant_response=assistant_response,
            tool_calls_made=tool_calls_made_this_turn,
            trace_id=trace_id,
        )
    )
```

Note: `tool_calls_made_this_turn` needs to be collected in the agent loop. Currently tool names are logged but not passed to `_schedule_background_tasks`. Add a local list in the loop body.

**Wire into `main.py`:** Initialize `SkillExtractionTask` with `llm`, `registry`, `skill_executor`. Inject into `Agent`.

**New EventType entries needed:**
- `SKILL_EXTRACTION_START`
- `SKILL_EXTRACTION_SKIP` (below threshold or no pattern)
- `SKILL_EXTRACTION_DUPLICATE` (similar skill exists)
- `SKILL_EXTRACTION_CREATED`
- `SKILL_EXTRACTION_ERROR`

**Tests:** `tests/memory/test_skill_extractor.py`
- Test: turns with < MIN_TOOL_CALLS don't fire
- Test: LLM returning `should_create=false` is handled
- Test: duplicate skill names are detected and skipped
- Test: valid skill is written and registered
- Test: LLM failure doesn't crash the agent

---

### Phase C — Skill Self-Improvement on Failure

**Why:** Generated skills can be wrong or break on edge cases. Currently the error is returned as text and the skill stays broken forever. Hermes refines skills automatically during use.

**Effort:** ~half day  
**Risk:** Low — only fires on generated skill failures

#### C1. Auto-fix hook in SkillExecutor

**File:** `skills/executor.py`

Current error handling (line ~75):
```python
except asyncio.TimeoutError:
    error_msg = f"Timeout Error: Skill '{name}' exceeded {self.timeout} seconds."
    if (_GENERATED_DIR / f"{name}.py").exists():
        error_msg += f" — Call fix_skill(name='{name}') to retrieve..."
```

Extend this pattern for all error types when the skill is in `generated/`:

```python
async def _attempt_auto_fix(self, name: str, error: str, kwargs: dict) -> str | None:
    """For generated skills only: read source, ask LLM to fix, rewrite.
    Returns fixed result or None if fix failed."""
```

Flow:
1. Detect that failed skill is in `skills/local/generated/{name}.py`
2. Read current source via `fix_skill(name)`
3. Single LLM call: "This skill failed with error X. Here is the source. Return corrected Python."
4. Call `create_skill(name=name, description=existing_desc, code=fixed_code)` to overwrite (goes through quarantine/staging gate from Phase A2b)
5. **Only re-execute if skill is `is_read_only=True`.** For mutating skills (file writes, shell commands, API calls), surface the fix to the user and ask them to re-invoke rather than auto-retrying. A partially completed side-effecting action run twice can cause data corruption or double-sends.
6. Return result or surface the failure cleanly

**Guard:** Max 1 auto-fix attempt per execution (no infinite retry). Track with a `_fix_attempted: set[str]` in the executor instance, cleared each session.

**New EventType entries:**
- `SKILL_AUTO_FIX_ATTEMPT`
- `SKILL_AUTO_FIX_SUCCESS`
- `SKILL_AUTO_FIX_FAILED`

**Tests:** `tests/skills/test_skill_auto_fix.py`
- Test: built-in skills never trigger auto-fix
- Test: generated skill timeout → fix attempted
- Test: fix succeeds → re-execution returns result
- Test: fix fails → original error returned cleanly

---

### Phase D — Semantic Skill Routing

**Why:** The current keyword-overlap router (`get_relevant_schemas`) will miss generated skills when the user's phrasing differs from the skill name. If the agent creates a skill called `fetch_github_pr_summary` and the user asks "pull up the latest PR details," keyword overlap will score low. Semantic search fixes this.

**Effort:** ~half day  
**Risk:** Low — additive change; fallback to keyword if embedding fails

#### D1. Embed skill descriptions at registration time

**File:** `skills/registry.py`

Add optional embedding storage to `SkillRegistration`:
```python
@dataclass
class SkillRegistration:
    ...
    description_embedding: list[float] | None = None  # set at registration if embedder available
```

Add `set_embedder(embedding_service)` to `SkillRegistry` so `main.py` can inject the shared embedding service after initialization.

On `register()`, if embedder is set:
```python
self._registrations[name].description_embedding = self.embedder.encode(description)
```

**Backfill on `set_embedder()`:** Built-in skills are imported and registered before `memory` (and thus the embedder) is available in `main.py`. When `set_embedder()` is called, immediately embed all currently-registered skills that have `description_embedding=None`:

```python
def set_embedder(self, embedder):
    self.embedder = embedder
    for reg in self._registrations.values():
        if reg.description_embedding is None:
            reg.description_embedding = self.embedder.encode(reg.description)
```

Without this backfill, semantic routing silently falls back to keyword matching for all built-in skills.

#### D2. Semantic `get_relevant_schemas()`

**File:** `skills/registry.py`

Extend `get_relevant_schemas(query, max_tools)`:
1. If embedder is available: embed query, compute cosine similarity against all description embeddings, rank by similarity
2. Fallback to keyword overlap if embedder unavailable or all embeddings are None
3. Blend: score = 0.7 * semantic_similarity + 0.3 * keyword_overlap (configurable)

**Tests:** `tests/skills/test_semantic_routing.py`
- Test: paraphrase of skill description returns correct skill
- Test: fallback to keyword works when embedder absent
- Test: generated skills are ranked correctly

---

### Phase E — User Profile / Behavioral Modeling

**Why:** Hermes builds "a deepening model of who you are across sessions" via Honcho. dolOS's `LessonExtractor` captures corrections per-turn but produces a flat list of lessons, not a synthesized behavioral profile. Over time the lessons list grows and the agent gets noisy signal.

**Effort:** ~1 day  
**Risk:** Low — new file, optional component

#### E1. UserProfileExtractor

**File:** `memory/user_profile_extractor.py` (new)

Inspired by Honcho's dialectic framework: rather than just storing raw corrections, maintain a living `data/USER.md` profile document that gets updated and consolidated.

```python
class UserProfileExtractor:
    """Maintains a structured USER.md profile that captures:
    - Communication preferences (verbosity, tone, format)
    - Technical profile (languages, tools, expertise level)
    - Work context (current projects, goals, constraints)
    - Interaction patterns (what they correct most, what they like)
    
    Updated after every N turns (not every turn — too expensive).
    Uses prior USER.md as context to avoid full rewrite each time.
    """
    
    UPDATE_EVERY_N_TURNS = 10
    
    async def maybe_update(self, session_id: str, recent_turns: list[dict], trace_id: str):
        ...
```

**Prompt approach** (dialectic = ask the agent to reason about the user, not just extract facts):
```
You maintain a profile of this user to serve them better. 

Current profile:
{current_user_md}

Recent conversation (last 10 turns):
{recent_turns_summary}

Update the profile. Add/modify/remove sections based on what you learned.
Return the complete updated USER.md. Sections: Communication Style, Technical Profile, 
Current Work Context, Interaction Preferences, Things to Always/Never Do.
```

**File:** `data/USER.md` — already exists and is indexed at startup via `main.py:104`. Updated incrementally at runtime.

**Injection:** `data/USER.md` is already indexed into semantic memory at startup (`StaticFileLoader`). It's also available via direct file read for system prompt injection alongside `SOUL.md`. **Do not inject both ways without a sync plan** — semantic memory and prompt context will diverge if the file is updated at runtime.

**Sync on update:** After writing an updated `USER.md`, call `_static_loader.index_file("data/USER.md", source_tag="user_profile")` to re-index. The `StaticFileLoader` must first evict the previous chunks for that `source_tag` before re-indexing (add `evict_by_source_tag()` to `StaticFileLoader`). This ensures semantic search doesn't serve stale profile chunks alongside fresh ones.

**Wire into:** `_schedule_background_tasks()` with a turn counter gate (every `UPDATE_EVERY_N_TURNS` turns). Do not use heartbeat — profile update needs the turn's conversation context.

**Tests:** `tests/memory/test_user_profile_extractor.py`

---

### Phase F — FTS5 Transcript Search

**Why:** Hermes uses "FTS5 session search with LLM summarization for cross-session recall." dolOS stores all transcripts as JSONL at `data/transcripts/{session_id}.jsonl` but there's no way to search them by content. The vector memory captures summaries/facts but misses verbatim recall ("what exactly did I say about X three sessions ago").

**Effort:** ~half day  
**Risk:** Low — new index layer, existing JSONL unaffected

#### F1. TranscriptIndex

**File:** `memory/transcript_index.py` (new)

SQLite with FTS5 virtual table — zero new dependencies (SQLite3 is stdlib):

```python
class TranscriptIndex:
    """SQLite FTS5 index over all transcript JSONL files.
    
    Schema:
        CREATE VIRTUAL TABLE transcript_fts USING fts5(
            session_id, entry_type, content, timestamp UNINDEXED
        );
    
    Built incrementally — tracks last-indexed row_id per session file so
    appends don't re-index existing content.
    Rebuilds on startup if schema version mismatches.
    """
    
    def index_session(self, session_id: str, jsonl_path: Path) -> int:
        """Append new entries since last index position. Returns count added."""
    
    def append_entry(self, session_id: str, entry: dict) -> None:
        """Index a single entry immediately after it is written to JSONL.
        Called by TranscriptStore.append() so the index stays current."""
    
    def search(self, query: str, limit: int = 10) -> list[dict]:
        """FTS5 MATCH query across all sessions. Returns ranked results."""
    
    def index_all(self, transcripts_dir: Path) -> int:
        """Synchronous bulk index of all JSONL files. Called once at startup
        in a thread pool executor — NOT wrapped in asyncio.create_task()
        directly (it is not a coroutine)."""
```

**Incremental indexing:** `TranscriptIndex.append_entry()` must be called from `TranscriptStore.append()` (or `core/agent.py`'s `_append_transcript()`) so every new entry is indexed immediately. Startup `index_all()` only catches entries written before the index was created (first run or schema migration).

**Async wrapper:** `index_all()` is synchronous (SQLite writes). Schedule it at startup with:
```python
loop.run_in_executor(None, transcript_index.index_all, Path("data/transcripts"))
```
Not `asyncio.create_task()` — that requires a coroutine.

**File:** `skills/local/memory.py`

Add `search_transcripts(query, limit)` skill:
```python
@skill(name="search_transcripts", description=(
    "Full-text search across all past conversation transcripts. "
    "Use when you need to recall exactly what was said in a previous session. "
    "Complements search_memory (which uses vector similarity)."
))
async def search_transcripts(query: str, limit: int = 10) -> str: ...
```

**Wire into `main.py`:** Initialize `TranscriptIndex`, index on startup (background task), inject into `skills/local/memory.py`.

**Tests:** `tests/memory/test_transcript_index.py`

---

## Wiring Summary — `main.py` changes

```python
# Phase A — no filter changes needed (already correct); extend MemoryMaintenanceTask
# memory_manager.search_cross_session() added as named alias only

# Phase A2 — quarantine gate; no main.py change; logic inside create_skill()

# Phase B
from memory.skill_extractor import SkillExtractionTask
skill_extractor = SkillExtractionTask(llm=llm, registry=_default_registry, skill_executor=skill_executor)
# inject into Agent.__init__

# Phase C
# SkillExecutor gets reference to llm for auto-fix
skill_executor = SkillExecutor(event_bus=event_bus, registry=_default_registry, llm=llm)

# Phase D — MUST come after memory init so backfill runs on all already-registered skills
_default_registry.set_embedder(memory_manager.embedding_service)

# Phase E
from memory.user_profile_extractor import UserProfileExtractor
user_profile_extractor = UserProfileExtractor(
    llm=llm, profile_path="data/USER.md", static_loader=_static_loader, event_bus=event_bus
)
# inject into Agent.__init__

# Phase F
from memory.transcript_index import TranscriptIndex
transcript_index = TranscriptIndex(db_path="data/transcript_index.db")
# Synchronous bulk index at startup — run in thread pool, not asyncio.create_task()
loop.run_in_executor(None, transcript_index.index_all, Path("data/transcripts"))
# inject into skills/local/memory.py via set_transcript_index()
# inject into TranscriptStore so append_entry() is called on each new write
```

---

## Agent `__init__` additions

```python
class Agent:
    def __init__(
        self,
        ...
        skill_extractor: SkillExtractionTask | None = None,   # Phase B
        user_profile_extractor: UserProfileExtractor | None = None,  # Phase E
    ):
```

---

## New EventType entries (core/telemetry.py)

```python
# Phase B
SKILL_EXTRACTION_START = "skill_extraction_start"
SKILL_EXTRACTION_SKIP = "skill_extraction_skip"
SKILL_EXTRACTION_DUPLICATE = "skill_extraction_duplicate"
SKILL_EXTRACTION_CREATED = "skill_extraction_created"
SKILL_EXTRACTION_ERROR = "skill_extraction_error"

# Phase C
SKILL_AUTO_FIX_ATTEMPT = "skill_auto_fix_attempt"
SKILL_AUTO_FIX_SUCCESS = "skill_auto_fix_success"
SKILL_AUTO_FIX_FAILED = "skill_auto_fix_failed"

# Phase E
USER_PROFILE_UPDATE_START = "user_profile_update_start"
USER_PROFILE_UPDATE_COMPLETE = "user_profile_update_complete"
```

---

## File Creation Summary

| File | Phase | New/Modified | Notes |
|---|---|---|---|
| `memory/memory_manager.py` | A | Modified — add `search_cross_session()` alias | |
| `heartbeat/integrations/memory_maintenance.py` | A | Modified — add semantic eviction params | Do NOT create new retention_policy.py |
| `skills/local/meta.py` | A2 | Modified — quarantine staging, `is_read_only`/`concurrency_safe` params | |
| `memory/skill_extractor.py` | B | New | |
| `memory/user_profile_extractor.py` | E | New | |
| `memory/transcript_index.py` | F | New | |
| `skills/executor.py` | C | Modified — auto-fix for read-only skills only | |
| `skills/registry.py` | D | Modified — embedding field, backfill in `set_embedder()`, semantic routing | |
| `skills/local/memory.py` | F | Modified — add `search_transcripts` skill | |
| `storage/transcripts.py` | F | Modified — call `transcript_index.append_entry()` on write | |
| `memory/static_loader.py` | E | Modified — add `evict_by_source_tag()` for USER.md re-index | |
| `core/agent.py` | B, E | Modified — pass tool_calls_made to background tasks; inject new extractors | |
| `core/telemetry.py` | B, C, E | Modified — new EventType entries | |
| `data/USER.md` | E | Already exists — updated at runtime, re-indexed via StaticFileLoader | |
| `main.py` | All | Modified — wire new components | Fix asyncio.create_task → run_in_executor for transcript index |
| `tests/memory/test_skill_extractor.py` | B | New | |
| `tests/memory/test_user_profile_extractor.py` | E | New | Include re-index consistency test |
| `tests/memory/test_transcript_index.py` | F | New | Include incremental append test |
| `tests/skills/test_skill_auto_fix.py` | A2, C | New | Cover quarantine, promotion, read-only re-exec guard |
| `tests/skills/test_semantic_routing.py` | D | New | Include backfill test |

---

## Implementation Order & Dependencies

```
Phase A  (memory scoping + retention extension)   ← no deps; do first; clarifies principal model
    ↓
Phase A2 (generated skill safety gate)            ← prerequisite for B and C; create_skill() must be safe before automation
    ↓
Phase D  (semantic routing + backfill)            ← needs memory embedder available; backfill requires set_embedder()
    ↓
Phase B  (skill auto-extraction)                  ← needs A2 (safe create_skill), D (semantic dedup)
    ↓
Phase C  (skill auto-fix)                         ← needs B (generated skills must exist), A2 (quarantine gate)
    ↓
Phase E  (user profile)                           ← needs static_loader evict_by_source_tag (add in Phase A or E)
Phase F  (FTS5 transcripts)                       ← standalone; needs TranscriptStore hook for incremental indexing
```

E and F can be built in parallel with B/C once A2 is complete.

> **Open Questions (to resolve before starting)**
> - Is dolOS guaranteed to be single-operator? If yes, principal_id scoping is optional. If no, it must be in Phase A.
> - Should Phase B auto-extracted skills be limited to read-only until manually promoted? That would reduce quarantine complexity.
> - Should USER.md be injected into the system prompt AND semantic memory, or only one? Current code does both (file read + StaticFileLoader); the plan must define the sync contract before Phase E ships.

---

## Token Cost Estimation

New LLM calls added per turn:

| Phase | LLM calls | When | Estimated tokens/call |
|---|---|---|---|
| B — skill extraction | 1 | only if tool_count >= 3 | ~800 in, ~300 out |
| C — auto-fix | 1 | only on generated skill failure | ~600 in, ~400 out |
| E — user profile | 1 | every 10 turns | ~1200 in, ~600 out |

All run as background tasks — zero impact on response latency. Skill extraction gated by `MIN_TOOL_CALLS=3` so it won't fire on simple Q&A turns.

---

## Testing Strategy

Each phase ships with unit tests targeting the new component in isolation (mock LLM, mock registry). Integration coverage via the existing `tests/core/test_agent.py` pattern — add test cases for the new background task firing conditions.

Baseline: 579 passing, 11 pre-existing failures (in `test_agent.py` and `test_llm.py`). Each phase should maintain that baseline.

```bash
# Run after each phase
python -m pytest tests/ -x -q
```

**Additional test coverage required for high-risk areas (not in original plan):**

Phase A2 — Generated Skill Safety:
- [ ] Auto-generated skill defaults to `is_read_only=False, concurrency_safe=False`
- [ ] Skill in staging does not appear in `get_relevant_schemas()` before promotion
- [ ] Staging skill that raises on test-invoke stays in staging, is not promoted
- [ ] Promoted skill is correctly registered with declared safety flags
- [ ] Promoted skill's `is_read_only=True` means it can enter concurrent batch
- [ ] Promoted skill's `is_read_only=False` means it goes to serial queue

Phase C — Auto-fix Safety:
- [ ] Mutating generated skill failure → fix applied but NOT re-executed automatically
- [ ] Read-only generated skill failure → fix applied AND re-executed
- [ ] Built-in skills never enter auto-fix path

Phase D — Semantic Routing Backfill:
- [ ] Skills registered before `set_embedder()` receive embeddings on `set_embedder()` call
- [ ] `get_relevant_schemas()` returns correct skill for paraphrase even when skill was registered at import time

Phase E — USER.md Sync:
- [ ] After profile update, stale semantic chunks for `source_tag="user_profile"` are evicted
- [ ] Re-indexed chunks reflect the updated profile content
- [ ] System prompt does not serve old profile content after update

Phase F — Incremental Transcript Indexing:
- [ ] Entry appended to TranscriptStore → immediately searchable in TranscriptIndex
- [ ] Startup `index_all()` does not duplicate entries already indexed by `append_entry()`
- [ ] `search_transcripts` skill returns results across multiple sessions

Manual verification checklist for Phase B (most complex):
- [ ] Turn with 1-2 tool calls → no skill created
- [ ] Turn with 3+ tool calls → LLM consulted, skill created if appropriate
- [ ] LLM returns `is_read_only=false` → skill in serial queue, not concurrent batch
- [ ] Same skill type requested again → existing skill used (not duplicated)
- [ ] Skill in `generated/staging/` during quarantine, moves to `generated/` on promotion
- [ ] Restart → generated skill auto-loaded from `generated/` directory
- [ ] `search_memory` returns generated skill description in semantic results

---

## Hermes Reference Points

| Hermes feature | Our implementation | Divergence |
|---|---|---|
| Skills stored at `~/.hermes/skills/` | `skills/local/generated/` | Different path, same concept |
| agentskills.io open standard | dolOS skill schema (name/description/handler) | Compatible in spirit; not wire-compatible |
| Honcho dialectic user modeling | `UserProfileExtractor` + `data/USER.md` | Simplified — no external Honcho dependency |
| FTS5 cross-session search | `TranscriptIndex` (SQLite FTS5) | Same technology, local-only |
| `agent/` triggers skill creation | `memory/skill_extractor.py` + `_schedule_background_tasks()` | Same position in architecture |
| Skill self-improvement during use | `SkillExecutor._attempt_auto_fix()` | Same trigger (failure), same mechanism (LLM rewrite) |
| Memory nudges | `RetentionPolicy` heartbeat + existing `ReflectionTask` | Similar outcome via different mechanism |

---

## Out of Scope for This Plan

- **Voice pipeline** — separate project
- **agentskills.io compatibility / Skills Hub** — requires external service; not needed for internal use
- **Atropos RL trajectory export** — research feature; no current use case
- **14+ messaging channels** — 3 channels sufficient for current deployment
- **Multi-model routing** — single model is acceptable; add when needed
- **Docker/SSH/Modal backends** — edge device is local-only
