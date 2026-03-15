# Implementation Plan: Directive 006 - Agent Orchestrator

## Overview
This plan outlines the implementation of the `Agent` class in `core/agent.py`. The agent coordinates Memory, LLM, and Telemetry.

## Steps

### Task 1: Scaffolding and Tests (RED)
- **Path**: `tests/core/test_agent.py`
- **Code**:
  - Write test fixtures mocking `LLMGateway`, `MemoryManager`, and `EventBus`.
  - Write `test_agent_initialization`
  - Write `test_process_message_sets_trace_id_and_emits_events`
  - Write `test_process_message_stores_and_retrieves_memory`
  - Write `test_process_message_calls_llm_and_returns_content`
- **Command**: `pytest tests/core/test_agent.py -v`
- **Expected Output**: Failing tests (`ImportError` for `Agent`).

### Task 2: Core Implementation (GREEN)
- **Path**: `core/agent.py`
- **Code**:
  - Implement `Agent` class initializing with `llm`, `memory`, `event_bus`.
  - Implement `async def process_message(self, session_id: str, message: str) -> str:`
  - Inside, generate a new UUID trace ID string setting it via `set_trace_id()` from `core.telemetry`.
  - Emit an `AgentEvent` (e.g. `system.start`? We'll just define the flow).
  - Add user message to memory via `add_memory()`.
  - Query memory via `search()`.
  - Compile the system prompt + recent memories + current message.
  - Await `self.llm.generate()`.
  - Add the assistant's reply to memory via `add_memory()`.
  - Return the content.
- **Command**: `pytest tests/core/test_agent.py -v`
- **Expected Output**: Passing tests.

### Task 3: Refactor & Lints (REFACTOR)
- **Code**: Clean up typing and ensure imports are correct. 
- **Command**: `ruff check core/agent.py tests/core/test_agent.py && mypy core/agent.py`
- **Expected Output**: Clean linters.
