"""Chat subpage for the GUI, modeled after shell TUI logic."""

from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QKeyEvent, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    DropDownPushButton,
    PrimaryPushButton,
    RoundMenu,
    ScrollArea,
    StrongBodyLabel,
    TextBrowser,
    ToolButton,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)
from qfluentwidgets import (
    TextEdit as FluentTextEdit,
)

from omg_cli.config import get_config_manager
from omg_cli.context.chat import ChatContext
from omg_cli.context.tool_manager import ToolConfirmationDecision
from omg_cli.log import logger
from omg_cli.types.event import (
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
    TextDetailSegment,
    TextSegment,
    ThinkDetailSegment,
    ThinkSegment,
    ToolCallDetailSegment,
    ToolSegment,
)
from omg_cli.types.message import (
    MessageStreamDeltaEvent as MsgStreamDeltaEvent,
)
from omg_cli.utils import _format_arguments

if TYPE_CHECKING:
    pass


# =============================================================================
# UI Helpers
# =============================================================================


class AutoHeightTextBrowser(TextBrowser):
    """Read-only TextBrowser that auto-resizes its height."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)
        # Hide the qfluentwidgets focus underline layer
        if hasattr(self, "layer"):
            self.layer.hide()
        self.document().contentsChanged.connect(self._adjust_height)
        # Force transparent background for all states to prevent hover/focus highlight
        self.setStyleSheet(
            "TextBrowser { border: none; background: transparent; color: rgb(33, 37, 41); }\n"
            "TextBrowser:hover { background: transparent; color: rgb(33, 37, 41); }\n"
            "TextBrowser:focus { background: transparent; border: none; color: rgb(33, 37, 41); }"
        )
        self._adjust_height()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._adjust_height()

    def setMarkdownText(self, text: str) -> None:
        self.setMarkdown(text)

    def _adjust_height(self) -> None:
        doc = self.document()
        width = max(self.viewport().width(), 100)
        doc.setTextWidth(width)
        h = int(doc.size().height()) + 12
        self.setFixedHeight(max(h, 20))


class InputMethodTextEdit(FluentTextEdit):
    """Text edit with explicit IME cursor geometry support."""

    def inputMethodQuery(self, query, argument=None):
        if query == Qt.InputMethodQuery.ImEnabled:
            return True
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            # Qt expects widget-local cursor geometry for IME candidate placement.
            cursor_rect = self.cursorRect()
            return QRect(cursor_rect.topLeft(), cursor_rect.size())
        try:
            return super().inputMethodQuery(query, argument)
        except TypeError:
            return super().inputMethodQuery(query)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Shift:
            ime_enabled = self.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
            logger.info("IME keyPress Shift hasFocus={} inputMethodEnabled={}", self.hasFocus(), ime_enabled)
        super().keyPressEvent(event)


class ToolCallCard(CardWidget):
    """Card displaying a tool call."""

    def __init__(self, tool_name: str, arguments: dict | None, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMaximumWidth(16777215)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 10, 12, 10)

        title = StrongBodyLabel(f"Tool: {tool_name}", self)
        layout.addWidget(title)

        if arguments:
            args_text = _format_arguments(arguments, max_lines=5)
            if args_text:
                body = BodyLabel(args_text, self)
                body.setWordWrap(True)
                body.setTextInteractionFlags(Qt.TextSelectableByMouse)
                layout.addWidget(body)

    def _normalBackgroundColor(self):
        return QColor(0, 0, 0, 0)

    def _hoverBackgroundColor(self):
        return self._normalBackgroundColor()

    def _pressedBackgroundColor(self):
        return self._normalBackgroundColor()


class ThinkCard(CardWidget):
    """Collapsible card displaying a thinking segment."""

    def __init__(self, thought_process: str, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMaximumWidth(16777215)
        self._full_text = thought_process
        self._collapsed = True

        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(6)

        self._header = StrongBodyLabel(self)
        self._header.setCursor(Qt.PointingHandCursor)
        self._layout.addWidget(self._header)

        self._body = BodyLabel(thought_process, self)
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._layout.addWidget(self._body)

        self._refresh()

    def mousePressEvent(self, event: QEvent) -> None:
        self._collapsed = not self._collapsed
        self._refresh()
        super().mousePressEvent(event)

    def _refresh(self) -> None:
        self._header.setText("> 思考")
        self._body.setVisible(not self._collapsed)
        if self._collapsed:
            self._layout.setContentsMargins(8, 4, 8, 4)
            self._layout.setSpacing(0)
        else:
            self._layout.setContentsMargins(12, 10, 12, 10)
            self._layout.setSpacing(6)

    def _normalBackgroundColor(self):
        return QColor(0, 0, 0, 0)

    def _hoverBackgroundColor(self):
        return self._normalBackgroundColor()

    def _pressedBackgroundColor(self):
        return self._normalBackgroundColor()


# =============================================================================
# Message Bubble
# =============================================================================


class MessageBubble(CardWidget):
    """Visual representation of a single chat message."""

    def __init__(self, message: Message, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.message = message
        self.has_visible_content = False
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMaximumWidth(16777215)
        self.setObjectName("messageBubble")
        self._setup_ui()

    def _hoverBackgroundColor(self):
        return self._normalBackgroundColor()

    def _pressedBackgroundColor(self):
        return self._normalBackgroundColor()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(14, 10, 14, 10)

        title = self._title_text()
        if title:
            self.title_label = StrongBodyLabel(title, self)
            layout.addWidget(self.title_label)

        visible_count = 0
        for segment in self.message.content:
            widget = self._build_segment_widget(segment)
            if widget:
                widget.setFocusPolicy(Qt.NoFocus)
                layout.addWidget(widget)
                visible_count += 1

        self.has_visible_content = visible_count > 0

    def _title_text(self) -> str:
        match self.message.role:
            case "user":
                return ""
            case "assistant":
                return self.message.name or "AI"
            case "tool":
                return ""
            case _:
                return self.message.role.capitalize()

    def _build_segment_widget(self, segment) -> QWidget | None:
        match segment:
            case TextSegment(text=text):
                if self.message.role == "user":
                    label = BodyLabel(text, self)
                    label.setWordWrap(True)
                    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                    return label
                browser = AutoHeightTextBrowser(self)
                browser.setMarkdownText(text)
                return browser
            case ThinkSegment(thought_process=thought_process):
                return ThinkCard(thought_process, self)
            case ToolSegment(tool_name=tool_name, arguments=arguments):
                return ToolCallCard(tool_name, arguments, self)
            case _:
                # ToolResult and other segments are intentionally hidden in GUI message flow.
                pass
        return None


class ErrorMessageBubble(CardWidget):
    """Bubble displaying a detailed error message on the right side."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("errorMessageBubble")
        self.setMaximumWidth(2880)
        self.setStyleSheet(
            "CardWidget#errorMessageBubble {"
            "  background-color: rgba(255, 107, 107, 0.15);"
            "  border: 1px solid rgba(255, 107, 107, 0.5);"
            "  border-radius: 8px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(14, 10, 14, 10)

        title = StrongBodyLabel(self.tr("Error"), self)
        layout.addWidget(title)

        browser = AutoHeightTextBrowser(self)
        browser.setPlainText(text)
        browser.setStyleSheet("color: #ff6b6b; background: transparent;")
        layout.addWidget(browser)

    def _hoverBackgroundColor(self):
        return self._normalBackgroundColor()

    def _pressedBackgroundColor(self):
        return self._normalBackgroundColor()


class StreamMessageBubble(CardWidget):
    """Live-updating bubble for streaming assistant responses."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("streamMessageBubble")
        self.setMaximumWidth(2880)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(14, 10, 14, 10)

        title = StrongBodyLabel("AI", self)
        layout.addWidget(title)

        self.think_label = BodyLabel("", self)
        self.think_label.setWordWrap(True)
        self.think_label.setStyleSheet("color: gray; font-style: italic;")
        self.think_label.hide()
        layout.addWidget(self.think_label)

        self.tool_label = BodyLabel("", self)
        self.tool_label.setWordWrap(True)
        self.tool_label.setStyleSheet("color: #0078d4;")
        self.tool_label.hide()
        layout.addWidget(self.tool_label)

        self.text_edit = AutoHeightTextBrowser(self)
        layout.addWidget(self.text_edit)

        self._text_buffer = ""
        self._think_buffer = ""
        self._tool_name = ""
        self._tool_args_buffer = ""

    def append_text(self, text: str) -> None:
        self._text_buffer += text
        self.text_edit.setMarkdownText(self._text_buffer)
        if self.think_label.isVisible():
            self.think_label.hide()

    def append_thinking(self, text: str) -> None:
        self._think_buffer += text
        self.think_label.setText("> 思考")
        self.think_label.show()

    def append_tool(self, tool_name: str, args: str) -> None:
        if tool_name != self._tool_name:
            self._tool_name = tool_name
            self._tool_args_buffer = ""

        if args:
            # Support both delta chunks and cumulative snapshots.
            if args.startswith(self._tool_args_buffer):
                self._tool_args_buffer = args
            else:
                self._tool_args_buffer += args

        display = f"> Tool: {self._tool_name}"
        if self._tool_args_buffer:
            display += f"\n{self._tool_args_buffer}"
        self.tool_label.setText(display)
        self.tool_label.show()

    def _hoverBackgroundColor(self):
        return self._normalBackgroundColor()

    def _pressedBackgroundColor(self):
        return self._normalBackgroundColor()


# =============================================================================
# Approval Panel
# =============================================================================


class ApprovalPanel(CardWidget):
    """Embedded tool approval panel above the composer."""

    def __init__(
        self,
        tool_name: str,
        arguments: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.setObjectName("approvalPanel")
        self.setMaximumWidth(16777215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._result: ToolConfirmationDecision | None = None
        self._future: asyncio.Future[ToolConfirmationDecision] | None = None
        self.setStyleSheet("CardWidget#approvalPanel { background: transparent; border: none; }")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)

        self.info_card = CardWidget(self)
        self.info_card.setObjectName("approvalInfoCard")
        self.info_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.info_card.setStyleSheet(
            "CardWidget#approvalInfoCard {"
            "  background-color: rgba(69, 185, 99, 0.16);"
            "  border: 1px solid rgba(100, 220, 140, 0.45);"
            "  border-radius: 10px;"
            "}"
        )

        info_layout = QVBoxLayout(self.info_card)
        info_layout.setSpacing(6)
        info_layout.setContentsMargins(14, 12, 14, 12)

        title = StrongBodyLabel(self.tr(f"调用工具确认 · {tool_name}"), self.info_card)
        info_layout.addWidget(title)

        if arguments:
            args_label = BodyLabel(arguments, self.info_card)
            args_label.setWordWrap(True)
            args_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            info_layout.addWidget(args_label)

        self.action_card = CardWidget(self)
        self.action_card.setObjectName("approvalActionCard")
        self.action_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.action_card.setStyleSheet(
            "CardWidget#approvalActionCard {"
            "  background-color: rgba(60, 63, 68, 0.85);"
            "  border: 1px solid rgba(255, 255, 255, 0.08);"
            "  border-radius: 10px;"
            "}"
        )

        action_layout = QHBoxLayout(self.action_card)
        action_layout.setSpacing(8)
        action_layout.setContentsMargins(12, 12, 12, 12)

        self.btn_approve = ToolButton(FIF.SEND, self.action_card)

        self.btn_approve_all = ToolButton(FIF.HISTORY, self.action_card)
        self.btn_skip = ToolButton(FIF.SKIP_BACK, self.action_card)

        self._buttons = [self.btn_approve, self.btn_approve_all, self.btn_skip]
        self._selected_index = 0
        for btn in self._buttons:
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setFixedHeight(40)
            btn.setMinimumWidth(130)
            action_layout.addWidget(btn)

        action_layout.addStretch()
        layout.addWidget(self.info_card)
        layout.addWidget(self.action_card)
        self._refresh_styles()

        self.btn_approve.clicked.connect(lambda: self._resolve(ToolConfirmationDecision(approved=True)))
        self.btn_approve_all.clicked.connect(
            lambda: self._resolve(ToolConfirmationDecision(approved=True, session_approved=True))
        )
        self.btn_skip.clicked.connect(lambda: self._resolve(ToolConfirmationDecision(approved=False)))

    def select_previous(self) -> None:
        self._selected_index = (self._selected_index - 1) % len(self._buttons)
        self._refresh_styles()

    def select_next(self) -> None:
        self._selected_index = (self._selected_index + 1) % len(self._buttons)
        self._refresh_styles()

    def confirm_selection(self) -> None:
        self._buttons[self._selected_index].click()

    def _refresh_styles(self) -> None:
        for i, btn in enumerate(self._buttons):
            if i == self._selected_index:
                btn.setStyleSheet(
                    "QToolButton {"
                    "  border: 1px solid #8fe0ad;"
                    "  background-color: rgba(90, 215, 130, 0.20);"
                    "  color: white;"
                    "  border-radius: 8px;"
                    "}"
                )
            else:
                btn.setStyleSheet(
                    "QToolButton {"
                    "  border: 1px solid rgba(255, 255, 255, 0.1);"
                    "  background-color: rgba(100, 100, 100, 0.3);"
                    "  color: white;"
                    "  border-radius: 8px;"
                    "}"
                    "QToolButton:hover {"
                    "  background-color: rgba(120, 120, 120, 0.4);"
                    "}"
                    "QToolButton:pressed {"
                    "  background-color: rgba(90, 90, 90, 0.5);"
                    "}"
                )

    def _resolve(self, decision: ToolConfirmationDecision) -> None:
        self._result = decision
        if self._future is not None and not self._future.done():
            self._future.set_result(decision)
        self.hide()

    async def wait(self) -> ToolConfirmationDecision:
        self._future = asyncio.get_event_loop().create_future()
        self._result = None
        self._selected_index = 0
        self._refresh_styles()
        self.show()
        return await self._future


# =============================================================================
# Message Row (alignment wrapper)
# =============================================================================


class MessageItem(QWidget):
    """Wrapper that aligns the bubble left, right, or center depending on role."""

    BUBBLE_WIDTH_RATIO = 0.72
    USER_BUBBLE_MIN_WIDTH = 120
    BUBBLE_MAX_WIDTH = 980
    BUBBLE_MIN_WIDTH = 220

    def __init__(self, bubble: QWidget, role: str, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self._bubble = bubble
        self._role = role

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if role == "user":
            layout.addStretch(1)
            layout.addWidget(bubble, alignment=Qt.AlignTop | Qt.AlignRight)
        elif role == "status":
            layout.addStretch(1)
            layout.addWidget(bubble, alignment=Qt.AlignCenter)
            layout.addStretch(1)
        else:
            layout.addWidget(bubble, alignment=Qt.AlignTop | Qt.AlignLeft)
            layout.addStretch(1)

        # Run after layout is settled so initial width follows container size.
        QTimer.singleShot(0, self._update_bubble_width)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_bubble_width()

    def _update_bubble_width(self) -> None:
        if self._role == "status":
            return

        available = self.width()
        if available <= 0:
            return

        upper = max(available - 8, 0)
        if upper <= 0:
            return

        if self._role == "user":
            preferred_width = self._bubble.sizeHint().width()
            target = min(max(preferred_width, self.USER_BUBBLE_MIN_WIDTH), self.BUBBLE_MAX_WIDTH, upper)
        else:
            target = min(int(available * self.BUBBLE_WIDTH_RATIO), self.BUBBLE_MAX_WIDTH, upper)
            target = max(min(self.BUBBLE_MIN_WIDTH, upper), target)

        self._bubble.setFixedWidth(target)


# =============================================================================
# Chat Interface
# =============================================================================


class ChatInterface(QWidget):
    """Chat subpage with scrollable history and a bottom composer."""

    def __init__(
        self,
        context: ChatContext | None = None,
        *,
        debug: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)

        self.setObjectName("chatInterface")
        self.setStyleSheet("ChatInterface { background-color: #f5f6f8; }")
        self.context = context
        self._debug = debug
        self._is_processing = False
        self._current_stream_bubble: StreamMessageBubble | None = None
        self._pending_tasks: set = set()
        self._init_ui()
        self._bind_context()

    # -------------------------------------------------------------------------
    # UI Setup
    # -------------------------------------------------------------------------
    def _init_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(10)

        # ---- Scroll area for messages ----
        self.scroll_area = ScrollArea(self)
        self.scroll_widget = QWidget(self.scroll_area)
        self.messages_layout = QVBoxLayout(self.scroll_widget)
        self.messages_layout.setAlignment(Qt.AlignTop)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addStretch(1)

        self.scroll_area.setWidget(self.scroll_widget)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.enableTransparentBackground()
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_widget.setStyleSheet("background-color: transparent;")

        self.main_layout.addWidget(self.scroll_area, stretch=1)

        # ---- Approval panel (hidden by default) ----
        self.approval_panel: ApprovalPanel | None = None

        # ---- Composer area ----
        self.input_container = QWidget(self)
        input_layout = QHBoxLayout(self.input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(10)

        self._model_menu = RoundMenu(parent=self)

        self.text_edit = InputMethodTextEdit(self)
        self.text_edit.setPlaceholderText(self.tr("输入需求，Enter 发送，Ctrl+Enter 换行..."))
        self.text_edit.setFixedHeight(80)
        self.text_edit.setFocusPolicy(Qt.StrongFocus)
        self.text_edit.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)

        self.model_button = DropDownPushButton(self.tr("模型"), self)
        self.model_button.setFixedSize(90, 32)
        self.model_button.setStyleSheet("QPushButton { font-size: 11px; border: 0;}")
        self.model_button.setMenu(self._model_menu)

        self.send_button = PrimaryPushButton(self.tr("发送"), self)
        self.send_button.setIcon(FIF.SEND)
        self.send_button.setFixedSize(90, 32)

        self.button_column = QWidget(self.input_container)
        button_column_layout = QVBoxLayout(self.button_column)
        button_column_layout.setContentsMargins(0, 0, 0, 0)
        button_column_layout.setSpacing(4)
        button_column_layout.addWidget(self.model_button)
        button_column_layout.addWidget(self.send_button)

        input_layout.addWidget(self.text_edit, stretch=1)
        input_layout.addWidget(self.button_column, alignment=Qt.AlignBottom)

        self.main_layout.addWidget(self.input_container)
        QTimer.singleShot(0, self.text_edit.setFocus)
        self._refresh_model_selector()

        # ---- Signals ----
        self.send_button.clicked.connect(self._on_send)
        self.model_button.setMenu(self._model_menu)
        self.text_edit.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[name-defined]
        if obj is self.text_edit and event.type() == QEvent.Type.ShortcutOverride:
            key_event = event
            if key_event.key() == Qt.Key.Key_Shift:
                logger.info("IME ShortcutOverride Shift hasFocus={}", self.text_edit.hasFocus())
            return False

        if event.type() == QEvent.Type.KeyPress:
            key_event = event
            if obj is self.text_edit and key_event.key() == Qt.Key.Key_Shift:
                logger.info("IME eventFilter KeyPress Shift hasFocus={}", self.text_edit.hasFocus())
            if self.approval_panel is not None and self.approval_panel.isVisible():
                if key_event.key() == Qt.Key.Key_Up:
                    self.approval_panel.select_previous()
                    return True
                if key_event.key() == Qt.Key.Key_Down:
                    self.approval_panel.select_next()
                    return True
                if key_event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if obj is self.text_edit:
                        text = self.text_edit.toPlainText().strip()
                        if text:
                            self.approval_panel._resolve(ToolConfirmationDecision(approved=False, reason=text))
                            self.text_edit.clear()
                            return True
                    self.approval_panel.confirm_selection()
                    return True
            if obj is self.text_edit and key_event.key() in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
            ):
                if key_event.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
                    return False
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    # -------------------------------------------------------------------------
    # Context binding
    # -------------------------------------------------------------------------
    def _bind_context(self) -> None:
        if self.context is None:
            return

        self.context.register_event_handler(BaseEvent, self._on_event)
        self.context.register_event_handler(SessionStreamDeltaEvent, self._on_stream)
        self.context.register_event_handler(SessionStreamCompletedEvent, self._on_stream)
        self.context.set_tool_confirmation_handler(self._confirm_tool_call)

        for msg in self.context.messages:
            self._add_message_bubble(msg)

        self._refresh_model_selector()

    # -------------------------------------------------------------------------
    # User actions
    # -------------------------------------------------------------------------
    def _on_send(self) -> None:
        text = self.text_edit.toPlainText().strip()

        if self.approval_panel is not None and self.approval_panel.isVisible():
            if text:
                self.approval_panel._resolve(ToolConfirmationDecision(approved=False, reason=text))
                self.text_edit.clear()
            else:
                self.approval_panel.confirm_selection()
            return

        if not text:
            return

        self.text_edit.clear()
        self._ctrl_c_count = 0

        if self.context is None:
            # Demo fallback: echo user message as a dummy assistant reply
            from datetime import UTC, datetime

            user_msg = Message(role="user", content=[TextSegment(text=text)])
            self._add_message_bubble(user_msg)
            self._add_message_bubble(
                Message(
                    role="assistant",
                    content=[TextSegment(text=f"Echo: {text}")],
                    time=datetime.now(UTC),
                )
            )
            return

        if self._is_processing:
            self.context.pending_messages.append(text)
            return

        self._is_processing = True
        import asyncio

        task = asyncio.create_task(self._submit_text(text))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _submit_text(self, text: str) -> None:
        try:
            await self.context.send(text)  # type: ignore[union-attr]
            while self.context.pending_messages:  # type: ignore[union-attr]
                pending = list(self.context.pending_messages)  # type: ignore[union-attr]
                self.context.pending_messages.clear()  # type: ignore[union-attr]
                await self.context.send(pending)  # type: ignore[union-attr]
        except Exception as exc:
            logger.exception("Chat send failed")
            detail = f"发送失败: {type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
            self._add_status_item(detail, "error")
        finally:
            self._is_processing = False

    async def _confirm_tool_call(self, tool_call, tool) -> ToolConfirmationDecision:
        arguments = _format_arguments(tool_call.function.arguments)

        if self.approval_panel is not None:
            self.main_layout.removeWidget(self.approval_panel)
            self.approval_panel.deleteLater()

        self.approval_panel = ApprovalPanel(tool.name, arguments, parent=self)
        # Insert above input_container
        idx = self.main_layout.indexOf(self.input_container)
        self.main_layout.insertWidget(idx, self.approval_panel)
        self.approval_panel.setFocus()

        result = await self.approval_panel.wait()

        self.main_layout.removeWidget(self.approval_panel)
        self.approval_panel.deleteLater()
        self.approval_panel = None
        self.text_edit.setFocus()

        if not result.approved and result.reason:
            await self.logger.info(f"Tool call rejected: {tool.name}, reason: {result.reason}")

        return result

    def _refresh_model_selector(self) -> None:
        config_manager = get_config_manager()
        models = config_manager.list_models()
        current_model = config_manager.get_default_model()

        self._model_menu.clear()

        if self.context is None:
            self.model_button.setText(self.tr("模型"))
            self.model_button.setEnabled(False)
            disabled_action = Action(self.tr("未连接上下文"), self)
            disabled_action.setEnabled(False)
            self._model_menu.addAction(disabled_action)
            return

        if not models:
            self.model_button.setText(self.tr("模型"))
            self.model_button.setEnabled(False)
            disabled_action = Action(self.tr("未配置模型"), self)
            disabled_action.setEnabled(False)
            self._model_menu.addAction(disabled_action)
            return

        for model in models:
            action = Action(
                model.name,
                self,
                triggered=lambda checked=False, model_name=model.name: self._switch_model(model_name),
            )
            self._model_menu.addAction(action)

        self.model_button.setEnabled(True)
        self.model_button.setText(current_model.name if current_model is not None else self.tr("模型"))

    async def _switch_model(self, model_name: str) -> None:
        if self.context is None:
            return

        config_manager = get_config_manager()
        if not config_manager.set_default_model(model_name):
            logger.error("未找到模型: {}", model_name)
            return

        success = await self.context.switch_model(model_name)
        self._refresh_model_selector()

        if success:
            logger.info("已切换到模型: {}", model_name)
        else:
            logger.error("切换模型失败: {}", model_name)

    # -------------------------------------------------------------------------
    # Event handlers
    # -------------------------------------------------------------------------
    def _on_event(self, event: BaseEvent) -> None:
        # Ensure UI updates happen on the main thread
        QTimer.singleShot(0, lambda: self._handle_event(event))

    def _handle_event(self, event: BaseEvent) -> None:
        match event:
            case SessionMessageEvent(message=message):
                if message.role == "assistant":
                    self._finalize_stream()
                self._add_message_bubble(message)
                self._scroll_to_bottom()
            case SessionStatusEvent(level=level, detail=detail):
                if not self._debug:
                    pass
                elif level >= StatusLevel.ERROR:
                    self._add_status_item(detail or "", "error")
                elif level == StatusLevel.SUCCESS:
                    self._add_status_item(detail or "", "success")
                else:
                    self._add_status_item(detail or "", "info")
            case SessionErrorEvent(error=error):
                self._add_status_item(error, "error")
                self._is_processing = False
            case SessionResetEvent():
                self._clear_messages()
            case SessionLoadedEvent() | SessionCompactedEvent():
                self._clear_messages()
                for msg in self.context.display_messages:  # type: ignore[union-attr]
                    self._add_message_bubble(msg)
                self._scroll_to_bottom()
            case _:
                pass

    def _on_stream(self, event: SessionStreamDeltaEvent | SessionStreamCompletedEvent) -> None:
        if not isinstance(event, SessionStreamDeltaEvent):
            return
        stream_event = event.stream_event
        if not isinstance(stream_event, MsgStreamDeltaEvent):
            return
        QTimer.singleShot(0, lambda: self._apply_stream_delta(stream_event.segment))

    def _apply_stream_delta(self, segment) -> None:
        match segment:
            case TextDetailSegment(text=text):
                self._ensure_stream_bubble()
                self._current_stream_bubble.append_text(text)
            case ThinkDetailSegment(thought_process=text):
                self._ensure_stream_bubble()
                self._current_stream_bubble.append_thinking(text)
            case ToolCallDetailSegment(tool_name=tool_name, partial_arguments=partial_arguments):
                self._ensure_stream_bubble()
                self._current_stream_bubble.append_tool(tool_name, partial_arguments)
        self._scroll_to_bottom()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _add_status_item(self, text: str, variant: str = "info") -> None:
        if variant == "error":
            bubble = ErrorMessageBubble(text)
            item = MessageItem(bubble, "error")
        else:
            label = CaptionLabel(text)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignCenter)
            match variant:
                case "success":
                    color = "#51cf66"
                case _:
                    color = "#adb5bd"
            label.setStyleSheet(f"color: {color}; padding: 6px 0;")
            item = MessageItem(label, "status")
        idx = self.messages_layout.count() - 1
        self.messages_layout.insertWidget(idx, item)
        self._scroll_to_bottom()

    def _add_message_bubble(self, message: Message) -> None:
        bubble = MessageBubble(message)
        if not bubble.has_visible_content:
            bubble.deleteLater()
            return
        item = MessageItem(bubble, message.role)
        # insert before the trailing stretch
        idx = self.messages_layout.count() - 1
        self.messages_layout.insertWidget(idx, item)
        self._scroll_to_bottom()

    def _clear_messages(self) -> None:
        self._finalize_stream()
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _ensure_stream_bubble(self) -> None:
        if self._current_stream_bubble is None:
            self._current_stream_bubble = StreamMessageBubble()
            item = MessageItem(self._current_stream_bubble, "assistant")
            idx = self.messages_layout.count() - 1
            self.messages_layout.insertWidget(idx, item)

    def _finalize_stream(self) -> None:
        if self._current_stream_bubble is None:
            return
        item = self._current_stream_bubble.parentWidget()
        if item and isinstance(item, MessageItem):
            self.messages_layout.removeWidget(item)
            item.deleteLater()
        self._current_stream_bubble = None

    def _scroll_to_bottom(self) -> None:
        vsb = self.scroll_area.verticalScrollBar()
        if vsb:
            vsb.setValue(vsb.maximum())
