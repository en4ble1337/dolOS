from typing import Protocol

from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown

from core.agent import Agent
from core.telemetry import Event, EventBus, EventType


class Channel(Protocol):
    """Protocol defining the interface for all communication channels."""

    async def start(self) -> None:
        """Starts the channel's main message-processing loop."""
        ...


class TerminalChannel:
    """A command-line interface for chatting with the agent."""

    def __init__(
        self,
        agent: Agent,
        event_bus: EventBus,
        session_id: str = "terminal",
    ) -> None:
        self.agent = agent
        self.event_bus = event_bus
        self.session_id = session_id

        self.console = Console()
        self.style = Style.from_dict({
            "prompt": "ansiwhite bold",
        })

    async def start(self) -> None:
        """Start the interactive terminal session."""
        self.console.print("\n[bold green]Starting Terminal Channel.[/bold green]")
        self.console.print("Type your message and press Enter. Press Ctrl-D or type 'exit' to quit.\n")

        session: PromptSession[str] = PromptSession()

        while True:
            try:
                user_input = await session.prompt_async("\nYou: ", style=self.style)

                if user_input.strip().lower() in ["exit", "quit"]:
                    break

                if not user_input.strip():
                    continue

                await self._process_turn(user_input)

            except (EOFError, KeyboardInterrupt):
                break
            except Exception as e:
                self.console.print(f"[bold red]Error:[/bold red] {e}")

        self.console.print("\n[bold yellow]Terminal session ended.[/bold yellow]")

    async def _process_turn(self, user_input: str) -> None:
        """Process a single turn of conversation."""
        # Wrap the whole turn in a channel trace, maybe emit event
        await self.event_bus.emit(
            Event(
                event_type=EventType.MESSAGE_RECEIVED,
                component="channel.terminal",
                trace_id="pending",
                payload={"session_id": self.session_id, "text": user_input},
            )
        )

        try:
            # Send message to agent (agent generates trace internally)
            reply = await self.agent.process_message(
                session_id=self.session_id,
                message=user_input
            )

            # Print response
            self.console.print("[bold cyan]Assistant:[/bold cyan]", Markdown(reply))

            await self.event_bus.emit(
                Event(
                    event_type=EventType.MESSAGE_SENT,
                    component="channel.terminal",
                    trace_id="pending",
                    payload={"session_id": self.session_id, "reply": reply},
                )
            )
        except Exception as e:
            self.console.print(f"[bold red]Agent error: {e}[/bold red]")
