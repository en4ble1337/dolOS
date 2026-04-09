"""Tests for HookRegistry and HookVeto (Gap 12).

TDD Red phase — these tests MUST FAIL before core/hooks.py exists.
"""

from __future__ import annotations

import asyncio

import pytest

from core.hooks import HookRegistry, HookVeto


# ---------------------------------------------------------------------------
# HookVeto exception
# ---------------------------------------------------------------------------

class TestHookVeto:
    def test_is_exception(self):
        assert issubclass(HookVeto, Exception)

    def test_can_raise_and_catch(self):
        with pytest.raises(HookVeto):
            raise HookVeto("blocked by hook")

    def test_carries_message(self):
        exc = HookVeto("no write allowed")
        assert "no write allowed" in str(exc)


# ---------------------------------------------------------------------------
# HookRegistry construction
# ---------------------------------------------------------------------------

class TestHookRegistryConstruction:
    def test_instantiates(self):
        reg = HookRegistry()
        assert reg is not None

    def test_has_register_method(self):
        reg = HookRegistry()
        assert callable(reg.register)

    def test_has_fire_method(self):
        reg = HookRegistry()
        assert callable(reg.fire)


# ---------------------------------------------------------------------------
# Fire-and-forget (non-blocking) hooks
# ---------------------------------------------------------------------------

class TestFireAndForgetHooks:
    @pytest.mark.asyncio
    async def test_non_blocking_hook_is_called(self):
        reg = HookRegistry()
        called = []

        async def my_hook(**kwargs):
            called.append(kwargs)

        reg.register("pre_tool_use", my_hook, blocking=False)
        await reg.fire("pre_tool_use", tool_name="read_file")
        # Give the event loop a chance to run the background task
        await asyncio.sleep(0)
        assert len(called) == 1
        assert called[0]["tool_name"] == "read_file"

    @pytest.mark.asyncio
    async def test_non_blocking_hook_does_not_raise_on_exception(self):
        """Fire-and-forget hooks that raise must not propagate to caller."""
        reg = HookRegistry()

        async def bad_hook(**kwargs):
            raise RuntimeError("hook error")

        reg.register("pre_tool_use", bad_hook, blocking=False)
        # Should not raise
        await reg.fire("pre_tool_use", tool_name="run_command")
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_multiple_non_blocking_hooks_all_called(self):
        reg = HookRegistry()
        results = []

        async def hook_a(**kwargs):
            results.append("a")

        async def hook_b(**kwargs):
            results.append("b")

        reg.register("pre_tool_use", hook_a, blocking=False)
        reg.register("pre_tool_use", hook_b, blocking=False)
        await reg.fire("pre_tool_use")
        await asyncio.sleep(0)
        assert "a" in results
        assert "b" in results


# ---------------------------------------------------------------------------
# Blocking hooks
# ---------------------------------------------------------------------------

class TestBlockingHooks:
    @pytest.mark.asyncio
    async def test_blocking_hook_is_called(self):
        reg = HookRegistry()
        called = []

        async def guard(**kwargs):
            called.append(kwargs)

        reg.register("pre_tool_use", guard, blocking=True)
        await reg.fire("pre_tool_use", tool_name="read_file")
        assert len(called) == 1

    @pytest.mark.asyncio
    async def test_blocking_hook_veto_propagates(self):
        """A blocking hook that raises HookVeto must propagate to caller."""
        reg = HookRegistry()

        async def veto_hook(**kwargs):
            raise HookVeto("tool not allowed")

        reg.register("pre_tool_use", veto_hook, blocking=True)
        with pytest.raises(HookVeto, match="tool not allowed"):
            await reg.fire("pre_tool_use", tool_name="run_command")

    @pytest.mark.asyncio
    async def test_blocking_hook_non_veto_exception_propagates(self):
        """Non-HookVeto exceptions from blocking hooks also propagate."""
        reg = HookRegistry()

        async def broken_hook(**kwargs):
            raise ValueError("unexpected error")

        reg.register("pre_tool_use", broken_hook, blocking=True)
        with pytest.raises(ValueError):
            await reg.fire("pre_tool_use")

    @pytest.mark.asyncio
    async def test_blocking_hook_runs_before_fire_returns(self):
        """Blocking hooks must complete before fire() returns."""
        reg = HookRegistry()
        log = []

        async def hook(**kwargs):
            log.append("hook_ran")

        reg.register("pre_tool_use", hook, blocking=True)
        await reg.fire("pre_tool_use")
        assert log == ["hook_ran"]


# ---------------------------------------------------------------------------
# Supported events
# ---------------------------------------------------------------------------

class TestSupportedEvents:
    @pytest.mark.asyncio
    async def test_pre_tool_use_event_fires(self):
        reg = HookRegistry()
        called = []

        async def hook(**kwargs):
            called.append(True)

        reg.register("pre_tool_use", hook, blocking=True)
        await reg.fire("pre_tool_use")
        assert called

    @pytest.mark.asyncio
    async def test_permission_request_event_fires(self):
        reg = HookRegistry()
        called = []

        async def hook(**kwargs):
            called.append(True)

        reg.register("permission_request", hook, blocking=True)
        await reg.fire("permission_request", tool_name="delete_file")
        assert called

    @pytest.mark.asyncio
    async def test_fire_unknown_event_is_noop(self):
        """Firing an event with no registered hooks should not raise."""
        reg = HookRegistry()
        await reg.fire("no_such_event")  # must not raise

    @pytest.mark.asyncio
    async def test_mixed_blocking_and_non_blocking_same_event(self):
        """Both hook types can coexist on the same event."""
        reg = HookRegistry()
        log = []

        async def blocking(**kwargs):
            log.append("blocking")

        async def nonblocking(**kwargs):
            log.append("nonblocking")

        reg.register("pre_tool_use", blocking, blocking=True)
        reg.register("pre_tool_use", nonblocking, blocking=False)
        await reg.fire("pre_tool_use")
        await asyncio.sleep(0)
        assert "blocking" in log
        assert "nonblocking" in log
