from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent import Agent
from core.llm import LLMGateway, LLMResponse
from core.telemetry import EventBus
from memory.memory_manager import MemoryManager
from skills.executor import SkillExecutor
from skills.registry import SkillRegistry


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    bus.emit_sync = MagicMock()
    return bus


@pytest.fixture
def mock_llm() -> LLMGateway:
    llm = MagicMock(spec=LLMGateway)
    llm.generate = AsyncMock(return_value=LLMResponse(content="Hello from LLM"))
    return llm


@pytest.fixture
def mock_memory() -> MemoryManager:
    memory = MagicMock(spec=MemoryManager)
    memory.add_memory = MagicMock()
    # Mock search to return one fake context memory
    memory.search = MagicMock(
        return_value=[{"text": "Previous context from memory."}]
    )
    return memory


@pytest.fixture
def mock_skill_executor() -> SkillExecutor:
    executor = MagicMock(spec=SkillExecutor)
    executor.registry = MagicMock(spec=SkillRegistry)
    executor.registry.get_all_schemas.return_value = [
        {"name": "test_tool", "description": "A test tool", "parameters": {}}
    ]
    executor.execute = AsyncMock(return_value="Tool execution result")
    return executor


class TestAgent:
    @pytest.mark.asyncio
    async def test_process_message(
        self,
        mock_event_bus: EventBus,
        mock_llm: LLMGateway,
        mock_memory: MemoryManager,
    ) -> None:
        agent = Agent(llm=mock_llm, memory=mock_memory, event_bus=mock_event_bus)

        session_id = "test-session"
        user_msg = "What is the capital of France?"

        reply = await agent.process_message(session_id, user_msg)

        assert reply == "Hello from LLM"

        # 1. User message was saved to memory
        mock_memory.add_memory.assert_any_call(
            text=f"User: {user_msg}",
            memory_type="episodic",
            metadata={"session_id": session_id, "role": "user"}
        )

        # 2. Assistant reply was saved
        mock_memory.add_memory.assert_any_call(
            text=f"Assistant: {reply}",
            memory_type="episodic",
            metadata={"session_id": session_id, "role": "assistant"}
        )

        # 3. Memory was searched for context
        mock_memory.search.assert_called_once_with(
            query=user_msg,
            memory_type="episodic",
            limit=5
        )

        # 4. LLM was called with formatted messages
        call_args = mock_llm.generate.call_args
        assert call_args is not None
        _, kwargs = call_args

        messages = kwargs["messages"]
        assert len(messages) >= 2
        assert "Previous context from memory." in messages[0]["content"]
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == user_msg

    @pytest.mark.asyncio
    async def test_process_message_with_tool_call(
        self,
        mock_event_bus: EventBus,
        mock_llm: LLMGateway,
        mock_memory: MemoryManager,
        mock_skill_executor: SkillExecutor,
    ) -> None:
        agent = Agent(llm=mock_llm, memory=mock_memory, event_bus=mock_event_bus, skill_executor=mock_skill_executor)

        # Setup LLM to return a tool call first, then a final message
        tool_call_mock = MagicMock()
        tool_call_mock.id = "call_123"
        tool_call_mock.function.name = "test_tool"
        tool_call_mock.function.arguments = "{}"
        
        mock_llm.generate.side_effect = [
            LLMResponse(content=None, tool_calls=[tool_call_mock]),
            LLMResponse(content="Final response after tool")
        ]

        reply = await agent.process_message("session-1", "Use the tool")

        assert reply == "Final response after tool"
        assert mock_llm.generate.call_count == 2
        mock_skill_executor.execute.assert_called_once_with("test_tool", {}, mock_llm.generate.call_args_list[0].kwargs['trace_id'])

