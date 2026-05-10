"""Tests for context compaction and dynamic context trimming."""

import pytest

from omg_cli.context.meta import (
    COMPACT_THRESHOLD_PERCENT,
    MAX_TOOL_RESULT_LENGTH,
    _truncate_tool_result,
    tool_call_to_message,
)
from omg_cli.types.message import Message, TextSegment, ToolCall, ToolCallFunctionBody, ToolResultSegment


class TestTruncateToolResult:
    def test_short_result_unchanged(self) -> None:
        short = "short result"
        assert _truncate_tool_result(short) == short

    def test_long_result_truncated(self) -> None:
        long_result = "x" * (MAX_TOOL_RESULT_LENGTH + 1000)
        truncated = _truncate_tool_result(long_result)
        assert len(truncated) < len(long_result)
        assert "truncated" in truncated
        assert truncated.startswith("x" * (MAX_TOOL_RESULT_LENGTH // 2))

    def test_truncation_preserves_head_and_tail(self) -> None:
        long_result = "HEAD" + "x" * 50000 + "TAIL"
        truncated = _truncate_tool_result(long_result)
        assert "HEAD" in truncated
        assert "TAIL" in truncated
        assert "truncated" in truncated


class TestToolCallToMessageTruncation:
    def test_long_string_result_truncated(self) -> None:
        tool_call = ToolCall(
            id="test-id",
            function=ToolCallFunctionBody(name="ReadFile", arguments={"path": "test.py"}),
        )
        long_result = "x" * (MAX_TOOL_RESULT_LENGTH + 1000)
        msg = tool_call_to_message(tool_call, long_result)
        content = msg.content[0]
        assert isinstance(content, ToolResultSegment)
        assert len(content.content) < len(long_result)
        assert "truncated" in content.content

    def test_dict_result_truncated(self) -> None:
        tool_call = ToolCall(
            id="test-id",
            function=ToolCallFunctionBody(name="ReadFile", arguments={"path": "test.py"}),
        )
        long_dict = {"content": "x" * (MAX_TOOL_RESULT_LENGTH + 1000)}
        msg = tool_call_to_message(tool_call, long_dict)
        content = msg.content[0]
        assert isinstance(content, ToolResultSegment)
        assert "truncated" in content.content

    def test_short_result_not_truncated(self) -> None:
        tool_call = ToolCall(
            id="test-id",
            function=ToolCallFunctionBody(name="ReadFile", arguments={"path": "test.py"}),
        )
        short_result = "short content"
        msg = tool_call_to_message(tool_call, short_result)
        content = msg.content[0]
        assert isinstance(content, ToolResultSegment)
        assert content.content == short_result


class TestCompactThreshold:
    def test_compact_threshold_is_85(self) -> None:
        assert COMPACT_THRESHOLD_PERCENT == 85.0


class TestSendMarksPending:
    @pytest.fixture
    def ctx(self):
        """Create a minimal concrete subclass of MetaContext for testing."""
        from omg_cli.context.meta import MetaContext

        class TestContext(MetaContext):
            async def _run_single_tool_call(self, tool_call):
                return Message(role="tool", content=[])

        ctx = TestContext.__new__(TestContext)
        ctx._pending_compact_ranges = []
        ctx.messages = []
        ctx._message_queue = []
        return ctx

    def test_first_user_message_no_pending(self, ctx) -> None:
        # First user message: messages is empty, _mark_pending_compact(0) is no-op
        msg = Message(role="user", content=[TextSegment(text="hello")])
        # Simulate the logic in send()
        if msg.role == "user":
            ctx._mark_pending_compact(len(ctx.messages))
        assert len(ctx._pending_compact_ranges) == 0

    def test_second_user_message_marks_pending(self, ctx) -> None:
        # First message
        first_msg = Message(role="user", content=[TextSegment(text="do A")])
        ctx.messages = [first_msg]

        # Second message should mark pending (range 0-1)
        msg = Message(role="user", content=[TextSegment(text="do B")])
        if msg.role == "user":
            ctx._mark_pending_compact(len(ctx.messages))

        assert len(ctx._pending_compact_ranges) == 1
        assert ctx._pending_compact_ranges[0] == (0, 1)


class TestMarkPendingCompact:
    @pytest.fixture
    def ctx(self):
        from omg_cli.context.meta import MetaContext

        class TestContext(MetaContext):
            async def _run_single_tool_call(self, tool_call):
                return Message(role="tool", content=[])

        return TestContext.__new__(TestContext)

    def test_mark_pending_adds_range(self, ctx) -> None:
        ctx._pending_compact_ranges = []
        ctx.messages = [Message(role="user", content=[TextSegment(text="msg")]) for _ in range(10)]

        ctx._mark_pending_compact(5)
        assert len(ctx._pending_compact_ranges) == 1
        assert ctx._pending_compact_ranges[0] == (0, 5)

    def test_mark_pending_with_existing_range(self, ctx) -> None:
        ctx._pending_compact_ranges = [(0, 5)]
        ctx.messages = [Message(role="user", content=[TextSegment(text="msg")]) for _ in range(10)]

        ctx._mark_pending_compact(8)
        assert len(ctx._pending_compact_ranges) == 2
        assert ctx._pending_compact_ranges[1] == (5, 8)

    def test_mark_pending_no_op_when_start_equals_end(self, ctx) -> None:
        ctx._pending_compact_ranges = []
        ctx.messages = []

        ctx._mark_pending_compact(0)
        assert len(ctx._pending_compact_ranges) == 0
