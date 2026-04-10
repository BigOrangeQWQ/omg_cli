import asyncio
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget

from omg_cli.config import get_config_manager
from omg_cli.context import ChatContext
from omg_cli.context.tool_manager import ToolConfirmationDecision
from omg_cli.log import logger
from omg_cli.types.event import (
    AppExitEvent,
    BaseEvent,
    SessionCompactedEvent,
    SessionErrorEvent,
    SessionLoadedEvent,
    SessionMessageEvent,
    SessionResetEvent,
    SessionStatusEvent,
    SessionStreamCompletedEvent,
    SessionStreamDeltaEvent,
    StatusLevel,
)
from omg_cli.types.message import (
    Message,
    MessageStreamDeltaEvent,
    TextDetailSegment,
    ThinkDetailSegment,
    ToolCall,
    ToolCallDetailSegment,
)
from omg_cli.types.tool import Tool

from .command_definitions import register_commands
from .import_wizard import ImportWizard
from .styles import CSS
from .utils import _format_arguments
from .widgets import (
    ApprovalDialog,
    CommandPalette,
    ComposerTextArea,
    ContextFooter,
    MessageHistoryView,
    MessageRow,
    PendingMessagesDisplay,
    PreviewRow,
    StatusWidget,
    ToolPreviewRow,
    UnifiedStreamPreviewRow,
)


class ChatTerminalApp(App):
    CSS = CSS
    ENABLE_COMMAND_PALETTE = False

    BINDINGS: ClassVar[list[BindingType]] = [
        ("ctrl+t", "toggle_thinking", "切换 Thinking"),
        ("ctrl+x", "toggle_planning", "切换 Planning"),
        ("ctrl+l", "clear_session", "清空会话"),
        ("ctrl+c", "interrupt", "打断输出"),
        ("ctrl+d", "quit", "退出"),
    ]

    def __init__(self, context: ChatContext) -> None:
        super().__init__()
        self.context = context
        self._stream_previews: dict[tuple[str, str | int | None], PreviewRow] = {}
        self._is_processing: bool = False
        self._ctrl_c_count: int = 0
        self._pending_rejection_future: asyncio.Future[str] | None = None
        self.context.set_tool_confirmation_handler(self._confirm_tool_call)
        register_commands(self.context)

    @property
    def logger(self):
        return self.context.logger

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="chat-panel"):
                yield MessageHistoryView(id="messages")
                yield CommandPalette()
                yield PendingMessagesDisplay(id="pending-messages")
                yield Vertical(id="approval-container")
                yield ComposerTextArea(placeholder="输入消息，Enter 发送，Ctrl+Enter 换行，/ 查看命令……")
        yield ContextFooter()

    async def on_mount(self) -> None:
        logger.debug(f"provider={self.context.provider.type}:{self.context.provider.model_name}")

        messages_view = self.query_one("#messages", VerticalScroll)
        messages_view.show_vertical_scrollbar = False

        self.context.register_event_handler(BaseEvent, self._handle_context_event)
        self.context.register_event_handler(SessionStreamDeltaEvent, self._handle_stream_event)
        self.context.register_event_handler(SessionStreamCompletedEvent, self._handle_stream_event)

        await self.logger.info(f"Session ID: {self.context.session_id}")
        for message in self.context.messages:
            await self._mount_message(message)

        self._sync_composer_height()
        self._focus_composer()

    async def check_and_show_import_wizard(self) -> None:
        config_manager = get_config_manager()
        if not config_manager.has_models():
            await self.logger.info("No models configured. Please import a model first")
            await self.start_import_wizard()
            return

        model_config = config_manager.get_default_model()
        if model_config:
            await self.logger.info(f"Current model: {model_config.name} ({model_config.model})")
        await self._update_context_display()

    async def start_import_wizard(self) -> None:
        composer = self.query_one("#composer", ComposerTextArea)
        composer.styles.display = "none"

        container = self.query_one("#approval-container", Vertical)
        wizard = ImportWizard()
        await container.mount(wizard)
        self.call_after_refresh(wizard.focus)

    async def on_model_imported(self, model_name: str) -> None:
        messages_view = self.query_one("#messages", VerticalScroll)
        await messages_view.remove_children()
        await self.logger.success(f"✓ 模型 '{model_name}' 导入成功")
        await self.reload_model()

    async def reload_model(self) -> None:
        config_manager = get_config_manager()
        model_config = config_manager.get_default_model()

        if model_config is None:
            await self.logger.error("No model configuration available")
            return

        success = await self.context.switch_model(model_config.name)
        if success:
            await self._update_context_display()

    async def on_ready(self) -> None:
        self._sync_composer_height()
        self.call_after_refresh(self._focus_composer)
        await self.check_and_show_import_wizard()
        await self.context.initialize_mcp_servers()

    async def on_unmount(self) -> None:
        session_id = self.context.session_id
        print(f"\n下次可以通过 omg-cli -r {session_id} 恢复本次会话")
        self.context.set_tool_confirmation_handler(None)
        await self.context.disconnect_all_mcp_servers()

    async def _update_context_display(self) -> None:
        try:
            await self.context.ensure_context_size()
            footer = self.query_one(ContextFooter)
            logger.debug(
                f"Current context tokens: {self.context.token_usage.context_tokens},\
                    max: {self.context.token_usage.max_context_size}"
            )
            footer.update_context_display(
                self.context.token_usage.context_tokens,
                self.context.token_usage.max_context_size,
            )
        except Exception as e:
            logger.error(f"Failed to update context display: {e}")

    async def on_composer_text_area_submitted(self, event: ComposerTextArea.Submitted) -> None:
        text = event.value.strip()

        # If we're waiting for a custom rejection reason, forward the text and don't send it as a chat message.
        if self._pending_rejection_future is not None and not self._pending_rejection_future.done():
            self._pending_rejection_future.set_result(text)
            composer = self.query_one("#composer", ComposerTextArea)
            composer.load_text("")
            self._sync_composer_height()
            return

        if not text:
            return

        self._ctrl_c_count = 0
        composer = self.query_one(ComposerTextArea)
        composer.add_history(text)

        if text.startswith("/"):
            if await self._handle_meta_command(text):
                composer.load_text("")
                self._sync_composer_height()
                return

        if self._is_processing:
            self.context.pending_messages.append(text)
            composer.load_text("")
            self._sync_composer_height()
            self.query_one("#pending-messages", PendingMessagesDisplay).update_messages(self.context.pending_messages)
            return

        logger.debug(f"User input submitted: {text[:80]!r}")
        composer.load_text("")
        self._sync_composer_height()
        self.run_worker(self._submit_text(text), thread=False, exclusive=True)

    async def _handle_meta_command(self, text: str) -> bool:
        parts = text.split(maxsplit=1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        command = self.context.command_registry.get(cmd_name)
        if command:
            result = command.handler(self.context, args)
            if result is not None and hasattr(result, "__await__"):
                await result
            return True

        await self.logger.error(f"Unknown command: {cmd_name}, use /help for available commands")
        return True

    async def _submit_text(self, text: str) -> None:
        self._is_processing = True
        composer = self.query_one(ComposerTextArea)
        pending_display = self.query_one("#pending-messages", PendingMessagesDisplay)
        try:
            await self.context.send(text)

            while self.context.pending_messages:
                pending = list(self.context.pending_messages)
                self.context.pending_messages.clear()
                pending_display.update_messages(self.context.pending_messages)
                await self.logger.info(f"Sending {len(pending)} pending messages...")
                await self.context.send(pending)
        except Exception as exc:
            logger.debug(f"Session exception: {exc}")
            await self.logger.error(f"Session failed: {exc}")
        finally:
            self._is_processing = False
            pending_display.update_messages([])
            self._sync_composer_height()
            composer.focus()

    async def _handle_context_event(self, event: BaseEvent) -> None:
        match event:
            case SessionMessageEvent(message=message):
                if message.role == "assistant":
                    await self._clear_stream_previews()
                await self._mount_message(message)
                await self._update_context_display()
            case SessionStatusEvent(level=level, detail=detail):
                if level >= StatusLevel.ERROR:
                    await self._mount_status(f"{detail}", variant="error")
                elif level == StatusLevel.SUCCESS:
                    await self._mount_status(f"{detail}", variant="success")
                elif level >= StatusLevel.INFO:
                    await self._mount_status(f"{detail}", variant="status")
                else:
                    logger.debug(f"Status event received: level={level.name}, detail={detail}")
            case AppExitEvent():
                self.exit()
            case SessionErrorEvent(error=error):
                logger.debug(f"Error event received: {error}")
                await self._mount_status(error, variant="error")
            case SessionResetEvent():
                messages_view = self.query_one("#messages", VerticalScroll)
                await messages_view.remove_children()
                self._stream_previews.clear()
                logger.debug("Session reset")
                await self._update_context_display()
                self.call_after_refresh(self._focus_composer)
            case SessionLoadedEvent():
                messages_view = self.query_one("#messages", VerticalScroll)
                await messages_view.remove_children()
                self._stream_previews.clear()
                for message in self.context.display_messages:
                    await self._mount_message(message)
                logger.debug("Session loaded")
                await self._update_context_display()
                self.call_after_refresh(self._focus_composer)
            case SessionCompactedEvent():
                messages_view = self.query_one("#messages", VerticalScroll)
                await messages_view.remove_children()
                self._stream_previews.clear()
                for message in self.context.display_messages:
                    await self._mount_message(message)
                logger.debug("Session compacted")
                await self._update_context_display()
                self.call_after_refresh(self._focus_composer)
            case _:
                pass

    async def _handle_stream_event(self, session_event: SessionStreamDeltaEvent | SessionStreamCompletedEvent) -> None:
        if not isinstance(session_event, SessionStreamDeltaEvent):
            return

        stream_event = session_event.stream_event
        if not isinstance(stream_event, MessageStreamDeltaEvent):
            return

        match stream_event.segment:
            case TextDetailSegment(text=text):
                await self._append_unified_preview(stream_event.segment.index, text, thinking=False)
            case ThinkDetailSegment(thought_process=text):
                await self._append_unified_preview(stream_event.segment.index, text, thinking=True)
            case ToolCallDetailSegment(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                partial_arguments=partial_arguments,
            ):
                preview_key = ("tool", tool_call_id)
                is_first_chunk = preview_key not in self._stream_previews
                if is_first_chunk:
                    formatted_args = _format_arguments(partial_arguments, max_lines=1) if partial_arguments else ""
                    preview_text = (
                        f"调用工具 · {tool_name} · {formatted_args}" if formatted_args else f"调用工具 · {tool_name}"
                    )
                else:
                    preview_text = partial_arguments

                tool_row: ToolPreviewRow | None = None
                existing = self._stream_previews.get(preview_key)
                if existing is None:
                    new_row = ToolPreviewRow()
                    self._stream_previews[preview_key] = new_row
                    messages_view = self.query_one("#messages", VerticalScroll)
                    await messages_view.mount(new_row)
                    tool_row = new_row
                elif isinstance(existing, ToolPreviewRow):
                    tool_row = existing
                if tool_row is not None:
                    await tool_row.append(preview_text)
                self.query_one("#messages", VerticalScroll).scroll_end(animate=False)
            case _:
                return

    async def _append_unified_preview(self, index: int, text: str, *, thinking: bool) -> None:
        preview_key = ("unified", index)
        unified_row: UnifiedStreamPreviewRow | None = None
        existing = self._stream_previews.get(preview_key)
        if existing is None:
            new_row = UnifiedStreamPreviewRow(message_index=index)
            self._stream_previews[preview_key] = new_row
            messages_view = self.query_one("#messages", VerticalScroll)
            await messages_view.mount(new_row)
            unified_row = new_row
        elif isinstance(existing, UnifiedStreamPreviewRow):
            unified_row = existing
        if unified_row is not None:
            if thinking:
                await unified_row.append_thinking(text)
            else:
                await unified_row.append_text(text)
        self.query_one("#messages", VerticalScroll).scroll_end(animate=False)

    async def _mount_message(self, message: Message) -> None:
        messages_view = self.query_one("#messages", VerticalScroll)
        row = MessageRow(message)
        await messages_view.mount(row)
        row.refresh(layout=True)
        for child in row.walk_children():
            if isinstance(child, Widget):
                child.refresh(layout=True)
        messages_view.scroll_end(animate=False)

    async def _mount_status(self, text: str, *, variant: str = "status") -> None:
        messages_view = self.query_one("#messages", VerticalScroll)
        await messages_view.mount(StatusWidget(text, variant=variant))
        messages_view.scroll_end(animate=False)

    async def _clear_stream_previews(self) -> None:
        rows = list(self._stream_previews.values())
        self._stream_previews.clear()
        for row in rows:
            await row.close()
            await row.remove()

    async def action_toggle_thinking(self) -> None:
        if not self.context.provider.thinking_supported:
            await self.logger.error("Current model does not support Thinking mode")
            return
        self.context.thinking_mode = not self.context.thinking_mode
        mode = "enabled" if self.context.thinking_mode else "disabled"
        await self.logger.info(f"Thinking {mode}")

    async def action_toggle_planning(self) -> None:
        self.context.planning_mode = not self.context.planning_mode
        mode = "enabled" if self.context.planning_mode else "disabled"
        await self.logger.info(f"Planning {mode}")

    async def action_clear_session(self) -> None:
        await self.context.reset()

    async def action_interrupt(self) -> None:
        if self._is_processing:
            self.context.interrupt()
            await self.logger.error("Interrupted by user")
            self._ctrl_c_count = 0
            return

        self._ctrl_c_count += 1
        if self._ctrl_c_count >= 2:
            await self.logger.info("Hint: Use Ctrl+D to exit")
            self._ctrl_c_count = 0

    async def action_quit(self) -> None:
        self.exit()

    def on_mouse_scroll_up(self, event) -> None:
        self._forward_scroll_to_history(event, step=-3)

    def on_mouse_scroll_down(self, event) -> None:
        self._forward_scroll_to_history(event, step=3)

    def _focus_composer(self) -> None:
        self.query_one("#composer", ComposerTextArea).focus()

    def _sync_composer_height(self) -> None:
        composer = self.query_one(ComposerTextArea)
        visible_lines = max(3, min(composer.wrapped_document.height, 8))
        target_height = visible_lines + 7
        css_height = composer.styles.height
        if css_height is not None and not str(css_height).endswith("fr"):
            composer.styles.height = target_height

    def _forward_scroll_to_history(self, event, *, step: int) -> None:
        messages_view = self.query_one("#messages", MessageHistoryView)
        if not messages_view.region.contains_point(event.screen_offset):
            return
        if messages_view.scroll_for_wheel(step):
            event.stop()
            event.prevent_default()

    async def _confirm_tool_call(
        self,
        tool_call: ToolCall,
        tool: Tool[object],
    ) -> ToolConfirmationDecision:
        arguments = _format_arguments(tool_call.function.arguments)

        container = self.query_one("#approval-container", Vertical)
        dialog = ApprovalDialog(tool.name, arguments)
        await container.mount(dialog)
        dialog.focus()

        composer = self.query_one("#composer", ComposerTextArea)
        old_placeholder = composer.placeholder
        old_text = composer.text
        composer.placeholder = "输入拒绝原因，Enter 提交；或在上方选择操作（y/s/n）"
        self._pending_rejection_future = asyncio.Future()

        try:
            dialog_task = asyncio.create_task(dialog.wait())
            composer_task = asyncio.ensure_future(self._pending_rejection_future)

            done, pending_set = await asyncio.wait(
                [dialog_task, composer_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending_set:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            result = next(iter(done)).result()
        finally:
            if dialog.is_mounted:
                dialog.remove()
            self._pending_rejection_future = None
            composer.placeholder = old_placeholder
            composer.focus()
            self._sync_composer_height()

        if isinstance(result, ToolConfirmationDecision):
            decision = result
            # 恢复原先输入的内容，以防用户在 composer 里误触键盘改了文字
            composer.load_text(old_text)
        else:
            # result is str from composer
            composer.load_text(old_text)
            decision = ToolConfirmationDecision(approved=False, reason=result or "Rejected by user")

        if not decision.approved and decision.reason:
            await self.logger.info(f"Tool call rejected: {tool.name}, reason: {decision.reason}")

        return decision


def run_terminal(context: ChatContext, *, channel: bool = False) -> None:
    ChatTerminalApp(context, channel_mode=channel).run()
