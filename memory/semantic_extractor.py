"""LLM-powered fact extraction pipeline for semantic memory."""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from core.llm import LLMGateway
from core.telemetry import Event, EventBus, EventType
from memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Extract factual, durable information from this conversation exchange that would \
be useful to remember long-term. Return ONLY a JSON array of fact strings. \
If no durable facts exist, return an empty array [].

Rules:
- Facts should be self-contained (understandable without the conversation)
- Skip ephemeral/transient information (greetings, acknowledgments)
- Skip information that is only relevant to this specific moment
- Focus on: user preferences, personal details, project decisions, technical choices, important dates, relationships

User: {user_message}
Assistant: {assistant_response}"""


class SemanticExtractor:
    """Extracts durable facts from conversation turns and stores them in semantic memory."""

    def __init__(
        self,
        llm: LLMGateway,
        memory: MemoryManager,
        event_bus: Optional[EventBus] = None,
        similarity_threshold: float = 0.85,
        default_importance: float = 0.8,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.event_bus = event_bus
        self.similarity_threshold = similarity_threshold
        self.default_importance = default_importance

    async def extract_and_store(
        self,
        user_message: str,
        assistant_response: str,
        session_id: str,
        trace_id: str,
    ) -> int:
        """Extract facts from a conversation turn and store non-duplicates.

        Returns:
            Number of new facts stored.
        """
        if not user_message.strip() or not assistant_response.strip():
            return 0

        if self.event_bus:
            self.event_bus.emit_sync(Event(
                event_type=EventType.SEMANTIC_EXTRACTION_START,
                component="semantic_extractor",
                trace_id=trace_id,
                payload={"session_id": session_id},
            ))

        start = time.time()
        try:
            facts = await self._extract_facts(user_message, assistant_response, trace_id)
        except Exception as e:
            if self.event_bus:
                self.event_bus.emit_sync(Event(
                    event_type=EventType.SEMANTIC_EXTRACTION_ERROR,
                    component="semantic_extractor",
                    trace_id=trace_id,
                    payload={"error": str(e)},
                    success=False,
                ))
            raise

        stored = 0
        duplicates = 0
        for fact in facts:
            if self._is_duplicate(fact):
                duplicates += 1
                if self.event_bus:
                    self.event_bus.emit_sync(Event(
                        event_type=EventType.SEMANTIC_DUPLICATE_DETECTED,
                        component="semantic_extractor",
                        trace_id=trace_id,
                        payload={"fact": fact[:100]},
                    ))
                continue

            self.memory.add_memory(
                text=fact,
                memory_type="semantic",
                importance=self.default_importance,
                metadata={"session_id": session_id, "source": "extraction"},
            )
            stored += 1

        duration_ms = (time.time() - start) * 1000
        if self.event_bus:
            self.event_bus.emit_sync(Event(
                event_type=EventType.SEMANTIC_EXTRACTION_COMPLETE,
                component="semantic_extractor",
                trace_id=trace_id,
                payload={
                    "facts_extracted": len(facts),
                    "facts_stored": stored,
                    "duplicates_skipped": duplicates,
                },
                duration_ms=duration_ms,
            ))

        return stored

    async def _extract_facts(
        self, user_message: str, assistant_response: str, trace_id: str
    ) -> List[str]:
        """Call the LLM to extract durable facts from a conversation turn."""
        prompt = _EXTRACTION_PROMPT.format(
            user_message=user_message,
            assistant_response=assistant_response,
        )

        response = await self.llm.generate(
            messages=[{"role": "user", "content": prompt}],
            trace_id=trace_id,
        )

        content = (response.content or "").strip()
        # Strip markdown code fences if present
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return [str(f) for f in parsed if f]
        except json.JSONDecodeError:
            pass

        # Regex fallback: find a JSON array anywhere in the response
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    return [str(f) for f in parsed if f]
            except json.JSONDecodeError:
                pass

        logger.debug("Could not parse facts from LLM response: %s", content[:200])
        return []

    def _is_duplicate(self, fact: str) -> bool:
        """Check if a near-identical fact already exists in semantic memory."""
        results = self.memory.search(
            query=fact,
            memory_type="semantic",
            limit=1,
            similarity_weight=1.0,
            recency_weight=0.0,
            importance_weight=0.0,
        )
        if results and results[0].get("similarity", 0) > self.similarity_threshold:
            return True
        return False
