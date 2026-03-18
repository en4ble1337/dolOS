"""Tests for AlertNotifier."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.alerting import AlertNotifier
from core.config import Settings


def _make_settings(
    telegram_token: str | None = None,
    telegram_chat_id: str | None = None,
    discord_webhook: str | None = None,
) -> Settings:
    return Settings(
        telegram_bot_token=telegram_token,
        telegram_alert_chat_id=telegram_chat_id,
        discord_alert_webhook_url=discord_webhook,
    )


class TestAlertNotifier:
    @pytest.mark.asyncio
    async def test_send_telegram_when_configured(self) -> None:
        settings = _make_settings(telegram_token="tok", telegram_chat_id="123")
        notifier = AlertNotifier(settings)

        with patch("core.alerting.Bot") as mock_bot_cls:
            mock_bot = AsyncMock()
            mock_bot_cls.return_value = mock_bot
            await notifier.send("test alert")

        mock_bot.send_message.assert_called_once_with(chat_id="123", text="test alert")

    @pytest.mark.asyncio
    async def test_send_discord_webhook_when_configured(self) -> None:
        settings = _make_settings(discord_webhook="https://discord.com/api/webhooks/x")
        notifier = AlertNotifier(settings)

        mock_response = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = AsyncMock(return_value=mock_response)

        with patch("core.alerting.aiohttp.ClientSession", return_value=mock_session):
            await notifier.send("test alert")

        mock_session.post.assert_called_once()
        call_kwargs = mock_session.post.call_args
        assert call_kwargs[0][0] == "https://discord.com/api/webhooks/x"
        assert call_kwargs[1]["json"] == {"content": "test alert"}

    @pytest.mark.asyncio
    async def test_send_skips_unconfigured_channels(self) -> None:
        settings = _make_settings()
        notifier = AlertNotifier(settings)
        # Should not raise
        await notifier.send("test alert")

    @pytest.mark.asyncio
    async def test_send_swallows_telegram_exception(self) -> None:
        settings = _make_settings(telegram_token="tok", telegram_chat_id="123")
        notifier = AlertNotifier(settings)

        with patch("core.alerting.Bot") as mock_bot_cls:
            mock_bot = AsyncMock()
            mock_bot.send_message.side_effect = RuntimeError("network error")
            mock_bot_cls.return_value = mock_bot
            # Must not raise
            await notifier.send("test alert")

    @pytest.mark.asyncio
    async def test_send_discord_swallows_exception(self) -> None:
        settings = _make_settings(discord_webhook="https://discord.com/api/webhooks/x")
        notifier = AlertNotifier(settings)

        with patch("core.alerting.aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.side_effect = RuntimeError("network error")
            # Must not raise
            await notifier.send("test alert")

    def test_is_configured_false_when_no_targets(self) -> None:
        notifier = AlertNotifier(_make_settings())
        assert notifier.is_configured() is False

    def test_is_configured_true_with_telegram(self) -> None:
        notifier = AlertNotifier(_make_settings(telegram_token="tok", telegram_chat_id="123"))
        assert notifier.is_configured() is True

    def test_is_configured_true_with_discord(self) -> None:
        notifier = AlertNotifier(_make_settings(discord_webhook="https://discord.com/api/webhooks/x"))
        assert notifier.is_configured() is True
