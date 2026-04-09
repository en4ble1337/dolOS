"""Conversation summarizer for managing context window size."""

import logging
import time
from typing import Dict, Optional

from core.llm import LLMGateway
from core.telemetry import Event, EventBus, EventType
from memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

_SUMMARIZATION_PROMPT = """\
Summarize the following conversation into a concise summary paragraph. \
Preserve key decisions, facts, action items, and the overall topic. \
The summary should be self-contained and useful for future context.

Conversation:
{conversation}"""


class ConversationSummarizer:
    """Summarizes long conversation sessions to manage context window size."""

    def __init__(
        self,
        llm: LLMGateway,
        memory: MemoryManager,
        event_bus: Optional[EventBus] = None,
        turn_threshold: int = 10,
        summary_importance: float = 0.9,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.event_bus = event_bus
        self.turn_threshold = turn_threshold
        self.summary_importance = summary_importance
        self._turn_counts: Dict[str, int] = {}

    def increment_turn(self, session_id: str) -> bool:
        """Increment the turn counter for a session.

        Returns:
            True if the threshold has been reached (summarization should trigger).
        """
        self._turn_counts[session_id] = self._turn_counts.get(session_id, 0) + 1
        if self._turn_counts[session_id] >= self.turn_threshold:
            self._turn_counts[session_id] = 0
            return True
        return False

    async def summarize_session(
        self, session_id: str, trace_id: str
    ) -> Optional[str]:
        """Summarize a session's recent conversation history.

        Args:
            session_id: The session to summarize.
            trace_id: Trace ID for telemetry correlation.

        Returns:
            The summary text, or None if too few memories exist.
        """
        if self.event_bus:
            self.event_bus.emit_sync(Event(
                event_type=EventType.SUMMARIZATION_START,
                component="summarizer",
                trace_id=trace_id,
                payload={"session_id": session_id},
            ))

        start = time.time()
        try:
            # Retrieve recent episodic memories for this session.
            # Use a broad conversational anchor (not "conversation summary") so
            # that the vector search does not bias toward summary-like text and
            # instead returns ALL turns for the session.  The filter_metadata
            # scope by session_id ensures we only see this session's turns.
            memories = self.memory.search(
                query="user assistant conversation exchange message",
                memory_type="episodic",
                limit=self.turn_threshold * 2,
                filter_metadata={"session_id": session_id},
            )

            # Filter out existing summaries
            memories = [m for m in memories if not m.get("metadata", {}).get("is_summary")]

            if len(memories) < 3:
                return None

            # Sort chronologically
            memories.sort(key=lambda m: m.get("timestamp", 0))

            conversation_text = "\n".join(m["text"] for m in memories)
            prompt = _SUMMARIZATION_PROMPT.format(conversation=conversation_text)

            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                trace_id=trace_id,
            )

            summary = (response.content or "").strip()
            if not summary:
                return None

            # Store the summary with high importance
            self.memory.add_memory(
                text=summary,
                memory_type="episodic",
                importance=self.summary_importance,
                metadata={
                    "session_id": session_id,
                    "role": "summary",
                    "is_summary": True,
                    "summarized_turn_count": len(memories),
                },
            )

            duration_ms = (time.time() - start) * 1000
            if self.event_bus:
                self.event_bus.emit_sync(Event(
                    event_type=EventType.SUMMARIZATION_COMPLETE,
                    component="summarizer",
                    trace_id=trace_id,
                    payload={
                        "session_id": session_id,
                        "memory_count_summarized": len(memories),
                        "summary_length": len(summary),
                    },
                    duration_ms=duration_ms,
                ))

            return summary

        except Exception as e:
            if self.event_bus:
                self.event_bus.emit_sync(Event(
                    event_type=EventType.SUMMARIZATION_ERROR,
                    component="summarizer",
                    trace_id=trace_id,
                    payload={"session_id": session_id, "error": str(e)},
                    success=False,
                ))
            raise

    def get_session_summary(self, session_id: str) -> Optional[str]:
        """Retrieve the most recent summary for a session.

        Returns:
            The summary text, or None if no summary exists.
        """
        results = self.memory.search(
            query="conversation summary",
            memory_type="episodic",
            limit=1,
            filter_metadata={"session_id": session_id, "is_summary": True},
        )
        if results:
            summary_text = results[0].get("text")
            if isinstance(summary_text, str):
                return summary_text
        return None
