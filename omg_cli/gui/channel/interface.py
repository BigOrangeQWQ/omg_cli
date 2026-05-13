"""Channel page with chat-like layout and thread tabs."""

from __future__ import annotations

import asyncio
from typing import Any

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    PrimaryPushButton,
    ScrollArea,
    StrongBodyLabel,
    TabBar,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from omg_cli.gui.bridge import ContextEventBridge
from omg_cli.gui.chat import InputMethodTextEdit, MessageBubble, MessageItem
from omg_cli.log import logger
from omg_cli.types.event import RoleActivityEvent
from omg_cli.types.message import Message, TextSegment


class ThreadPage(QWidget):
    """Single thread page rendered in the stacked widget."""

    submitRequested = Signal(int, str)

    def __init__(self, thread_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.thread_id = thread_id

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(10)

        self.message_card = CardWidget(self)
        self.message_card.setObjectName("channelThreadMessageCard")
        self.message_card.setBorderRadius(8)
        self.message_card.setStyleSheet(
            "CardWidget#channelThreadMessageCard {"
            "  background-color: rgba(28, 31, 36, 0.95);"
            "  border: 1px solid rgba(255, 255, 255, 0.08);"
            "  border-radius: 8px;"
            "}"
        )

        message_layout = QVBoxLayout(self.message_card)
        message_layout.setContentsMargins(12, 12, 12, 12)
        message_layout.setSpacing(8)

        self.message_title = StrongBodyLabel(self.tr("对话"), self.message_card)
        self.message_scroll_area = ScrollArea(self.message_card)
        self.message_scroll_widget = QWidget(self.message_scroll_area)
        self.messages_layout = QVBoxLayout(self.message_scroll_widget)
        self.messages_layout.setAlignment(Qt.AlignTop)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addStretch(1)

        self.message_scroll_area.setWidget(self.message_scroll_widget)
        self.message_scroll_area.setWidgetResizable(True)
        self.message_scroll_area.enableTransparentBackground()
        self.message_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.message_scroll_widget.setStyleSheet("background-color: transparent;")

        message_layout.addWidget(self.message_title)
        message_layout.addWidget(self.message_scroll_area, stretch=1)

        self.input_container = QWidget(self)

        input_layout = QHBoxLayout(self.input_container)
        input_layout.setContentsMargins(12, 12, 12, 12)
        input_layout.setSpacing(10)

        self.input_edit = InputMethodTextEdit(self)
        self.input_edit.setPlaceholderText(self.tr("发送到当前 Thread，Enter 发送，Ctrl+Enter 换行..."))
        self.input_edit.setFixedHeight(80)

        self.send_button = PrimaryPushButton(self.tr("发送"), self)
        self.send_button.setIcon(FIF.SEND)
        self.send_button.setFixedSize(90, 80)

        input_layout.addWidget(self.input_edit, stretch=1)
        input_layout.addWidget(self.send_button)

        self.root_layout.addWidget(self.message_card, stretch=1)
        self.root_layout.addWidget(self.input_container)

        self.send_button.clicked.connect(self._on_submit)
        self.input_edit.installEventFilter(self)

    def set_messages(self, messages: list[Message]) -> None:
        self._clear_messages()
        for message in messages:
            self.append_message(message)

    def append_message(self, message: Message) -> None:
        bubble = MessageBubble(message)
        if not bubble.has_visible_content:
            bubble.deleteLater()
            return
        item = MessageItem(bubble, message.role)
        idx = self.messages_layout.count() - 1
        self.messages_layout.insertWidget(idx, item)
        self._scroll_to_bottom()

    def _clear_messages(self) -> None:
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _scroll_to_bottom(self) -> None:
        vsb = self.message_scroll_area.verticalScrollBar()
        if vsb:
            vsb.setValue(vsb.maximum())

    def _on_submit(self) -> None:
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        self.input_edit.clear()
        self.submitRequested.emit(self.thread_id, text)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.input_edit and event.type() == QEvent.Type.KeyPress:
            key_event = event
            if key_event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                modifiers = key_event.modifiers()
                if modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
                    return False
                self._on_submit()
                return True
        return super().eventFilter(obj, event)


class ChannelInterface(QWidget):
    """Channel interface that mirrors chat layout with thread tabs."""

    def __init__(
        self,
        *,
        channel_context: Any | None = None,
        bridge: ContextEventBridge | None = None,
        debug: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.channel_context = channel_context
        self.bridge = bridge or ContextEventBridge(channel_context)
        self.debug = debug
        self._route_to_thread_id: dict[str, int] = {}
        self._thread_pages: dict[int, ThreadPage] = {}
        self._tab_routes: list[str] = []
        self._pending_tasks: set[asyncio.Task[Any]] = set()

        self.setObjectName("channelInterface")
        self.setStyleSheet("ChannelInterface { background-color: #f5f6f8; }")

        self._init_ui()
        self._bind_bridge_events()
        self.refresh_threads()

    def _init_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(8)

        self.tab_bar = TabBar(self)
        self.tab_bar.setMovable(False)
        self.tab_bar.setTabMaximumWidth(220)
        self.tab_bar.setTabShadowEnabled(False)
        self.tab_bar.setTabSelectedBackgroundColor(QColor(255, 255, 255, 125), QColor(255, 255, 255, 50))
        self.tab_bar.setAddButtonVisible(True)
        self.tab_bar.setTabsClosable(False)
        self.tab_bar.setFixedHeight(44)
        self.tab_bar.tabAddRequested.connect(self._on_add_tab_requested)

        # Place thread tabs directly above message content for a clearer visual hierarchy.
        self.main_layout.addWidget(self.tab_bar)

        self.runtime_label = BodyLabel("", self)
        self.runtime_label.setWordWrap(True)
        self.runtime_label.setStyleSheet("color: #6c757d; padding: 2px 6px;")
        self.runtime_label.hide()
        self.main_layout.addWidget(self.runtime_label)

        self.empty_hint = BodyLabel(self.tr("暂无线程，等待后续 Event 创建。"), self)
        self.empty_hint.setStyleSheet("color: #6c757d; padding: 12px 6px;")
        self.empty_hint.hide()
        self.main_layout.addWidget(self.empty_hint)

        self.stacked_widget = QStackedWidget(self)
        self.main_layout.addWidget(self.stacked_widget, stretch=1)
        self.tab_bar.currentChanged.connect(self._on_tab_changed)

    def refresh_threads(self) -> None:
        threads = self._collect_threads()

        self.tab_bar.clear()
        self._route_to_thread_id.clear()
        self._tab_routes.clear()

        while self.stacked_widget.count() > 0:
            widget = self.stacked_widget.widget(0)
            if widget is None:
                break
            self.stacked_widget.removeWidget(widget)
            widget.deleteLater()

        self._thread_pages.clear()

        if not threads:
            self.empty_hint.show()
            return

        self.empty_hint.hide()

        for thread in threads:
            thread_id = int(getattr(thread, "id", 0))
            route_key = f"thread-{thread_id}"

            page = ThreadPage(thread_id=thread_id, parent=self.stacked_widget)
            page.submitRequested.connect(self._on_submit_to_thread)
            page.set_messages(list(getattr(thread, "messages", [])))

            self.stacked_widget.addWidget(page)
            self._thread_pages[thread_id] = page

            self.tab_bar.addTab(
                routeKey=route_key,
                text=self._thread_tab_text(thread),
                onClick=lambda rid=route_key: self._switch_to_route(rid),
            )
            self._route_to_thread_id[route_key] = thread_id
            self._tab_routes.append(route_key)

        if self._tab_routes:
            self._switch_to_route(self._tab_routes[0])

    def _bind_bridge_events(self) -> None:
        if self.bridge is None:
            return
        self.bridge.threadSpawned.connect(self._on_thread_spawned)
        self.bridge.threadMessageReceived.connect(self._append_thread_message)
        self.bridge.threadStatusChanged.connect(self._on_thread_status_changed)
        if self.debug:
            self.bridge.roleActivityReceived.connect(self._on_role_activity)
            self.bridge.statusReceived.connect(self._on_session_status)
        self.bridge.errorReceived.connect(self._on_session_error)
        if self.debug:
            self.bridge.eventReceived.connect(self._on_any_event)

    def _on_thread_spawned(self, thread: Any) -> None:
        self.refresh_threads()
        thread_id = int(getattr(thread, "id", -1))
        route = self._thread_route_key(thread_id)
        if route in self._route_to_thread_id:
            self._switch_to_route(route)
            self._set_runtime_hint(f"已创建线程 #{thread_id}", "info")

    def _on_role_activity(self, thread_id: int, role_name: str, activity_type: str, content: str) -> None:
        page = self._thread_pages.get(thread_id)
        if page is None:
            return

        activity_text = activity_type.strip().lower()
        body = f"[{activity_text}] {content}".strip()
        if content.strip():
            page.append_message(Message(role="assistant", name=role_name, content=[TextSegment(text=body)]))
        else:
            page.append_message(Message(role="assistant", name=role_name, content=[TextSegment(text=body)]))

    def _on_session_status(self, detail: str) -> None:
        if detail.strip():
            self._set_runtime_hint(detail, "info")

    def _on_session_error(self, detail: str) -> None:
        if detail.strip():
            self._set_runtime_hint(detail, "error")

    def _on_any_event(self, event: Any) -> None:
        # Keep eventReceived wired for future channel-side expansion and quick diagnostics.
        if isinstance(event, RoleActivityEvent):
            self._set_runtime_hint(
                f"{event.role_name}: {event.activity_type}",
                "info",
            )

    def _set_runtime_hint(self, text: str, level: str) -> None:
        if not text:
            self.runtime_label.hide()
            return

        color = "#6c757d"
        if level == "error":
            color = "#ff6b6b"
        elif level == "success":
            color = "#51cf66"

        self.runtime_label.setText(text)
        self.runtime_label.setStyleSheet(f"color: {color}; padding: 2px 6px;")
        self.runtime_label.show()

    def _append_thread_message(self, thread_id: int, message: Message) -> None:
        page = self._thread_pages.get(thread_id)
        if page is None:
            self.refresh_threads()
            return
        page.append_message(message)

    def _collect_threads(self) -> list[Any]:
        if self.channel_context is None:
            return []

        thread_map = getattr(self.channel_context, "thread_map", None)
        if isinstance(thread_map, dict):
            return sorted(thread_map.values(), key=lambda item: getattr(item, "id", 0))

        threads = getattr(self.channel_context, "threads", None)
        if isinstance(threads, list):
            return sorted(threads, key=lambda item: getattr(item, "id", 0))

        return []

    def _thread_tab_text(self, thread: Any) -> str:
        thread_id = getattr(thread, "id", 0)
        title = getattr(thread, "title", f"Thread {thread_id}")
        if thread_id == 0:
            return f"#{thread_id} {title}"

        emoji = self._status_emoji(getattr(thread, "status", "draft"))
        return f"{emoji} #{thread_id} {title}"

    @staticmethod
    def _status_emoji(status: Any) -> str:
        status_text = str(status).strip().lower()
        return {
            "draft": "📝",
            "running": "🟢",
            "review": "🟡",
            "done": "✅",
            "error": "❌",
            "stalled": "⏸️",
        }.get(status_text, "⚪")

    def _thread_route_key(self, thread_id: int) -> str:
        return f"thread-{thread_id}"

    def _update_thread_tab_text(self, thread_id: int) -> None:
        thread = self._thread_for_id(thread_id)
        if thread is None:
            return

        route_key = self._thread_route_key(thread_id)
        item = self.tab_bar.tab(route_key)
        if item is None:
            return

        text = self._thread_tab_text(thread)
        index = self.tab_bar.items.index(item)
        self.tab_bar.setTabText(index, text)

    def _thread_for_id(self, thread_id: int) -> Any | None:
        if self.channel_context is None:
            return None

        thread_map = getattr(self.channel_context, "thread_map", None)
        if isinstance(thread_map, dict):
            return thread_map.get(thread_id)

        threads = getattr(self.channel_context, "threads", None)
        if isinstance(threads, list):
            for thread in threads:
                if getattr(thread, "id", None) == thread_id:
                    return thread

        return None

    def _on_thread_status_changed(self, thread_id: int, status: str) -> None:
        thread = self._thread_for_id(thread_id)
        if thread is None:
            return

        if hasattr(thread, "status"):
            thread.status = status

        if thread_id != 0:
            self._update_thread_tab_text(thread_id)

    def _switch_to_route(self, route_key: str) -> None:
        thread_id = self._route_to_thread_id.get(route_key)
        if thread_id is None:
            return
        page = self._thread_pages.get(thread_id)
        if page is None:
            return
        self.stacked_widget.setCurrentWidget(page)
        self.tab_bar.setCurrentTab(route_key)

    def _on_tab_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._tab_routes):
            return
        route_key = self._tab_routes[index]
        thread_id = self._route_to_thread_id.get(route_key)
        if thread_id is None:
            return
        page = self._thread_pages.get(thread_id)
        if page is not None:
            self.stacked_widget.setCurrentWidget(page)

    def _on_submit_to_thread(self, thread_id: int, text: str) -> None:
        if self.channel_context is None:
            return

        page = self._thread_pages.get(thread_id)
        if page is not None:
            page.append_message(Message(role="user", content=[TextSegment(text=text)]))

        async def _dispatch() -> None:
            try:
                dispatch = getattr(self.channel_context, "dispatch_to_thread", None)
                if dispatch is None:
                    raise RuntimeError("Channel context does not support dispatch_to_thread")
                await dispatch(
                    thread_id,
                    Message(role="user", content=[TextSegment(text=text)]),
                )
            except Exception as exc:
                logger.exception("Dispatch message to thread failed")
                if page is not None:
                    page.append_message(Message(role="assistant", content=[TextSegment(text=f"发送失败: {exc}")]))

        task = asyncio.create_task(_dispatch())
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    def _on_add_tab_requested(self) -> None:
        # TODO: Wire this to channel thread creation flow when event-driven creation API is finalized.
        logger.info("Tab add requested in Channel UI; thread creation is pending implementation")
