"""GUI entrypoints and compatibility exports."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget
from qasync import QEventLoop
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import MSFluentWindow, SubtitleLabel, Theme, setFont, setTheme

from omg_cli.gui.utils import emoji_to_pixmap


def _try_apply_sources_font(app: QApplication) -> bool:
    font_path = Path(__file__).resolve().parent.parent.parent / "sources" / "HarmonyOS_Sans_Regular.ttf"
    if not font_path.exists():
        return False

    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id < 0:
        return False

    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        return False

    app.setFont(QFont(families[0]))
    return True


class Widget(QWidget):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.label = SubtitleLabel(text, self)
        self.hBoxLayout = QHBoxLayout(self)
        setFont(self.label, 24)
        self.label.setAlignment(Qt.AlignCenter)
        self.hBoxLayout.addWidget(self.label, 1, Qt.AlignCenter)
        self.setObjectName(text.replace(" ", "-"))


class Window(MSFluentWindow):
    def __init__(self, *, context: Any | None = None, debug: bool = False) -> None:
        super().__init__()

        from omg_cli.gui.chat import ChatInterface
        from omg_cli.gui.session import SessionInterface

        self.chatInterface = ChatInterface(context=context, debug=debug, parent=self)
        self.sessionInterface = SessionInterface(context=context, parent=self)
        self.initNavigation()
        self.initWindow()

    def initNavigation(self) -> None:
        self.addSubInterface(self.chatInterface, FIF.CHAT, "对话", FIF.CHAT)
        self.addSubInterface(self.sessionInterface, FIF.HISTORY, "会话历史", FIF.HISTORY)

    def initWindow(self) -> None:
        self.resize(1000, 800)
        self.setWindowTitle("OMG Code Demo")
        self.setWindowIcon(emoji_to_pixmap("🤯"))

        desktop = QApplication.screens()[0].availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)


def _resolve_chat_context(context: Any, channel: bool) -> Any:
    if context is None:
        return None
    if channel and hasattr(context, "default_context"):
        return context.default_context
    return context


def run_gui(*, context: Any | None = None, channel: bool = False, debug: bool = False) -> None:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    elif not isinstance(app, QApplication):
        app = QApplication(sys.argv)

    owns_app = QApplication.instance() is app

    setTheme(Theme.DARK)
    _try_apply_sources_font(app)

    chat_context = _resolve_chat_context(context, channel)
    window = Window(context=chat_context, debug=debug)

    window.show()

    if not owns_app:
        return

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    app.aboutToQuit.connect(loop.stop)
    with loop:
        loop.run_forever()
