import asyncio
import json
import logging
import os
import re
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core.context_compressor import ContextCompressor
from core.hooks import HookRegistry
from core.llm import LLMGateway
from core.plan_mode import PlanModeState
from core.prompt_builder import PromptBuilder
from core.telemetry import EventBus, reset_trace_id, set_trace_id
from memory.memory_manager import MemoryManager
from memory.session_kv import SessionKVStore
from skills.executor import SkillExecutor
from skills.permissions import PermissionPolicy, filter_schemas
from storage.transcripts import TranscriptStore

if TYPE_CHECKING:
    from memory.combined_extractor import CombinedTurnExtractor
    from memory.lesson_extractor import LessonExtractor
    from memory.semantic_extractor import SemanticExtractor
    from memory.skill_extractor import SkillExtractionTask
    from memory.summarizer import ConversationSummarizer
    from memory.user_profile_extractor import UserProfileExtractor

_DEFAULT_LESSONS_PATH = "data/LESSONS.md"

logger = logging.getLogger(__name__)

# Default context window size used when Settings is not available.
_DEFAULT_CONTEXT_WINDOW = 32768


def _score_importance(text: str) -> float:
    """Heuristic importance score for an episodic memory (0.0–1.0)."""
    high_signals = ["decision:", "remember:", "important:", "never ", "always ",
                    "decided", "switched", "replaced", "changed", "critical", "must "]
    low_signals = ["hello", "hi ", "thanks", "thank you", "ok", "sure",
                   "got it", "sounds good", "great", "awesome", "cool"]
    lower = text.lower()
    if any(s in lower for s in high_signals):
        return 0.9
    if any(s in lower for s in low_signals):
        return 0.2
    return 0.5

_REACT_TAG_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_THINK_TAG_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)

def _supports_native_tools(_model_name: str) -> bool:
    """All models support native tool calling.

    Non-Ollama models (Claude, GPT-4) support it natively. Ollama models are
    transparently remapped to openai/+/v1 in LLMGateway, giving them the same
    OpenAI-compatible tool_calls wire format.
    """
    return True


def _parse_react_tool_calls(text: str) -> List[tuple]:
    """Parse <tool_call> tags from model output, including inside <think> blocks (qwen3 thinking mode)."""
    calls = []
    # Search both the visible text and any <think> block content
    think_content = " ".join(m.group(1) for m in _THINK_TAG_RE.finditer(text))
    search_in = text + " " + think_content
    for match in _REACT_TAG_RE.finditer(search_in):
        try:
            payload = json.loads(match.group(1).strip())
            name = payload.get("name", "")
            args = payload.get("arguments", {})
            if name:
                calls.append((name, args))
        except (json.JSONDecodeError, AttributeError):
            logger.warning(f"[REACT] Failed to parse tool_call: {match.group(1)[:100]}")
    return calls


class Agent:
    """The central agent orchestrator wrapping LLM, Memory, Telemetry, and Skills."""

    def __init__(
        self,
        llm: LLMGateway,
        memory: MemoryManager,
        event_bus: Optional[EventBus] = None,
        skill_executor: Optional[SkillExecutor] = None,
        semantic_extractor: Optional["SemanticExtractor"] = None,
        summarizer: Optional["ConversationSummarizer"] = None,
        lesson_extractor: Optional["LessonExtractor"] = None,
        combined_extractor: Optional["CombinedTurnExtractor"] = None,
        skill_extractor: Optional["SkillExtractionTask"] = None,
        user_profile_extractor: Optional["UserProfileExtractor"] = None,
        session_kv: Optional[SessionKVStore] = None,
        transcript_store: Optional[TranscriptStore] = None,
        permission_policy: Optional[PermissionPolicy] = None,
        hook_registry: Optional[HookRegistry] = None,
        plan_mode_state: Optional[PlanModeState] = None,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.event_bus = event_bus
        self.skill_executor = skill_executor
        self.semantic_extractor = semantic_extractor
        self.summarizer = summarizer
        self.lesson_extractor = lesson_extractor
        self.combined_extractor = combined_extractor
        self.skill_extractor = skill_extractor
        self.user_profile_extractor = user_profile_extractor
        self._lessons_path = _DEFAULT_LESSONS_PATH
        # Per-session cumulative token counters: {session_id: total_tokens}
        self._session_tokens: dict[str, int] = {}
        # Optional session K/V store for per-session structured memory
        self.session_kv: Optional[SessionKVStore] = session_kv
        # Optional durable transcript store
        self.transcript_store: Optional[TranscriptStore] = transcript_store
        # Optional permission policy — filters schemas before LLM sees them
        self.permission_policy: Optional[PermissionPolicy] = permission_policy
        # Optional hook registry — pre_tool_use / permission_request events
        self.hook_registry: Optional[HookRegistry] = hook_registry
        # Optional plan mode state — when active, tools are hidden and LLM proposes a plan
        self.plan_mode_state: Optional[PlanModeState] = plan_mode_state
        # Context compressor (Gap H1) — one instance shared across all sessions
        self._context_compressor = ContextCompressor()
        # Per-session running summary produced by the compressor: {session_id: summary_str}
        self._session_summary: dict[str, str] = {}

    async def process_message(self, session_id: str, message: str) -> str:
        """Process an incoming message from a user/channel."""
        # 1. Start a trace
        trace_id = uuid.uuid4().hex
        trace_token = set_trace_id(trace_id)

        try:
            # 2. Add user message to episodic memory
            user_text = f"User: {message}"
            self.memory.add_memory(
                text=user_text,
                memory_type="episodic",
                importance=_score_importance(message),
                metadata={"session_id": session_id, "role": "user"},
            )
            # Transcript: record user message
            self._append_transcript(session_id, "user", content=message)

            # 3. Retrieve context from both memory streams
            summary_context = ""
            episodic_limit = 5
            if self.summarizer:
                summary = self.summarizer.get_session_summary(session_id)
                if summary:
                    summary_context = f"Previous conversation summary:\n{summary}\n\n"
                    episodic_limit = 3

            episodic_results = self.memory.search(
                query=message, memory_type="episodic", limit=episodic_limit, min_score=0.30
            )
            semantic_results = self.memory.search(
                query=message, memory_type="semantic", limit=3, min_score=0.35
            )

            episodic_block = "\n".join([r["text"] for r in episodic_results])
            semantic_block = "\n".join([r["text"] for r in semantic_results])

            soul_path = os.path.join("data", "SOUL.md")
            soul_content = "You are a helpful, autonomous AI agent."
            if os.path.exists(soul_path):
                with open(soul_path, "r", encoding="utf-8") as f:
                    soul_content = f.read()

            if len(soul_content) > 8000:
                logger.warning(
                    "SOUL.md is large (%d chars). Consider splitting into SOUL_CORE.md + SOUL_EXTENDED.md "
                    "to reduce prompt token cost.", len(soul_content)
                )

            lessons_content = ""
            if os.path.exists(self._lessons_path):
                with open(self._lessons_path, "r", encoding="utf-8") as f:
                    raw_lessons = f.read().strip()
                if raw_lessons:
                    lessons_content = (
                        "Here are behavioural lessons learned from past mistakes — follow these strictly:\n\n"
                        f"<lessons_learned>\n{raw_lessons}\n</lessons_learned>\n\n"
                    )

            user_profile_content = ""
            user_profile_path = os.path.join("data", "USER.md")
            if os.path.exists(user_profile_path):
                with open(user_profile_path, "r", encoding="utf-8") as f:
                    user_profile_content = f.read().strip()

            # Build system prompt using PromptBuilder
            _settings = getattr(self.llm, "settings", None)
            _primary_model = getattr(_settings, "primary_model", "")
            model_name = _primary_model if isinstance(_primary_model, str) else ""
            use_native_tools = _supports_native_tools(model_name)
            if self.skill_executor:
                registry = self.skill_executor.registry
                if len(registry.get_all_skill_names()) > 10:
                    schemas = registry.get_relevant_schemas(message)
                else:
                    schemas = registry.get_all_schemas()
            else:
                schemas = []
            if self.permission_policy is not None:
                schemas = filter_schemas(schemas, self.permission_policy)

            # Plan mode: hide all tools from the LLM so it proposes a plan instead
            _in_plan_mode = self.plan_mode_state is not None and self.plan_mode_state.active
            if _in_plan_mode:
                schemas = []

            # Working memory: read static context files + per-session note
            _working_memory_parts: list[str] = []
            for _wm_name, _wm_path in (
                ("CURRENT_TASK", os.path.join("data", "CURRENT_TASK.md")),
                ("RUNBOOK", os.path.join("data", "RUNBOOK.md")),
                ("KNOWN_ISSUES", os.path.join("data", "KNOWN_ISSUES.md")),
            ):
                if os.path.exists(_wm_path):
                    with open(_wm_path, "r", encoding="utf-8") as _f:
                        _wm_text = _f.read().strip()
                    if _wm_text:
                        _working_memory_parts.append(f"## {_wm_name}\n{_wm_text}")
            _session_note_path = os.path.join(
                "data", "SESSION_NOTES", f"{session_id}.md"
            )
            if os.path.exists(_session_note_path):
                with open(_session_note_path, "r", encoding="utf-8") as _f:
                    _note_text = _f.read().strip()
                if _note_text:
                    _working_memory_parts.append(f"## SESSION NOTE\n{_note_text}")
            working_memory_content = "\n\n".join(_working_memory_parts)

            system_prompt = PromptBuilder(
                soul_content=soul_content,
                user_profile_content=user_profile_content,
                lessons_content=lessons_content,
                summary_context=summary_context,
                episodic_block=episodic_block,
                semantic_block=semantic_block,
                use_native_tools=use_native_tools,
                schemas=schemas,
                session_kv_store=self.session_kv,
                working_memory_content=working_memory_content,
            ).build(session_id=session_id)

            # Append plan-mode instruction so LLM responds with a numbered list
            if _in_plan_mode:
                system_prompt += (
                    "\n\n[PLAN MODE ACTIVE] Do NOT execute any actions or call any tools. "
                    "Instead, respond ONLY with a numbered list of steps you WOULD take to "
                    "complete the request. Format each step as: '1. Step description'. "
                    "Do not include any other text."
                )

            logger.debug(f"[SYSTEM_PROMPT] {system_prompt[:800]!r}")

            # 4. Form message list
            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ]

            # Pass native tools to models that support OpenAI-style function calling.
            # Qwen3 and other capable Ollama models need native tools — the ReAct XML
            # fallback doesn't work because their RLHF training overrides the XML instructions.
            # Only older/uncapable Ollama models fall back to the ReAct XML format.
            tools = None
            if self.skill_executor and use_native_tools:
                tools = [{"type": "function", "function": s} for s in schemas] or None

            # 5. Generate reply (Loop for tool calls)
            max_loops = 10
            tool_calls_made: list[str] = []
            for loop_idx in range(max_loops):
                # On the final iteration force a plain-text response — no more tool calls.
                # This prevents qwen3's thinking mode from looping indefinitely.
                final_loop = (loop_idx == max_loops - 1)
                loop_tools = None if final_loop else tools
                if final_loop and messages[-1].get("role") != "user":
                    messages.append({"role": "user", "content": "You have all the information you need. Give your final answer to the user now. Do not call any more tools."})

                response = await self.llm.generate(messages=messages, trace_id=trace_id, tools=loop_tools)
                content = response.content or ""
                logger.info(f"[LLM_RAW] tool_calls={bool(response.tool_calls)} | has_tool_tag={'<tool_call>' in content} | content={content[:300]!r}")

                # Track cumulative token usage for this session.
                # Use int() guarded access so plain MagicMock responses (used in tests) don't crash.
                _in_tok = getattr(response, "input_tokens", 0)
                _out_tok = getattr(response, "output_tokens", 0)
                input_tokens_int: int = _in_tok if isinstance(_in_tok, int) else 0
                output_tokens_int: int = _out_tok if isinstance(_out_tok, int) else 0
                turn_tokens: int = input_tokens_int + output_tokens_int
                self._session_tokens[session_id] = (
                    self._session_tokens.get(session_id, 0) + turn_tokens
                )
                _settings = getattr(self.llm, "settings", None)
                _cw = getattr(_settings, "model_context_window", _DEFAULT_CONTEXT_WINDOW)
                context_window: int = _cw if isinstance(_cw, int) else _DEFAULT_CONTEXT_WINDOW
                _wt = getattr(_settings, "token_budget_warn_threshold", 0.8)
                warn_threshold: float = _wt if isinstance(_wt, (int, float)) else 0.8
                if turn_tokens > 0 and (input_tokens_int / context_window) >= warn_threshold:
                    logger.warning(
                        "[TOKEN_BUDGET] Session %s: %d/%d input tokens (%.0f%% of context window)",
                        session_id,
                        input_tokens_int,
                        context_window,
                        100 * input_tokens_int / context_window,
                    )
                    # Gap H1 — structured context compression when approaching budget
                    try:
                        messages, new_summary = await self._context_compressor.compress(
                            messages=messages,
                            prior_summary=self._session_summary.get(session_id),
                            llm=self.llm,
                            trace_id=trace_id,
                        )
                        if new_summary:
                            self._session_summary[session_id] = new_summary
                    except Exception as _comp_exc:
                        logger.warning("[COMPRESSOR] Compression failed: %s", _comp_exc)

                # --- Native function calling path ---
                if response.tool_calls:
                    messages.append({
                        "role": "assistant",
                        "content": content,
                        "tool_calls": [
                            tc.model_dump() if hasattr(tc, "model_dump") else
                            tc.dict() if hasattr(tc, "dict") else
                            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                            for tc in response.tool_calls
                        ],
                    })

                    # Parse all tool calls upfront
                    parsed_calls: List[tuple] = []
                    for tc in response.tool_calls:
                        fn_name = tc.function.name
                        try:
                            args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            args = {}
                        parsed_calls.append((tc, fn_name, args))

                    # Partition: concurrent_batch (read_only + concurrency_safe) vs serial_queue
                    concurrent_batch: List[tuple] = []
                    serial_queue: List[tuple] = []
                    if self.skill_executor:
                        for entry in parsed_calls:
                            _tc, _fn_name, _args = entry
                            try:
                                _reg = self.skill_executor.registry.get_registration(_fn_name)
                                _is_parallel = _reg.is_read_only and _reg.concurrency_safe
                            except KeyError:
                                _is_parallel = False
                            if _is_parallel:
                                concurrent_batch.append(entry)
                            else:
                                serial_queue.append(entry)
                    else:
                        serial_queue = parsed_calls

                    async def _execute_tool(
                        _tc_: Any, _fn_: str, _ag_: Dict[str, Any]
                    ) -> str:
                        """Fire pre_tool_use hook then execute the skill."""
                        if self.hook_registry:
                            await self.hook_registry.fire(
                                "pre_tool_use", tool_name=_fn_, arguments=_ag_
                            )
                        _res = (
                            await self.skill_executor.execute(_fn_, _ag_, trace_id)
                            if self.skill_executor
                            else "Error: SkillExecutor not configured."
                        )
                        return str(_res)

                    def _record_tool(
                        _fn_: str, _ag_: Dict[str, Any], _result_: str
                    ) -> None:
                        """Append transcript entries and episodic memory for one tool call."""
                        tool_calls_made.append(_fn_)
                        self._append_transcript(session_id, "tool_call", name=_fn_, arguments=_ag_)
                        self._append_transcript(session_id, "tool_result", name=_fn_, content=_result_[:500])
                        self.memory.add_memory(
                            text=f"Tool {_fn_} called. Result: {_result_[:300]}",
                            memory_type="episodic",
                            importance=0.7,
                            metadata={"session_id": session_id, "role": "tool", "tool_name": _fn_},
                        )

                    # Execute read-only calls concurrently (Gap 11)
                    if concurrent_batch:
                        batch_results = await asyncio.gather(
                            *[_execute_tool(tc, fn, ag) for tc, fn, ag in concurrent_batch]
                        )
                        for (tc, fn_name, args), result in zip(concurrent_batch, batch_results):
                            messages.append({"role": "tool", "tool_call_id": tc.id, "name": fn_name, "content": result})
                            _record_tool(fn_name, args, result)

                    # Execute state-mutating calls serially
                    for tc, fn_name, args in serial_queue:
                        result = await _execute_tool(tc, fn_name, args)
                        messages.append({"role": "tool", "tool_call_id": tc.id, "name": fn_name, "content": result})
                        _record_tool(fn_name, args, result)

                    continue  # loop back with tool results

                # --- ReAct XML fallback (for models that don't support native tool calling) ---
                react_calls = _parse_react_tool_calls(content)
                if react_calls and self.skill_executor:
                    logger.info(f"[REACT] parsed {len(react_calls)} tool call(s) from text")
                    messages.append({"role": "assistant", "content": content})
                    tool_results = []
                    for fn_name, args in react_calls:
                        result = await self.skill_executor.execute(fn_name, args, trace_id)
                        tool_calls_made.append(fn_name)
                        tool_results.append(f"<tool_result name=\"{fn_name}\">{result}</tool_result>")
                        logger.info(f"[REACT] {fn_name}({args}) → {str(result)[:120]}")
                        # Transcript: record ReAct tool call and result
                        self._append_transcript(session_id, "tool_call", name=fn_name, arguments=args)
                        self._append_transcript(session_id, "tool_result", name=fn_name, content=str(result)[:500])
                        _result_preview = str(result)[:300]
                        _tool_summary = f"Tool {fn_name} called. Result: {_result_preview}"
                        self.memory.add_memory(
                            text=_tool_summary,
                            memory_type="episodic",
                            importance=0.7,
                            metadata={"session_id": session_id, "role": "tool", "tool_name": fn_name},
                        )
                    messages.append({"role": "user", "content": "\n".join(tool_results) + "\nNow give the final answer to the user based on the above results."})
                    continue  # loop back so model can compose final answer

                # --- No tool calls — final response ---
                else:
                    content = response.content or ""

                    # Plan mode: parse numbered steps from response and store them
                    if self.plan_mode_state is not None and self.plan_mode_state.active:
                        _steps = re.findall(r"^\s*\d+\.\s+(.+)$", content, re.MULTILINE)
                        self.plan_mode_state.store_plan(_steps)

                    # 6. Add assistant reply to memory
                    assistant_text = f"Assistant: {content}"
                    self.memory.add_memory(
                        text=assistant_text,
                        memory_type="episodic",
                        importance=_score_importance(content),
                        metadata={"session_id": session_id, "role": "assistant"},
                    )
                    # Transcript: record final assistant response
                    self._append_transcript(session_id, "assistant", content=content)

                    # 7. Fire background tasks (non-blocking)
                    self._schedule_background_tasks(
                        session_id,
                        message,
                        content,
                        tool_calls_made,
                        trace_id,
                    )

                    return content

            # If we exit the loop, we hit MAX_LOOPS
            fallback_content = response.content or "Error: Exceeded max tool loops."
            self.memory.add_memory(
                text=f"Assistant: {fallback_content}",
                memory_type="episodic",
                importance=_score_importance(fallback_content),
                metadata={"session_id": session_id, "role": "assistant"},
            )
            return fallback_content

        finally:
            reset_trace_id(trace_token)

    def _append_transcript(self, session_id: str, entry_type: str, **kwargs: object) -> None:
        """Append a transcript entry non-blockingly.

        Called at each turn stage (user, tool_call, tool_result, assistant).
        If no transcript_store is configured, this is a no-op.
        """
        if self.transcript_store is None:
            return
        try:
            self.transcript_store.append(session_id, entry_type, **kwargs)
        except Exception as exc:
            logger.warning("Transcript append failed (%s): %s", entry_type, exc)

    def _schedule_background_tasks(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        tool_calls_made: list[str],
        trace_id: str,
    ) -> None:
        """Fire semantic extraction and summarization as non-blocking background tasks."""
        if self.combined_extractor:
            # Single LLM call for both facts + lessons
            asyncio.create_task(
                self._run_combined_extraction(session_id, user_message, assistant_response, trace_id)
            )
        else:
            # Fallback: separate extractors
            if self.semantic_extractor:
                asyncio.create_task(
                    self._run_semantic_extraction(session_id, user_message, assistant_response, trace_id)
                )
            if self.lesson_extractor:
                asyncio.create_task(
                    self._run_lesson_extraction(session_id, user_message, assistant_response, trace_id)
                )

        if self.skill_extractor and len(tool_calls_made) >= self.skill_extractor.MIN_TOOL_CALLS:
            asyncio.create_task(
                self.skill_extractor.evaluate_and_extract(
                    session_id=session_id,
                    user_message=user_message,
                    assistant_response=assistant_response,
                    tool_calls_made=tool_calls_made,
                    trace_id=trace_id,
                )
            )

        if self.user_profile_extractor and self.transcript_store:
            try:
                transcript_entries = self.transcript_store.read_session(session_id)
                recent_turns = [
                    entry
                    for entry in transcript_entries
                    if entry.get("type") in {"user", "assistant"}
                ][-20:]
                asyncio.create_task(
                    self.user_profile_extractor.maybe_update(
                        session_id=session_id,
                        recent_turns=recent_turns,
                        trace_id=trace_id,
                    )
                )
            except Exception as e:
                logger.warning("User profile scheduling failed: %s", e)

        if self.summarizer:
            should_summarize = self.summarizer.increment_turn(session_id)
            # Also trigger summarization when approaching the token budget threshold
            if not should_summarize:
                _settings = getattr(self.llm, "settings", None)
                _cw2 = getattr(_settings, "model_context_window", _DEFAULT_CONTEXT_WINDOW)
                _sum_cw: int = _cw2 if isinstance(_cw2, int) else _DEFAULT_CONTEXT_WINDOW
                _st = getattr(_settings, "token_budget_summarize_threshold", 0.7)
                summarize_token_threshold: float = _st if isinstance(_st, (int, float)) else 0.7
                session_total = self._session_tokens.get(session_id, 0)
                if session_total > 0 and (session_total / _sum_cw) >= summarize_token_threshold:
                    logger.info(
                        "[TOKEN_BUDGET] Triggering summarization for session %s: "
                        "%d tokens (%.0f%% of context window)",
                        session_id,
                        session_total,
                        100 * session_total / _sum_cw,
                    )
                    should_summarize = True
            if should_summarize:
                asyncio.create_task(
                    self._run_summarization(session_id, trace_id)
                )

    async def _run_combined_extraction(
        self, session_id: str, user_message: str, assistant_response: str, trace_id: str
    ) -> None:
        start = asyncio.get_event_loop().time()
        try:
            await self.combined_extractor.extract_and_store(  # type: ignore[union-attr]
                user_message=user_message,
                assistant_response=assistant_response,
                session_id=session_id,
                trace_id=trace_id,
            )
            elapsed_ms = (asyncio.get_event_loop().time() - start) * 1000
            logger.debug("CombinedTurnExtractor completed in %.0fms", elapsed_ms)
            if elapsed_ms > 3000:
                logger.warning("CombinedTurnExtractor took %.0fms — may race with next user query", elapsed_ms)
        except Exception as e:
            logger.warning("Combined extraction failed: %s", e)

    async def _run_semantic_extraction(
        self, session_id: str, user_message: str, assistant_response: str, trace_id: str
    ) -> None:
        """Background task: extract facts from this turn into semantic memory."""
        start = asyncio.get_event_loop().time()
        try:
            await self.semantic_extractor.extract_and_store(  # type: ignore[union-attr]
                user_message=user_message,
                assistant_response=assistant_response,
                session_id=session_id,
                trace_id=trace_id,
            )
            elapsed_ms = (asyncio.get_event_loop().time() - start) * 1000
            logger.debug("SemanticExtractor completed in %.0fms", elapsed_ms)
            if elapsed_ms > 3000:
                logger.warning("SemanticExtractor took %.0fms — may race with next user query", elapsed_ms)
        except Exception as e:
            logger.warning("Semantic extraction failed: %s", e)

    async def _run_summarization(self, session_id: str, trace_id: str) -> None:
        """Background task: summarize this session's conversation."""
        start = asyncio.get_event_loop().time()
        try:
            await self.summarizer.summarize_session(  # type: ignore[union-attr]
                session_id=session_id,
                trace_id=trace_id,
            )
            elapsed_ms = (asyncio.get_event_loop().time() - start) * 1000
            logger.debug("Summarization completed in %.0fms", elapsed_ms)
            if elapsed_ms > 3000:
                logger.warning("Summarization took %.0fms — may race with next user query", elapsed_ms)
        except Exception as e:
            logger.warning("Summarization failed: %s", e)

    async def _run_lesson_extraction(
        self, session_id: str, user_message: str, assistant_response: str, trace_id: str
    ) -> None:
        """Background task: extract behavioural lessons from this turn."""
        start = asyncio.get_event_loop().time()
        try:
            await self.lesson_extractor.extract_and_store(  # type: ignore[union-attr]
                user_message=user_message,
                assistant_response=assistant_response,
                session_id=session_id,
                trace_id=trace_id,
            )
            elapsed_ms = (asyncio.get_event_loop().time() - start) * 1000
            logger.debug("LessonExtractor completed in %.0fms", elapsed_ms)
            if elapsed_ms > 3000:
                logger.warning("LessonExtractor took %.0fms — may race with next user query", elapsed_ms)
        except Exception as e:
            logger.warning("Lesson extraction failed: %s", e)
