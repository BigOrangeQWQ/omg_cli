from pathlib import Path

from omg_cli.config import SessionMetadata
from omg_cli.config.session_storage import SessionStorage
from omg_cli.context.command import CommandProtocol
from omg_cli.context.meta import MetaContext, Notifier, tool_call_to_message
from omg_cli.context.tool_manager import ToolConfirmationDecision, ToolManagerProtocol
from omg_cli.types.event import SessionErrorEvent, SessionMessageEvent
from omg_cli.types.message import Message, ToolCall
from omg_cli.types.skill import SkillRef
from omg_cli.types.tool import Tool, ToolError

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
        tools: list[Tool] | None = None,
        messages: list[Message] | None = None,
        skills: list[SkillRef] | None = None,
    ) -> None:
        super().__init__(
            provider=provider,
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
            skills=skills,
        )
        self._pending_messages: list[str] = []

        self._session_metadata = SessionMetadata(
            session_id=self.session_id,
            workspace=Path.cwd(),
            model_name=self.provider.model_name,
        )
        self._session_storage = SessionStorage()

    async def append(self, message: Message, display: bool = True) -> None:
        try:
            self._session_storage.append_message(self.session_id, message)
        except Exception:
            pass
        self.messages.append(message)
        if display:
            self.display_messages.append(message)
        await self._emit(SessionMessageEvent(message=message))

    @property
    def pending_messages(self) -> list[str]:
        return self._pending_messages

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
        self._session_storage.save_messages(self.session_id, [])
        self._session_storage.save_metadata(self._session_metadata)

        await super().reset()

    async def compact_context(self, keep_recent: int = RECENT_MESSAGES_TO_KEEP) -> str | None:
        await super().compact_context(keep_recent=keep_recent)
        self._session_storage.save_messages(self.session_id, self.messages)

    def interrupt(self) -> None:
        self._interrupt_requested = True

    def _clear_interrupt(self) -> None:
        self._interrupt_requested = False

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
