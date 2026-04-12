import abc
from collections.abc import AsyncIterator
from functools import cache
from typing import Any

from omg_cli.abstract.utils import Messages
from omg_cli.types.message import (
    Message,
    MessageStreamCompleteEvent,
    MessageStreamEvent,
    StopSegment,
)
from omg_cli.types.tool import Tool


class ChatAdapter(abc.ABC):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str,
        stream: bool = True,
        max_input_tokens: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.stream_enabled = stream
        self.max_input_tokens = max_input_tokens

    @property
    @abc.abstractmethod
    def type(self) -> str:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    def thinking_supported(self) -> bool:
        return False

    async def _call_api(self, api: str, data: Any) -> Any:
        raise NotImplementedError

    @abc.abstractmethod
    async def chat(
        self,
        system_prompt: str,
        messages: "Messages",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Message:
        """chat with the model"""
        raise NotImplementedError

    @abc.abstractmethod
    async def stream(
        self,
        system_prompt: str,
        messages: "Messages",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        thinking: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[MessageStreamEvent]:
        """stream responses from the model"""
        if False:
            yield MessageStreamCompleteEvent(segment=StopSegment(reason="stop"))
        raise NotImplementedError

    @cache
    async def list_models(self) -> list[str]:
        """list available models"""
        raise NotImplementedError

    async def balance(self) -> float:
        """account balance"""
        raise NotImplementedError

    async def context_length(self) -> int:
        """Get the model's context window length in tokens.

        Returns:
            int: The maximum context length in tokens. Defaults to 100000 if unknown.
        """
        raise NotImplementedError
