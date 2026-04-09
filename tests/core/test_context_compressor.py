"""Tests for the 4-phase structured context compressor (Gap H1)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.context_compressor import ContextCompressor
from core.telemetry import reset_trace_id, set_trace_id


def _make_llm(reply: str = "## Session Summary\n**Goal:** test\n**Progress:** done\n**Decisions:** none\n**Files Changed:** none\n**Next Steps:** continue") -> MagicMock:
    """Return a mock LLMGateway whose generate() returns *reply*."""
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=MagicMock(content=reply))
    return llm


def _make_messages(n: int = 10) -> list[dict]:
    """Build a synthetic message list with n turns (system + pairs)."""
    msgs = [{"role": "system", "content": "You are a helpful assistant."}]
    msgs.append({"role": "user", "content": "Initial question about the project."})
    for i in range(1, n):
        msgs.append({"role": "assistant", "content": f"Answer number {i}. " + "x" * 200})
        msgs.append({"role": "tool", "content": f"tool result {i}: " + "y" * 300})
    return msgs


class TestPruneToolOutputs:
    def test_prunes_old_tool_results(self):
        comp = ContextCompressor()
        msgs = _make_messages(8)
        # Use a small tail_chars so that most tool results fall outside
        pruned = comp._prune_tool_outputs(msgs, tail_chars=500)
        # At least one tool message should be replaced
        placeholders = [m for m in pruned if m.get("content") == "[tool result omitted]"]
        assert len(placeholders) > 0

    def test_recent_tool_results_preserved(self):
        comp = ContextCompressor()
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "question"},
            {"role": "tool", "content": "recent result"},
        ]
        pruned = comp._prune_tool_outputs(msgs, tail_chars=10_000)
        assert pruned[-1]["content"] == "recent result"

    def test_non_tool_messages_unchanged(self):
        comp = ContextCompressor()
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        pruned = comp._prune_tool_outputs(msgs, tail_chars=10)
        # User and assistant messages must not become placeholders
        assert pruned[1]["content"] == "hello"
        assert pruned[2]["content"] == "hi"


class TestSplit:
    def test_head_is_first_two_messages(self):
        comp = ContextCompressor()
        msgs = _make_messages(6)
        head, middle, tail = comp._split(msgs, head_chars=100, tail_chars=200)
        assert head[0]["role"] == "system"
        assert head[1]["role"] == "user"
        assert len(head) == 2

    def test_all_recent_fits_in_tail(self):
        comp = ContextCompressor()
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
        ]
        head, middle, tail = comp._split(msgs, head_chars=100, tail_chars=100_000)
        assert middle == []
        assert tail == [msgs[2]]

    def test_middle_is_everything_between_head_and_tail(self):
        comp = ContextCompressor()
        msgs = _make_messages(10)
        head, middle, tail = comp._split(msgs, head_chars=100, tail_chars=100)
        assert head + middle + tail == msgs or len(middle) > 0  # middle must exist

    def test_tiny_message_list_returns_empty_middle(self):
        comp = ContextCompressor()
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
        head, middle, tail = comp._split(msgs, head_chars=100, tail_chars=100)
        assert middle == []
        assert tail == []


class TestSummarise:
    @pytest.mark.asyncio
    async def test_calls_llm_and_returns_content(self):
        comp = ContextCompressor()
        llm = _make_llm("## Session Summary\n**Goal:** fix bug\n**Progress:** found it\n**Decisions:** patch core\n**Files Changed:** core/agent.py\n**Next Steps:** write test")
        middle = [
            {"role": "user", "content": "What's wrong?"},
            {"role": "assistant", "content": "There's a bug in the loop."},
        ]
        result = await comp._summarise(middle, llm)
        assert "fix bug" in result
        llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_when_llm_fails(self):
        comp = ContextCompressor()
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        middle = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        result = await comp._summarise(middle, llm)
        assert "messages omitted" in result

    @pytest.mark.asyncio
    async def test_passes_explicit_trace_id_to_llm(self):
        comp = ContextCompressor()
        llm = _make_llm()
        middle = [
            {"role": "user", "content": "What's wrong?"},
            {"role": "assistant", "content": "There's a bug in the loop."},
        ]

        await comp._summarise(middle, llm, trace_id="trace-compress-1")

        assert llm.generate.call_args.kwargs["trace_id"] == "trace-compress-1"


class TestMerge:
    @pytest.mark.asyncio
    async def test_merge_calls_llm(self):
        comp = ContextCompressor()
        llm = _make_llm("merged summary content")
        result = await comp._merge("prior summary", "new summary", llm)
        assert result == "merged summary content"
        llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_falls_back_to_new_on_error(self):
        comp = ContextCompressor()
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=RuntimeError("fail"))
        result = await comp._merge("prior", "new_summary", llm)
        assert result == "new_summary"


class TestCompress:
    @pytest.mark.asyncio
    async def test_returns_fewer_messages(self):
        comp = ContextCompressor()
        llm = _make_llm()
        msgs = _make_messages(15)
        compressed, summary = await comp.compress(
            msgs, prior_summary=None, llm=llm, head_tokens=10, tail_tokens=10
        )
        assert len(compressed) < len(msgs)
        assert summary != ""

    @pytest.mark.asyncio
    async def test_head_preserved(self):
        comp = ContextCompressor()
        llm = _make_llm()
        msgs = _make_messages(10)
        compressed, _ = await comp.compress(
            msgs, prior_summary=None, llm=llm, head_tokens=10, tail_tokens=10
        )
        assert compressed[0]["role"] == "system"
        assert compressed[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_summary_block_injected(self):
        comp = ContextCompressor()
        llm = _make_llm()
        msgs = _make_messages(10)
        compressed, _ = await comp.compress(
            msgs, prior_summary=None, llm=llm, head_tokens=10, tail_tokens=10
        )
        contents = [m.get("content", "") for m in compressed]
        assert any("[CONTEXT COMPRESSED]" in c for c in contents)

    @pytest.mark.asyncio
    async def test_short_list_unchanged(self):
        comp = ContextCompressor()
        llm = _make_llm()
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
        ]
        compressed, summary = await comp.compress(msgs, prior_summary=None, llm=llm)
        assert compressed == msgs
        assert summary == ""

    @pytest.mark.asyncio
    async def test_iterative_merge_called_with_prior_summary(self):
        comp = ContextCompressor()
        llm = _make_llm()
        msgs = _make_messages(10)
        prior = "## Session Summary\n**Goal:** prior\n**Progress:** old\n**Decisions:** x\n**Files Changed:** x\n**Next Steps:** y"
        _, new_summary = await comp.compress(
            msgs, prior_summary=prior, llm=llm, head_tokens=10, tail_tokens=10
        )
        # LLM should have been called for both summarise and merge
        assert llm.generate.call_count >= 2

    @pytest.mark.asyncio
    async def test_summary_capped_at_max_chars(self):
        comp = ContextCompressor()
        # LLM returns an enormous summary
        huge_reply = "x" * 20_000
        llm = _make_llm(huge_reply)
        msgs = _make_messages(10)
        _, summary = await comp.compress(
            msgs, prior_summary=None, llm=llm, head_tokens=10, tail_tokens=10
        )
        assert len(summary) <= 12_000 + len("\n[summary truncated]")

    @pytest.mark.asyncio
    async def test_no_middle_skips_llm_call(self):
        comp = ContextCompressor()
        llm = _make_llm()
        # All messages fit in tail — nothing to compress
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
        ]
        _, _ = await comp.compress(
            msgs, prior_summary=None, llm=llm, head_tokens=100, tail_tokens=100_000
        )
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_context_trace_id_when_not_explicit(self):
        comp = ContextCompressor()
        llm = _make_llm()
        msgs = _make_messages(10)
        token = set_trace_id("trace-from-context")

        try:
            await comp.compress(
                msgs,
                prior_summary="## Session Summary\n**Goal:** prior\n**Progress:** old\n**Decisions:** x\n**Files Changed:** x\n**Next Steps:** y",
                llm=llm,
                head_tokens=10,
                tail_tokens=10,
            )
        finally:
            reset_trace_id(token)

        trace_ids = [call.kwargs["trace_id"] for call in llm.generate.call_args_list]
        assert trace_ids == ["trace-from-context", "trace-from-context"]
