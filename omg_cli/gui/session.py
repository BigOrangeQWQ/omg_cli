"""Session history management subpage for GUI."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SingleDirectionScrollArea,
    StrongBodyLabel,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from omg_cli.config.session_storage import SessionMetadata, SessionStorage
from omg_cli.context.chat import ChatContext


class SessionCard(CardWidget):
    """A single session item card with load/delete actions."""

    loadRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, metadata: SessionMetadata, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.metadata = metadata
        self.setObjectName("sessionCard")
        self.setMaximumWidth(1440)
        self.setBorderRadius(8)
        self.setStyleSheet(
            "CardWidget#sessionCard {  border: 1px solid rgba(255, 255, 255, 0.08);  border-radius: 8px;}"
        )

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 12)
        self._layout.setSpacing(12)

        self._text_layout = QVBoxLayout()
        self._text_layout.setContentsMargins(0, 0, 0, 0)
        self._text_layout.setSpacing(2)

        title = metadata.title or f"会话 {metadata.session_id[:8]}"
        self.title_label = StrongBodyLabel(title, self)

        self.detail_label = CaptionLabel(self._build_detail_text(), self)
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextColor(QColor("#808080"), QColor("#c0c0c0"))

        self._text_layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._text_layout.addWidget(self.detail_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._layout.addLayout(self._text_layout)
        self._layout.addStretch(1)

        self.open_button = PrimaryPushButton(self.tr("加载"), self)
        self.open_button.setIcon(FIF.HISTORY)
        self.open_button.setFixedWidth(100)

        self.delete_button = PushButton(self.tr("删除"), self)
        self.delete_button.setIcon(FIF.DELETE)
        self.delete_button.setFixedWidth(90)

        self._layout.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignRight)
        self._layout.addWidget(self.delete_button, 0, Qt.AlignmentFlag.AlignRight)

        self.open_button.clicked.connect(self._on_open_clicked)
        self.delete_button.clicked.connect(self._on_delete_clicked)

    def _normalBackgroundColor(self):
        return QColor(32, 35, 40, 225)

    def _hoverBackgroundColor(self):
        return QColor(41, 45, 50, 238)

    def _pressedBackgroundColor(self):
        return QColor(27, 30, 35, 245)

    def _build_detail_text(self) -> str:
        updated_at = self._format_time(self.metadata.updated_at)
        created_at = self._format_time(self.metadata.created_at)
        model = self.metadata.model_name or "unknown"
        workspace = str(self.metadata.workspace)
        session_short = self.metadata.session_id[:12]
        return (
            f"ID: {session_short} · 模型: {model}\n更新时间: {updated_at} · 创建时间: {created_at}\n工作区: {workspace}"
        )

    @staticmethod
    def _format_time(value: datetime) -> str:
        local_time = value.astimezone()
        return local_time.strftime("%Y-%m-%d %H:%M:%S")

    def _on_open_clicked(self) -> None:
        self.loadRequested.emit(self.metadata.session_id)

    def _on_delete_clicked(self) -> None:
        self.deleteRequested.emit(self.metadata.session_id)


class SessionInterface(QWidget):
    """Session history management page implemented with card widgets."""

    sessionLoaded = Signal(str)
    sessionDeleted = Signal(str)

    def __init__(
        self,
        context: ChatContext | None = None,
        chat_mode: str = "chat",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.setObjectName("sessionInterface")
        self.setStyleSheet("SessionInterface { background-color: #151515; }")

        self.context = context
        self.storage = SessionStorage()
        self.chat_mode = chat_mode

        self._init_ui()
        self.refresh_sessions()

    def _init_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(10)

        self.toolbar_card = CardWidget(self)
        self.toolbar_card.setObjectName("sessionToolbarCard")
        self.toolbar_card.setBorderRadius(8)
        self.toolbar_card.setStyleSheet(
            "CardWidget#sessionToolbarCard {"
            "  background-color: rgba(36, 40, 46, 0.92);"
            "  border: 1px solid rgba(255, 255, 255, 0.08);"
            "  border-radius: 8px;"
            "}"
        )
        toolbar_layout = QHBoxLayout(self.toolbar_card)
        toolbar_layout.setContentsMargins(16, 10, 16, 10)
        toolbar_layout.setSpacing(12)

        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        self.title_label = StrongBodyLabel(self.tr("会话历史"), self)
        self.summary_label = CaptionLabel(self.tr("加载中..."), self)
        self.summary_label.setTextColor(QColor("#808080"), QColor("#c0c0c0"))

        title_layout.addWidget(self.title_label)
        title_layout.addWidget(self.summary_label)

        self.refresh_button = PushButton(self.tr("刷新"), self)
        self.refresh_button.setIcon(FIF.SYNC)
        self.refresh_button.setFixedWidth(90)

        toolbar_layout.addLayout(title_layout)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self.refresh_button)

        self.main_layout.addWidget(self.toolbar_card)

        self.status_label = BodyLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        self.main_layout.addWidget(self.status_label)

        self.scroll_area = SingleDirectionScrollArea(orient=Qt.Orientation.Vertical, parent=self)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.scroll_widget = QWidget(self.scroll_area)
        self.list_layout = QVBoxLayout(self.scroll_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.list_layout.addStretch(1)

        self.scroll_area.setWidget(self.scroll_widget)
        self.scroll_area.setWidgetResizable(True)
        # Transparent scroll area + transparent internal view to keep dark layered background clean.
        self.scroll_area.enableTransparentBackground()
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll_widget.setStyleSheet("QWidget { background: transparent; }")

        self.main_layout.addWidget(self.scroll_area, stretch=1)

        self.refresh_button.clicked.connect(self.refresh_sessions)

    def refresh_sessions(self) -> None:
        sessions = self._load_sessions()
        self._render_sessions(sessions)

    def _load_sessions(self) -> list[SessionMetadata]:
        if self.context is not None:
            sessions = self.context.list_saved_sessions()
        else:
            sessions = self.storage.list_sessions()
        return [s for s in sessions if self._session_mode(s) == self.chat_mode]

    def _session_mode(self, metadata: SessionMetadata) -> str:
        # Backward compatibility: some old channel sessions may still carry default chat_mode,
        # so infer channel mode when channel_state.json exists.
        if metadata.chat_mode == "channel":
            return "channel"

        if self.storage.load_channel_session(metadata.session_id) is not None:
            return "channel"

        return "chat"

    def _render_sessions(self, sessions: list[SessionMetadata]) -> None:
        self._clear_session_cards()

        if not sessions:
            empty = CardWidget(self)
            empty.setObjectName("sessionEmptyCard")
            empty.setBorderRadius(8)
            empty.setStyleSheet(
                "CardWidget#sessionEmptyCard {"
                "  background-color: rgba(36, 40, 46, 0.92);"
                "  border: 1px solid rgba(255, 255, 255, 0.08);"
                "  border-radius: 8px;"
                "}"
            )
            layout = QVBoxLayout(empty)
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(6)

            title = StrongBodyLabel(self.tr("暂无会话"), empty)
            detail = CaptionLabel(self.tr("当前还没有已保存会话，开始聊天后会自动出现在这里。"), empty)
            detail.setWordWrap(True)
            detail.setTextColor(QColor("#808080"), QColor("#c0c0c0"))

            layout.addWidget(title)
            layout.addWidget(detail)

            idx = self.list_layout.count() - 1
            self.list_layout.insertWidget(idx, empty)
            self.summary_label.setText(self.tr("共 0 条会话"))
            return

        for metadata in sessions:
            card = SessionCard(metadata, self)
            card.loadRequested.connect(self._load_session)
            card.deleteRequested.connect(self._delete_session)
            idx = self.list_layout.count() - 1
            self.list_layout.insertWidget(idx, card)

        self.summary_label.setText(self.tr(f"共 {len(sessions)} 条会话，按更新时间排序"))

    def _clear_session_cards(self) -> None:
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

    def _set_status(self, text: str, variant: str = "info") -> None:
        if not text:
            self.status_label.hide()
            return

        color = "#adb5bd"
        if variant == "error":
            color = "#ff6b6b"
        elif variant == "success":
            color = "#51cf66"

        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; padding: 2px 2px 6px 2px;")
        self.status_label.show()

    def _load_session(self, session_id: str) -> None:
        if self.context is None:
            self.sessionLoaded.emit(session_id)
            self._set_status(self.tr(f"已选择会话: {session_id[:12]}"), "info")
            return

        if self.context.load_session(session_id):
            self.sessionLoaded.emit(session_id)
            self._set_status(self.tr(f"已加载会话: {session_id[:12]}"), "success")
            return

        self._set_status(self.tr("会话加载失败，可能已被删除。"), "error")
        self.refresh_sessions()

    def _delete_session(self, session_id: str) -> None:
        box = MessageBox(
            self.tr("删除会话"),
            self.tr(f"确定删除会话 {session_id[:12]} 吗？此操作不可撤销。"),
            self,
        )
        box.yesButton.setText(self.tr("删除"))
        box.cancelButton.setText(self.tr("取消"))

        if not box.exec():
            return

        if self.context is not None:
            success = self.context.delete_session(session_id)
        else:
            success = self.storage.delete(session_id)

        if success:
            self.sessionDeleted.emit(session_id)
            self._set_status(self.tr(f"会话已删除: {session_id[:12]}"), "success")
            self.refresh_sessions()
            return

        self._set_status(self.tr("删除失败，会话可能不存在。"), "error")
