"""Tests for the Agent orchestrator."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent import Agent, _score_importance
from core.llm import LLMGateway, LLMResponse
from core.telemetry import EventBus
from memory.memory_manager import MemoryManager
from memory.semantic_extractor import SemanticExtractor
from memory.summarizer import ConversationSummarizer
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
    # Mock search to return context for episodic, empty for semantic
    memory.search = MagicMock(
        side_effect=lambda **kwargs: (
            [{"text": "Previous context from memory."}]
            if kwargs.get("memory_type") == "episodic"
            else []
        )
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


@pytest.fixture
def mock_semantic_extractor() -> SemanticExtractor:
    ext = MagicMock(spec=SemanticExtractor)
    ext.extract_and_store = AsyncMock(return_value=2)
    return ext


@pytest.fixture
def mock_summarizer() -> ConversationSummarizer:
    summ = MagicMock(spec=ConversationSummarizer)
    summ.increment_turn = MagicMock(return_value=False)
    summ.get_session_summary = MagicMock(return_value=None)
    return summ


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

        # User message was saved to memory
        mock_memory.add_memory.assert_any_call(
            text=f"User: {user_msg}",
            memory_type="episodic",
            importance=_score_importance(user_msg),
            metadata={"session_id": session_id, "role": "user"}
        )

        # Assistant reply was saved
        mock_memory.add_memory.assert_any_call(
            text=f"Assistant: {reply}",
            memory_type="episodic",
            importance=_score_importance(reply),
            metadata={"session_id": session_id, "role": "assistant"}
        )

        # Memory was searched for both episodic and semantic context
        search_calls = mock_memory.search.call_args_list
        search_types = [c.kwargs.get("memory_type") for c in search_calls]
        assert "episodic" in search_types
        assert "semantic" in search_types

        # LLM was called with formatted messages including context
        call_args = mock_llm.generate.call_args
        assert call_args is not None
        messages = call_args.kwargs["messages"]
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

    @pytest.mark.asyncio
    async def test_searches_both_episodic_and_semantic(
        self,
        mock_event_bus: EventBus,
        mock_llm: LLMGateway,
        mock_memory: MemoryManager,
    ) -> None:
        # Semantic search returns facts
        mock_memory.search = MagicMock(
            side_effect=lambda **kwargs: (
                [{"text": "User: previous chat"}]
                if kwargs.get("memory_type") == "episodic"
                else [{"text": "User prefers dark mode"}]
            )
        )

        agent = Agent(llm=mock_llm, memory=mock_memory, event_bus=mock_event_bus)
        await agent.process_message("s1", "hello")

        # System prompt should contain both blocks
        system_prompt = mock_llm.generate.call_args.kwargs["messages"][0]["content"]
        assert "episodic memory" in system_prompt
        assert "semantic memory" in system_prompt
        assert "User prefers dark mode" in system_prompt

    @pytest.mark.asyncio
    async def test_semantic_extraction_runs_in_background(
        self,
        mock_event_bus: EventBus,
        mock_llm: LLMGateway,
        mock_memory: MemoryManager,
        mock_semantic_extractor: SemanticExtractor,
    ) -> None:
        agent = Agent(
            llm=mock_llm,
            memory=mock_memory,
            event_bus=mock_event_bus,
            semantic_extractor=mock_semantic_extractor,
        )

        await agent.process_message("s1", "I live in NYC")
        # Allow background task to run
        await asyncio.sleep(0.05)

        mock_semantic_extractor.extract_and_store.assert_called_once()
        call_kwargs = mock_semantic_extractor.extract_and_store.call_args.kwargs
        assert call_kwargs["user_message"] == "I live in NYC"
        assert call_kwargs["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_semantic_extraction_failure_doesnt_crash(
        self,
        mock_event_bus: EventBus,
        mock_llm: LLMGateway,
        mock_memory: MemoryManager,
        mock_semantic_extractor: SemanticExtractor,
    ) -> None:
        mock_semantic_extractor.extract_and_store = AsyncMock(
            side_effect=RuntimeError("extraction boom")
        )

        agent = Agent(
            llm=mock_llm,
            memory=mock_memory,
            event_bus=mock_event_bus,
            semantic_extractor=mock_semantic_extractor,
        )

        # Should not raise
        reply = await agent.process_message("s1", "test")
        assert reply == "Hello from LLM"
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_summarization_triggers_at_threshold(
        self,
        mock_event_bus: EventBus,
        mock_llm: LLMGateway,
        mock_memory: MemoryManager,
        mock_summarizer: ConversationSummarizer,
    ) -> None:
        mock_summarizer.increment_turn.return_value = True
        mock_summarizer.summarize_session = AsyncMock(return_value="A summary")

        agent = Agent(
            llm=mock_llm,
            memory=mock_memory,
            event_bus=mock_event_bus,
            summarizer=mock_summarizer,
        )

        await agent.process_message("s1", "message")
        await asyncio.sleep(0.05)

        mock_summarizer.summarize_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_summary_used_in_context(
        self,
        mock_event_bus: EventBus,
        mock_llm: LLMGateway,
        mock_memory: MemoryManager,
        mock_summarizer: ConversationSummarizer,
    ) -> None:
        mock_summarizer.get_session_summary.return_value = "Previously discussed Python project setup."

        agent = Agent(
            llm=mock_llm,
            memory=mock_memory,
            event_bus=mock_event_bus,
            summarizer=mock_summarizer,
        )

        await agent.process_message("s1", "continue our discussion")

        system_prompt = mock_llm.generate.call_args.kwargs["messages"][0]["content"]
        assert "Previously discussed Python project setup." in system_prompt

        # Episodic limit should be reduced when summary exists
        episodic_search = [
            c for c in mock_memory.search.call_args_list
            if c.kwargs.get("memory_type") == "episodic"
        ]
        assert episodic_search[0].kwargs["limit"] == 3


class TestScoreImportance:
    def test_score_importance_high_signals(self) -> None:
        assert _score_importance("we decided to switch models") == 0.9

    def test_score_importance_low_signals(self) -> None:
        assert _score_importance("hello there") == 0.2

    def test_score_importance_neutral(self) -> None:
        assert _score_importance("tell me about vectors") == 0.5

    @pytest.mark.asyncio
    async def test_episodic_write_uses_importance(
        self,
        mock_event_bus: EventBus,
        mock_llm: LLMGateway,
        mock_memory: MemoryManager,
    ) -> None:
        agent = Agent(llm=mock_llm, memory=mock_memory, event_bus=mock_event_bus)
        message = "we decided to switch models"
        await agent.process_message("s1", message)

        # The user episodic write should use importance=0.9 (high signal)
        mock_memory.add_memory.assert_any_call(
            text=f"User: {message}",
            memory_type="episodic",
            importance=0.9,
            metadata={"session_id": "s1", "role": "user"},
        )

    @pytest.mark.asyncio
    async def test_min_score_passed_to_search(
        self,
        mock_event_bus: EventBus,
        mock_llm: LLMGateway,
        mock_memory: MemoryManager,
    ) -> None:
        agent = Agent(llm=mock_llm, memory=mock_memory, event_bus=mock_event_bus)
        await agent.process_message("s1", "some query")

        search_calls = mock_memory.search.call_args_list
        episodic_calls = [c for c in search_calls if c.kwargs.get("memory_type") == "episodic"]
        semantic_calls = [c for c in search_calls if c.kwargs.get("memory_type") == "semantic"]

        assert episodic_calls, "Expected at least one episodic search call"
        assert semantic_calls, "Expected at least one semantic search call"
        assert episodic_calls[0].kwargs.get("min_score") == 0.30
        assert semantic_calls[0].kwargs.get("min_score") == 0.35
