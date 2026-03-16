from unittest.mock import AsyncMock, MagicMock
import pytest
import discord
from channels.discord_channel import DiscordChannel
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
    agent.process_message = AsyncMock(return_value="Discord Response")
    return agent

@pytest.mark.asyncio
async def test_discord_channel_process_message(mock_agent, mock_event_bus):
    channel = DiscordChannel(mock_agent, mock_event_bus, "fake-token")
    
    # Mock Discord Message
    mock_message = MagicMock(spec=discord.Message)
    mock_message.author = MagicMock(spec=discord.User)
    mock_message.author.bot = False
    mock_message.author.id = 54321
    mock_message.channel = MagicMock(spec=discord.TextChannel)
    mock_message.channel.id = 98765
    mock_message.content = "Hello Discord"
    mock_message.channel.send = AsyncMock()
    
    # Trigger the on_message handler
    await channel.client.on_message(mock_message)
    
    # Check agent was called (using channel ID for session)
    mock_agent.process_message.assert_called_once_with(
        session_id="disc-98765",
        message="Hello Discord"
    )
    
    # Check reply was sent
    mock_message.channel.send.assert_called_once_with("Discord Response")
    
    # Check telemetry
    assert mock_event_bus.emit.call_count == 2
    
    # First emit is MESSAGE_RECEIVED
    received_event = mock_event_bus.emit.call_args_list[0].args[0]
    assert received_event.event_type == EventType.MESSAGE_RECEIVED
    assert received_event.component == "channel.discord"
    assert received_event.payload["session_id"] == "disc-98765"
    assert received_event.payload["text"] == "Hello Discord"
    
    # Second emit is MESSAGE_SENT
    sent_event = mock_event_bus.emit.call_args_list[1].args[0]
    assert sent_event.event_type == EventType.MESSAGE_SENT
    assert sent_event.component == "channel.discord"
    assert sent_event.payload["reply"] == "Discord Response"

@pytest.mark.asyncio
async def test_discord_channel_ignore_bot_messages(mock_agent, mock_event_bus):
    channel = DiscordChannel(mock_agent, mock_event_bus, "fake-token")
    
    mock_message = MagicMock(spec=discord.Message)
    mock_message.author.bot = True  # It's a bot!
    
    await channel.client.on_message(mock_message)
    
    # Agent should not be called
    mock_agent.process_message.assert_not_called()
