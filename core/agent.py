import json
import uuid
from typing import Optional

from core.llm import LLMGateway
from core.telemetry import EventBus, reset_trace_id, set_trace_id
from memory.memory_manager import MemoryManager
from skills.executor import SkillExecutor


class Agent:
    """The central agent orchestrator wrapping LLM, Memory, Telemetry, and Skills."""

    def __init__(
        self,
        llm: LLMGateway,
        memory: MemoryManager,
        event_bus: Optional[EventBus] = None,
        skill_executor: Optional[SkillExecutor] = None,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.event_bus = event_bus
        self.skill_executor = skill_executor

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
            context_blocks = "\n".join([r["text"] for r in results])

            import os
            soul_path = os.path.join("data", "SOUL.md")
            soul_content = "You are a helpful, autonomous AI agent."
            if os.path.exists(soul_path):
                with open(soul_path, "r", encoding="utf-8") as f:
                    soul_content = f.read()

            system_prompt = (
                "You are the following AI Agent. Below is your core identity, rules, and personality defined in your SOUL.md file:\n\n"
                f"<soul_instructions>\n{soul_content}\n</soul_instructions>\n\n"
                "Here is relevant context from your exact episodic memory. Always cite them if relevant:\n\n"
                f"{context_blocks}"
            )

            # 4. Form message list
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ]

            tools = None
            if self.skill_executor:
                tools = [{"type": "function", "function": schema} for schema in self.skill_executor.registry.get_all_schemas()]
                if not tools:
                    tools = None

            # 5. Generate reply (Loop for tool calls)
            MAX_LOOPS = 5
            for _ in range(MAX_LOOPS):
                response = await self.llm.generate(messages=messages, trace_id=trace_id, tools=tools)

                if response.tool_calls:
                    # Append the assistant's tool call message
                    assistant_msg = {"role": "assistant", "content": response.content or "", "tool_calls": response.tool_calls}
                    # Some litellm models require tool_calls to be dictionaries, let's keep it as is.
                    # We might need to map objects to dicts depending on litellm output type.
                    # LiteLLM returns objects that behave like dicts, but to be safe, we'll convert them.
                    tool_calls_dict = []
                    for tc in response.tool_calls:
                        if hasattr(tc, "model_dump"):
                            tool_calls_dict.append(tc.model_dump())
                        elif hasattr(tc, "dict"):
                            tool_calls_dict.append(tc.dict())
                        else:
                            # It might already be a dict
                            if isinstance(tc, dict):
                                tool_calls_dict.append(tc)
                            else:
                                # Fallback: construct from attrs
                                tool_calls_dict.append({
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments
                                    }
                                })
                    
                    assistant_msg["tool_calls"] = tool_calls_dict
                    messages.append(assistant_msg)

                    for tool_call in response.tool_calls:
                        function_name = tool_call.function.name
                        try:
                            arguments = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            arguments = {}

                        if self.skill_executor:
                            result = await self.skill_executor.execute(function_name, arguments, trace_id)
                        else:
                            result = "Error: SkillExecutor not configured."

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": function_name,
                            "content": str(result),
                        })
                    # Loop back to generate again with the tool result
                else:
                    content = response.content or ""
                    
                    # 6. Add assistant reply to memory
                    assistant_text = f"Assistant: {content}"
                    self.memory.add_memory(
                        text=assistant_text,
                        memory_type="episodic",
                        metadata={"session_id": session_id, "role": "assistant"},
                    )

                    return content
            
            # If we exit the loop, we hit MAX_LOOPS
            fallback_content = response.content or "Error: Exceeded max tool loops."
            self.memory.add_memory(
                text=f"Assistant: {fallback_content}",
                memory_type="episodic",
                metadata={"session_id": session_id, "role": "assistant"},
            )
            return fallback_content

        finally:
            reset_trace_id(trace_token)
