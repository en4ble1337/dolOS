# Implementation Plan: Reliability Utilities

## Task 1: Create Tests for `retry_with_backoff` and `CircuitBreaker`
- **File**: `tests/core/test_reliability.py`
- **Command**: `pytest tests/core/test_reliability.py -v`
- **Expected Output**: Tests should fail (ModuleNotFoundError or AssertionError) since implementation doesn't exist.

## Task 2: Implement `retry_with_backoff` and `CircuitBreaker`
- **File**: `core/reliability.py`
- **Command**: `pytest tests/core/test_reliability.py -v`
- **Expected Output**: All tests pass.

## Task 3: Verify Types and Formatting
- **Command**: `mypy core/reliability.py tests/core/test_reliability.py`
- **Command**: `ruff check core/reliability.py tests/core/test_reliability.py`
- **Expected Output**: No issues found.
