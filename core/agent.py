import uuid
from typing import Optional

from core.llm import LLMGateway
from core.telemetry import EventBus, reset_trace_id, set_trace_id
from memory.memory_manager import MemoryManager


class Agent:
    """The central agent orchestrator wrapping LLM, Memory, and Telemetry."""

    def __init__(
        self,
        llm: LLMGateway,
        memory: MemoryManager,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.event_bus = event_bus

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
                metadata={"session_id": session_id, "role": "user"},
            )

            # 3. Retrieve context
            results = self.memory.search(query=message, memory_type="episodic", limit=5)
            # Reverse results so chronological order is bottom-heavy (assuming search returns highest relevance first,
            # this might not strictly be chronological, but we'll list them as context).
            context_blocks = "\n".join([r["text"] for r in results])

            import os
            soul_path = os.path.join("data", "SOUL.md")
            soul_content = "You are a helpful, autonomous AI agent."
            if os.path.exists(soul_path):
                with open(soul_path, "r", encoding="utf-8") as f:
                    soul_content = f.read()

            system_prompt = (
                f"{soul_content}\n\n"
                "Here is relevant context from your exact episodic memory. Always cite them if relevant:\n\n"
                f"{context_blocks}"
            )

            # 4. Form message list
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ]

            # 5. Generate reply
            response = await self.llm.generate(messages=messages, trace_id=trace_id)
            content = response.content or ""

            # 6. Add assistant reply to memory
            assistant_text = f"Assistant: {content}"
            self.memory.add_memory(
                text=assistant_text,
                memory_type="episodic",
                metadata={"session_id": session_id, "role": "assistant"},
            )

            return content
        finally:
            reset_trace_id(trace_token)
