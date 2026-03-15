from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent import Agent
from core.llm import LLMGateway, LLMResponse
from core.telemetry import EventBus
from memory.memory_manager import MemoryManager


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


class TestAgent:
    @pytest.mark.asyncio
    async def test_process_message(
        self,
        mock_event_bus: EventBus,
        mock_llm: LLMGateway,
        mock_memory: MemoryManager,
    ) -> None:
        agent = Agent(llm=mock_llm, memory=mock_memory, event_bus=mock_event_bus)

        # We need to trace get_trace_id within process_message to verify context var is set
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
        # Check the messages passed to LLM generate
        call_args = mock_llm.generate.call_args
        assert call_args is not None
        _, kwargs = call_args

        messages = kwargs["messages"]
        assert len(messages) >= 2
        # System prompt should include the context
        assert "Previous context from memory." in messages[0]["content"]
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == user_msg
