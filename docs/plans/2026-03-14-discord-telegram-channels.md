# Implementation Plan: Discord & Telegram Channels

## 1. Overview
This plan details the implementation of Discord and Telegram channel adapters, allowing the agent to converse with users on those platforms in real-time. This follows the architecture established by the `TerminalChannel`.

## 2. Tasks

### Task 1: Configuration Updates
- **File:** `core/config.py`
- **Implementation:** Add optional `telegram_bot_token` and `discord_bot_token` as `SecretStr` to the `Settings` class to securely load these from the environment.
- **File:** `tests/core/test_config.py`
- **Implementation:** Ensure the new optional tokens default to None and parse properly.

### Task 2: Telegram Channel Adapter
- **Source File:** `channels/telegram_channel.py`
- **Test File:** `tests/channels/test_telegram.py`
- **Implementation:**
  - Build `TelegramChannel` implementing the `Channel` protocol.
  - Use `python-telegram-bot` (`ApplicationBuilder`).
  - Add an asynchronous message handler that takes user text, routes it to `agent.process_message(session_id=user_id, message=text)`, and replies.
  - Emit `MESSAGE_RECEIVED` and `MESSAGE_SENT` telemetry events.
  - TDD using `unittest.mock` to simulate `Update` and `Context` without network calls.

### Task 3: Discord Channel Adapter
- **Source File:** `channels/discord_channel.py`
- **Test File:** `tests/channels/test_discord.py`
- **Implementation:**
  - Build `DiscordChannel` implementing the `Channel` protocol.
  - Use `discord.py` (`discord.Client` or `commands.Bot`).
  - Listen for the `on_message` event. Ignore the bot's own messages.
  - Route text to `agent.process_message(session_id=channel_id, message=text)` and reply in the channel.
  - Emit telemetry events (`MESSAGE_RECEIVED`, `MESSAGE_SENT`).
  - TDD using mocks for the Discord API.
