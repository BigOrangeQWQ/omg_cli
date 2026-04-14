"""Channel page with chat-like layout and thread tabs."""

from __future__ import annotations

import asyncio
from typing import Any

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    PrimaryPushButton,
    StrongBodyLabel,
    TabBar,
    TextBrowser,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from omg_cli.gui.chat import InputMethodTextEdit
from omg_cli.log import logger
from omg_cli.types.event import BaseEvent, ThreadMessageEvent, ThreadSpawnedEvent, ThreadStatusChangedEvent
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
        self.message_view = TextBrowser(self.message_card)
        self.message_view.setOpenExternalLinks(True)
        self.message_view.setStyleSheet(
            "TextBrowser { border: none; background: transparent; color: rgb(255, 255, 255); }"
        )

        message_layout.addWidget(self.message_title)
        message_layout.addWidget(self.message_view, stretch=1)

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
        self.message_view.clear()
        for message in messages:
            role = message.role
            name = message.name or role
            text = message.text or ""
            if not text:
                text = "\n".join(str(seg) for seg in message.content)
            self.message_view.append(f"[{name}] {text}")

    def append_message(self, message: Message) -> None:
        role = message.role
        name = message.name or role
        text = message.text or ""
        if not text:
            text = "\n".join(str(seg) for seg in message.content)
        self.message_view.append(f"[{name}] {text}")

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

    def __init__(self, *, channel_context: Any | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.channel_context = channel_context
        self._route_to_thread_id: dict[str, int] = {}
        self._thread_pages: dict[int, ThreadPage] = {}
        self._tab_routes: list[str] = []
        self._pending_tasks: set[asyncio.Task[Any]] = set()

        self.setObjectName("channelInterface")
        self.setStyleSheet("ChannelInterface { background-color: #151515; }")

        self._init_ui()
        self._bind_context_events()
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

        self.empty_hint = BodyLabel(self.tr("暂无线程，等待后续 Event 创建。"), self)
        self.empty_hint.setStyleSheet("color: #c0c0c0; padding: 12px 6px;")
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

    def _bind_context_events(self) -> None:
        if self.channel_context is None:
            return

        default_context = getattr(self.channel_context, "default_context", None)
        if default_context is None:
            return

        default_context.register_event_handler(BaseEvent, self._on_context_event)

    async def _on_context_event(self, event: BaseEvent) -> None:
        if isinstance(event, ThreadSpawnedEvent):
            QTimer.singleShot(0, self.refresh_threads)
            return

        if isinstance(event, ThreadMessageEvent):
            QTimer.singleShot(0, lambda: self._append_thread_message(event.thread_id, event.message))

        if isinstance(event, ThreadStatusChangedEvent):
            QTimer.singleShot(0, lambda: self._on_thread_status_changed(event.thread_id, event.status))

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
