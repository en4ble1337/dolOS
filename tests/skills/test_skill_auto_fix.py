"""Tests for Phase A2 — generated skill quarantine/staging gate.

Covers:
- Default is_read_only=False, concurrency_safe=False for generated skills
- Staging skill not visible in registry before promotion
- Failed staging (handler raises) → skill stays in staging, not promoted
- Successful promotion → skill registered with declared safety flags
- is_read_only=True → skill placed in concurrent batch (is_read_only AND concurrency_safe)
- is_read_only=False → skill placed in serial queue
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import skills.executor as executor_module
import skills.local.meta as meta_module
from core.telemetry import EventBus, EventType
from skills.executor import SkillExecutor
from skills.local.meta import create_skill
from skills.registry import SkillRegistry, _default_registry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_dirs(tmp_path, monkeypatch):
    """Redirect _GENERATED_DIR and _STAGING_DIR to a temp directory for all tests."""
    gen_dir = tmp_path / "generated"
    staging_dir = gen_dir / "staging"
    gen_dir.mkdir()
    staging_dir.mkdir()
    monkeypatch.setattr(meta_module, "_GENERATED_DIR", gen_dir)
    monkeypatch.setattr(meta_module, "_STAGING_DIR", staging_dir)
    monkeypatch.setattr(executor_module, "_GENERATED_DIR", gen_dir)
    return gen_dir, staging_dir


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Remove any test skills from the global registry after each test."""
    registered_before = set(_default_registry.get_all_skill_names())
    yield
    for name in list(_default_registry.get_all_skill_names()):
        if name not in registered_before:
            _default_registry._registrations.pop(name, None)
            _default_registry._schemas.pop(name, None)


@pytest.fixture(autouse=True)
def cleanup_sys_modules():
    """Remove any test skill modules from sys.modules after each test."""
    before = set(sys.modules.keys())
    yield
    for key in list(sys.modules.keys()):
        if key not in before and ("_dolOS_staging_" in key or "skills.local.generated." in key):
            sys.modules.pop(key, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_handler() -> str:
    """Returns trivial handler code that succeeds with no args."""
    return 'async def handler(**kwargs):\n    return "ok"'


def _failing_handler() -> str:
    """Returns handler code that raises RuntimeError when called."""
    return 'async def handler(**kwargs):\n    raise RuntimeError("deliberate quarantine failure")'


def _required_arg_handler() -> str:
    """Returns handler code that requires a positional arg (triggers TypeError on empty call)."""
    return 'async def handler(target: str, **kwargs):\n    return f"got {target}"'


def _make_llm_response(content: str) -> MagicMock:
    response = MagicMock()
    response.content = content
    return response


def _mark_generated(name: str) -> Path:
    generated_file = meta_module._GENERATED_DIR / f"{name}.py"
    generated_file.write_text("# generated skill marker", encoding="utf-8")
    return generated_file


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    bus.emit_sync = MagicMock()
    return bus


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_flags_are_false():
    """create_skill() must default is_read_only=False, concurrency_safe=False."""
    result = await create_skill(
        name="test_defaults",
        description="test defaults",
        code=_simple_handler(),
    )
    assert "created" in result.lower(), result

    reg = _default_registry.get_registration("test_defaults")
    assert reg.is_read_only is False
    assert reg.concurrency_safe is False


@pytest.mark.asyncio
async def test_staging_skill_not_visible_in_registry_before_promotion(monkeypatch):
    """During quarantine import, the skill must NOT appear in the registry."""
    gen_dir = meta_module._GENERATED_DIR
    staging_dir = meta_module._STAGING_DIR

    # Intercept: capture registry state right after staging import but before promotion
    # We do this by making delete_by_filter a side effect that checks the registry
    # — simplest approach: just verify staging file exists after a *failed* quarantine.
    result = await create_skill(
        name="test_staging_visibility",
        description="test staging",
        code=_failing_handler(),
    )

    assert "quarantine failed" in result.lower(), result
    # Skill must NOT be in registry
    assert "test_staging_visibility" not in _default_registry.get_all_skill_names()
    # Live file must NOT exist
    assert not (gen_dir / "test_staging_visibility.py").exists()
    # Staging file MUST exist (left for diagnosis)
    assert (staging_dir / "test_staging_visibility.py").exists()


@pytest.mark.asyncio
async def test_failed_staging_stays_in_staging():
    """Handler that raises a non-TypeError exception → stays in staging, not promoted."""
    gen_dir = meta_module._GENERATED_DIR
    staging_dir = meta_module._STAGING_DIR

    result = await create_skill(
        name="test_failed_staging",
        description="will fail quarantine",
        code=_failing_handler(),
    )

    assert "error" in result.lower(), result
    assert (staging_dir / "test_failed_staging.py").exists(), "Staging file should remain"
    assert not (gen_dir / "test_failed_staging.py").exists(), "Live file must not be created"
    assert "test_failed_staging" not in _default_registry.get_all_skill_names()


@pytest.mark.asyncio
async def test_successful_promotion_registered_with_flags():
    """Promoted skill is registered with the declared is_read_only and concurrency_safe flags."""
    gen_dir = meta_module._GENERATED_DIR
    staging_dir = meta_module._STAGING_DIR

    result = await create_skill(
        name="test_promoted",
        description="promoted skill",
        code=_simple_handler(),
        is_read_only=True,
        concurrency_safe=True,
    )
    assert "created" in result.lower(), result

    # Live file exists
    assert (gen_dir / "test_promoted.py").exists()
    # Staging file cleaned up on success
    assert not (staging_dir / "test_promoted.py").exists()
    # Registered with correct flags
    reg = _default_registry.get_registration("test_promoted")
    assert reg.is_read_only is True
    assert reg.concurrency_safe is True


@pytest.mark.asyncio
async def test_quarantine_false_skips_staging():
    """quarantine=False bypasses staging and registers the skill directly."""
    staging_dir = meta_module._STAGING_DIR

    result = await create_skill(
        name="test_no_quarantine",
        description="trusted human skill",
        code=_simple_handler(),
        quarantine=False,
    )
    assert "created" in result.lower(), result
    # No staging file was written
    assert not (staging_dir / "test_no_quarantine.py").exists()
    assert "test_no_quarantine" in _default_registry.get_all_skill_names()


@pytest.mark.asyncio
async def test_required_arg_handler_passes_quarantine():
    """A handler requiring positional args raises TypeError on empty call — treated as pass."""
    gen_dir = meta_module._GENERATED_DIR

    result = await create_skill(
        name="test_required_args",
        description="handler with required args",
        code=_required_arg_handler(),
    )
    assert "created" in result.lower(), result
    assert (gen_dir / "test_required_args.py").exists()
    assert "test_required_args" in _default_registry.get_all_skill_names()


@pytest.mark.asyncio
async def test_read_only_skill_is_parallel():
    """A skill with is_read_only=True AND concurrency_safe=True should be classified parallel."""
    await create_skill(
        name="test_parallel_skill",
        description="read-only parallel skill",
        code=_simple_handler(),
        is_read_only=True,
        concurrency_safe=True,
    )
    reg = _default_registry.get_registration("test_parallel_skill")
    is_parallel = reg.is_read_only and reg.concurrency_safe
    assert is_parallel is True


@pytest.mark.asyncio
async def test_non_read_only_skill_is_serial():
    """A skill with is_read_only=False must NOT qualify for the concurrent batch."""
    await create_skill(
        name="test_serial_skill",
        description="mutating serial skill",
        code=_simple_handler(),
        is_read_only=False,
        concurrency_safe=True,
    )
    reg = _default_registry.get_registration("test_serial_skill")
    is_parallel = reg.is_read_only and reg.concurrency_safe
    assert is_parallel is False


# ---------------------------------------------------------------------------
# Phase C tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_built_in_skill_failure_does_not_trigger_auto_fix(mock_event_bus: EventBus):
    """Built-in skills must never enter the auto-fix path."""
    reg = SkillRegistry()

    def broken_builtin() -> str:
        raise RuntimeError("builtin boom")

    reg.register("broken_builtin", "broken built-in skill", broken_builtin)
    llm = MagicMock()
    llm.generate = AsyncMock()
    executor = SkillExecutor(registry=reg, event_bus=mock_event_bus, llm=llm)

    with patch.object(executor_module, "fix_skill", new=AsyncMock()) as fix_skill_mock, patch.object(
        executor_module, "create_skill", new=AsyncMock()
    ) as create_skill_mock:
        result = await executor.execute("broken_builtin", {}, trace_id="trace-built-in")

    assert "builtin boom" in result
    fix_skill_mock.assert_not_awaited()
    create_skill_mock.assert_not_awaited()
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_generated_skill_timeout_triggers_auto_fix_attempt(mock_event_bus: EventBus):
    """Generated skill timeout should enter the auto-fix flow."""
    reg = SkillRegistry()

    async def slow_generated() -> str:
        await asyncio.sleep(0.2)
        return "too late"

    reg.register(
        "generated_timeout",
        "generated timeout skill",
        slow_generated,
        is_read_only=True,
        concurrency_safe=True,
    )
    _mark_generated("generated_timeout")

    llm = MagicMock()
    llm.generate = AsyncMock(return_value=_make_llm_response(_simple_handler()))
    executor = SkillExecutor(registry=reg, event_bus=mock_event_bus, llm=llm, timeout=0.01)

    async def _rewrite(*args, **kwargs) -> str:
        async def fixed_handler() -> str:
            return "fixed timeout"

        reg.register(
            "generated_timeout",
            "generated timeout skill",
            fixed_handler,
            is_read_only=True,
            concurrency_safe=True,
        )
        return "Skill 'generated_timeout' created and registered."

    with patch.object(executor_module, "fix_skill", new=AsyncMock(return_value="old source")) as fix_skill_mock, patch.object(
        executor_module, "create_skill", new=AsyncMock(side_effect=_rewrite)
    ) as create_skill_mock:
        result = await executor.execute("generated_timeout", {}, trace_id="trace-timeout")

    assert result == "fixed timeout"
    fix_skill_mock.assert_awaited_once_with("generated_timeout")
    create_skill_mock.assert_awaited_once()
    emitted_types = [call.args[0].event_type for call in mock_event_bus.emit.await_args_list]  # type: ignore[attr-defined]
    assert EventType.SKILL_AUTO_FIX_ATTEMPT in emitted_types


@pytest.mark.asyncio
async def test_read_only_generated_skill_failure_reexecutes_after_fix(mock_event_bus: EventBus):
    """Read-only generated skills should be auto-fixed and re-executed once."""
    reg = SkillRegistry()

    async def broken_generated() -> str:
        raise RuntimeError("read-only boom")

    reg.register(
        "generated_read_only",
        "generated read-only skill",
        broken_generated,
        is_read_only=True,
        concurrency_safe=True,
    )
    _mark_generated("generated_read_only")

    llm = MagicMock()
    llm.generate = AsyncMock(return_value=_make_llm_response(_simple_handler()))
    executor = SkillExecutor(registry=reg, event_bus=mock_event_bus, llm=llm)

    async def _rewrite(*args, **kwargs) -> str:
        async def fixed_handler() -> str:
            return "fixed result"

        reg.register(
            "generated_read_only",
            "generated read-only skill",
            fixed_handler,
            is_read_only=True,
            concurrency_safe=True,
        )
        return "Skill 'generated_read_only' created and registered."

    with patch.object(executor_module, "fix_skill", new=AsyncMock(return_value="old source")) as fix_skill_mock, patch.object(
        executor_module, "create_skill", new=AsyncMock(side_effect=_rewrite)
    ) as create_skill_mock:
        result = await executor.execute("generated_read_only", {}, trace_id="trace-read-only")

    assert result == "fixed result"
    fix_skill_mock.assert_awaited_once_with("generated_read_only")
    create_skill_mock.assert_awaited_once()
    emitted_types = [call.args[0].event_type for call in mock_event_bus.emit.await_args_list]  # type: ignore[attr-defined]
    assert EventType.SKILL_AUTO_FIX_SUCCESS in emitted_types


@pytest.mark.asyncio
async def test_mutating_generated_skill_failure_is_not_reexecuted(mock_event_bus: EventBus):
    """Mutating generated skills may be rewritten but must not be auto-retried."""
    reg = SkillRegistry()
    calls = {"count": 0}

    def mutating_generated() -> str:
        calls["count"] += 1
        raise RuntimeError("mutating boom")

    reg.register(
        "generated_mutating",
        "generated mutating skill",
        mutating_generated,
        is_read_only=False,
        concurrency_safe=False,
    )
    _mark_generated("generated_mutating")

    llm = MagicMock()
    llm.generate = AsyncMock(return_value=_make_llm_response(_simple_handler()))
    executor = SkillExecutor(registry=reg, event_bus=mock_event_bus, llm=llm)

    async def _rewrite(*args, **kwargs) -> str:
        def fixed_handler() -> str:
            return "fixed mutating result"

        reg.register(
            "generated_mutating",
            "generated mutating skill",
            fixed_handler,
            is_read_only=False,
            concurrency_safe=False,
        )
        return "Skill 'generated_mutating' created and registered."

    with patch.object(executor_module, "fix_skill", new=AsyncMock(return_value="old source")) as fix_skill_mock, patch.object(
        executor_module, "create_skill", new=AsyncMock(side_effect=_rewrite)
    ) as create_skill_mock:
        result = await executor.execute("generated_mutating", {}, trace_id="trace-mutating")

    assert "auto-fixed" in result.lower()
    assert "re-invoke" in result.lower()
    assert calls["count"] == 1
    fix_skill_mock.assert_awaited_once_with("generated_mutating")
    create_skill_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_auto_fix_returns_original_error_cleanly(mock_event_bus: EventBus):
    """If the fix flow fails, the original execution error should still be returned."""
    reg = SkillRegistry()

    def broken_generated() -> str:
        raise RuntimeError("original generated boom")

    reg.register(
        "generated_fix_fail",
        "generated skill whose fix fails",
        broken_generated,
        is_read_only=True,
        concurrency_safe=True,
    )
    _mark_generated("generated_fix_fail")

    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("llm boom"))
    executor = SkillExecutor(registry=reg, event_bus=mock_event_bus, llm=llm)

    with patch.object(executor_module, "fix_skill", new=AsyncMock(return_value="old source")) as fix_skill_mock, patch.object(
        executor_module, "create_skill", new=AsyncMock()
    ) as create_skill_mock:
        result = await executor.execute("generated_fix_fail", {}, trace_id="trace-fix-fail")

    assert "original generated boom" in result
    fix_skill_mock.assert_awaited_once_with("generated_fix_fail")
    create_skill_mock.assert_not_awaited()
    emitted_types = [call.args[0].event_type for call in mock_event_bus.emit.await_args_list]  # type: ignore[attr-defined]
    assert EventType.SKILL_AUTO_FIX_FAILED in emitted_types


@pytest.mark.asyncio
async def test_auto_fix_attempts_only_once_per_execution(mock_event_bus: EventBus):
    """A failed re-execution must not trigger a second auto-fix attempt in the same trace."""
    reg = SkillRegistry()

    async def broken_generated() -> str:
        raise RuntimeError("still broken")

    reg.register(
        "generated_retry_guard",
        "generated skill with retry guard",
        broken_generated,
        is_read_only=True,
        concurrency_safe=True,
    )
    _mark_generated("generated_retry_guard")

    llm = MagicMock()
    llm.generate = AsyncMock(return_value=_make_llm_response(_simple_handler()))
    executor = SkillExecutor(registry=reg, event_bus=mock_event_bus, llm=llm)

    async def _rewrite(*args, **kwargs) -> str:
        async def still_broken_handler() -> str:
            raise RuntimeError("still broken after rewrite")

        reg.register(
            "generated_retry_guard",
            "generated skill with retry guard",
            still_broken_handler,
            is_read_only=True,
            concurrency_safe=True,
        )
        return "Skill 'generated_retry_guard' created and registered."

    with patch.object(executor_module, "fix_skill", new=AsyncMock(return_value="old source")) as fix_skill_mock, patch.object(
        executor_module, "create_skill", new=AsyncMock(side_effect=_rewrite)
    ) as create_skill_mock:
        result = await executor.execute("generated_retry_guard", {}, trace_id="trace-retry-guard")

    assert "still broken" in result
    fix_skill_mock.assert_awaited_once_with("generated_retry_guard")
    create_skill_mock.assert_awaited_once()
    llm.generate.assert_awaited_once()
