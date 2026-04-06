"""Operator command layer — deterministic /-prefixed commands.

These commands are handled before the agent loop: they don't go through
the LLM, don't consume tokens, and always return predictable output.
This makes control operations (inspect memory, list skills, etc.) cheap,
fast, and auditable.

Usage:
    router = CommandRouter(agent, memory_manager, event_bus)
    result = await router.handle(session_id, "/skills list")
    if result is not None:
        # It was a command — return result directly, skip agent loop
    else:
        # Not a command — pass to agent.process_message() as normal

Adding new commands:
    Register a handler in CommandRouter._register_handlers() following
    the existing pattern. Handlers are async callables:
        async def _cmd_foo(self, session_id: str, args: str) -> str
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Awaitable

if TYPE_CHECKING:
    from core.agent import Agent
    from memory.memory_manager import MemoryManager
    from core.telemetry import EventBus

logger = logging.getLogger(__name__)

# Type alias for a bound command handler function
_Handler = Callable[[str, str], Awaitable[str]]


class CommandRouter:
    """Routes /-prefixed operator commands to their handlers.

    All public state (agent, memory, event_bus) is injected at construction
    time so commands can introspect the live system without going through the LLM.
    """

    COMMAND_PREFIX = "/"

    def __init__(
        self,
        agent: "Agent",
        memory: "MemoryManager",
        event_bus: "EventBus | None" = None,
    ) -> None:
        self.agent = agent
        self.memory = memory
        self.event_bus = event_bus
        self._handlers: dict[str, _Handler] = {}
        self._register_handlers()

    def _register_handlers(self) -> None:
        self._handlers.update(
            {
                "memory search": self._cmd_memory_search,
                "memory stats": self._cmd_memory_stats,
                "compact": self._cmd_compact,
                "skills": self._cmd_skills,
                "skills list": self._cmd_skills,
                "doctor": self._cmd_doctor,
                "help": self._cmd_help,
            }
        )

    async def handle(self, session_id: str, text: str) -> str | None:
        """Attempt to dispatch a command.

        Args:
            session_id: The current session ID.
            text: The raw input string from the user/API.

        Returns:
            A string response if the input was a recognised command,
            or None if it is not a command (should be passed to the agent).
        """
        stripped = text.strip()
        if not stripped.startswith(self.COMMAND_PREFIX):
            return None

        # Strip the leading slash and normalise whitespace
        body = stripped[len(self.COMMAND_PREFIX):].strip()
        cmd_lower = body.lower()

        # Try longest-prefix match first (e.g. "memory search" before "memory")
        for key in sorted(self._handlers, key=len, reverse=True):
            if cmd_lower == key or cmd_lower.startswith(key + " "):
                args = body[len(key):].strip()
                logger.info("[COMMAND] session=%s cmd=%r args=%r", session_id, key, args)
                try:
                    return await self._handlers[key](session_id, args)
                except Exception as e:
                    logger.exception("[COMMAND] Error in handler %r: %s", key, e)
                    return f"Command error: {e}"

        return f"Unknown command: /{body}\nType /help for a list of available commands."

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _cmd_memory_search(self, session_id: str, args: str) -> str:
        if not args:
            return "Usage: /memory search <query>"
        try:
            episodic = self.memory.search(query=args, memory_type="episodic", limit=5, min_score=0.3)
            semantic = self.memory.search(query=args, memory_type="semantic", limit=5, min_score=0.35)
            lines = ["**Episodic results:**"]
            for r in episodic:
                score = r.get("score", 0)
                lines.append(f"  [{score:.2f}] {r['text'][:120]}")
            lines.append("\n**Semantic results:**")
            for r in semantic:
                score = r.get("score", 0)
                lines.append(f"  [{score:.2f}] {r['text'][:120]}")
            if not episodic and not semantic:
                return "No results found."
            return "\n".join(lines)
        except Exception as e:
            return f"Memory search error: {e}"

    async def _cmd_memory_stats(self, session_id: str, args: str) -> str:
        try:
            lines = ["**Memory stats:**"]
            for collection in ("episodic", "semantic"):
                try:
                    count = self.memory.vector_store.count(collection)
                    lines.append(f"  {collection}: {count} entries")
                except Exception:
                    lines.append(f"  {collection}: unavailable")
            return "\n".join(lines)
        except Exception as e:
            return f"Memory stats error: {e}"

    async def _cmd_compact(self, session_id: str, args: str) -> str:
        if not self.agent.summarizer:
            return "Summarizer not configured — cannot compact."
        try:
            from core.telemetry import Event, EventType
            trace_id = "compact-cmd"
            await self.agent._run_summarization(session_id, trace_id)
            return "Conversation compacted (summarization triggered)."
        except Exception as e:
            return f"Compact error: {e}"

    async def _cmd_skills(self, session_id: str, args: str) -> str:
        if not self.agent.skill_executor:
            return "No skill executor configured."
        names = self.agent.skill_executor.registry.get_all_skill_names()
        if not names:
            return "No skills registered."
        lines = ["**Registered skills:**"]
        for name in sorted(names):
            try:
                schema = self.agent.skill_executor.registry.get_schema(name)
                desc = schema.get("description", "")[:80]
            except KeyError:
                desc = ""
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)

    async def _cmd_doctor(self, session_id: str, args: str) -> str:
        checks: list[tuple[str, bool, str]] = [
            ("LLM gateway", self.agent.llm is not None, ""),
            ("Memory manager", self.agent.memory is not None, ""),
            ("Skill executor", self.agent.skill_executor is not None, ""),
            ("Summarizer", self.agent.summarizer is not None, "optional"),
            ("Combined extractor", self.agent.combined_extractor is not None, "optional"),
            ("Lesson extractor", self.agent.lesson_extractor is not None, "optional"),
            ("Semantic extractor", self.agent.semantic_extractor is not None, "optional"),
            ("Event bus", self.agent.event_bus is not None, "optional"),
        ]
        lines = ["**System health check:**"]
        all_required_ok = True
        for label, ok, note in checks:
            status = "✓" if ok else ("?" if note == "optional" else "✗")
            suffix = f" ({note})" if note and not ok else ""
            lines.append(f"  {status} {label}{suffix}")
            if not ok and note != "optional":
                all_required_ok = False
        lines.append("")
        lines.append("All required components OK." if all_required_ok else "WARNING: some required components are missing.")
        return "\n".join(lines)

    async def _cmd_help(self, session_id: str, args: str) -> str:
        return (
            "**Available operator commands:**\n"
            "  /memory search <query>  — search episodic + semantic memory\n"
            "  /memory stats           — show memory collection sizes\n"
            "  /compact                — trigger conversation summarization now\n"
            "  /skills list            — list all registered skills\n"
            "  /doctor                 — system health check\n"
            "  /help                   — show this message\n"
        )
