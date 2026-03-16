import logging

import discord

from channels import Channel
from core.agent import Agent
from core.telemetry import Event, EventBus, EventType

logger = logging.getLogger(__name__)


class DiscordChannel(Channel):
    """A Discord bot interface for chatting with the agent."""

    def __init__(self, agent: Agent, event_bus: EventBus, token: str) -> None:
        self.agent = agent
        self.event_bus = event_bus
        self.token = token
        
        # Setup intents required for reading message content
        intents = discord.Intents.default()
        intents.message_content = True
        
        self.client = discord.Client(intents=intents)
        
        # Register the event handler manually
        self.client.event(self.on_ready)
        self.client.event(self.on_message)

    async def on_ready(self) -> None:
        logger.info(f"Discord Channel logged in as {self.client.user}")

    async def on_message(self, message: discord.Message) -> None:
        """Handles incoming messages from Discord."""
        # Ignore messages from bots (including ourselves)
        if message.author.bot:
            return
            
        user_input = message.content
        if not user_input:
            return

        # Keep session ID isolated per channel. Here we use discord channel ID
        # so everyone in the channel shares the same context. 
        # Alternatively, we could use message.author.id for private context per user.
        session_id = f"disc-{message.channel.id}"

        # Emit received event
        await self.event_bus.emit(
            Event(
                event_type=EventType.MESSAGE_RECEIVED,
                component="channel.discord",
                trace_id="pending",
                payload={"session_id": session_id, "text": user_input},
            )
        )

        try:
            # Send message to agent
            reply = await self.agent.process_message(
                session_id=session_id,
                message=user_input
            )

            # Reply to user
            await message.channel.send(reply)

            # Emit sent event
            await self.event_bus.emit(
                Event(
                    event_type=EventType.MESSAGE_SENT,
                    component="channel.discord",
                    trace_id="pending",
                    payload={"session_id": session_id, "reply": reply},
                )
            )
        except Exception as e:
            logger.error(f"Discord channel error: {e}")
            await message.channel.send("Sorry, I encountered an internal error.")

    async def start(self) -> None:
        """Starts the Discord bot connection."""
        logger.info("Starting Discord Channel.")
        await self.client.start(self.token)
