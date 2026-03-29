"""CombinedTurnExtractor — single LLM call that extracts both durable facts and
behavioural lessons from a conversation turn, delegating storage to SemanticExtractor
and LessonExtractor respectively.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import TYPE_CHECKING, Optional

from core.telemetry import Event, EventBus, EventType

if TYPE_CHECKING:
    from core.llm import LLMGateway
    from memory.lesson_extractor import LessonExtractor
    from memory.semantic_extractor import SemanticExtractor

logger = logging.getLogger(__name__)

_COMBINED_PROMPT = """\
Analyze this conversation exchange and return a JSON object with exactly two keys:

"facts": A JSON array of durable factual strings worth remembering long-term \
(user preferences, technical decisions, project choices). Return [] if none.

"lessons": A JSON array of objects [{{"title": "...", "context": "...", "lesson": "..."}}] \
capturing corrections, preference signals, or better approaches discovered. Return [] if none.

Rules for facts:
- Self-contained (understandable without this conversation)
- Skip ephemeral info (greetings, acknowledgments)
- Focus on: preferences, decisions, technical choices, important dates

Rules for lessons:
- Only when user corrected the assistant, assistant made and recovered from a mistake,
  a better approach was discovered, or user stated a preference about HOW assistant should work

User: {user_message}
Assistant: {assistant_response}"""


class CombinedTurnExtractor:
    """Runs one LLM call per turn to extract both facts and lessons."""

    def __init__(
        self,
        llm: "LLMGateway",
        semantic_extractor: "SemanticExtractor",
        lesson_extractor: "LessonExtractor",
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.llm = llm
        self.semantic_extractor = semantic_extractor
        self.lesson_extractor = lesson_extractor
        self.event_bus = event_bus

    async def extract_and_store(
        self,
        user_message: str,
        assistant_response: str,
        session_id: str,
        trace_id: str,
    ) -> dict:
        """Run combined extraction. Returns {"facts_stored": N, "lessons_stored": N}"""
        if not user_message.strip() or not assistant_response.strip():
            return {"facts_stored": 0, "lessons_stored": 0}

        start = time.time()

        # 1. Call LLM once with combined prompt
        prompt = _COMBINED_PROMPT.format(
            user_message=user_message,
            assistant_response=assistant_response,
        )
        try:
            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                trace_id=trace_id,
            )
        except Exception as e:
            logger.warning("CombinedTurnExtractor: LLM call failed: %s", e)
            return {"facts_stored": 0, "lessons_stored": 0}

        # 2. Parse JSON response → facts list + lessons list
        facts, lessons = _parse_combined_response(response.content or "")

        # 3. Store facts via semantic_extractor internals
        facts_stored = 0
        for fact in facts:
            if not fact:
                continue
            if not self.semantic_extractor._is_duplicate(fact):
                self.semantic_extractor.memory.add_memory(
                    text=fact,
                    memory_type="semantic",
                    importance=self.semantic_extractor.default_importance,
                    metadata={"session_id": session_id, "source": "extraction"},
                )
                facts_stored += 1

        # 4. Store lessons via lesson_extractor internals
        lessons_stored = 0
        new_lessons = []
        for lesson in lessons:
            lesson_text = f"{lesson.get('title', '')} {lesson.get('lesson', '')}"
            if not await self.lesson_extractor._is_duplicate(lesson_text):
                new_lessons.append(lesson)

        if new_lessons:
            self.lesson_extractor._append_to_file(new_lessons)
            for lesson in new_lessons:
                lesson_text = f"{lesson.get('title', '')}: {lesson.get('lesson', '')}"
                self.lesson_extractor.memory.add_memory(
                    text=lesson_text,
                    memory_type="semantic",
                    metadata={"source": "lesson", "title": lesson.get("title", "")},
                )
            lessons_stored = len(new_lessons)

        # 5. Emit telemetry event
        duration_ms = (time.time() - start) * 1000
        if self.event_bus:
            self.event_bus.emit_sync(Event(
                event_type=EventType.SEMANTIC_EXTRACTION_COMPLETE,
                component="memory.combined_extractor",
                trace_id=trace_id,
                payload={
                    "session_id": session_id,
                    "facts_stored": facts_stored,
                    "lessons_stored": lessons_stored,
                },
                duration_ms=duration_ms,
            ))

        return {"facts_stored": facts_stored, "lessons_stored": lessons_stored}


def _parse_combined_response(content: str) -> tuple[list[str], list[dict]]:
    """Parse combined JSON response from LLM. Returns (facts, lessons).

    Handles markdown fences and falls back to regex extraction on malformed JSON.
    """
    text = content.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    parsed = _try_parse_json_object(text)
    if parsed is None:
        # Regex fallback: find {"facts": [...], "lessons": [...]} anywhere in response
        match = re.search(r'\{[^{}]*"facts"\s*:\s*\[.*?\][^{}]*"lessons"\s*:\s*\[.*?\][^{}]*\}',
                          text, re.DOTALL)
        if match is None:
            match = re.search(r'\{[^{}]*"lessons"\s*:\s*\[.*?\][^{}]*"facts"\s*:\s*\[.*?\][^{}]*\}',
                              text, re.DOTALL)
        if match:
            parsed = _try_parse_json_object(match.group())

    if parsed is None:
        logger.warning("CombinedTurnExtractor: could not parse JSON from LLM response: %s", content[:200])
        return [], []

    facts_raw = parsed.get("facts", [])
    lessons_raw = parsed.get("lessons", [])

    facts: list[str] = [str(f) for f in facts_raw if f] if isinstance(facts_raw, list) else []
    lessons: list[dict] = [l for l in lessons_raw if isinstance(l, dict)] if isinstance(lessons_raw, list) else []

    return facts, lessons


def _try_parse_json_object(text: str) -> dict | None:
    """Attempt to parse text as a JSON object. Returns dict or None."""
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    return None
