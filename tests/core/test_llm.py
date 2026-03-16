from unittest.mock import AsyncMock, patch

import litellm
import pytest

from core.config import Settings
from core.llm import LLMGateway
from core.telemetry import EventBus, EventType


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()

@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.delenv("PRIMARY_MODEL", raising=False)
    monkeypatch.delenv("FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    return Settings(
        primary_model="ollama/llama3",
        fallback_model="gpt-4-turbo"
    )

@pytest.fixture
def llm_gateway(event_bus: EventBus, settings: Settings) -> LLMGateway:
    return LLMGateway(event_bus=event_bus, settings=settings)

@pytest.mark.asyncio
async def test_llm_gateway_success(llm_gateway: LLMGateway, event_bus: EventBus) -> None:
    messages = [{"role": "user", "content": "Hello"}]

    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(content="Hi there!", tool_calls=None))]
    mock_response.usage = AsyncMock(total_tokens=10)

    with patch("core.llm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.return_value = mock_response

        response = await llm_gateway.generate(messages, trace_id="trace-123")

        assert response.content == "Hi there!"
        assert response.tool_calls is None

        # We want to check that it was called with the right model and messages, but we don't care about api_base if it's set
        kwargs = mock_acompletion.call_args.kwargs
        assert kwargs["model"] == "ollama/llama3"
        assert kwargs["messages"] == messages
        assert kwargs["tools"] is None

    # Check telemetry
    assert event_bus._queue.qsize() == 2

    start_event = await event_bus._queue.get()
    assert start_event.event_type == EventType.LLM_CALL_START
    assert start_event.trace_id == "trace-123"
    assert start_event.payload["model"] == "ollama/llama3"

    end_event = await event_bus._queue.get()
    assert end_event.event_type == EventType.LLM_CALL_END
    assert end_event.trace_id == "trace-123"
    assert end_event.payload["model"] == "ollama/llama3"
    assert end_event.payload["total_tokens"] == 10

@pytest.mark.asyncio
async def test_llm_gateway_fallback(llm_gateway: LLMGateway, event_bus: EventBus) -> None:
    messages = [{"role": "user", "content": "Hello"}]

    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock(message=AsyncMock(content="Fallback response", tool_calls=None))]
    mock_response.usage = AsyncMock(total_tokens=15)

    with patch("core.llm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        # First call fails, second succeeds
        mock_acompletion.side_effect = [
            litellm.exceptions.Timeout("Timeout error", model="ollama/llama3", llm_provider="ollama"),
            mock_response
        ]

        response = await llm_gateway.generate(messages, trace_id="trace-fallback")

        assert response.content == "Fallback response"

        assert mock_acompletion.call_count == 2
        
        call_1_kwargs = mock_acompletion.call_args_list[0].kwargs
        assert call_1_kwargs["model"] == "ollama/llama3"
        assert call_1_kwargs["messages"] == messages
        assert call_1_kwargs["tools"] is None
        
        call_2_kwargs = mock_acompletion.call_args_list[1].kwargs
        assert call_2_kwargs["model"] == "gpt-4-turbo"
        assert call_2_kwargs["messages"] == messages
        assert call_2_kwargs["tools"] is None

    # Check telemetry
    assert event_bus._queue.qsize() == 3

    start_event = await event_bus._queue.get()
    assert start_event.event_type == EventType.LLM_CALL_START

    fallback_event = await event_bus._queue.get()
    assert fallback_event.event_type == EventType.LLM_FALLBACK
    assert fallback_event.payload["failed_model"] == "ollama/llama3"
    assert fallback_event.payload["fallback_model"] == "gpt-4-turbo"
    assert "error" in fallback_event.payload

    end_event = await event_bus._queue.get()
    assert end_event.event_type == EventType.LLM_CALL_END
    assert end_event.payload["model"] == "gpt-4-turbo"

@pytest.mark.asyncio
async def test_llm_gateway_no_fallback_configured(event_bus: EventBus) -> None:
    settings = Settings(primary_model="ollama/llama3", fallback_model=None)
    gateway = LLMGateway(event_bus=event_bus, settings=settings)

    messages = [{"role": "user", "content": "Hello"}]

    with patch("core.llm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.side_effect = Exception("General error")

        with pytest.raises(Exception, match="General error"):
            await gateway.generate(messages, trace_id="trace-error")
