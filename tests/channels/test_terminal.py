from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from channels.terminal import TerminalChannel
from core.agent import Agent
from core.telemetry import EventBus, EventType


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    bus.emit_sync = MagicMock()
    return bus


@pytest.fixture
def mock_agent() -> Agent:
    agent = MagicMock(spec=Agent)
    agent.process_message = AsyncMock(return_value="Hello from agent")
    return agent


class TestTerminalChannel:
    @pytest.mark.asyncio
    async def test_terminal_single_turn(
        self, mock_agent: Agent, mock_event_bus: EventBus
    ) -> None:
        """Test a single conversation turn in the terminal channel."""
        channel = TerminalChannel(agent=mock_agent, event_bus=mock_event_bus)

        # We will mock the console to prevent actual printing
        with patch.object(channel.console, "print") as mock_print:
            # First it returns "ping", then raises EOFError to exit loop
            with patch("channels.terminal.PromptSession") as mock_session_class:
                session_instance = MagicMock()
                session_instance.prompt_async = AsyncMock(side_effect=["ping", EOFError()])
                mock_session_class.return_value = session_instance

                await channel.start()

                # Check interaction with agent
                mock_agent.process_message.assert_called_once_with(
                    session_id="terminal", message="ping"
                )

                # The response from the agent must be printed to the console (wrapped in Markdown)
                found = False
                for call in mock_print.mock_calls:
                    for arg in call.args:
                        if hasattr(arg, "markup") and "Hello from agent" in arg.markup:
                            found = True
                            break
                        elif getattr(arg, "markup", "") == "Hello from agent":
                            found = True
                            break
                        elif getattr(arg, "text", "") == "Hello from agent":
                            found = True
                            break
                        elif isinstance(arg, str) and "Hello from agent" in arg:
                            found = True
                            break
                assert found, f"Did not find 'Hello from agent' in print calls: {mock_print.mock_calls}"

                # Verify telemetry
                # Expected: MESSAGE_RECEIVED -> MESSAGE_SENT
                emitted = [
                    call.args[0].event_type
                    for call in mock_event_bus.emit.await_args_list
                ]
                assert EventType.MESSAGE_RECEIVED in emitted
                assert EventType.MESSAGE_SENT in emitted
