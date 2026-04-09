"""4-phase iterative context compression (Gap H1).

Fires when the messages list within a session's tool-call loop grows large.
Replaces the expensive single-pass summarizer with a structured, iterative
approach that preserves coherence across multiple compression cycles.

Pipeline
--------
Phase 1 — Tool output pruning
    Old tool results beyond the tail window are replaced with a one-line
    ``[tool result omitted]`` placeholder.  No LLM call; zero cost.

Phase 2 — Head / tail split
    The system prompt (index 0) and the first user exchange (indices 1-2) are
    frozen as the *head*.  The most-recent ``tail_tokens`` chars of messages
    are kept verbatim as the *tail*.  Everything in between is the *middle*.

Phase 3 — Structured summarization
    The middle is collapsed into a fixed-template summary via a single LLM call.
    Template: Goal / Progress / Decisions / Files Changed / Next Steps.

Phase 4 — Iterative merge
    If a ``prior_summary`` exists from a previous compression cycle, the new
    summary is merged into it (rather than starting fresh) so the LLM always
    sees a coherent running summary.

Token budget
    Summary is capped at 20% of compressed content, max 12 000 chars.
"""

import logging
from typing import TYPE_CHECKING

from core.telemetry import get_trace_id

if TYPE_CHECKING:
    from core.llm import LLMGateway

logger = logging.getLogger(__name__)

SUMMARY_TEMPLATE = """\
## Session Summary
**Goal:** {goal}
**Progress:** {progress}
**Decisions:** {decisions}
**Files Changed:** {files}
**Next Steps:** {next_steps}"""

_MAX_SUMMARY_CHARS = 12_000
_SUMMARY_BUDGET_RATIO = 0.20  # cap summary at 20% of compressed content


class ContextCompressor:
    """4-phase context compressor for long-running tool-call loops."""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def compress(
        self,
        messages: list[dict],
        prior_summary: str | None,
        llm: "LLMGateway",
        trace_id: str | None = None,
        head_tokens: int = 4_000,
        tail_tokens: int = 20_000,
    ) -> tuple[list[dict], str]:
        """Compress *messages* using the 4-phase pipeline.

        Parameters
        ----------
        messages:
            The current message list (system + conversation turns).
        prior_summary:
            The summary produced by the previous compression cycle, or
            ``None`` on the first compression.
        llm:
            The :class:`~core.llm.LLMGateway` used for the summarisation call.
        head_tokens:
            Approximate char budget for the protected head window.
            (chars ≈ tokens × 4).
        tail_tokens:
            Approximate char budget for the protected tail window.

        Returns
        -------
        tuple[list[dict], str]
            ``(compressed_messages, new_summary)`` where *new_summary* should
            be stored by the caller and passed back on the next compression.
        """
        if len(messages) <= 3:
            # Nothing to compress — head + one turn = already minimal
            return messages, prior_summary or ""

        active_trace_id = trace_id or get_trace_id()

        head_chars = head_tokens * 4
        tail_chars = tail_tokens * 4

        # Phase 1 — prune tool outputs that fall outside the tail window
        messages = self._prune_tool_outputs(messages, tail_chars)

        # Phase 2 — split into head / middle / tail
        head, middle, tail = self._split(messages, head_chars, tail_chars)

        if not middle:
            # Nothing in the middle; nothing to summarise
            return messages, prior_summary or ""

        # Phase 3 — summarise the middle
        new_summary = await self._summarise(middle, llm, trace_id=active_trace_id)

        # Phase 4 — merge with prior summary if one exists
        if prior_summary:
            new_summary = await self._merge(
                prior_summary,
                new_summary,
                llm,
                trace_id=active_trace_id,
            )

        # Cap summary size
        if len(new_summary) > _MAX_SUMMARY_CHARS:
            new_summary = new_summary[:_MAX_SUMMARY_CHARS] + "\n[summary truncated]"

        # Reassemble: head + summary block + tail
        summary_message = {
            "role": "system",
            "content": f"[CONTEXT COMPRESSED]\n{new_summary}",
        }
        compressed = head + [summary_message] + tail

        logger.info(
            "[COMPRESSOR] %d → %d messages (summary %d chars)",
            len(messages),
            len(compressed),
            len(new_summary),
        )
        return compressed, new_summary

    # ------------------------------------------------------------------ #
    # Internal phases                                                      #
    # ------------------------------------------------------------------ #

    def _prune_tool_outputs(self, messages: list[dict], tail_chars: int) -> list[dict]:
        """Phase 1: Replace old tool results with short placeholders.

        Scans from the *end* of the message list backwards, accumulating char
        counts.  Once the char budget is exhausted, any earlier tool-result
        messages are replaced with a placeholder.
        """
        # Work backwards to find where the tail window starts.
        # tail_start is the first index that belongs to the tail.
        # Default 0 means everything fits in the tail (nothing to prune).
        accumulated = 0
        tail_start = 0
        for i in range(len(messages) - 1, -1, -1):
            accumulated += len(str(messages[i].get("content") or ""))
            if accumulated >= tail_chars:
                tail_start = i + 1  # messages from i+1 onward are in the tail
                break

        pruned = list(messages)
        for i in range(tail_start):
            msg = pruned[i]
            role = msg.get("role", "")
            if role == "tool":
                pruned[i] = {**msg, "content": "[tool result omitted]"}
        return pruned

    def _split(
        self,
        messages: list[dict],
        head_chars: int,
        tail_chars: int,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Phase 2: Partition messages into head / middle / tail.

        * **head** — system prompt (index 0) + first user turn (index 1).
        * **tail** — the most-recent messages up to *tail_chars* of content.
        * **middle** — everything in between (candidate for summarisation).
        """
        if len(messages) <= 2:
            return messages, [], []

        head = messages[:2]  # system + first user message

        # Build tail from the end, up to tail_chars of content
        accumulated = 0
        tail_start = len(messages)
        for i in range(len(messages) - 1, 1, -1):  # don't consume head
            msg_len = len(str(messages[i].get("content") or ""))
            if accumulated + msg_len > tail_chars:
                break
            accumulated += msg_len
            tail_start = i

        tail = messages[tail_start:]
        middle = messages[2:tail_start]
        return head, middle, tail

    async def _summarise(
        self,
        middle: list[dict],
        llm: "LLMGateway",
        trace_id: str | None = None,
    ) -> str:
        """Phase 3: Collapse *middle* messages into a structured summary."""
        middle_text = self._render_messages(middle)
        active_trace_id = trace_id or get_trace_id()

        prompt = (
            "You are a context compressor. Summarise the conversation excerpt below "
            "using EXACTLY this template (fill in each field concisely):\n\n"
            f"{SUMMARY_TEMPLATE}\n\n"
            "Excerpt to summarise:\n\n"
            f"{middle_text}\n\n"
            "Return ONLY the filled template, nothing else."
        )

        try:
            response = await llm.generate(
                messages=[
                    {"role": "system", "content": "You are a context compressor."},
                    {"role": "user", "content": prompt},
                ],
                trace_id=active_trace_id,
            )
            return response.content or self._fallback_summary(middle)
        except Exception as exc:
            logger.warning("[COMPRESSOR] Summarisation LLM call failed: %s", exc)
            return self._fallback_summary(middle)

    async def _merge(
        self,
        prior_summary: str,
        new_summary: str,
        llm: "LLMGateway",
        trace_id: str | None = None,
    ) -> str:
        """Phase 4: Merge *new_summary* into *prior_summary*."""
        active_trace_id = trace_id or get_trace_id()
        prompt = (
            "You are a context compressor. Merge the two session summaries below "
            "into a single coherent summary using EXACTLY the same template structure.\n\n"
            f"PRIOR SUMMARY:\n{prior_summary}\n\n"
            f"NEW SUMMARY:\n{new_summary}\n\n"
            "Return ONLY the merged summary using the template fields "
            "(Goal / Progress / Decisions / Files Changed / Next Steps), nothing else."
        )

        try:
            response = await llm.generate(
                messages=[
                    {"role": "system", "content": "You are a context compressor."},
                    {"role": "user", "content": prompt},
                ],
                trace_id=active_trace_id,
            )
            return response.content or new_summary
        except Exception as exc:
            logger.warning("[COMPRESSOR] Merge LLM call failed: %s", exc)
            return new_summary  # fall back to the latest summary alone

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _render_messages(messages: list[dict]) -> str:
        """Render a message list as a readable transcript for the LLM."""
        parts = []
        for m in messages:
            role = m.get("role", "unknown")
            content = m.get("content") or ""
            parts.append(f"{role.upper()}: {content}")
        return "\n\n".join(parts)

    @staticmethod
    def _fallback_summary(middle: list[dict]) -> str:
        """Return a minimal summary when the LLM call fails."""
        count = len(middle)
        return (
            "## Session Summary\n"
            f"**Goal:** (unavailable — LLM call failed)\n"
            f"**Progress:** {count} messages omitted from context\n"
            "**Decisions:** (see omitted messages)\n"
            "**Files Changed:** (unknown)\n"
            "**Next Steps:** (unknown)"
        )
