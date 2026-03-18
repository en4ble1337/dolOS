"""LessonExtractor — detects corrections and preference signals in conversation turns,
stores them to data/LESSONS.md and into semantic memory for deduplication.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from core.telemetry import Event, EventBus, EventType

if TYPE_CHECKING:
    from core.llm import LLMGateway
    from memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Analyse this conversation exchange. Identify any of the following signals:
1. The user explicitly corrected the assistant.
2. The assistant made a mistake and then recovered.
3. A better approach or method was discovered.
4. The user stated a preference about HOW the assistant should work.

Return ONLY a JSON array: [{{"title": "...", "context": "...", "lesson": "..."}}]
If none apply, return [].

User: {user_message}
Assistant: {assistant_response}"""

_FILE_HEADER = """\
# Agent Lessons Learned

<!-- This file is auto-managed. Do not edit manually. -->

"""


class LessonExtractor:
    """Extracts behavioural lessons from conversation turns and persists them."""

    def __init__(
        self,
        llm: "LLMGateway",
        memory: "MemoryManager",
        lessons_path: str = "data/LESSONS.md",
        event_bus: Optional[EventBus] = None,
        similarity_threshold: float = 0.90,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.lessons_path = lessons_path
        self.event_bus = event_bus
        self.similarity_threshold = similarity_threshold

    async def extract_and_store(
        self,
        user_message: str,
        assistant_response: str,
        session_id: str,
        trace_id: str,
    ) -> int:
        """Extract lessons from a turn and persist new ones. Returns count stored."""
        if not user_message.strip() or not assistant_response.strip():
            return 0

        if self.event_bus:
            await self.event_bus.emit(Event(
                event_type=EventType.LESSON_EXTRACTION_START,
                component="memory.lesson_extractor",
                trace_id=trace_id,
                payload={"session_id": session_id},
            ))

        try:
            lessons = await self._call_llm(user_message, assistant_response, trace_id)
        except Exception as e:
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.LESSON_EXTRACTION_ERROR,
                    component="memory.lesson_extractor",
                    trace_id=trace_id,
                    payload={"error": str(e)},
                    success=False,
                ))
            raise

        new_lessons = []
        for lesson in lessons:
            lesson_text = f"{lesson.get('title', '')} {lesson.get('lesson', '')}"
            if await self._is_duplicate(lesson_text):
                if self.event_bus:
                    await self.event_bus.emit(Event(
                        event_type=EventType.LESSON_DUPLICATE_SKIPPED,
                        component="memory.lesson_extractor",
                        trace_id=trace_id,
                        payload={"title": lesson.get("title")},
                    ))
                continue
            new_lessons.append(lesson)

        if new_lessons:
            self._append_to_file(new_lessons)
            for lesson in new_lessons:
                lesson_text = f"{lesson.get('title', '')}: {lesson.get('lesson', '')}"
                self.memory.add_memory(
                    text=lesson_text,
                    memory_type="semantic",
                    metadata={"source": "lesson", "title": lesson.get("title", "")},
                )

        if self.event_bus:
            await self.event_bus.emit(Event(
                event_type=EventType.LESSON_EXTRACTION_COMPLETE,
                component="memory.lesson_extractor",
                trace_id=trace_id,
                payload={"stored": len(new_lessons)},
                success=True,
            ))

        return len(new_lessons)

    async def _call_llm(
        self, user_message: str, assistant_response: str, trace_id: str
    ) -> list[dict]:
        prompt = _EXTRACTION_PROMPT.format(
            user_message=user_message,
            assistant_response=assistant_response,
        )
        response = await self.llm.generate(
            messages=[{"role": "user", "content": prompt}],
            trace_id=trace_id,
        )
        return _parse_json(response.content or "[]")

    async def _is_duplicate(self, lesson_text: str) -> bool:
        results = self.memory.search(
            query=lesson_text,
            memory_type="semantic",
            filter_metadata={"source": "lesson"},
            limit=1,
        )
        if not results:
            return False
        top_score = results[0].get("score", 0.0)
        return float(top_score) >= self.similarity_threshold

    def _append_to_file(self, lessons: list[dict]) -> None:
        os.makedirs(os.path.dirname(self.lessons_path) or ".", exist_ok=True)

        if not os.path.exists(self.lessons_path):
            with open(self.lessons_path, "w", encoding="utf-8") as f:
                f.write(_FILE_HEADER)

        today = date.today().isoformat()
        with open(self.lessons_path, "a", encoding="utf-8") as f:
            for lesson in lessons:
                title = lesson.get("title", "Untitled")
                context = lesson.get("context", "")
                lesson_text = lesson.get("lesson", "")
                f.write(f"## [{today}] {title}\n")
                f.write(f"**Context:** {context}\n")
                f.write(f"**Lesson:** {lesson_text}\n\n")
                f.write("---\n\n")


def _parse_json(raw: str) -> list[dict]:
    """Parse JSON from LLM output, stripping markdown fences if present."""
    text = raw.strip()
    # Strip ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    return []
