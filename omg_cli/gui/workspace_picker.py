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
    TitleLabel,
    ToolButton,
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
        self.setBorderRadius(10)
        self.setStyleSheet(
            "CardWidget#recentDirCard {"
            "  background-color: rgba(255, 255, 255, 0.98);"
            "  border: 1px solid rgba(0, 0, 0, 0.08);"
            "  border-radius: 10px;"
            "}"
            "CardWidget#recentDirCard:hover {"
            "  background-color: rgba(245, 247, 250, 0.98);"
            "  border: 1px solid rgba(0, 0, 0, 0.16);"
            "}"
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        # Folder icon
        self.folder_icon = ToolButton(FIF.FOLDER, self)
        self.folder_icon.setFixedSize(36, 36)
        self.folder_icon.setEnabled(False)
        layout.addWidget(self.folder_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)

        display_name = path.name or str(path)
        self.title_label = StrongBodyLabel(display_name, self)
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 600;")

        self.path_label = CaptionLabel(str(path), self)
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet("color: rgba(0, 0, 0, 0.45);")

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.path_label)

        layout.addLayout(text_layout, 1)

        self.open_button = PrimaryPushButton(self.tr("打开"), self)
        self.open_button.setIcon(FIF.RIGHT_ARROW)
        self.open_button.setFixedWidth(90)
        self.open_button.setFixedHeight(32)
        layout.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.open_button.clicked.connect(self._on_open_clicked)
        self.mousePressEvent = lambda _event: self._on_open_clicked()  # type: ignore[method-assign]

    def _on_open_clicked(self) -> None:
        self.selected.emit(self.path)


class EmptyStateCard(CardWidget):
    """Shown when no recent directories exist."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setBorderRadius(10)
        self.setStyleSheet(
            "CardWidget {"
            "  background-color: rgba(255, 255, 255, 0.60);"
            "  border: 1px dashed rgba(0, 0, 0, 0.12);"
            "  border-radius: 10px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = BodyLabel("📂", self)
        icon_label.setStyleSheet("font-size: 32px;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        text = BodyLabel(self.tr("暂无最近打开的工作区"), self)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setStyleSheet("color: rgba(0, 0, 0, 0.40); font-size: 14px;")
        layout.addWidget(text)

        hint = CaptionLabel(self.tr("点击上方「浏览文件夹」选择一个新的工作区"), self)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: rgba(0, 0, 0, 0.30);")
        layout.addWidget(hint)


class WorkspacePicker(QWidget):
    """Workspace picker page shown on GUI startup."""

    workspaceSelected = Signal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("workspacePicker")
        self.setStyleSheet("WorkspacePicker { background-color: #f0f2f5; }")
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._init_ui()
        self._load_recent_directories()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(48, 36, 48, 36)
        main_layout.setSpacing(24)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Header with logo and title
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        logo_label = BodyLabel("🤯", self)
        logo_label.setStyleSheet("font-size: 28px;")
        header_layout.addWidget(logo_label)

        title = TitleLabel(self.tr("OMG CLI"), self)
        title.setStyleSheet("font-size: 24px; font-weight: 700; color: #1a1a2e;")
        header_layout.addWidget(title)
        header_layout.addStretch(1)

        main_layout.addLayout(header_layout)

        # Subtitle
        subtitle = StrongBodyLabel(self.tr("选择工作区"), self)
        subtitle.setStyleSheet("font-size: 18px; font-weight: 600; color: #333;")
        main_layout.addWidget(subtitle)

        # Description
        desc = BodyLabel(
            self.tr("请选择一个文件夹作为当前工作区。OMG CLI 将使用该目录作为文件操作和会话的基准路径。"),
            self,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: rgba(0, 0, 0, 0.50); font-size: 13px; line-height: 1.5;")
        main_layout.addWidget(desc)

        # Browse button card
        browse_card = CardWidget(self)
        browse_card.setObjectName("browseCard")
        browse_card.setBorderRadius(10)
        browse_card.setStyleSheet(
            "CardWidget#browseCard {"
            "  background-color: rgba(255, 255, 255, 0.98);"
            "  border: 1px solid rgba(0, 0, 0, 0.08);"
            "  border-radius: 10px;"
            "}"
            "CardWidget#browseCard:hover {"
            "  background-color: rgba(250, 251, 252, 0.98);"
            "  border: 1px solid rgba(0, 0, 0, 0.14);"
            "}"
        )
        browse_card.setCursor(Qt.PointingHandCursor)
        browse_card.mousePressEvent = lambda _event: self._on_browse_clicked()  # type: ignore[method-assign]

        browse_layout = QHBoxLayout(browse_card)
        browse_layout.setContentsMargins(20, 18, 20, 18)
        browse_layout.setSpacing(14)

        browse_icon = ToolButton(FIF.FOLDER_ADD, browse_card)
        browse_icon.setFixedSize(40, 40)
        browse_icon.setEnabled(False)
        browse_layout.addWidget(browse_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        browse_text_layout = QVBoxLayout()
        browse_text_layout.setSpacing(2)
        browse_title = StrongBodyLabel(self.tr("浏览文件夹..."), browse_card)
        browse_title.setStyleSheet("font-size: 15px; font-weight: 600;")
        browse_hint = CaptionLabel(self.tr("从系统中选择一个已有的工作文件夹"), browse_card)
        browse_hint.setStyleSheet("color: rgba(0, 0, 0, 0.40);")
        browse_text_layout.addWidget(browse_title)
        browse_text_layout.addWidget(browse_hint)
        browse_layout.addLayout(browse_text_layout, 1)

        self.browse_button = PrimaryPushButton(self.tr("浏览"), browse_card)
        self.browse_button.setIcon(FIF.FOLDER)
        self.browse_button.setFixedWidth(100)
        self.browse_button.setFixedHeight(36)
        self.browse_button.clicked.connect(self._on_browse_clicked)
        browse_layout.addWidget(self.browse_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        main_layout.addWidget(browse_card)

        # Recent directories section header
        self.recent_title = StrongBodyLabel(self.tr("最近打开的工作区"), self)
        self.recent_title.setStyleSheet("font-size: 15px; font-weight: 600; color: #444;")
        main_layout.addWidget(self.recent_title)

        # Recent directories container
        self.recent_container = QWidget(self)
        self.recent_layout = QVBoxLayout(self.recent_container)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(10)
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
            empty_card = EmptyStateCard(parent=self.recent_container)
            self.recent_layout.insertWidget(self.recent_layout.count() - 1, empty_card)
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
