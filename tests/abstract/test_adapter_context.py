"""Tests for adapter context_length with max_input_tokens override."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from omg_cli.abstract.anthropic import AnthropicAPI
from omg_cli.abstract.deepseek import DeepSeekAPI
from omg_cli.abstract.openai import OpenAIAPI
from omg_cli.abstract.openai_legacy import OpenAILegacy


class TestOpenAIAPIContextLength:
    @pytest.mark.asyncio
    async def test_default_context_length(self) -> None:
        adapter = OpenAIAPI(api_key="test", model="gpt-4")
        assert await adapter.context_length() == 150000

    @pytest.mark.asyncio
    async def test_max_input_tokens_override(self) -> None:
        adapter = OpenAIAPI(api_key="test", model="gpt-4", max_input_tokens=64000)
        assert await adapter.context_length() == 64000


class TestOpenAILegacyContextLength:
    @pytest.mark.asyncio
    async def test_default_context_length(self) -> None:
        adapter = OpenAILegacy(api_key="test", model="gpt-4")
        assert await adapter.context_length() == 100000

    @pytest.mark.asyncio
    async def test_max_input_tokens_override(self) -> None:
        adapter = OpenAILegacy(api_key="test", model="gpt-4", max_input_tokens=64000)
        assert await adapter.context_length() == 64000


class TestAnthropicAPIContextLength:
    @pytest.mark.asyncio
    async def test_default_context_length_fallback(self) -> None:
        adapter = AnthropicAPI(api_key="test", model="claude-3-opus")
        adapter.client = MagicMock()
        adapter.client.models.retrieve = AsyncMock(side_effect=Exception("API error"))
        assert await adapter.context_length() == 150000

    @pytest.mark.asyncio
    async def test_max_input_tokens_override(self) -> None:
        adapter = AnthropicAPI(api_key="test", model="claude-3-opus", max_input_tokens=64000)
        assert await adapter.context_length() == 64000


class TestDeepSeekAPIContextLength:
    @pytest.mark.asyncio
    async def test_default_context_length(self) -> None:
        adapter = DeepSeekAPI(api_key="test", model="deepseek-chat")
        assert await adapter.context_length() == 100000

    @pytest.mark.asyncio
    async def test_max_input_tokens_override(self) -> None:
        adapter = DeepSeekAPI(api_key="test", model="deepseek-chat", max_input_tokens=64000)
        assert await adapter.context_length() == 64000
