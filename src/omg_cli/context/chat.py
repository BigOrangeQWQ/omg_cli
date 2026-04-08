from typing import Any
from uuid import uuid4

from src.omg_cli.config import SessionMetadata
from src.omg_cli.context.command import CommandProtocol
from src.omg_cli.context.meta import MetaContext, Notifier, tool_call_to_message
from src.omg_cli.context.tool_manager import ToolConfirmationDecision, ToolManagerProtocol
from src.omg_cli.log import logger
from src.omg_cli.types.event import SessionErrorEvent, SessionMessageEvent, SessionResetEvent
from src.omg_cli.types.message import Message, TextSegment, ToolCall
from src.omg_cli.types.tool import ToolError
from src.omg_cli.types.usage import TokenUsage

SUB_ROUNDS_LIMIT = 10
RESERVED_TOKENS = 50_000
RECENT_MESSAGES_TO_KEEP = 4


class ChatContext(MetaContext):
    """Context for managing a chat session with an LLM provider."""

    def __init__(
        self,
        *,
        provider,
        system_prompt: str,
        tools=None,
        messages=None,
        skills=None,
    ) -> None:
        super().__init__(
            provider=provider,
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
            skills=skills,
        )
        self.session_id = uuid4().hex
        self.thinking_mode = False

        self._pending_texts: list[str] = []

    async def append(self, message: Message) -> None:
        try:
            self._session_storage.append_message(self.session_id, message)
        except Exception:
            pass
        self.messages.append(message)
        self.display_messages.append(message)
        await self._emit(SessionMessageEvent(message=message))

    @property
    def pending_messages(self) -> list[str]:
        return self._pending_texts

    @property
    def command_registry(self) -> CommandProtocol:
        return self

    async def _update_max_context_size(self) -> None:
        try:
            max_context = await self.provider.context_length()
            if max_context > 0:
                self.token_usage.max_context_size = max_context
            self.token_usage.initial_context_size = True
        except Exception:
            pass

    async def ensure_context_size(self) -> None:
        if not self.token_usage.initial_context_size:
            await self._update_max_context_size()

    async def reset(self) -> None:
        self.messages.clear()
        self.display_messages.clear()
        self._session_approve_all = False
        self.token_usage = TokenUsage()
        self._message_queue.clear()
        self._pending_texts.clear()

        self.session_id = str(uuid4())
        self._session_metadata = None

        await self._update_max_context_size()
        await self._emit(SessionResetEvent())

    def interrupt(self) -> None:
        self._interrupt_requested = True

    def _clear_interrupt(self) -> None:
        self._interrupt_requested = False

    async def send(
        self,
        user_input: str | list[str],
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> None:
        texts = [user_input] if isinstance(user_input, str) else user_input
        if not texts:
            return

        if not self.token_usage.initial_context_size:
            await self._update_max_context_size()

        for text in texts:
            await self.append(Message(role="user", content=[TextSegment(text=text)]))

        self._interrupt_requested = False

        round_num = 0
        while True:
            await self.logger.debug(f"Assistant request started: {self.provider.model_name}")
            logger.debug(f"Current token usage before request: {self.token_usage}")

            provider_kwargs = dict(kwargs)
            max_tokens = provider_kwargs.pop("max_tokens", None)

            assistant_messages, tool_calls = await self.thinking(
                system_prompt=system_prompt or self.system_prompt,
                messages=self.messages,
                tools=self.tools,
                max_tokens=max_tokens,
                **provider_kwargs,
            )

            for message in assistant_messages:
                logger.debug(f"Assistant message received: {message}")

            if self._interrupt_requested or not tool_calls:
                return None

            round_num += 1
            await self.logger.debug(f"Round completed: {round_num}")

    async def _run_single_tool_call(self, tool_call: ToolCall) -> Message:
        tool_name = tool_call.function.name
        await self.logger.debug(f"Tool call started: {tool_name}")

        tool = self._tool_map.get(tool_name)
        if tool is None:
            error_message = f"Tool '{tool_name}' is not registered"
            await self._emit(SessionErrorEvent(error=error_message))
            return tool_call_to_message(tool_call, {"error": error_message})

        if tool.confirm:
            decision = await self._confirm_tool_call(tool_call, tool)
            if not decision.approved:
                rejection = {"error": "Tool call rejected by user"}
                if decision.reason:
                    rejection["reason"] = decision.reason
                if decision.next_steps:
                    rejection["next_steps"] = decision.next_steps
                await self.logger.warn(f"Tool call rejected: {tool_name}")
                return tool_call_to_message(tool_call, rejection)

        try:
            result = await tool(**tool_call.function.arguments)
        except ToolError as exc:
            error_message = str(exc)
            await self._emit(SessionErrorEvent(error=f"Tool '{tool_name}' failed: {error_message}"))
            return tool_call_to_message(tool_call, {"error": error_message})
        except Exception as exc:
            error_message = f"Tool '{tool_name}' failed unexpectedly: {exc}"
            await self._emit(SessionErrorEvent(error=error_message))
            return tool_call_to_message(tool_call, {"error": str(exc)})

        await self.logger.debug(f"Tool call completed: {tool_name}")
        return tool_call_to_message(tool_call, result)

    def load_session(self, session_id: str) -> bool:
        try:
            metadata = self._session_storage.load_metadata(session_id)
            if metadata is None:
                return False

            messages = self._session_storage.load_messages(session_id)

            self.session_id = session_id
            self._session_metadata = metadata
            self.messages = messages
            self.display_messages = list(messages)

            return True
        except Exception:
            return False

    def list_saved_sessions(self) -> list[SessionMetadata]:
        return self._session_storage.list_sessions()

    def delete_session(self, session_id: str) -> bool:
        return self._session_storage.delete(session_id)

    async def switch_model(self, model_name: str) -> bool:
        model_config = self.config_manager.get_model(model_name)
        if model_config is None:
            await self.logger.error(f"未找到模型: {model_name}")
            return False

        try:
            adapter = model_config.create_adapter()
            self.provider = adapter
            if not adapter.thinking_supported:
                self.thinking_mode = False
            await self.logger.success(f"已切换到模型: {model_name}")
            return True
        except Exception as exc:
            await self.logger.error(f"切换模型失败: {exc}")
            return False


__all__ = [
    "ChatContext",
    "Notifier",
    "SessionMetadata",
    "ToolConfirmationDecision",
    "ToolManagerProtocol",
]
