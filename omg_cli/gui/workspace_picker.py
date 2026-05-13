"""Workspace picker page for GUI - select or browse working directory on startup."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    PrimaryPushButton,
    StrongBodyLabel,
)
from qfluentwidgets import FluentIcon as FIF

from omg_cli.config import get_config_manager
from omg_cli.log import logger


class RecentDirCard(CardWidget):
    """A single recent directory item card."""

    selected = Signal(Path)

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.path = path
        self.setObjectName("recentDirCard")
        self.setBorderRadius(8)
        self.setStyleSheet(
            "CardWidget#recentDirCard {"
            "  background-color: rgba(255, 255, 255, 0.96);"
            "  border: 1px solid rgba(0, 0, 0, 0.12);"
            "  border-radius: 8px;"
            "}"
            "CardWidget#recentDirCard:hover {"
            "  background-color: rgba(240, 240, 240, 0.96);"
            "  border: 1px solid rgba(0, 0, 0, 0.20);"
            "}"
        )
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        display_name = path.name or str(path)
        self.title_label = StrongBodyLabel(display_name, self)

        self.path_label = CaptionLabel(str(path), self)
        self.path_label.setWordWrap(True)

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.path_label)

        layout.addLayout(text_layout)
        layout.addStretch(1)

        self.open_button = PrimaryPushButton(self.tr("打开"), self)
        self.open_button.setIcon(FIF.FOLDER)
        self.open_button.setFixedWidth(100)
        layout.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignRight)

        self.open_button.clicked.connect(self._on_open_clicked)
        self.mousePressEvent = lambda _event: self._on_open_clicked()  # type: ignore[method-assign]

    def _on_open_clicked(self) -> None:
        self.selected.emit(self.path)


class WorkspacePicker(QWidget):
    """Workspace picker page shown on GUI startup."""

    workspaceSelected = Signal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("workspacePicker")
        self.setStyleSheet("WorkspacePicker { background-color: #f5f6f8; }")

        self._init_ui()
        self._load_recent_directories()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 30, 40, 30)
        main_layout.setSpacing(20)

        # Title
        title = StrongBodyLabel(self.tr("选择工作区"), self)
        main_layout.addWidget(title)

        # Description
        desc = BodyLabel(
            self.tr("请选择一个文件夹作为当前工作区。OMG CLI 将使用该目录作为文件操作和会话的基准路径。"),
            self,
        )
        desc.setWordWrap(True)
        main_layout.addWidget(desc)

        # Browse button card
        browse_card = CardWidget(self)
        browse_card.setObjectName("browseCard")
        browse_card.setBorderRadius(8)
        browse_card.setStyleSheet(
            "CardWidget#browseCard {"
            "  background-color: rgba(255, 255, 255, 0.96);"
            "  border: 1px solid rgba(0, 0, 0, 0.12);"
            "  border-radius: 8px;"
            "}"
        )

        browse_layout = QHBoxLayout(browse_card)
        browse_layout.setContentsMargins(20, 16, 20, 16)
        browse_layout.setSpacing(12)

        browse_text = BodyLabel(self.tr("浏览文件夹..."), browse_card)
        browse_layout.addWidget(browse_text)
        browse_layout.addStretch(1)

        self.browse_button = PrimaryPushButton(self.tr("浏览"), browse_card)
        self.browse_button.setIcon(FIF.FOLDER_ADD)
        self.browse_button.clicked.connect(self._on_browse_clicked)
        browse_layout.addWidget(self.browse_button)

        main_layout.addWidget(browse_card)

        # Recent directories section
        self.recent_title = StrongBodyLabel(self.tr("最近打开的工作区"), self)
        main_layout.addWidget(self.recent_title)

        self.recent_container = QWidget(self)
        self.recent_layout = QVBoxLayout(self.recent_container)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(8)
        self.recent_layout.addStretch(1)

        main_layout.addWidget(self.recent_container)
        main_layout.addStretch(1)

    def _load_recent_directories(self) -> None:
        """Load and display recent directories from config."""
        config_manager = get_config_manager()
        recent = config_manager.list_recent_directories()

        # Clear existing widgets (except stretch)
        while self.recent_layout.count() > 1:
            item = self.recent_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not recent:
            self.recent_title.hide()
            self.recent_container.hide()
            return

        self.recent_title.show()
        self.recent_container.show()

        for path in recent:
            card = RecentDirCard(path, parent=self.recent_container)
            card.selected.connect(self._on_directory_selected)
            self.recent_layout.insertWidget(self.recent_layout.count() - 1, card)

    def _on_browse_clicked(self) -> None:
        """Open native file dialog to select a directory."""
        from PySide6.QtWidgets import QFileDialog

        config_manager = get_config_manager()
        default_dir = str(config_manager.get_working_directory() or Path.home())

        selected = QFileDialog.getExistingDirectory(
            self,
            self.tr("选择工作区文件夹"),
            default_dir,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )

        if selected:
            self._on_directory_selected(Path(selected))

    def _on_directory_selected(self, path: Path) -> None:
        """Handle directory selection - persist and emit signal."""
        try:
            config_manager = get_config_manager()
            config_manager.set_working_directory(path)
            logger.info(f"工作区已选择: {path}")
            self.workspaceSelected.emit(path)
        except Exception as exc:
            logger.error(f"设置工作区失败: {exc}")
            from qfluentwidgets import MessageBox

            MessageBox(
                self.tr("错误"),
                self.tr(f"无法设置工作区: {exc}"),
                self,
            ).exec()
