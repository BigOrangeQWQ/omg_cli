"""Tests for ChatContext.thinking core loop."""

from pydantic import BaseModel
import pytest

from src.omg_cli.abstract import ChatAdapter
from src.omg_cli.context import ChatContext
from src.omg_cli.types.message import (
    Message,
    MessageStreamCompleteEvent,
    MessageStreamDeltaEvent,
    StopSegment,
    TextSegment,
    ThinkDetailSegment,
    ThinkSegment,
    ToolSegment,
    UsageSegment,
)
from src.omg_cli.types.tool import Tool


class DummyParams(BaseModel):
    pass


class EchoParams(BaseModel):
    msg: str


class MockProvider(ChatAdapter):
    """Mock LLM provider that yields a predefined sequence of stream events."""

    def __init__(self, events_list=None):
        super().__init__(api_key="test", model="test-model", base_url="http://test")
        self.events_list = events_list or []
        self.stream_call_count = 0

    @property
    def type(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "test-model"

    async def chat(self, system_prompt, messages, tools=None, max_tokens=None, **kwargs):
        raise NotImplementedError

    async def stream(self, system_prompt, messages, tools=None, max_tokens=None, thinking=False, **kwargs):
        self.stream_call_count += 1
        # Support per-round event lists (list of lists) or a single flat list
        if (
            self.events_list
            and isinstance(self.events_list, list)
            and isinstance(self.events_list[0], list)
        ):
            idx = self.stream_call_count - 1
            events = self.events_list[idx] if idx < len(self.events_list) else []
        else:
            events = self.events_list
        for event in events:
            yield event

    async def list_models(self):
        return []

    async def balance(self):
        return 0.0

    async def context_length(self):
        return 100000


def _make_context(provider: ChatAdapter) -> ChatContext:
    return ChatContext(provider=provider, system_prompt="You are a test assistant.")


@pytest.mark.asyncio
async def test_thinking_simple_text_response() -> None:
    """A single text response with no tool calls ends immediately."""
    provider = MockProvider(
        events_list=[
            MessageStreamCompleteEvent(segment=TextSegment(text="Hello!"), index=0),
            MessageStreamCompleteEvent(segment=StopSegment(reason="stop"), index=0),
        ]
    )
    ctx = _make_context(provider)

    messages, had_tool_calls = await ctx.thinking(
        system_prompt=ctx.system_prompt,
        messages=[Message(role="user", content=[TextSegment(text="Hi")])],
    )

    assert not had_tool_calls
    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].text == "Hello!"


@pytest.mark.asyncio
async def test_thinking_single_tool_call() -> None:
    """Provider requests a tool call; after executing it, another text response arrives."""
    provider = MockProvider(
        events_list=[
            # round 1
            [
                MessageStreamCompleteEvent(
                    segment=ToolSegment(tool_call_id="call-1", tool_name="dummy_tool", arguments={}),
                    index=0,
                ),
                MessageStreamCompleteEvent(segment=StopSegment(reason="tool_calls"), index=0),
            ],
            # round 2
            [
                MessageStreamCompleteEvent(segment=TextSegment(text="Done."), index=1),
                MessageStreamCompleteEvent(segment=StopSegment(reason="stop"), index=1),
            ],
        ]
    )
    ctx = _make_context(provider)

    dummy_tool = Tool(
        name="dummy_tool",
        description="A dummy tool",
        params_model=DummyParams,
    )
    dummy_tool.bind(lambda: {"result": "ok"})
    ctx.register_tool(dummy_tool)

    messages, had_tool_calls = await ctx.thinking(
        system_prompt=ctx.system_prompt,
        messages=[Message(role="user", content=[TextSegment(text="Call tool")])],
    )

    assert had_tool_calls
    assert provider.stream_call_count == 2
    # messages: assistant (tool call) + tool result + assistant (text)
    assert len(messages) == 3
    assert messages[0].role == "assistant"
    assert messages[1].role == "tool"
    assert messages[2].role == "assistant"
    assert messages[2].text == "Done."


@pytest.mark.asyncio
async def test_thinking_with_usage_segment() -> None:
    """UsageSegment should be handled gracefully without affecting output."""
    provider = MockProvider(
        events_list=[
            MessageStreamCompleteEvent(segment=TextSegment(text="Yes."), index=0),
            MessageStreamCompleteEvent(
                segment=UsageSegment(input_tokens=10, output_tokens=2), index=0
            ),
            MessageStreamCompleteEvent(segment=StopSegment(reason="stop"), index=0),
        ]
    )
    ctx = _make_context(provider)

    messages, had_tool_calls = await ctx.thinking(
        system_prompt=ctx.system_prompt,
        messages=[Message(role="user", content=[TextSegment(text="Ok?")])],
    )

    assert not had_tool_calls
    assert len(messages) == 1
    assert ctx.token_usage.input_tokens == 10
    assert ctx.token_usage.output_tokens == 2


@pytest.mark.asyncio
async def test_thinking_think_mode() -> None:
    """Thinking content is accumulated and preserved in assistant messages."""
    provider = MockProvider(
        events_list=[
            MessageStreamDeltaEvent(segment=ThinkDetailSegment(thought_process="Hmm...", index=0), index=0),
            MessageStreamCompleteEvent(
                segment=ThinkSegment(thought_process="Hmm...", signature="sig-1"), index=0
            ),
            MessageStreamCompleteEvent(segment=TextSegment(text="Answer."), index=0),
            MessageStreamCompleteEvent(segment=StopSegment(reason="stop"), index=0),
        ]
    )
    ctx = _make_context(provider)
    ctx.thinking_mode = True

    messages, had_tool_calls = await ctx.thinking(
        system_prompt=ctx.system_prompt,
        messages=[Message(role="user", content=[TextSegment(text="Think")])],
    )

    assert not had_tool_calls
    assert len(messages) == 1
    assert messages[0].thinking == "Hmm..."
    assert messages[0].text == "Answer."


@pytest.mark.asyncio
async def test_thinking_sub_rounds_limit() -> None:
    """If the provider keeps emitting tool calls, the loop stops at sub_rounds_limit."""
    provider = MockProvider(
        events_list=[
            [
                MessageStreamCompleteEvent(
                    segment=ToolSegment(
                        tool_call_id=f"call-{i}", tool_name="echo_tool", arguments={"msg": "x"}
                    ),
                    index=i,
                )
            ]
            for i in range(5)
        ]
    )
    ctx = _make_context(provider)

    echo_tool = Tool(name="echo_tool", description="Echo", params_model=EchoParams)
    echo_tool.bind(lambda msg: msg)
    ctx.register_tool(echo_tool)

    _, had_tool_calls = await ctx.thinking(
        system_prompt=ctx.system_prompt,
        messages=[Message(role="user", content=[TextSegment(text="Loop")])],
        sub_rounds_limit=2,
    )

    assert had_tool_calls
    # 2 rounds of assistant + tool result
    assert provider.stream_call_count == 2
