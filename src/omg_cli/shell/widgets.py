from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol, cast

if TYPE_CHECKING:
    from .app import ChatTerminalApp


from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message as TextualMessage
from textual.visual import VisualType
from textual.widget import Widget
from textual.widgets import Footer, ListItem, ListView, Markdown, Static, TextArea

from src.omg_cli.types.message import (
    Message,
    TextSegment,
    ThinkSegment,
    ToolResultSegment,
    ToolSegment,
)

from .file_completion import FileCompletionMixin
from .utils import _build_message_title, _build_thinking_preview, _format_arguments

type StreamPreviewType = Literal["tool", "thinking", " text"]


class PreviewRow(Protocol):
    """Protocol for stream preview rows."""

    async def close(self) -> None: ...

    def remove(self) -> Any: ...


class ToolPreviewRowProtocol(PreviewRow, Protocol):
    """Protocol for tool call preview rows."""

    async def append(self, text: str) -> None: ...


class UnifiedPreviewRow(PreviewRow, Protocol):
    """Protocol for unified preview rows."""

    async def append_thinking(self, text: str) -> None: ...

    async def append_text(self, text: str) -> None: ...


class SafeStatic(Static):
    """Static widget that disables rich markup parsing to avoid errors with special characters."""

    def __init__(self, content: str = "", **kwargs) -> None:
        super().__init__(content, **kwargs)
        self.data_model: Any = None  # Store arbitrary data

    def render(self) -> Text:
        """Return content as Rich Text with markup disabled."""
        content = self._Static__content
        if content is None:
            return Text("")
        # Return plain Text to avoid Rich markup parsing errors
        return Text(str(content))

    def update(self, content: VisualType = "", *, layout: bool = True) -> None:
        self._Static__content = content
        self.refresh(layout=layout)


class CollapsibleWidget(SafeStatic):
    """Base class for collapsible content widgets (thinking, tool results, etc.)."""

    can_focus = True
    can_focus_children = False

    BINDINGS: ClassVar[list[BindingType]] = [
        ("enter", "toggle", "展开/折叠"),
        ("space", "toggle", "展开/折叠"),
    ]

    def __init__(self, title_collapsed: str, title_expanded: str, content: str, **kwargs) -> None:
        super().__init__(title_collapsed, **kwargs)
        self.title_collapsed = title_collapsed
        self.title_expanded = title_expanded
        self._content = content
        self.collapsed = True
        self.mouse_enabled = True

    def on_mount(self) -> None:
        self._refresh()

    async def on_click(self) -> None:
        await self.action_toggle()

    async def action_toggle(self, attribute_name: str | None = None) -> None:
        self.collapsed = not self.collapsed
        self._refresh()

    def _refresh(self) -> None:
        if self.collapsed:
            self.update(self.title_collapsed)
        else:
            self.update(f"{self.title_expanded}\n{self._content}")


class StatusWidget(SafeStatic):
    """Simple status message widget."""

    def __init__(self, text: str, *, variant: str = "status") -> None:
        super().__init__(text, classes=f"status status--{variant}")


class ContextStatusWidget(Static):
    """Widget to display context usage in the footer."""

    def __init__(self) -> None:
        super().__init__("", classes="context-status")
        self.update_display(0, 100000)

    def update_display(self, context_tokens: int, max_context_size: int) -> None:
        """Update the context usage display."""
        if max_context_size <= 0:
            self.update("context: --")
            return

        usage_pct = (context_tokens / max_context_size) * 100
        context_k = context_tokens / 1000
        max_k = max_context_size / 1000

        self.update(f"context: {usage_pct:.1f}%({context_k:.1f}k/{max_k:.1f}k)")


class ContextFooter(Footer):
    """Custom footer with context usage display on the right."""

    # CSS styles are defined in styles.py

    def __init__(
        self,
        *children: Widget,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        show_command_palette: bool = True,
        compact: bool = False,
    ) -> None:
        super().__init__(
            *children,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
            show_command_palette=show_command_palette,
            compact=compact,
        )
        self._context_widget: ContextStatusWidget | None = None

    def compose(self) -> ComposeResult:
        """Compose the footer with context status."""
        with Horizontal(classes="footer-content"):
            yield from super().compose()
        self._context_widget = ContextStatusWidget()
        yield self._context_widget

    def update_context_display(self, context_tokens: int, max_context_size: int) -> None:
        """Update the context usage display."""
        if self._context_widget is not None:
            self._context_widget.update_display(context_tokens, max_context_size)


class CommandPalette(ListView, FileCompletionMixin):
    """Command palette for meta commands (shows when typing /) and directory completion (shows when typing !)."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("escape", "dismiss", "Dismiss"),
        ("tab", "select", "Select"),
        ("enter", "select", "Select"),
    ]

    def __init__(self) -> None:
        super().__init__(classes="command-palette", id="command-palette")
        self.visible = False
        self.commands: list = []
        self.completing_dirs: bool = False  # True when completing directories (starts with !)

    def _get_app(self) -> "ChatTerminalApp":
        from .app import ChatTerminalApp

        return cast(ChatTerminalApp, self.app)

    def _get_registry(self):
        """Get command registry from app context."""
        return self._get_app().context.command_registry

    async def show_commands(self, text: str = "") -> None:
        """Show command palette filtered by text.

        Supports both command matching and argument completion.
        Examples:
            "/" -> show all commands
            "/sw" -> show matching commands (switch, etc.)
            "/switch " -> show argument completions for switch
            "/switch mo" -> show filtered argument completions
        """
        await self.clear()
        self.commands = []
        self.completing_dirs = False

        try:
            registry = self._get_registry()

            # Check if we're completing arguments (contains space after command)
            # Use split(" ", 1) instead of split(maxsplit=1) to preserve trailing space
            parts = text.split(" ", 1)
            if len(parts) >= 2 or (len(parts) == 1 and text.endswith(" ")):
                # We're completing arguments: text = "/switch mo" or "/switch "
                cmd_name = parts[0]  # "/switch"
                arg_prefix = parts[1] if len(parts) >= 2 else ""  # "mo" or ""

                cmd = registry.get(cmd_name)
                if cmd and cmd.completer:
                    # Use command's completer
                    ctx = self._get_app().context
                    completions = cmd.completer(ctx, arg_prefix)

                    for completion in completions:
                        self.commands.append(completion)
                        await self.append(ListItem(Static(completion), classes="command-item"))

                    if completions:
                        self.visible = True
                        self.add_class("visible")
                    else:
                        self.visible = False
                        self.remove_class("visible")
                    return

            # Regular command matching
            matching = registry.find_matches(text)

            for cmd in matching:
                self.commands.append(cmd)
                display = f"{cmd.full_name} - {cmd.description_zh}"
                await self.append(ListItem(Static(display), classes="command-item"))

            if self.commands:
                self.visible = True
                self.add_class("visible")
            else:
                self.visible = False
                self.remove_class("visible")
        except Exception:
            self.visible = False

    def _format_path_display(self, path: str, max_width: int) -> str:
        """Format path for display with smart truncation.

        Args:
            path: The path to display
            max_width: Maximum width available

        Returns:
            Formatted string with prefix and truncation if needed
        """
        is_dir = path.endswith("/")
        display_path = path.rstrip("/")

        # Try with full prefix
        prefix = "📁 " if is_dir else "📄 "
        full_display = f"{prefix}{display_path}{'/' if is_dir else ''}"

        if len(full_display) <= max_width:
            return full_display

        # Remove prefix if too long
        no_prefix = f"{display_path}{'/' if is_dir else ''}"
        if len(no_prefix) <= max_width:
            return no_prefix

        # Truncate with .. in the middle
        # Keep some chars from start and end
        suffix_len = min(10, max_width // 3)  # Keep up to 10 chars at end
        prefix_len = max_width - suffix_len - 3  # 3 for "..."

        if prefix_len < 5:  # Not enough space, just truncate end
            return no_prefix[: max_width - 3] + "..."

        return no_prefix[:prefix_len] + "..." + no_prefix[-suffix_len:]

    async def show_directory_completions(self, word: str = "") -> None:
        """Show directory completions for paths starting with !.

        Args:
            word: The full word starting with ! (e.g., "!src/omg")
        """
        await self.clear()
        self.commands = []
        self.completing_dirs = True

        try:
            # Use FileCompletionProtocol to get completions
            results = await self.get_directory_completions(
                word,
                max_results=50,
                include_files=True,
                include_hidden=False,
            )

            # Calculate dynamic width based on longest path
            max_path_len = max((len(p.rstrip("/")) + 1 for p in results), default=0)
            # Account for prefix "📁 " (3 chars) or "📄 " (3 chars)
            dynamic_width = max_path_len + 3

            for path in results:
                self.commands.append(path)
                # Format display with smart truncation
                display = self._format_path_display(path, dynamic_width)
                await self.append(ListItem(Static(display), classes="command-item"))

            if self.commands:
                self.visible = True
                self.add_class("visible")
                # Auto-focus first item for ! mode
                self.index = 0
            else:
                self.visible = False
                self.remove_class("visible")
        except Exception:
            self.visible = False
            self.completing_dirs = False

    def dismiss(self) -> None:
        """Hide the command palette."""
        self.visible = False
        self.remove_class("visible")
        # Reset width to default
        try:
            composer = self._get_app().query_one("#composer", ComposerTextArea)
            composer.focus()
        except Exception:
            pass

    def action_dismiss(self) -> None:
        self.dismiss()

    def action_select(self) -> None:
        """Select the highlighted item (command, argument completion, or directory)."""
        if self.highlighted_child is None:
            return

        index = self.index
        if index is None or not (0 <= index < len(self.commands)):
            return

        selected = self.commands[index]
        was_completing_dirs = self.completing_dirs
        self.dismiss()
        self.completing_dirs = False

        try:
            composer = self._get_app().query_one("#composer", ComposerTextArea)

            # Handle directory completion
            if was_completing_dirs:
                # selected is a path string
                path = selected.rstrip("/")  # Remove trailing slash for cleaner display
                # Hide palette after selecting a file; allow deeper navigation for directories.
                composer._suppress_completion_on_change = not selected.endswith("/")
                # Replace the !prefix with !selected in the text
                current_text = composer.text
                cursor_row, cursor_col = composer.cursor_location

                # Find the ! at the start of current word
                line_start = current_text.rfind("\n", 0, cursor_col) + 1
                line = current_text[line_start:cursor_col]

                # Find where ! starts
                bang_pos = line.find("!")
                if bang_pos >= 0:
                    # Replace from ! to cursor with !selected
                    before_bang = current_text[: line_start + bang_pos]
                    after_cursor = current_text[cursor_col:]
                    composer.text = before_bang + "!" + path + after_cursor
                    composer.cursor_location = (cursor_row, len(before_bang) + 1 + len(path))
                else:
                    # Fallback: just insert
                    composer.text = "!" + path
                    composer.cursor_location = (cursor_row, len("!" + path))
                composer.focus()
                return

            # Check if it's a command or a string completion
            from src.omg_cli.types.command import MetaCommand

            if isinstance(selected, MetaCommand):
                # Selected a command
                composer.text = selected.full_name + " "
            else:
                # Selected an argument completion (string)
                # Get current text to preserve the command name
                current_text = composer.text
                parts = current_text.split(maxsplit=1)
                if len(parts) >= 1:
                    cmd_name = parts[0]
                    composer.text = f"{cmd_name} {selected}"
                else:
                    composer.text = selected

            composer.cursor_location = (0, len(composer.text))
            composer.focus()
        except Exception:
            pass

    def on_list_view_selected(self, _event: ListView.Selected) -> None:
        """Handle selection via mouse/enter."""
        self.action_select()


class ComposerTextArea(TextArea):
    """Multi-line input with autocomplete integration."""

    can_focus = True

    @dataclass
    class Submitted(TextualMessage):
        text_area: "ComposerTextArea"
        value: str

        @property
        def control(self) -> "ComposerTextArea":
            return self.text_area

    def __init__(self, *, placeholder: str = "") -> None:
        super().__init__(
            soft_wrap=True,
            show_line_numbers=False,
            tab_behavior="focus",
            highlight_cursor_line=False,
            placeholder=placeholder,
            id="composer",
        )
        self._suppress_completion_on_change = False
        from src.omg_cli.config import InputHistory

        self._history = InputHistory()
        self._history_index: int = -1
        self._draft_text: str = ""

    def add_history(self, text: str) -> None:
        """Add a submitted text to the input history."""
        self._history.add(text)
        self._history_index = -1
        self._draft_text = ""

    def _get_current_word(self) -> str:
        """Get the current word being typed at cursor position.

        For command completion, returns the full command prefix including
        the command name and any arguments typed so far.
        """
        text = self.text
        cursor_pos = self.cursor_location[1]

        # Find the start of the current word
        start = cursor_pos
        while start > 0 and text[start - 1] not in (" ", "\n"):
            start -= 1

        # Check if we're typing arguments for a command (e.g., "/switch model")
        # If current word is empty or we started after a space, check if there's a command before
        if start > 0 and text[start - 1] == " ":
            # Look backwards to find the command start (starts with /)
            cmd_start = start - 1
            while cmd_start > 0 and text[cmd_start - 1] not in (" ", "\n"):
                cmd_start -= 1
            # Check if what we found is a command (starts with /)
            if cmd_start < start - 1 and text[cmd_start] == "/":
                # Include the command and the space
                start = cmd_start

        return text[start:cursor_pos]

    def _get_palette(self) -> CommandPalette | None:
        """Get command palette if available."""
        try:
            from .app import ChatTerminalApp

            app = cast(ChatTerminalApp, self.app)
            return cast(CommandPalette, app.query_one("#command-palette", CommandPalette))
        except Exception:
            return None

    def _get_registry(self):
        """Get command registry from app context."""
        from .app import ChatTerminalApp

        app = cast(ChatTerminalApp, self.app)
        return app.context.command_registry

    async def _on_key(self, event: events.Key) -> None:
        """Handle key events."""
        palette = self._get_palette()
        current_word = self._get_current_word()

        # Handle palette navigation when it's visible
        if palette and palette.visible:
            if event.key in ("up", "down", "tab"):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    palette.action_cursor_up()
                elif event.key == "down":
                    palette.action_cursor_down()
                elif event.key == "tab":
                    palette.action_select()
                return

        # Handle history navigation with up/down when palette is not visible
        if not (palette and palette.visible):
            cursor_row, _cursor_col = self.cursor_location
            if event.key == "up" and cursor_row == 0 and self._history.entries:
                event.stop()
                event.prevent_default()
                if self._history_index == -1:
                    self._draft_text = self.text
                entries = self._history.entries
                if self._history_index < len(entries) - 1:
                    self._history_index += 1
                    self.load_text(entries[-(self._history_index + 1)])
                    last_row = len(self.document.lines) - 1
                    self.cursor_location = (last_row, len(self.document.lines[last_row]))
                return
            if event.key == "down" and self._history_index != -1:
                last_row = len(self.document.lines) - 1
                if cursor_row == last_row:
                    event.stop()
                    event.prevent_default()
                    self._history_index -= 1
                    if self._history_index == -1:
                        self.load_text(self._draft_text)
                    else:
                        entries = self._history.entries
                        self.load_text(entries[-(self._history_index + 1)])
                    last_row = len(self.document.lines) - 1
                    self.cursor_location = (last_row, len(self.document.lines[last_row]))
                    return

        # Handle tab completion when palette is not visible
        if event.key == "tab":
            # Check if current word is a command that has a completer
            if palette and current_word.startswith("/") and not current_word.endswith(" "):
                registry = self._get_registry()
                cmd = registry.get(current_word)
                if cmd and cmd.completer:
                    # Insert a space to trigger argument completion
                    event.stop()
                    event.prevent_default()
                    cursor_row, cursor_col = self.cursor_location
                    self.text = self.text[:cursor_col] + " " + self.text[cursor_col:]
                    self.cursor_location = (cursor_row, cursor_col + 1)
                    # Trigger show_commands with trailing space to show all completions
                    await palette.show_commands(current_word + " ")
                    return
            # Check if current word is a directory completion trigger
            if palette and current_word.startswith("!") and not palette.visible:
                event.stop()
                event.prevent_default()
                dir_prefix = current_word[1:]  # Remove the leading !
                await palette.show_directory_completions(dir_prefix)
                return

        # Handle submit
        if event.key == "enter":
            if palette and palette.visible:
                event.stop()
                event.prevent_default()
                palette.action_select()
                return
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self, self.text))
            return

        # Handle newline
        if event.key == "ctrl+enter":
            event.stop()
            event.prevent_default()
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            return

        # Handle escape to dismiss palette
        if event.key == "escape":
            if palette and palette.visible:
                event.stop()
                event.prevent_default()
                palette.dismiss()
                return

        # Handle ctrl+d to quit (when text is empty)
        if event.key == "ctrl+d":
            if not self.text:
                event.stop()
                event.prevent_default()
                self.app.exit()
                return
            # When text is not empty, let parent handle it (delete character)

        # Call parent for normal input
        await super()._on_key(event)

        # Sync composer height
        try:
            from .app import ChatTerminalApp

            app = cast(ChatTerminalApp, self.app)
            app._sync_composer_height()
        except Exception:
            pass

    @on(TextArea.Changed)
    def handle_text_changed(self, event: TextArea.Changed) -> None:
        """Handle text changes and update command palette visibility."""
        if self._suppress_completion_on_change:
            self._suppress_completion_on_change = False
            return
        try:
            from .app import ChatTerminalApp

            word = self._get_current_word()
            app = cast(ChatTerminalApp, self.app)
            pal = app.query_one("#command-palette", CommandPalette)
            if word.startswith("/"):
                app.run_worker(pal.show_commands(word))
            elif word.startswith("!"):
                # Directory completion
                app.run_worker(pal.show_directory_completions(word))
            elif pal.visible:
                pal.dismiss()
        except Exception:
            pass


# =============================================================================
# Message Components
# =============================================================================


class PlainTextBlock(Static):
    """Plain text block with proper wrapping."""

    def __init__(self, text: str) -> None:
        super().__init__(text, classes="message__text")
        self.text_content = text

    def render(self) -> Any:
        from rich.text import Text

        return Text(self.text_content, overflow="fold")


class MarkdownBlock(Markdown):
    """Markdown block for assistant messages."""

    def __init__(self, text: str) -> None:
        super().__init__(text, classes="message__text", open_links=False)


class MessageWidget(Vertical):
    """Widget displaying a single message."""

    def __init__(self, message: Message) -> None:
        super().__init__(classes=f"message message--{message.role}")
        self.message = message

    def compose(self):
        title = _build_message_title(self.message)

        yield SafeStatic(title, classes="message__title")

        for segment in self.message.content:
            match segment:
                case TextSegment(text=text):
                    if self.message.role == "user":
                        yield PlainTextBlock(text)
                    else:
                        yield MarkdownBlock(text)
                case ThinkSegment(thought_process=thought_process):
                    yield ThinkingWidget(thought_process)
                case ToolResultSegment(tool_name=tool_name, is_error=is_error) as tool_result:
                    if is_error:
                        yield ToolResultWidget(tool_name, str(tool_result))
                case ToolSegment(tool_name=tool_name, arguments=arguments):
                    tool_summary = f"调用工具 · {tool_name}"
                    if arguments:
                        # Show 3-4 lines for completed (non-streaming) tool calls
                        formatted_args = _format_arguments(arguments, max_lines=5)
                        if formatted_args:
                            tool_summary = f"{tool_summary}\n{formatted_args}"
                    yield SafeStatic(tool_summary, classes="message__tool")


class MessageRow(Horizontal):
    """Horizontal container for a message."""

    def __init__(self, message: Message) -> None:
        super().__init__(classes=f"message-row message-row--{message.role}")
        self.message = message

    def compose(self):
        # 不渲染 tool 角色的消息
        if self.message.role == "tool":
            return
        yield MessageWidget(self.message)


class ThinkingWidget(CollapsibleWidget):
    """Collapsible widget for thinking content."""

    def __init__(self, thought_process: str) -> None:
        preview = _build_thinking_preview(thought_process, limit=18)
        super().__init__(
            title_collapsed=f"> 思考 · {preview}",
            title_expanded=f"> 思考 · {preview}\n────────────────────",
            content=thought_process.strip(),
            classes="message__thinking",
        )


class ToolResultWidget(CollapsibleWidget):
    """Collapsible widget for tool results."""

    def __init__(self, tool_name: str, result: str) -> None:
        super().__init__(
            title_collapsed=f"📦 {tool_name}",
            title_expanded=f"📦 {tool_name}",
            content=result,
            classes="message__tool-result",
        )


# =============================================================================
# Stream Preview Components
# =============================================================================


class ToolPreviewRow(Horizontal):
    """Stream preview for tool calls - shows last 15 chars of latest content."""

    PREVIEW_MAX_LEN: int = 60

    STARS: ClassVar[list[str]] = [
        "⭐",
        "💫",
    ]

    def __init__(self) -> None:
        super().__init__(classes="stream-row")
        self.buffer = ""
        self.last_star_index = 0

    def compose(self):
        yield SafeStatic("", classes="stream-preview stream-preview--tool")

    async def append(self, text: str) -> None:
        """Update preview with last N chars of latest content."""
        if not text:
            return
        widget = self.query_one(SafeStatic)

        self.buffer += text
        preview_text = self.buffer[-self.PREVIEW_MAX_LEN :]
        widget.update(f"{self.STARS[self.last_star_index]} {preview_text}")

        self.last_star_index = (self.last_star_index + 1) % len(self.STARS)

    async def close(self) -> None:
        """Close the preview (no-op for tool preview)."""
        pass


class UnifiedStreamPreviewRow(Horizontal):
    """Stream preview that combines thinking and text."""

    def __init__(self, message_index: int) -> None:
        super().__init__(classes="stream-row")
        self.message_index = message_index
        self.thinking_content = ""
        self.text_content = ""
        self.has_text_started = False
        self._container: SafeStatic | None = None

    def compose(self):
        yield SafeStatic(
            "", classes="stream-preview stream-preview--unified", id=f"unified-preview-{self.message_index}"
        )

    def on_mount(self) -> None:
        self._container = self.query_one(SafeStatic)
        self._refresh()

    async def append_thinking(self, text: str) -> None:
        self.thinking_content += text
        self._refresh()

    async def append_text(self, text: str) -> None:
        if not self.has_text_started and text:
            self.has_text_started = True
        self.text_content += text
        self._refresh()

    def _refresh(self) -> None:
        if self._container is None:
            return

        lines = []

        if self.thinking_content:
            preview = _build_thinking_preview(self.thinking_content, limit=18)
            lines.append(f"> 思考 · {preview}")
            if not self.has_text_started:
                lines.append("────────────────────")
                lines.append(self.thinking_content.strip())

        if self.has_text_started and self.text_content:
            if self.thinking_content:
                lines.append("")
            lines.append(self.text_content)

        self._container.update("\n".join(lines))

    async def close(self) -> None:
        pass


# =============================================================================
# Layout Components
# =============================================================================


class MessageHistoryView(VerticalScroll):
    """Scrollable message history."""

    def scroll_for_wheel(self, step: int) -> bool:
        if self.max_scroll_y <= 0:
            return False
        self.scroll_relative(y=step, animate=False)
        return True

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self.scroll_for_wheel(-3):
            event.stop()
            event.prevent_default()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self.scroll_for_wheel(3):
            event.stop()
            event.prevent_default()


# =============================================================================
# Pending Messages Queue Display
# =============================================================================


class PendingMessagesDisplay(Vertical):
    """Display pending messages in the queue while LLM is thinking."""

    def __init__(self, id: str | None = None) -> None:
        super().__init__(classes="pending-messages-display", id=id)
        self._message_widgets: list[SafeStatic] = []

    def compose(self) -> ComposeResult:
        yield SafeStatic("📋 待发送消息", classes="pending-messages-title")
        self._content_container = Vertical(classes="pending-messages-content")
        yield self._content_container

    def update_messages(self, messages: list[str]) -> None:
        """Update the displayed messages."""
        # Clear existing content
        self._content_container.remove_children()
        self._message_widgets.clear()

        if not messages:
            self.styles.display = "none"
            return

        # Show the widget
        self.styles.display = "block"

        # Add each message
        for i, msg in enumerate(messages, 1):
            # Truncate long messages for display
            display_text = msg[:100] + "…" if len(msg) > 100 else msg
            # Replace newlines with spaces for compact display
            display_text = display_text.replace("\n", " ")
            msg_widget = SafeStatic(f"  {i}. {display_text}", classes="pending-message-item")
            self._message_widgets.append(msg_widget)
            self._content_container.mount(msg_widget)


# =============================================================================
# Dialog Components
# =============================================================================


class ApprovalDialog(Vertical):
    """Tool approval dialog."""

    OPTIONS: ClassVar[list[tuple[str, str]]] = [
        ("Approve", "yes"),
        ("Approve all for this session", "yes for this session"),
        ("Skip", "no"),
    ]

    BINDINGS: ClassVar[list[BindingType]] = [
        ("up", "select_previous", "Previous option"),
        ("down", "select_next", "Next option"),
        ("enter", "confirm", "Confirm selection"),
        ("y", "select_yes", "Select Yes"),
        ("s", "select_session", "Select Session"),
        ("n", "select_no", "Select Skip"),
    ]

    def __init__(self, tool_name: str, arguments: str) -> None:
        super().__init__(classes="approval-dialog")
        self.tool_name = tool_name
        self.arguments = arguments
        self.selected_index = 0
        self.mouse_enabled = True
        self.can_focus = True

    def compose(self):
        yield SafeStatic(f"⚠ Tool approval requested: {self.tool_name}", classes="approval-title")
        yield SafeStatic(f"Arguments: {self.arguments}", classes="approval-args")
        yield SafeStatic("")
        self.option_widgets: list[SafeStatic] = []
        for i, (label, _) in enumerate(self.OPTIONS):
            option = SafeStatic(self._format_option(i, label), classes="approval-option")
            self.option_widgets.append(option)
            yield option

    def _format_option(self, index: int, label: str) -> str:
        prefix = "→ " if index == self.selected_index else "  "
        return f"{prefix}{label}"

    def _update_display(self) -> None:
        for i, widget in enumerate(self.option_widgets):
            widget.update(self._format_option(i, self.OPTIONS[i][0]))

    def _get_app(self) -> "ChatTerminalApp":
        from .app import ChatTerminalApp

        return cast(ChatTerminalApp, self.app)

    def action_select_next(self) -> None:
        if self.selected_index == len(self.OPTIONS) - 1:
            try:
                composer = self._get_app().query_one("#composer", ComposerTextArea)
                composer.focus()
            except Exception:
                pass
        else:
            self.selected_index += 1
            self._update_display()

    def action_select_previous(self) -> None:
        self.selected_index = (self.selected_index - 1) % len(self.OPTIONS)
        self._update_display()

    def action_confirm(self) -> None:
        self._confirm()

    def action_select_yes(self) -> None:
        self.selected_index = 0
        self._confirm()

    def action_select_session(self) -> None:
        self.selected_index = 1
        self._confirm()

    def action_select_no(self) -> None:
        self.selected_index = 2
        self._confirm()

    def on_click(self, event) -> None:
        for i, widget in enumerate(self.option_widgets):
            if widget == event.control:
                self.selected_index = i
                self._confirm()
                return

    def _confirm(self) -> None:
        choice = self.OPTIONS[self.selected_index][1]
        try:
            app = self._get_app()
            composer = app.query_one("#composer", ComposerTextArea)
            app.post_message(ComposerTextArea.Submitted(composer, choice))
        except Exception:
            pass
        self.remove()
