from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from channels.telegram_channel import TelegramChannel
from core.telemetry import EventBus, EventType
from core.agent import Agent

@pytest.fixture
def mock_event_bus():
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    return bus

@pytest.fixture
def mock_agent():
    agent = MagicMock(spec=Agent)
    agent.process_message = AsyncMock(return_value="Telegram Response")
    return agent

@pytest.mark.asyncio
async def test_telegram_channel_process_message(mock_agent, mock_event_bus):
    channel = TelegramChannel(mock_agent, mock_event_bus, "fake-token")
    
    # Mock Telegram Update and Context
    mock_update = MagicMock()
    mock_update.message.text = "Hello Telegram"
    mock_update.effective_user.id = 12345
    mock_update.message.reply_text = AsyncMock()
    
    mock_context = MagicMock()
    
    await channel.handle_message(mock_update, mock_context)
    
    # Check agent was called
    mock_agent.process_message.assert_called_once_with(
        session_id="tg-12345",
        message="Hello Telegram"
    )
    
    # Check reply was sent
    mock_update.message.reply_text.assert_called_once_with("Telegram Response")
    
    # Check telemetry
    assert mock_event_bus.emit.call_count == 2
    
    # First emit is MESSAGE_RECEIVED
    received_event = mock_event_bus.emit.call_args_list[0].args[0]
    assert received_event.event_type == EventType.MESSAGE_RECEIVED
    assert received_event.component == "channel.telegram"
    assert received_event.payload["session_id"] == "tg-12345"
    assert received_event.payload["text"] == "Hello Telegram"
    
    # Second emit is MESSAGE_SENT
    sent_event = mock_event_bus.emit.call_args_list[1].args[0]
    assert sent_event.event_type == EventType.MESSAGE_SENT
    assert sent_event.component == "channel.telegram"
    assert sent_event.payload["reply"] == "Telegram Response"
