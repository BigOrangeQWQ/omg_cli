"""None adapter for when no model is configured."""

from collections.abc import AsyncIterator
from functools import cache
from typing import Any

from omg_cli.abstract import ChatAdapter
from omg_cli.abstract.utils import Messages
from omg_cli.types.message import (
    Message,
    MessageStreamCompleteEvent,
    MessageStreamEvent,
    StopSegment,
)
from omg_cli.types.tool import Tool


class NoneAdapter(ChatAdapter):
    """Adapter placeholder when no model is configured.

    Raises RuntimeError with helpful message when any method is called.
    """

    def __init__(self) -> None:
        # Don't call super().__init__() to avoid setting up unnecessary attributes
        pass

    @property
    def type(self) -> str:
        return "none"

    @property
    def model_name(self) -> str:
        return "未配置模型"

    @property
    def thinking_supported(self) -> bool:
        return False

    def _raise_error(self) -> None:
        raise RuntimeError("未配置模型，请先使用 /import 命令导入模型，或等待导入向导完成")

    async def chat(
        self,
        system_prompt: str,
        messages: "Messages",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Message:
        self._raise_error()
        # Type hint for return, never reached
        return Message(role="assistant", content=[])

    async def stream(
        self,
        system_prompt: str,
        messages: "Messages",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        thinking: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[MessageStreamEvent]:
        self._raise_error()
        if False:
            yield MessageStreamCompleteEvent(segment=StopSegment(reason="stop"))

    @cache
    async def list_models(self) -> list[str]:
        return []

    async def balance(self) -> float:
        return 0.0

    async def context_length(self) -> int:
        return 0
