# User Profile / Behavioral Modeling Implementation Plan

**Directive:** User brief for Phase E User Profile / Behavioral Modeling (`directives/` missing in this checkout)
**Date:** 2026-04-09
**Goal:** Maintain a structured `data/USER.md` profile that updates every 10 turns, inject it into the system prompt alongside `SOUL.md`, and keep semantic memory in sync by evicting stale `user_profile` chunks before re-indexing.
**Architecture Notes:** Follow the existing optional background-task pattern used by `memory/summarizer.py` and `memory/lesson_extractor.py`: one guarded LLM call, explicit telemetry start/complete events, warning-and-skip failure handling, and no crashes in the live agent loop. Extend the vector delete path additively with a metadata-based delete method so existing age/importance deletion callers remain unchanged.

---

### Task 1: Plan and Red Tests

**Files:**
- Create/Modify: `docs/plans/2026-04-09-user-profile-behavioral-modeling.md`
- Create/Modify: `tests/memory/test_user_profile_extractor.py`
- Modify: `tests/memory/test_static_loader.py`
- Modify: `tests/memory/test_vector_store.py`
- Modify: `tests/core/test_prompt_builder.py`
- Modify: `tests/core/test_agent.py`

**Step 1:** Create the implementation plan file
- File: `docs/plans/2026-04-09-user-profile-behavioral-modeling.md`
- Run: `python -m pytest tests/memory/test_user_profile_extractor.py -q`
- Expected: test collection fails because `tests/memory/test_user_profile_extractor.py` does not exist yet

**Step 2:** Write failing extractor tests
- File: `tests/memory/test_user_profile_extractor.py`
- Add tests for:
  - below-threshold turn counts do not call the LLM
  - `llm is None` is a safe no-op
  - successful update writes full `USER.md`
  - successful update evicts stale `user_profile` chunks before re-indexing
  - invalid LLM output does not clobber the existing profile
  - LLM exception does not crash
  - existing `USER.md` content is included in the prompt
  - recent turns are rendered into the prompt
  - telemetry start and complete events are emitted on success
- Run: `python -m pytest tests/memory/test_user_profile_extractor.py -q`
- Expected: failures caused by missing `memory.user_profile_extractor.UserProfileExtractor`

**Step 3:** Write failing support-path tests
- File: `tests/memory/test_static_loader.py`
- Add tests for:
  - `evict_by_source_tag()` deletes semantic chunks for a given `source_tag`
  - `evict_by_source_tag()` returns `0` and logs safely when delete raises
- File: `tests/memory/test_vector_store.py`
- Add a test that the new metadata delete path builds the expected `FilterSelector` and calls the client delete API
- File: `tests/core/test_prompt_builder.py`
- Add tests for:
  - user profile content present when provided
  - user profile content wrapped in `<user_profile>` tags
  - user profile section absent when content is empty
  - identity section contains both soul and user profile content
- File: `tests/core/test_agent.py`
- Add tests for:
  - `USER.md` content is injected into the system prompt
  - background scheduling reads recent transcript entries from `TranscriptStore.read_session()`
  - user-profile scheduling skips cleanly when no transcript store is configured
- Run: `python -m pytest tests/memory/test_static_loader.py tests/memory/test_vector_store.py tests/core/test_prompt_builder.py tests/core/test_agent.py -q`
- Expected: failures caused by missing Phase E wiring and metadata delete support

---

### Task 2: Implement Runtime Profile Extraction

**Files:**
- Create/Modify: `memory/user_profile_extractor.py`

**Step 1:** Add the extractor skeleton and turn counter gate
- File: `memory/user_profile_extractor.py`
- Implement:
  - `UserProfileExtractor.UPDATE_EVERY_N_TURNS = 10`
  - constructor storing `llm`, `profile_path`, `static_loader`, `event_bus`
  - per-session `_turn_counts`
  - `maybe_update(...)` early returns for `llm is None`, below-threshold turns, and empty recent-turn input
- Run: `python -m pytest tests/memory/test_user_profile_extractor.py -q`
- Expected: failures move from import errors to behavior assertions

**Step 2:** Add prompt rendering, validation, and safe-write flow
- File: `memory/user_profile_extractor.py`
- Implement:
  - current profile file read from `profile_path`
  - readable rendering of the last 10 turns from the provided `recent_turns`
  - one `llm.generate(messages=[{"role": "user", "content": prompt}], trace_id=trace_id)` call
  - validation that the response is non-empty and contains all required sections before writing
  - write updated content to `profile_path` only after validation succeeds
  - warning log and `return 0` on LLM failure, parse/validation failure, or file-write failure
- Run: `python -m pytest tests/memory/test_user_profile_extractor.py -q`
- Expected: prompt and failure-path tests pass

**Step 3:** Add telemetry and semantic re-sync
- File: `memory/user_profile_extractor.py`
- Implement:
  - `USER_PROFILE_UPDATE_START` and `USER_PROFILE_UPDATE_COMPLETE` emissions
  - `static_loader.evict_by_source_tag("user_profile")` before re-indexing
  - `static_loader.index_file("data/USER.md", source_tag="user_profile")` after write
  - `return 1` on complete success
- Run: `python -m pytest tests/memory/test_user_profile_extractor.py -q`
- Expected: all extractor tests pass

---

### Task 3: Add Metadata Eviction Support

**Files:**
- Modify: `memory/vector_store.py`
- Modify: `memory/static_loader.py`

**Step 1:** Extend `VectorStore` with metadata-based delete
- File: `memory/vector_store.py`
- Implement:
  - `delete_by_metadata(collection_name: str, filter_metadata: dict[str, Any]) -> int`
  - `FieldCondition` + `MatchValue` filter construction matching all provided metadata keys
  - `client.delete(..., points_selector=FilterSelector(filter=...))`
  - proxy count return using `operation_id or 0`
- Run: `python -m pytest tests/memory/test_vector_store.py -q`
- Expected: new vector-store metadata delete test passes

**Step 2:** Add `StaticFileLoader.evict_by_source_tag()`
- File: `memory/static_loader.py`
- Implement:
  - semantic delete call for `{"source": source_tag}`
  - warning log and `return 0` on deletion failure
- Run: `python -m pytest tests/memory/test_static_loader.py -q`
- Expected: new static-loader eviction tests pass

---

### Task 4: Inject `USER.md` into Prompt and Agent Loop

**Files:**
- Modify: `core/prompt_builder.py`
- Modify: `core/agent.py`
- Modify: `core/telemetry.py`
- Modify: `main.py`

**Step 1:** Extend `PromptBuilder` identity section
- File: `core/prompt_builder.py`
- Implement:
  - `user_profile_content: str = ""` constructor argument
  - identity section that always renders `<soul_instructions>...</soul_instructions>`
  - conditional `<user_profile>...</user_profile>` block when profile content is non-empty
  - no empty tags when no profile content exists
- Run: `python -m pytest tests/core/test_prompt_builder.py -q`
- Expected: new prompt-builder tests pass

**Step 2:** Wire `USER.md` reads and background scheduling into `Agent`
- File: `core/agent.py`
- Implement:
  - `user_profile_extractor: Optional["UserProfileExtractor"] = None` constructor arg and `self.user_profile_extractor`
  - fresh `data/USER.md` read each turn beside `SOUL.md` / `LESSONS.md`
  - pass `user_profile_content` into `PromptBuilder(...)`
  - inside `_schedule_background_tasks()`, when both `user_profile_extractor` and `transcript_store` exist:
    - call `self.transcript_store.read_session(session_id)`
    - filter to only `user` and `assistant` entries
    - keep the last 20 such entries in chronological order
    - schedule `self.user_profile_extractor.maybe_update(session_id=..., recent_turns=..., trace_id=...)`
- Run: `python -m pytest tests/core/test_agent.py -q`
- Expected: new agent tests pass without changing the existing cross-session memory search call sites

**Step 3:** Add telemetry enum values and main wiring
- File: `core/telemetry.py`
- Add:
  - `USER_PROFILE_UPDATE_START = "user.profile.update.start"`
  - `USER_PROFILE_UPDATE_COMPLETE = "user.profile.update.complete"`
- File: `main.py`
- Implement:
  - `from memory.user_profile_extractor import UserProfileExtractor`
  - `user_profile_extractor = UserProfileExtractor(llm=llm, profile_path="data/USER.md", static_loader=_static_loader, event_bus=event_bus)`
  - pass `user_profile_extractor=user_profile_extractor` into `Agent(...)`
  - keep existing startup indexing of `data/USER.md`
- Run: `python -m pytest tests/core/test_prompt_builder.py tests/core/test_agent.py -q`
- Expected: Phase E prompt and agent wiring tests pass

---

### Task 5: Verification and Review

**Files:**
- Modify only the files listed above if verification exposes Phase E defects

**Step 1:** Run extractor verification
- Run: `python -m pytest tests/memory/test_user_profile_extractor.py -q`
- Expected: all tests pass

**Step 2:** Run support-path verification
- Run: `python -m pytest tests/memory/test_static_loader.py tests/memory/test_vector_store.py -q`
- Expected: all tests pass

**Step 3:** Run prompt and agent verification
- Run: `python -m pytest tests/core/test_prompt_builder.py tests/core/test_agent.py -q`
- Expected: all new Phase E tests pass; only known pre-existing failures may remain in those files

**Step 4:** Run full regression verification
- Run: `python -m pytest tests/ -x -q`
- Expected: stop only if a new regression appears outside the known 11 pre-existing failures
- Run: `python -m pytest tests/ -q`
- Expected: failure count does not exceed the current 11 pre-existing failures, and remaining failures are still limited to `tests/core/test_agent.py` and `tests/core/test_llm.py`

**Step 5:** Spec compliance review
- Confirm:
  - `USER.md` updates only after every 10 completed turns
  - invalid or partial profile output never overwrites the existing file
  - stale `user_profile` semantic chunks are evicted before re-indexing
  - `USER.md` is injected beside `SOUL.md`, with no empty profile tags
  - profile updates are optional and non-fatal

**Step 6:** Code quality review
- Confirm:
  - metadata delete support is additive and does not change existing delete APIs
  - transcript filtering ignores `tool_call` and `tool_result`
  - background scheduling remains non-blocking and does not use heartbeat
  - tests cover thresholding, prompt content, file safety, telemetry, and runtime re-indexing
