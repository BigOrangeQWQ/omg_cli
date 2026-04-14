import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _get_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeLogger:
    def __init__(self) -> None:
        self.errors: list[str] = []

    async def error(self, message: str) -> None:
        self.errors.append(message)


class _FakeCommandRegistry:
    def __init__(self, command=None, command_map=None) -> None:
        self._command = command
        self._command_map = command_map or {}

    def get(self, name: str):
        if name in self._command_map:
            return self._command_map[name]
        return self._command


class _FakeContext:
    def __init__(self, command=None, suggestions=None, command_map=None) -> None:
        self.command_registry = _FakeCommandRegistry(command, command_map=command_map)
        self.logger = _FakeLogger()
        self._suggestions = suggestions or []

    def find_commands(self, _prefix: str):
        return self._suggestions

    def set_tool_confirmation_handler(self, _handler):
        return None


class _FakeBridge:
    def __init__(self, context) -> None:
        from PySide6.QtCore import QObject, Signal

        class _Signals(QObject):
            message_received = Signal(object)
            thread_message_received = Signal(int, object)
            stream_delta_received = Signal(object)
            stream_completed_received = Signal(object)
            status_changed = Signal(str)
            error_received = Signal(str)
            role_activity_received = Signal(int, str, str, str)

        self.context = context
        self._signals = _Signals()
        self.message_received = self._signals.message_received
        self.thread_message_received = self._signals.thread_message_received
        self.stream_delta_received = self._signals.stream_delta_received
        self.stream_completed_received = self._signals.stream_completed_received
        self.status_changed = self._signals.status_changed
        self.error_received = self._signals.error_received
        self.role_activity_received = self._signals.role_activity_received


def test_run_meta_command_executes_handler(monkeypatch) -> None:
    from omg_cli.gui.main_window import MainWindow
    from omg_cli.gui.state import GuiAppState

    _get_qapp()

    called: list[str] = []

    async def _handler(_ctx, args: str):
        called.append(args)

    command = type("Cmd", (), {"handler": _handler})
    context = _FakeContext(command=command)
    bridge = _FakeBridge(context)

    monkeypatch.setattr(MainWindow, "_register_meta_commands", lambda self: None)

    window = MainWindow(GuiAppState(channel_mode=False, session_id="sid"), bridge)
    asyncio.run(window._run_meta_command("/help topic"))

    assert called == ["topic"]


def test_run_meta_command_unknown_command_logs_error(monkeypatch) -> None:
    from omg_cli.gui.main_window import MainWindow
    from omg_cli.gui.state import GuiAppState

    _get_qapp()
    context = _FakeContext(command=None)
    bridge = _FakeBridge(context)

    monkeypatch.setattr(MainWindow, "_register_meta_commands", lambda self: None)

    window = MainWindow(GuiAppState(channel_mode=False, session_id="sid"), bridge)
    asyncio.run(window._run_meta_command("/unknown"))

    assert context.logger.errors
    assert "Unknown command" in context.logger.errors[0]


def test_composer_command_suggestions_and_fill(monkeypatch) -> None:
    from omg_cli.gui.main_window import MainWindow
    from omg_cli.gui.state import GuiAppState

    _get_qapp()

    suggestion = type("Cmd", (), {"name": "models", "description_zh": "列出可用模型"})
    context = _FakeContext(suggestions=[suggestion])
    bridge = _FakeBridge(context)

    monkeypatch.setattr(MainWindow, "_register_meta_commands", lambda self: None)

    window = MainWindow(GuiAppState(channel_mode=False, session_id="sid"), bridge)

    window._on_composer_text_changed("/mo")
    assert window.chat_page.command_list.isHidden() is False
    assert window.chat_page.command_list.count() == 1

    window._on_command_selected("/models")
    assert window.chat_page.composer.toPlainText() == "/models "


def test_argument_completer_suggestions_and_keyboard_accept(monkeypatch) -> None:
    from omg_cli.gui.main_window import MainWindow
    from omg_cli.gui.state import GuiAppState

    _get_qapp()

    def _completer(_ctx, prefix: str):
        return [name for name in ["gpt-4o", "gpt-4o-mini"] if name.startswith(prefix)]

    switch_cmd = type(
        "Cmd",
        (),
        {"name": "switch", "description_zh": "切换模型", "completer": _completer},
    )
    context = _FakeContext(command_map={"switch": switch_cmd})
    bridge = _FakeBridge(context)

    monkeypatch.setattr(MainWindow, "_register_meta_commands", lambda self: None)

    window = MainWindow(GuiAppState(channel_mode=False, session_id="sid"), bridge)

    window._on_composer_text_changed("/switch gpt-4")
    assert window.chat_page.command_list.count() == 2

    window._on_command_next_requested()
    selected = window.chat_page.selected_command_text()
    assert selected in ["/switch gpt-4o ", "/switch gpt-4o-mini "]

    window._on_command_accept_requested()
    assert window.chat_page.composer.toPlainText().startswith("/switch gpt-4o")
