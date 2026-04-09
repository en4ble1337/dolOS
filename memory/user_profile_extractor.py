"""User profile extractor for maintaining a living USER.md document."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import Any, Optional

from core.telemetry import Event, EventBus, EventType

logger = logging.getLogger(__name__)

_REQUIRED_SECTIONS = (
    "Communication Style",
    "Technical Profile",
    "Current Work Context",
    "Interaction Preferences",
    "Things to Always Do",
    "Things to Never Do",
)

_UPDATE_PROMPT = """\
You maintain a profile of this user to serve them better.

Current profile:
{current_user_md}

Recent conversation (last 10 turns):
{recent_turns_summary}

Update the profile. Add, modify, or remove sections based on what you learned.
Return the complete updated USER.md and nothing else.

Required sections:
- Communication Style
- Technical Profile
- Current Work Context
- Interaction Preferences
- Things to Always Do
- Things to Never Do
"""


class UserProfileExtractor:
    """Maintains a structured USER.md profile updated every N turns."""

    UPDATE_EVERY_N_TURNS = 10

    def __init__(
        self,
        llm: Any,
        profile_path: str = "data/USER.md",
        static_loader: Any = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.llm = llm
        self.profile_path = profile_path
        self.static_loader = static_loader
        self.event_bus = event_bus
        self._turn_counts: dict[str, int] = {}

    async def maybe_update(
        self,
        session_id: str,
        recent_turns: list[dict],
        trace_id: str,
    ) -> int:
        """Return 1 when USER.md was updated, else 0."""
        if not self._increment_turn(session_id):
            return 0

        if self.llm is None:
            return 0

        filtered_turns = [
            turn for turn in recent_turns if turn.get("type") in {"user", "assistant"}
        ][-20:]
        if not filtered_turns:
            return 0

        current_profile = self._read_current_profile()
        prompt = _UPDATE_PROMPT.format(
            current_user_md=current_profile or "(empty)",
            recent_turns_summary=self._render_recent_turns(filtered_turns),
        )

        if self.event_bus:
            await self.event_bus.emit(
                Event(
                    event_type=EventType.USER_PROFILE_UPDATE_START,
                    component="memory.user_profile_extractor",
                    trace_id=trace_id,
                    payload={"session_id": session_id},
                )
            )

        try:
            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning("UserProfileExtractor: LLM call failed: %s", exc)
            return 0

        updated_profile = self._validate_profile_document(response.content or "")
        if updated_profile is None:
            logger.warning("UserProfileExtractor: invalid USER.md content returned by LLM.")
            return 0

        try:
            self._write_profile(updated_profile)
        except OSError as exc:
            logger.warning("UserProfileExtractor: failed to write USER.md: %s", exc)
            return 0

        if self.static_loader is not None:
            try:
                self.static_loader.evict_by_source_tag("user_profile")
                self.static_loader.index_file(self.profile_path, source_tag="user_profile")
            except Exception as exc:
                logger.warning("UserProfileExtractor: failed to refresh semantic profile chunks: %s", exc)
                return 0

        if self.event_bus:
            await self.event_bus.emit(
                Event(
                    event_type=EventType.USER_PROFILE_UPDATE_COMPLETE,
                    component="memory.user_profile_extractor",
                    trace_id=trace_id,
                    payload={"session_id": session_id, "profile_path": self.profile_path},
                )
            )

        return 1

    def _increment_turn(self, session_id: str) -> bool:
        self._turn_counts[session_id] = self._turn_counts.get(session_id, 0) + 1
        if self._turn_counts[session_id] < self.UPDATE_EVERY_N_TURNS:
            return False
        self._turn_counts[session_id] = 0
        return True

    def _read_current_profile(self) -> str:
        if not os.path.exists(self.profile_path):
            return ""
        try:
            with open(self.profile_path, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError as exc:
            logger.warning("UserProfileExtractor: failed to read USER.md: %s", exc)
            return ""

    def _render_recent_turns(self, recent_turns: list[dict]) -> str:
        lines: list[str] = []
        for turn in recent_turns:
            role = "User" if turn.get("type") == "user" else "Assistant"
            content = str(turn.get("content", "")).strip()
            if not content:
                continue
            lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else "(no recent turns)"

    def _validate_profile_document(self, raw_content: str) -> str | None:
        content = raw_content.strip()
        content = re.sub(r"^```(?:md|markdown)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        content = content.strip()
        if not content or "#" not in content:
            return None
        if not all(section in content for section in _REQUIRED_SECTIONS):
            return None
        return content + ("\n" if not content.endswith("\n") else "")

    def _write_profile(self, content: str) -> None:
        directory = os.path.dirname(self.profile_path) or "."
        os.makedirs(directory, exist_ok=True)
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=directory,
                prefix="user-profile-",
                suffix=".tmp",
                delete=False,
            ) as temp_handle:
                temp_handle.write(content)
                temp_path = temp_handle.name
            os.replace(temp_path, self.profile_path)
        except OSError:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            raise
