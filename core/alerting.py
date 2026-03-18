"""Outbound-only alert notifier for critical agent failures.

Fire-and-forget: sends to all configured targets, swallows all errors.
Never crashes the caller.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import Settings

# Optional dependencies — imported at module level so tests can patch them.
try:
    from telegram import Bot
except ImportError:
    Bot = None  # type: ignore[assignment,misc]

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class AlertNotifier:
    """Sends one-shot alert messages to configured Telegram/Discord targets."""

    def __init__(self, settings: "Settings") -> None:
        self._telegram_token = settings.telegram_bot_token
        self._telegram_chat_id = settings.telegram_alert_chat_id
        self._discord_webhook_url = settings.discord_alert_webhook_url

    async def send(self, message: str) -> None:
        """Send alert to all configured targets. Swallows all errors."""
        tasks = []
        if self._telegram_token and self._telegram_chat_id:
            tasks.append(self._send_telegram(message))
        if self._discord_webhook_url:
            tasks.append(self._send_discord(message))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logger.warning("AlertNotifier: no targets configured, alert not sent: %s", message)

    async def _send_telegram(self, message: str) -> None:
        try:
            bot = Bot(token=self._telegram_token.get_secret_value())
            await bot.send_message(chat_id=self._telegram_chat_id, text=message)
        except Exception as e:
            logger.error("AlertNotifier: Telegram send failed: %s", e)

    async def _send_discord(self, message: str) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    self._discord_webhook_url,
                    json={"content": message},
                )
        except Exception as e:
            logger.error("AlertNotifier: Discord send failed: %s", e)

    def is_configured(self) -> bool:
        """True if at least one alert target is configured."""
        return bool(
            (self._telegram_token and self._telegram_chat_id)
            or self._discord_webhook_url
        )
