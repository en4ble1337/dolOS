# Implementation Plan: Directive 007 - Channel Adapters

## Overview
This plan implements the entry points for interacting with the agent: a `TerminalChannel` using `rich` and `prompt_toolkit`, and a FastAPI `chat_router`.

## Steps

### Task 1: Scaffolding and Tests (RED)
- **Path**: `tests/channels/test_terminal.py` and `tests/api/test_chat.py`
- **Code**:
  - `test_terminal.py`: Write tests mocking console output and `Agent.process_message`, asserting telemetry (`MESSAGE_RECEIVED`, `MESSAGE_SENT`) is emitted. 
  - `test_chat.py`: Use `fastapi.testclient.TestClient` to mock hitting `/chat`, posting a message and asserting the returned LLM response and telemetry emission.
- **Command**: `pytest tests/channels/test_terminal.py tests/api/test_chat.py -v`
- **Expected Output**: Failing tests.

### Task 2: Core Implementation (GREEN)
- **Path**: `channels/terminal.py`
- **Code**:
  - Define a base `Channel` protocol using typing (`Protocol`).
  - Define `TerminalChannel` initializing with `Agent` and `EventBus`.
  - Implement an async `start()` loop utilizing `prompt_toolkit` to asynchronously gather input, emitting `MESSAGE_RECEIVED`.
  - Invoke `agent.process_message(self.session_id, user_text)`.
  - Use `rich.console.Console` to print the assistant text.
  - Emit `MESSAGE_SENT`.
- **Path**: `api/routes/chat.py`
- **Code**:
  - Import `APIRouter` from `fastapi`.
  - Create a generic endpoint `POST /chat` with a Pydantic schema for `ChatRequest(session_id: str, message: str)`.
  - Inject `Agent` and `EventBus` via FastAPI dependencies (usually `request.app.state.agent`).
  - Emit `MESSAGE_RECEIVED`.
  - Await `agent.process_message(session_id, request.message)`.
  - Emit `MESSAGE_SENT`.
  - Return `ChatResponse(content=reply)`.
- **Command**: `pytest tests/channels/test_terminal.py tests/api/test_chat.py -v`
- **Expected Output**: Passing tests.

### Task 3: Refactor & Lints (REFACTOR)
- **Code**: Clean up typing and dependencies (ensure `rich` and `prompt_toolkit` are mocked safely or installed). Oh! We will need to pip install `prompt_toolkit` and `rich`, and `fastapi`/`httpx` (for TestClient) if they aren't already. Let's check `pyproject.toml` or `requirements.txt`.
- **Command**: `ruff check channels/ api/ tests/ && mypy channels/ api/ tests/`
- **Expected Output**: Clean linters.
