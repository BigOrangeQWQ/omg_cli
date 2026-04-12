"""Tests for Channel mode app."""

from pathlib import Path

import pytest

from omg_cli.abstract import ChatAdapter
from omg_cli.config.adapter_manager import get_adapter_manager
from omg_cli.context.role import ChannelContext
from omg_cli.shell.channel_app import ChannelTerminalApp
from omg_cli.shell.meta_app import MetaApp
from omg_cli.types.channel import Role, Thread
from omg_cli.types.message import Message, TextSegment


class MockProvider(ChatAdapter):
    """Mock LLM provider for ChannelApp tests."""

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

    async def stream(
        self, system_prompt, messages, tools=None, max_tokens=None, thinking=False, **kwargs
    ):
        yield Message(role="assistant", content=[TextSegment(text="ok")])

    async def list_models(self):
        return []

    async def balance(self):
        return 0.0

    async def context_length(self):
        return 100000


def _register_mock_adapter():
    get_adapter_manager.cache_clear()
    get_adapter_manager()._cache["mock"] = MockProvider()


class TestableChannelApp(ChannelTerminalApp):
    """Testable subclass that skips import wizard and default role checks."""

    async def on_mount(self) -> None:
        # Call MetaApp.on_mount directly to register event handlers
        # without triggering import wizard or role selector dialogs.
        await MetaApp.on_mount(self)


class TestChannelAppThreadSpawned:
    @pytest.mark.asyncio
    async def test_active_thread_unchanged_for_other_events(self, tmp_path: Path) -> None:
        """Non-spawn events should not modify active_thread_id."""
        _register_mock_adapter()
        role = Role(
            name="coder",
            desc="",
            personal_space=tmp_path,
            adapter_name="mock",
        )
        channel_ctx = ChannelContext(
            channel_name="test",
            provider=MockProvider(),
            roles=[role],
            threads=[Thread(id=0, title="Default", description="")],
            default_role_name="coder",
        )
        app = TestableChannelApp(channel_ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.active_thread_id == 0

            # Emit a regular message event, not ThreadSpawnedEvent
            from omg_cli.types.event import SessionMessageEvent

            await channel_ctx.default_context._emit(
                SessionMessageEvent(message=Message(role="assistant", content=[TextSegment(text="hi")]))
            )
            await pilot.pause()
            assert app.active_thread_id == 0
