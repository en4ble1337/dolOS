import logging
from typing import Optional

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from channels import Channel
from core.agent import Agent
from core.telemetry import Event, EventBus, EventType

logger = logging.getLogger(__name__)


class TelegramChannel(Channel):
    """A Telegram bot interface for chatting with the agent."""

    def __init__(self, agent: Agent, event_bus: EventBus, token: str) -> None:
        self.agent = agent
        self.event_bus = event_bus
        self.token = token
        self.application = ApplicationBuilder().token(self.token).build()

        # Register message handler
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles incoming messages from Telegram."""
        if not update.message or not update.message.text:
            return

        user_input = update.message.text
        # Prefix with tg- to keep session ID namespaces separate per channel
        user_id = update.effective_user.id if update.effective_user else "unknown"
        session_id = f"tg-{user_id}"

        # Emit received event
        await self.event_bus.emit(
            Event(
                event_type=EventType.MESSAGE_RECEIVED,
                component="channel.telegram",
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
            await update.message.reply_text(reply)

            # Emit sent event
            await self.event_bus.emit(
                Event(
                    event_type=EventType.MESSAGE_SENT,
                    component="channel.telegram",
                    trace_id="pending",
                    payload={"session_id": session_id, "reply": reply},
                )
            )
        except Exception as e:
            logger.error(f"Telegram channel error: {e}")
            await update.message.reply_text("Sorry, I encountered an internal error.")

    async def start(self) -> None:
        """Starts the Telegram bot polling."""
        logger.info("Starting Telegram Channel.")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling() # type: ignore
        logger.info("Telegram polling started.")
