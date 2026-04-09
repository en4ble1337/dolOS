"""Automatic post-turn skill extraction for reusable multi-step workflows."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

from core.telemetry import Event, EventBus, EventType
from skills.local.meta import create_skill
from skills.registry import SkillRegistry, _cosine_similarity

logger = logging.getLogger(__name__)

_SKILL_EXTRACTION_PROMPT = """\
You just completed a task using these tools: {tool_calls_made}

User asked: {user_message}
You responded: {assistant_response}

Evaluate: Was there a REUSABLE multi-step pattern here worth a dedicated skill?

A good skill candidate:
- Combines 3+ tool calls in a non-obvious way
- Would be useful again for similar requests
- Is self-contained (no session-specific context)
- Is NOT already covered by: {existing_skill_names}

Return JSON:
{{
  "should_create": true/false,
  "reason": "...",
  "name": "snake_case_name",
  "description": "one sentence",
  "code": "async def handler(**kwargs): ...",
  "is_read_only": false,
  "concurrency_safe": false
}}

is_read_only: true ONLY if the skill reads but never writes/deletes/sends anything.
concurrency_safe: true ONLY if safe to run concurrently with itself.
Default both to false when in doubt.

If no skill needed: {{"should_create": false, "reason": "..."}}"""


class SkillExtractionTask:
    """Ask the LLM whether a multi-tool turn should become a reusable skill."""

    MIN_TOOL_CALLS = 3
    _DUPLICATE_THRESHOLD = 0.85

    def __init__(
        self,
        llm: Any,
        registry: SkillRegistry,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.event_bus = event_bus

    async def evaluate_and_extract(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        tool_calls_made: list[str],
        trace_id: str,
    ) -> int:
        """Evaluate the turn and create at most one new quarantined skill."""
        if self.llm is None:
            return 0
        if len(tool_calls_made) < self.MIN_TOOL_CALLS:
            return 0

        start = time.time()
        self._emit(
            EventType.SKILL_EXTRACTION_START,
            trace_id,
            session_id=session_id,
            tool_calls_made=tool_calls_made,
        )

        prompt = _SKILL_EXTRACTION_PROMPT.format(
            tool_calls_made=", ".join(tool_calls_made),
            user_message=user_message,
            assistant_response=assistant_response[:500],
            existing_skill_names=", ".join(self.registry.get_all_skill_names()) or "(none)",
        )

        try:
            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning("SkillExtractionTask: LLM call failed: %s", exc)
            self._emit(
                EventType.SKILL_EXTRACTION_ERROR,
                trace_id,
                session_id=session_id,
                error=str(exc),
                duration_ms=(time.time() - start) * 1000,
            )
            return 0

        parsed = _parse_skill_extraction_response(getattr(response, "content", "") or "")
        if parsed is None:
            logger.warning(
                "SkillExtractionTask: invalid JSON response: %s",
                (getattr(response, "content", "") or "")[:200],
            )
            self._emit(
                EventType.SKILL_EXTRACTION_ERROR,
                trace_id,
                session_id=session_id,
                error="invalid_json",
                duration_ms=(time.time() - start) * 1000,
            )
            return 0

        if not parsed.get("should_create"):
            self._emit(
                EventType.SKILL_EXTRACTION_SKIP,
                trace_id,
                session_id=session_id,
                reason=str(parsed.get("reason", "")),
                duration_ms=(time.time() - start) * 1000,
            )
            return 0

        name = str(parsed.get("name", "")).strip()
        description = str(parsed.get("description", "")).strip()
        code = str(parsed.get("code", "")).strip()
        is_read_only = bool(parsed.get("is_read_only", False))
        concurrency_safe = bool(parsed.get("concurrency_safe", False))

        if not name or not description or not code:
            logger.warning("SkillExtractionTask: missing required fields in LLM response")
            self._emit(
                EventType.SKILL_EXTRACTION_ERROR,
                trace_id,
                session_id=session_id,
                error="missing_fields",
                duration_ms=(time.time() - start) * 1000,
            )
            return 0

        if self._is_duplicate(name=name, description=description):
            self._emit(
                EventType.SKILL_EXTRACTION_DUPLICATE,
                trace_id,
                session_id=session_id,
                name=name,
                description=description,
                duration_ms=(time.time() - start) * 1000,
            )
            return 0

        try:
            create_result = await create_skill(
                name,
                description,
                code,
                is_read_only,
                concurrency_safe,
            )
        except Exception as exc:
            logger.warning("SkillExtractionTask: create_skill failed: %s", exc)
            self._emit(
                EventType.SKILL_EXTRACTION_ERROR,
                trace_id,
                session_id=session_id,
                error=str(exc),
                name=name,
                duration_ms=(time.time() - start) * 1000,
            )
            return 0

        if isinstance(create_result, str) and create_result.startswith("Error:"):
            logger.warning("SkillExtractionTask: create_skill returned error: %s", create_result)
            self._emit(
                EventType.SKILL_EXTRACTION_ERROR,
                trace_id,
                session_id=session_id,
                error=create_result,
                name=name,
                duration_ms=(time.time() - start) * 1000,
            )
            return 0

        self._emit(
            EventType.SKILL_EXTRACTION_CREATED,
            trace_id,
            session_id=session_id,
            name=name,
            description=description,
            is_read_only=is_read_only,
            concurrency_safe=concurrency_safe,
            duration_ms=(time.time() - start) * 1000,
        )
        return 1

    def _is_duplicate(self, name: str, description: str) -> bool:
        """Check exact-name duplicates, then embedding duplicates when available."""
        if name in self.registry.get_all_skill_names():
            return True

        embedder = getattr(self.registry, "_embedder", None)
        if embedder is None:
            return False

        try:
            proposed_embedding = embedder.encode(description)
        except Exception:
            return False

        for existing_name in self.registry.get_all_skill_names():
            registration = self.registry.get_registration(existing_name)
            if registration.description_embedding is None:
                continue
            similarity = _cosine_similarity(proposed_embedding, registration.description_embedding)
            if similarity > self._DUPLICATE_THRESHOLD:
                return True
        return False

    def _emit(self, event_type: EventType, trace_id: str, **payload: object) -> None:
        """Emit telemetry without letting extraction failures affect the agent loop."""
        if self.event_bus is None:
            return
        self.event_bus.emit_sync(Event(
            event_type=event_type,
            component="memory.skill_extractor",
            trace_id=trace_id,
            payload=dict(payload),
        ))


def _parse_skill_extraction_response(content: str) -> dict[str, Any] | None:
    """Parse the LLM JSON response, tolerating markdown fences."""
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, dict) else None
