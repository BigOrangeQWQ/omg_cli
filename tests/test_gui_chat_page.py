import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _get_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_chat_page_emits_submission() -> None:
    from omg_cli.gui.chat_page import ChatPage

    _get_qapp()
    page = ChatPage()

    received: list[str] = []
    page.submitted.connect(received.append)

    page.composer.setPlainText("hello world")
    page._emit_composer_text()

    assert received == ["hello world"]


def test_chat_page_appends_messages() -> None:
    from omg_cli.gui.chat_page import ChatPage

    _get_qapp()
    page = ChatPage()

    page.append_message("assistant", "hi there")

    assert "hi there" in page.message_view.toPlainText()
