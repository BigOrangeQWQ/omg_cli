"""Tests for RoleContext auto-approval and task execution."""

from pathlib import Path

from pydantic import BaseModel
import pytest

from omg_cli.abstract import ChatAdapter
from omg_cli.config.adapter_manager import get_adapter_manager
from omg_cli.context.role import ThreadRoleContext
from omg_cli.tool import register_tool
from omg_cli.types.channel import Role
from omg_cli.types.message import (
    Message,
    TextSegment,
    ToolResultSegment,
    ToolSegment,
)


class MockProvider(ChatAdapter):
    """Mock LLM provider for RoleContext tests."""

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
        return Message(role="assistant", content=[TextSegment(text="planned")])

    async def stream(self, system_prompt, messages, tools=None, max_tokens=None, thinking=False, **kwargs):
        self.stream_call_count += 1
        if self.events_list and isinstance(self.events_list, list) and isinstance(self.events_list[0], list):
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


class ConfirmParams(BaseModel):
    value: str


@pytest.fixture
def sample_role():
    return Role(
        name="coder",
        desc="Writes code",
        personal_space=Path("/tmp"),
        adapter_name="mock",
    )


def _register_mock_adapter(provider: ChatAdapter) -> None:
    get_adapter_manager.cache_clear()
    get_adapter_manager()._cache["mock"] = provider


@pytest.mark.asyncio
async def test_build_system_prompt(sample_role: Role) -> None:
    provider = MockProvider()
    _register_mock_adapter(provider)
    ctx = ThreadRoleContext(role=sample_role)
    assert "coder" in ctx.system_prompt
    assert "Writes code" in ctx.system_prompt


@pytest.mark.asyncio
async def test_auto_approve_tool_call(sample_role: Role) -> None:
    provider = MockProvider()
    _register_mock_adapter(provider)

    ctx = ThreadRoleContext(role=sample_role)

    @register_tool(confirm=True)
    def sensitive_tool(value: str) -> str:
        return f"done: {value}"

    ctx.register_tool(sensitive_tool)

    tool_call = ToolSegment(
        tool_call_id="1",
        tool_name="sensitive_tool",
        arguments={"value": "secret"},
    ).to_tool_call()

    msg = await ctx._run_single_tool_call(tool_call)
    assert msg.role == "tool"
    result_seg = msg.content[0]
    assert isinstance(result_seg, ToolResultSegment)
    assert "done: secret" in str(result_seg.content)


