from asyncio.futures import Future
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll

from src.omg_cli.config import get_config_manager
from src.omg_cli.context import ChatContext
from src.omg_cli.context.tool_manager import ToolConfirmationDecision
from src.omg_cli.log import logger
from src.omg_cli.types.event import (
    AppExitEvent,
    BaseEvent,
    SessionErrorEvent,
    SessionLoadedEvent,
    SessionMessageEvent,
    SessionResetEvent,
    SessionStatusEvent,
    SessionStreamCompletedEvent,
    SessionStreamDeltaEvent,
    StatusLevel,
)
from src.omg_cli.types.message import (
    Message,
    MessageStreamDeltaEvent,
    TextDetailSegment,
    ThinkDetailSegment,
    ToolCall,
    ToolCallDetailSegment,
)
from src.omg_cli.types.tool import Tool

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
    """Textual TUI for ChatContext."""

    CSS = CSS
    ENABLE_COMMAND_PALETTE = False

    BINDINGS: ClassVar[list[BindingType]] = [
        ("ctrl+t", "toggle_thinking", "切换 Thinking"),
        ("ctrl+l", "clear_session", "清空会话"),
        ("ctrl+c", "interrupt", "打断输出"),
        ("ctrl+d", "quit", "退出"),
    ]

    def __init__(self, context: ChatContext) -> None:
        super().__init__()
        self.context = context
        self._stream_previews: dict[tuple[str, str | int | None], PreviewRow] = {}
        self._pending_tool_confirmation: Future[ToolConfirmationDecision] | None = None
        self._pending_tool_name: str | None = None
        self._is_processing: bool = False
        self._ctrl_c_count: int = 0
        self._composer_stashed_text: str = ""  # Cache for composer text during approval
        # Set app reference on context for command access
        self.context.set_tool_confirmation_handler(self._confirm_tool_call)
        self._register_default_commands()

    @property
    def logger(self):
        """Get the context logger for sending status messages."""
        return self.context.logger

    def _register_default_commands(self) -> None:
        """Register default meta commands."""
        from .command_definitions import register_commands

        register_commands(self.context)

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="chat-panel"):
                yield MessageHistoryView(id="messages")
                yield CommandPalette()
                yield PendingMessagesDisplay(id="pending-messages")
                yield Vertical(id="approval-container")
                yield ComposerTextArea(placeholder="输入消息，Enter 发送，Ctrl+Enter 换行，/ 查看命令……")
        # Custom footer with context status on the right
        yield ContextFooter()

    async def on_mount(self) -> None:
        logger.debug(f"provider={self.context.provider.type}:{self.context.provider.model_name}")

        messages_view = self.query_one("#messages", VerticalScroll)
        messages_view.show_vertical_scrollbar = False

        # Register event handlers with context's event manager
        self.context.register_event_handler(BaseEvent, self._handle_context_event)
        self.context.register_event_handler(SessionStreamDeltaEvent, self._handle_stream_event)
        self.context.register_event_handler(SessionStreamCompletedEvent, self._handle_stream_event)

        for message in self.context.messages:
            await self._mount_message(message)

        self._sync_composer_height()
        self._focus_composer()

    async def show_current_model(self) -> None:
        """Display current model info in message history."""
        config_manager = get_config_manager()
        model_config = config_manager.get_default_model()
        if model_config:
            await self.logger.info(f"Current model: {model_config.name} ({model_config.model})")

    async def check_and_show_import_wizard(self) -> None:
        """Check if models exist, show import wizard if not, otherwise show current model."""
        config_manager = get_config_manager()
        if not config_manager.has_models():
            await self.logger.info("No models configured. Please import a model first")
            await self.start_import_wizard()
        else:
            # Show current model info
            await self.show_current_model()
            # Initialize context display
            await self._update_context_display()

    async def start_import_wizard(self) -> None:
        """Show the model import wizard."""
        # Hide composer while wizard is open
        composer = self.query_one("#composer", ComposerTextArea)
        composer.styles.display = "none"

        container = self.query_one("#approval-container", Vertical)
        wizard = ImportWizard()
        await container.mount(wizard)

        # Force focus to wizard after mount
        self.call_after_refresh(wizard.focus)

    async def on_model_imported(self, model_name: str) -> None:
        """Handle model import success - clear messages and show success."""
        # Clear all messages
        messages_view = self.query_one("#messages", VerticalScroll)
        await messages_view.remove_children()
        # Show success message
        await self.logger.success(f"✓ 模型 '{model_name}' 导入成功")
        # Reload model
        await self.reload_model()

    async def reload_model(self) -> None:
        """Reload the current model from config."""
        config_manager = get_config_manager()
        model_config = config_manager.get_default_model()

        if model_config is None:
            await self.logger.error("No model configuration available")
            return

        # Use the new switch_model method on context
        success = await self.context.switch_model(model_config.name)
        if success:
            await self._update_context_display()

    async def on_ready(self) -> None:
        self._sync_composer_height()
        self.call_after_refresh(self._focus_composer)

        # Check if we need to show import wizard (no models configured)
        await self.check_and_show_import_wizard()

        # Initialize MCP servers after model setup
        await self.context.initialize_mcp_servers()

    async def on_unmount(self) -> None:
        self.context.set_tool_confirmation_handler(None)
        self._resolve_pending_confirmation(
            ToolConfirmationDecision(
                approved=False,
                reason="Terminal closed before confirmation",
            )
        )
        await self.context.disconnect_all_mcp_servers()

    async def _update_context_display(self) -> None:
        """Update the context usage display in the footer."""
        try:
            # Ensure context size is initialized (delegated to ChatContext)
            await self.context.ensure_context_size()

            # Update the display
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
        if not text:
            return

        # Reset Ctrl+C counter on normal input
        self._ctrl_c_count = 0

        composer = self.query_one(ComposerTextArea)

        if self._pending_tool_confirmation is not None:
            composer.load_text("")
            self._sync_composer_height()
            await self._handle_confirmation_input(text)
            return

        composer.add_history(text)

        # Check for meta commands (starting with /)
        if text.startswith("/"):
            handled = await self._handle_meta_command(text)
            if handled:
                composer = self.query_one(ComposerTextArea)
                composer.load_text("")
                self._sync_composer_height()
                return

        # If LLM is thinking, queue the message and show feedback
        if self._is_processing:
            self.context.pending_messages.append(text)
            composer.load_text("")
            self._sync_composer_height()
            # Update the pending messages display
            pending_display = self.query_one("#pending-messages", PendingMessagesDisplay)
            pending_display.update_messages(self.context.pending_messages)
            return

        logger.debug(f"User input submitted: {text[:80]!r}")
        composer = self.query_one(ComposerTextArea)
        composer.load_text("")
        self._sync_composer_height()
        self.run_worker(self._submit_text(text), thread=False, exclusive=True)

    async def _handle_meta_command(self, text: str) -> bool:
        """Handle meta commands starting with /.

        Returns True if command was handled.
        """
        # Parse command and arguments
        parts = text.split(maxsplit=1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Look up command in registry
        command = self.context.command_registry.get(cmd_name)
        if command:
            # Execute handler
            result = command.handler(self.context, args)
            if result is not None and hasattr(result, "__await__"):
                await result
            return True

        # Unknown command
        await self.logger.error(f"Unknown command: {cmd_name}, use /help for available commands")
        return True

    async def _submit_text(self, text: str) -> None:
        """Submit user text to the context."""
        self._is_processing = True
        composer = self.query_one(ComposerTextArea)
        try:
            await self.context.send(text)

            # After processing, check if there are pending messages
            # Use a loop to handle messages that arrive during processing
            while self.context.pending_messages:
                pending = list(self.context.pending_messages)
                self.context.pending_messages.clear()
                # Update pending messages display (clear if empty)
                pending_display = self.query_one("#pending-messages", PendingMessagesDisplay)
                pending_display.update_messages(self.context.pending_messages)
                await self.logger.info(f"Sending {len(pending)} pending messages...")
                await self.context.send(pending)
        except Exception as exc:
            logger.debug(f"Session exception: {exc}")
            await self.logger.error(f"Session failed: {exc}")
        finally:
            self._is_processing = False
            # Clear pending messages display when done
            pending_display = self.query_one("#pending-messages", PendingMessagesDisplay)
            pending_display.update_messages([])
            self._sync_composer_height()
            composer.focus()

    async def _handle_context_event(self, event: BaseEvent) -> None:
        match event:
            case SessionMessageEvent(message=message):
                if message.role == "assistant":
                    await self._clear_stream_previews()
                await self._mount_message(message)
                # Update context display after each message
                await self._update_context_display()
            case SessionStatusEvent(level=level, detail=detail):
                logger.debug(f"Status event received: level={level.name}, detail={detail}")
                if level >= StatusLevel.ERROR:
                    await self._mount_status(f"{detail}", variant="error")
                elif level == StatusLevel.SUCCESS:
                    await self._mount_status(f"{detail}", variant="success")
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
                await self._update_context_display()  # Reset context display
                self.call_after_refresh(self._focus_composer)
            case SessionLoadedEvent():
                messages_view = self.query_one("#messages", VerticalScroll)
                await messages_view.remove_children()
                self._stream_previews.clear()
                # Re-mount all loaded messages
                for message in self.context.display_messages:
                    await self._mount_message(message)
                logger.debug("Session loaded")
                await self._update_context_display()
                self.call_after_refresh(self._focus_composer)
            case _:
                pass

    async def _handle_stream_event(self, session_event: SessionStreamDeltaEvent | SessionStreamCompletedEvent) -> None:
        if not isinstance(session_event, SessionStreamDeltaEvent):
            return

        # Get the actual message stream event from the session event wrapper
        stream_event = session_event.stream_event
        if not isinstance(stream_event, MessageStreamDeltaEvent):
            return

        match stream_event.segment:
            case TextDetailSegment(text=text):
                # Use unified preview for text - find or create one for this message index
                message_index = stream_event.segment.index
                preview_key = ("unified", message_index)
                unified_row: UnifiedStreamPreviewRow | None = None
                existing = self._stream_previews.get(preview_key)
                if existing is None:
                    # Create new unified preview row
                    new_row = UnifiedStreamPreviewRow(message_index=message_index)
                    self._stream_previews[preview_key] = new_row
                    messages_view = self.query_one("#messages", VerticalScroll)
                    await messages_view.mount(new_row)
                    unified_row = new_row
                elif isinstance(existing, UnifiedStreamPreviewRow):
                    unified_row = existing
                if unified_row is not None:
                    await unified_row.append_text(text)
                self.query_one("#messages", VerticalScroll).scroll_end(animate=False)

            case ThinkDetailSegment(thought_process=thought_process):
                # Use unified preview for thinking - find or create one for this message index
                message_index = stream_event.segment.index
                preview_key = ("unified", message_index)
                unified_row: UnifiedStreamPreviewRow | None = None
                existing = self._stream_previews.get(preview_key)
                if existing is None:
                    # Create new unified preview row
                    new_row = UnifiedStreamPreviewRow(message_index=message_index)
                    self._stream_previews[preview_key] = new_row
                    messages_view = self.query_one("#messages", VerticalScroll)
                    await messages_view.mount(new_row)
                    unified_row = new_row
                elif isinstance(existing, UnifiedStreamPreviewRow):
                    unified_row = existing
                if unified_row is not None:
                    await unified_row.append_thinking(thought_process)
                self.query_one("#messages", VerticalScroll).scroll_end(animate=False)

            case ToolCallDetailSegment(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                partial_arguments=partial_arguments,
            ):
                preview_key = ("tool", tool_call_id)
                # Only show tool name prefix on first chunk to avoid repetition
                is_first_chunk = preview_key not in self._stream_previews
                if is_first_chunk:
                    # Limit to 1 line for cleaner display in streaming mode
                    formatted_args = _format_arguments(partial_arguments, max_lines=1) if partial_arguments else ""
                    preview_text = (
                        f"调用工具 · {tool_name} · {formatted_args}" if formatted_args else f"调用工具 · {tool_name}"
                    )
                else:
                    preview_text = partial_arguments
                # logger.debug(f"[_handle_stream_event] tool={tool_name}, first_chunk={is_first_chunk}")

                tool_row: ToolPreviewRow | None = None
                existing = self._stream_previews.get(preview_key)
                if existing is None:
                    # Create new tool preview row
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

    async def _mount_message(self, message: Message) -> None:
        # logger.debug(f"[_mount_message] START role={message.role}, segments={len(message.content)}")
        messages_view = self.query_one("#messages", VerticalScroll)
        row = MessageRow(message)
        # logger.debug(f"[_mount_message] mounting MessageRow to messages_view")
        await messages_view.mount(row)
        # logger.debug(f"[_mount_message] MessageRow mounted, children count={len(row.children)}")
        # Force refresh to ensure all children are properly displayed
        row.refresh(layout=True)
        # Also refresh the MessageWidget inside
        refresh_count = 0
        for child in row.children:
            if hasattr(child, "refresh"):
                child.refresh(layout=True)
                refresh_count += 1
                pass  # skip logging
                # Refresh all grandchildren too
                for grandchild in child.children:
                    if hasattr(grandchild, "refresh"):
                        grandchild.refresh(layout=True)
                        refresh_count += 1
                        pass  # skip logging
        messages_view.scroll_end(animate=False)
        # logger.debug(f"[_mount_message] DONE, total refreshed={refresh_count}")

    async def _mount_status(self, text: str, *, variant: str = "status") -> None:
        messages_view = self.query_one("#messages", VerticalScroll)
        await messages_view.mount(StatusWidget(text, variant=variant))
        messages_view.scroll_end(animate=False)

    async def _clear_stream_previews(self) -> None:
        # logger.debug(f"[_clear_stream_previews] START, count={len(self._stream_previews)}")
        for key, row in list(self._stream_previews.items()):
            pass  # skip logging
            await row.close()
            await row.remove()
            pass  # skip logging
        self._stream_previews.clear()
        # logger.debug(f"[_clear_stream_previews] DONE")

    async def action_toggle_thinking(self) -> None:
        # Check if provider supports thinking
        if not self.context.provider.thinking_supported:
            await self.logger.error("Current model does not support Thinking mode")
            return
        self.context.thinking_mode = not self.context.thinking_mode
        mode = "enabled" if self.context.thinking_mode else "disabled"
        await self.logger.info(f"Thinking {mode}")

    async def action_clear_session(self) -> None:
        await self.context.reset()

    async def action_interrupt(self) -> None:
        """Interrupt the current LLM output stream."""
        if self._is_processing:
            self.context.interrupt()
            await self.logger.error("Interrupted by user")

            self._ctrl_c_count = 0
        else:
            # Not processing, user might be trying to quit
            self._ctrl_c_count += 1
            if self._ctrl_c_count >= 2:
                await self.logger.info("Hint: Use Ctrl+D to exit")
                self._ctrl_c_count = 0

    async def action_quit(self) -> None:
        # Print session UUID before exiting so user can resume later
        print(f"\n[Session UUID: {self.context.session_id}]")
        self.exit()

    def on_mouse_scroll_up(self, event) -> None:
        self._forward_scroll_to_history(event, step=-3)

    def on_mouse_scroll_down(self, event) -> None:
        self._forward_scroll_to_history(event, step=3)

    def _focus_composer(self) -> None:
        composer = self.query_one(ComposerTextArea)
        composer.focus()

    def _sync_composer_height(self) -> None:
        composer = self.query_one(ComposerTextArea)
        visible_lines = max(3, min(composer.wrapped_document.height, 8))
        target_height = visible_lines + 7
        # Respect CSS fractional height: only adjust if dynamic height would exceed bounds
        css_height = composer.styles.height
        if css_height is not None and not str(css_height).endswith("fr"):
            composer.styles.height = target_height

    def _forward_scroll_to_history(
        self,
        event,
        *,
        step: int,
    ) -> None:
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
        if self._pending_tool_confirmation is not None:
            return ToolConfirmationDecision(
                approved=False,
                reason="Another confirmation is already in progress",
            )

        self._pending_tool_confirmation = Future()
        self._pending_tool_name = tool.name

        arguments = _format_arguments(tool_call.function.arguments)

        # Show approval dialog in container
        container = self.query_one("#approval-container", Vertical)
        dialog = ApprovalDialog(tool.name, arguments)
        await container.mount(dialog)
        dialog.focus()

        # Cache current composer text and set placeholder
        composer = self.query_one("#composer", ComposerTextArea)
        self._composer_stashed_text = composer.text
        composer.load_text("")
        composer.placeholder = "直接输入拒绝原因，Enter 发送……"

        return await self._pending_tool_confirmation

    async def _handle_confirmation_input(self, text: str) -> None:
        normalized = text.strip()
        lowered = normalized.lower()
        tool_name = self._pending_tool_name or "unknown"

        # [1] yes - approve once
        if lowered in {"yes", "y", "1", "同意"}:
            self._resolve_pending_confirmation(ToolConfirmationDecision(approved=True))
            await self.logger.info(f"Tool call approved: {tool_name}")
            return

        # [2] yes for this session - approve for entire session
        if lowered in {"yes for this session", "session", "s", "2", "本次会话"}:
            self._resolve_pending_confirmation(ToolConfirmationDecision(approved=True, session_approved=True))
            await self.logger.info("All tool calls approved for this session")
            return

        # [3] no - reject without reason
        if lowered in {"no", "n", "3", "拒绝"}:
            self._resolve_pending_confirmation(ToolConfirmationDecision(approved=False))
            await self.logger.info(f"Tool call rejected: {tool_name}")
            return

        # Any other text - reject with clarification (reason is the text itself)
        if normalized:
            self._resolve_pending_confirmation(
                ToolConfirmationDecision(
                    approved=False,
                    reason=normalized,
                    next_steps="请根据用户反馈调整",
                )
            )
            await self.logger.info(f"Tool call rejected: {tool_name}, reason: {normalized}")
            return

        await self.logger.error(
            "无效选项，请使用 Y/S/N 或直接输入拒绝原因。",
        )

    def _resolve_pending_confirmation(self, decision: ToolConfirmationDecision) -> None:
        pending = self._pending_tool_confirmation
        self._pending_tool_confirmation = None
        self._pending_tool_name = None

        # Remove approval dialog and restore placeholder
        try:
            container = self.query_one("#approval-container", Vertical)
            for child in list(container.children):
                child.remove()
        except Exception:
            pass

        try:
            composer = self.query_one("#composer", ComposerTextArea)
            composer.placeholder = "输入消息，Enter 发送，Ctrl+Enter 换行……"
            # Restore stashed text if any
            if self._composer_stashed_text:
                composer.load_text(self._composer_stashed_text)
                self._composer_stashed_text = ""
                self._sync_composer_height()
            # Focus back to composer
            composer.focus()
        except Exception:
            pass

        if pending is None or pending.done():
            return
        pending.set_result(decision)

    def _parse_rejection_clarification(self, text: str) -> tuple[str, str] | None:
        parts = [part.strip() for part in text.split(";", maxsplit=1)]
        if len(parts) != 2:
            return None

        reason, next_steps = parts
        if not reason or not next_steps:
            return None
        return reason, next_steps


def run_terminal(context: ChatContext) -> None:
    ChatTerminalApp(context).run()
