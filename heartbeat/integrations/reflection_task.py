"""ReflectionTask — consolidates data/LESSONS.md when it grows past a threshold.

Runs as a heartbeat integration every 5 minutes. When the lesson count reaches
``consolidation_threshold``, calls the LLM to merge/deduplicate entries and
rewrites the file in-place.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from core.telemetry import Event, EventBus, EventType
from heartbeat.integrations.base import HeartbeatIntegration

if TYPE_CHECKING:
    from core.llm import LLMGateway

logger = logging.getLogger(__name__)

_CONSOLIDATION_PROMPT = """\
You are reviewing a list of lessons learned by an AI agent.
Consolidate these lessons by:
1. Merging lessons that cover the same topic.
2. Removing lessons that have become redundant.
3. Keeping the most specific and actionable phrasing.

Return the result as a valid LESSONS.md file using the exact same format.

Current lessons:
{current_content}"""


class ReflectionTask(HeartbeatIntegration):
    """Heartbeat integration that consolidates LESSONS.md when it grows too large."""

    name: str = "reflection_task"

    def __init__(
        self,
        llm: "LLMGateway",
        event_bus: EventBus,
        lessons_path: str = "data/LESSONS.md",
        consolidation_threshold: int = 20,
    ) -> None:
        super().__init__(event_bus)
        self.llm = llm
        self.lessons_path = lessons_path
        self.consolidation_threshold = consolidation_threshold

    async def check(self) -> dict[str, Any]:
        """Check lesson count and consolidate if threshold is reached."""
        try:
            with open(self.lessons_path, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            return {"status": "skipped", "lesson_count": 0}

        lesson_count = self._count_lessons(content)

        if lesson_count < self.consolidation_threshold:
            return {"status": "skipped", "lesson_count": lesson_count}

        trace_id = uuid.uuid4().hex

        await self.event_bus.emit(Event(
            event_type=EventType.REFLECTION_START,
            component="heartbeat.reflection_task",
            trace_id=trace_id,
            payload={"lesson_count": lesson_count},
        ))

        consolidated = await self._consolidate(content, trace_id)

        with open(self.lessons_path, "w", encoding="utf-8") as f:
            f.write(consolidated)

        new_count = self._count_lessons(consolidated)

        await self.event_bus.emit(Event(
            event_type=EventType.REFLECTION_COMPLETE,
            component="heartbeat.reflection_task",
            trace_id=trace_id,
            payload={"before": lesson_count, "after": new_count},
            success=True,
        ))

        logger.info("ReflectionTask consolidated %d → %d lessons", lesson_count, new_count)
        return {"status": "consolidated", "lesson_count": lesson_count, "new_count": new_count}

    def _count_lessons(self, content: str) -> int:
        """Count the number of lesson entries by counting '## [' headers."""
        return content.count("## [")

    async def _consolidate(self, content: str, trace_id: str) -> str:
        """Ask the LLM to merge and deduplicate the lessons."""
        prompt = _CONSOLIDATION_PROMPT.format(current_content=content)
        response = await self.llm.generate(
            messages=[{"role": "user", "content": prompt}],
            trace_id=trace_id,
        )
        return response.content or content
