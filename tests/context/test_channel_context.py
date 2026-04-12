"""Tests for ChannelContext event forwarding."""

from pathlib import Path

import pytest

from omg_cli.abstract import ChatAdapter
from omg_cli.config.adapter_manager import get_adapter_manager
from omg_cli.context.role import ChannelContext
from omg_cli.types.channel import Role
from omg_cli.types.event import (
    BaseEvent,
    RoleActivityEvent,
    SessionErrorEvent,
    SessionMessageEvent,
    SessionStatusEvent,
    StatusLevel,
    ThreadMessageEvent,
)
from omg_cli.types.message import Message, TextSegment


class MockProvider(ChatAdapter):
    """Mock LLM provider for ChannelContext tests."""

    def __init__(self):
        super().__init__(api_key="test", model="test-model", base_url="http://test")

    @property
    def type(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "test-model"

    async def chat(self, system_prompt, messages, tools=None, max_tokens=None, **kwargs):
        return Message(role="assistant", content=[TextSegment(text="ok")])

    async def stream(self, system_prompt, messages, tools=None, max_tokens=None, thinking=False, **kwargs):
        yield Message(role="assistant", content=[TextSegment(text="ok")])

    async def list_models(self):
        return []

    async def balance(self):
        return 0.0

    async def context_length(self):
        return 100000


def _register_mock_adapter() -> None:
    get_adapter_manager.cache_clear()
    get_adapter_manager()._cache["mock"] = MockProvider()


@pytest.fixture
def sample_role():
    _register_mock_adapter()
    return Role(
        name="coder",
        desc="Writes code",
        personal_space=Path("/tmp"),
        adapter_name="mock",
    )


@pytest.mark.asyncio
async def test_role_event_forwarding(sample_role: Role) -> None:
    """ThreadRoleContext events should be forwarded through the channel's default context."""
    channel = ChannelContext(
        channel_name="test-channel",
        roles=[sample_role],
        default_role_name="coder",
    )

    collected: list[BaseEvent] = []

    async def collect_event(event: BaseEvent) -> None:
        collected.append(event)

    channel.default_context.register_event_handler(BaseEvent, collect_event)

    role_ctx = channel.role_contexts["coder"]

    # Simulate a status event from the role context
    await role_ctx._emit(SessionStatusEvent(detail="working...", level=20))

    # Status should be wrapped in RoleActivityEvent with thread_id from contextvar
    # But since no contextvar is set, it should not be forwarded
    assert len(collected) == 0

    # Now set the contextvar and emit again
    from omg_cli.context.role import _current_thread_id

    token = _current_thread_id.set(1)
    try:
        await role_ctx._emit(SessionStatusEvent(detail="working...", level=20))
    finally:
        _current_thread_id.reset(token)

    assert len(collected) == 1
    assert isinstance(collected[0], RoleActivityEvent)
    assert collected[0].thread_id == 1
    assert collected[0].role_name == "coder"
    assert collected[0].activity_type == "status"
    assert collected[0].content == "working..."


@pytest.mark.asyncio
async def test_role_error_forwarding(sample_role: Role) -> None:
    """ThreadRoleContext errors should be forwarded as RoleActivityEvent and persisted."""
    channel = ChannelContext(
        channel_name="test-channel",
        roles=[sample_role],
        default_role_name="coder",
    )

    collected: list[BaseEvent] = []

    async def collect_event(event: BaseEvent) -> None:
        collected.append(event)

    channel.default_context.register_event_handler(BaseEvent, collect_event)
    role_ctx = channel.role_contexts["coder"]

    from omg_cli.context.role import _current_thread_id

    thread_2 = channel.add_thread(title="Thread 2")
    token = _current_thread_id.set(thread_2.id)
    try:
        await role_ctx._emit(SessionErrorEvent(error="something went wrong"))
    finally:
        _current_thread_id.reset(token)

    assert len(collected) == 1
    assert isinstance(collected[0], RoleActivityEvent)
    assert collected[0].thread_id == thread_2.id
    assert collected[0].role_name == "coder"
    assert collected[0].activity_type == "error"
    assert collected[0].content == "something went wrong"

    # Verify persistence
    thread = channel.thread_map[thread_2.id]
    assert "coder" in thread.role_activities
    assert len(thread.role_activities["coder"]) == 1
    assert thread.role_activities["coder"][0].activity_type == "error"
    assert thread.role_activities["coder"][0].content == "something went wrong"


@pytest.mark.asyncio
async def test_role_activity_persistence(sample_role: Role) -> None:
    """INFO and above SessionStatusEvent should be persisted to thread.role_activities."""
    channel = ChannelContext(
        channel_name="test-channel",
        roles=[sample_role],
        default_role_name="coder",
    )

    from omg_cli.context.role import _current_thread_id

    channel.add_thread(title="Thread 1")
    token = _current_thread_id.set(1)
    try:
        await channel.role_contexts["coder"]._emit(
            SessionStatusEvent(detail="working...", level=StatusLevel.INFO)
        )
    finally:
        _current_thread_id.reset(token)

    thread = channel.thread_map[1]
    assert "coder" in thread.role_activities
    assert len(thread.role_activities["coder"]) == 1
    assert thread.role_activities["coder"][0].activity_type == "status"
    assert thread.role_activities["coder"][0].content == "working..."


@pytest.mark.asyncio
async def test_role_activity_debug_filtered(sample_role: Role) -> None:
    """DEBUG SessionStatusEvent should NOT be forwarded nor persisted."""
    channel = ChannelContext(
        channel_name="test-channel",
        roles=[sample_role],
        default_role_name="coder",
    )

    collected: list[BaseEvent] = []

    async def collect_event(event: BaseEvent) -> None:
        collected.append(event)

    channel.default_context.register_event_handler(BaseEvent, collect_event)

    from omg_cli.context.role import _current_thread_id

    channel.add_thread(title="Thread 1")
    token = _current_thread_id.set(1)
    try:
        await channel.role_contexts["coder"]._emit(
            SessionStatusEvent(detail="debug detail", level=StatusLevel.DEBUG)
        )
    finally:
        _current_thread_id.reset(token)

    assert len(collected) == 0
    thread = channel.thread_map[1]
    assert "coder" not in thread.role_activities


@pytest.mark.asyncio
async def test_role_message_still_forwarded_as_thread_message(sample_role: Role) -> None:
    """SessionMessageEvent should still be forwarded as ThreadMessageEvent."""
    channel = ChannelContext(
        channel_name="test-channel",
        roles=[sample_role],
        default_role_name="coder",
    )

    collected: list[BaseEvent] = []

    async def collect_event(event: BaseEvent) -> None:
        collected.append(event)

    channel.default_context.register_event_handler(BaseEvent, collect_event)
    role_ctx = channel.role_contexts["coder"]

    from omg_cli.context.role import _current_thread_id

    msg = Message(role="assistant", content=[TextSegment(text="hello")])
    token = _current_thread_id.set(3)
    try:
        await role_ctx._emit(SessionMessageEvent(message=msg))
    finally:
        _current_thread_id.reset(token)

    assert len(collected) == 1
    assert isinstance(collected[0], ThreadMessageEvent)
    assert collected[0].thread_id == 3
    assert collected[0].message == msg
