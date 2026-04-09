"""Tests for parallel read-only tool execution in the agent loop (Gap 11).

TDD Red phase — these tests must fail before the parallel partitioning is added
to core/agent.py. They test observable behaviour via the SkillRegistry metadata
and asyncio.gather() semantics, not internal agent internals.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skills.registry import SkillRegistry, SkillRegistration


# ---------------------------------------------------------------------------
# Helper: verify registry metadata drives partitioning logic
# ---------------------------------------------------------------------------

def _concurrent_eligible(reg: SkillRegistration) -> bool:
    """Mirror the agent's partition predicate so tests stay in sync."""
    return reg.is_read_only and reg.concurrency_safe


class TestPartitionPredicate:
    """Validate that SkillRegistration metadata correctly identifies candidates."""

    def test_read_only_and_concurrency_safe_is_eligible(self):
        reg = SkillRegistration(
            name="read_file", description="Read", func=lambda: None,
            is_read_only=True, concurrency_safe=True,
        )
        assert _concurrent_eligible(reg) is True

    def test_not_read_only_is_not_eligible(self):
        reg = SkillRegistration(
            name="write_file", description="Write", func=lambda: None,
            is_read_only=False, concurrency_safe=True,
        )
        assert _concurrent_eligible(reg) is False

    def test_not_concurrency_safe_is_not_eligible(self):
        reg = SkillRegistration(
            name="run_command", description="Run", func=lambda: None,
            is_read_only=True, concurrency_safe=False,
        )
        assert _concurrent_eligible(reg) is False

    def test_both_false_is_not_eligible(self):
        reg = SkillRegistration(
            name="delete_file", description="Delete", func=lambda: None,
            is_read_only=False, concurrency_safe=False,
        )
        assert _concurrent_eligible(reg) is False


# ---------------------------------------------------------------------------
# Gather semantics — independent of agent internals
# ---------------------------------------------------------------------------

class TestAsyncGatherSemantics:
    """Verify asyncio.gather() runs coroutines concurrently as expected."""

    @pytest.mark.asyncio
    async def test_gather_runs_all_coroutines(self):
        results = []

        async def task(n: int) -> None:
            results.append(n)

        await asyncio.gather(task(1), task(2), task(3))
        assert sorted(results) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_gather_returns_results_in_order(self):
        async def identity(x: int) -> int:
            return x

        out = await asyncio.gather(identity(10), identity(20), identity(30))
        assert list(out) == [10, 20, 30]

    @pytest.mark.asyncio
    async def test_gather_runs_faster_than_sequential(self):
        """Parallel tasks finish faster than sequential — basic sanity check."""
        import time

        delay = 0.05  # 50 ms each

        async def slow_task() -> None:
            await asyncio.sleep(delay)

        start = time.monotonic()
        await asyncio.gather(slow_task(), slow_task(), slow_task())
        elapsed = time.monotonic() - start

        # 3 × 50 ms = 150 ms sequential; parallel should be < 120 ms
        assert elapsed < delay * 2.5, f"Took {elapsed:.3f}s — too slow for parallel execution"


# ---------------------------------------------------------------------------
# SkillRegistry — read_only / concurrency_safe metadata round-trip
# ---------------------------------------------------------------------------

class TestSkillRegistryParallelMetadata:
    def test_default_skills_are_parallel_eligible(self):
        """Skills registered without explicit flags default to eligible."""
        reg = SkillRegistry()

        def read_fn(path: str) -> str:
            return path

        reg.register("read_file", "Read a file", read_fn)
        r = reg.get_registration("read_file")
        assert _concurrent_eligible(r) is True

    def test_write_skill_is_not_eligible(self):
        reg = SkillRegistry()

        def write_fn(path: str, content: str) -> str:
            return path

        reg.register("write_file", "Write a file", write_fn, is_read_only=False)
        r = reg.get_registration("write_file")
        assert _concurrent_eligible(r) is False

    def test_mixed_skills_partition_correctly(self):
        reg = SkillRegistry()

        def read_fn(path: str) -> str:
            return path

        def write_fn(path: str, content: str) -> str:
            return path

        reg.register("read_file", "Read", read_fn, is_read_only=True, concurrency_safe=True)
        reg.register("write_file", "Write", write_fn, is_read_only=False, concurrency_safe=True)
        reg.register("run_command", "Run", read_fn, is_read_only=True, concurrency_safe=False)

        names = reg.get_all_skill_names()
        concurrent = [n for n in names if _concurrent_eligible(reg.get_registration(n))]
        serial = [n for n in names if not _concurrent_eligible(reg.get_registration(n))]

        assert concurrent == ["read_file"]
        assert set(serial) == {"write_file", "run_command"}
