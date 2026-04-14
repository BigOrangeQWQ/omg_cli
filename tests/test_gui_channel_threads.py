from types import SimpleNamespace
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _get_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeDefaultContext:
    def __init__(self) -> None:
        self.handlers = []

    def register_event_handler(self, event_type, handler) -> None:
        self.handlers.append((event_type, handler))

    def list_saved_sessions(self):
        return []


def test_channel_tabbar_in_content_area(monkeypatch) -> None:
    from omg_cli.gui import Window

    _get_qapp()

    thread_0 = SimpleNamespace(id=0, title="Default Thread", status="draft", messages=[])
    thread_1 = SimpleNamespace(id=1, title="Design", status="running", messages=[])
    channel_context = SimpleNamespace(
        thread_map={0: thread_0, 1: thread_1},
        threads=[thread_0, thread_1],
        default_context=_FakeDefaultContext(),
        list_saved_sessions=lambda: [],
    )

    monkeypatch.setattr(Window, "initWindow", lambda self: None)

    window = Window(context=channel_context, channel=True, debug=False)

    # TabBar should stay in channel content area (not title bar/header).
    assert window.channelInterface.tab_bar.parent() is window.channelInterface
    assert window.channelInterface.main_layout.indexOf(window.channelInterface.tab_bar) == 0
    assert window.channelInterface.tab_bar.tabText(0) == "#0 Default Thread"
    assert window.channelInterface.tab_bar.tabText(1).startswith("🟢 #1 Design")


def test_channel_status_updates_tab_text() -> None:
    from omg_cli.gui.channel.interface import ChannelInterface

    _get_qapp()

    thread = SimpleNamespace(id=1, title="Docs", status="draft", messages=[])
    channel_context = SimpleNamespace(
        thread_map={1: thread},
        threads=[thread],
        default_context=_FakeDefaultContext(),
    )

    interface = ChannelInterface(channel_context=channel_context)
    assert interface.tab_bar.tabText(0).startswith("📝 #1 Docs")

    interface._on_thread_status_changed(1, "done")
    assert thread.status == "done"
    assert interface.tab_bar.tabText(0).startswith("✅ #1 Docs")


from types import SimpleNamespace
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _get_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeDefaultContext:
    def __init__(self) -> None:
        self.handlers = []

    def register_event_handler(self, event_type, handler) -> None:
        self.handlers.append((event_type, handler))


def test_channel_header_tabbar_uses_thread_status_emojis(monkeypatch) -> None:
    from omg_cli.gui import Window

    _get_qapp()

    thread_0 = SimpleNamespace(id=0, title="Default Thread", status="draft", messages=[])
    thread_1 = SimpleNamespace(id=1, title="Design", status="running", messages=[])
    channel_context = SimpleNamespace(
        thread_map={0: thread_0, 1: thread_1},
        threads=[thread_0, thread_1],
        default_context=_FakeDefaultContext(),
    )

    monkeypatch.setattr(Window, "initWindow", lambda self: None)

    window = Window(context=channel_context, channel=True, debug=False)

    assert window.channelInterface.tab_bar.parent() is window.titleBar
    assert window.channelInterface.tab_bar.tabText(0) == "#0 Default Thread"
    assert window.channelInterface.tab_bar.tabText(1).startswith("🟢 #1 Design")


def test_channel_status_updates_tab_text(monkeypatch) -> None:
    from omg_cli.gui.channel.interface import ChannelInterface

    _get_qapp()

    thread = SimpleNamespace(id=1, title="Docs", status="draft", messages=[])
    channel_context = SimpleNamespace(
        thread_map={1: thread},
        threads=[thread],
        default_context=_FakeDefaultContext(),
    )

    interface = ChannelInterface(channel_context=channel_context)
    assert interface.tab_bar.tabText(0).startswith("📝 #1 Docs")

    interface._on_thread_status_changed(1, "done")
    assert thread.status == "done"
    assert interface.tab_bar.tabText(0).startswith("✅ #1 Docs")


from datetime import datetime
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _get_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeBridge:
    def __init__(self, *, root_context=None) -> None:
        from PySide6.QtCore import QObject, Signal

        class _Signals(QObject):
            message_received = Signal(object)
            thread_message_received = Signal(int, object)
            stream_delta_received = Signal(object)
            stream_completed_received = Signal(object)
            status_changed = Signal(str)
            error_received = Signal(str)
            role_activity_received = Signal(int, str, str, str)
            thread_status_changed = Signal(int, str)
            thread_spawned = Signal(int, str)

        self.context = SimpleNamespace(set_tool_confirmation_handler=lambda _h: None)
        self.root_context = root_context or SimpleNamespace(thread_map={}, default_context=SimpleNamespace(_emit=None))
        self._signals = _Signals()
        self.message_received = self._signals.message_received
        self.thread_message_received = self._signals.thread_message_received
        self.stream_delta_received = self._signals.stream_delta_received
        self.stream_completed_received = self._signals.stream_completed_received
        self.status_changed = self._signals.status_changed
        self.error_received = self._signals.error_received
        self.role_activity_received = self._signals.role_activity_received
        self.thread_status_changed = self._signals.thread_status_changed
        self.thread_spawned = self._signals.thread_spawned


def test_channel_thread_switch_updates_visible_messages(monkeypatch) -> None:
    from omg_cli.gui.main_window import MainWindow
    from omg_cli.gui.state import GuiAppState

    _get_qapp()

    msg_t1 = SimpleNamespace(role="assistant", name="coder", text="thread-1 message")
    msg_t2 = SimpleNamespace(role="assistant", name="reviewer", text="thread-2 message")
    state = GuiAppState(
        channel_mode=True,
        session_id="sid",
        active_thread_id=1,
        thread_messages={1: [msg_t1], 2: [msg_t2]},
        thread_status={1: "running", 2: "draft"},
    )
    state.set_active_thread(1)

    monkeypatch.setattr(MainWindow, "_register_meta_commands", lambda self: None)

    window = MainWindow(state, _FakeBridge())

    assert "thread-1 message" in window.chat_page.message_view.toPlainText()
    assert "thread-2 message" not in window.chat_page.message_view.toPlainText()

    index_t2 = window.thread_selector.findData(2)
    window.thread_selector.setCurrentIndex(index_t2)

    assert "thread-2 message" in window.chat_page.message_view.toPlainText()
    assert "thread-1 message" not in window.chat_page.message_view.toPlainText()


def test_channel_thread_message_ignores_non_active_thread(monkeypatch) -> None:
    from omg_cli.gui.main_window import MainWindow
    from omg_cli.gui.state import GuiAppState

    _get_qapp()

    state = GuiAppState(
        channel_mode=True,
        session_id="sid",
        active_thread_id=1,
        thread_messages={1: []},
        thread_status={1: "running"},
    )

    monkeypatch.setattr(MainWindow, "_register_meta_commands", lambda self: None)

    window = MainWindow(state, _FakeBridge())

    window._on_thread_message(2, SimpleNamespace(role="assistant", name="other", text="should-not-show"))

    assert "should-not-show" not in window.chat_page.message_view.toPlainText()


def test_channel_set_thread_status_updates_state_and_thread(monkeypatch) -> None:
    from omg_cli.gui.main_window import MainWindow
    from omg_cli.gui.state import GuiAppState

    _get_qapp()

    thread_obj = SimpleNamespace(
        id=1,
        title="T1",
        status="running",
        assigned_role_names=["coder"],
        reviewer_role_names=["reviewer"],
    )
    root_context = SimpleNamespace(thread_map={1: thread_obj}, default_context=SimpleNamespace(_emit=None))

    state = GuiAppState(
        channel_mode=True,
        session_id="sid",
        active_thread_id=1,
        thread_messages={1: [SimpleNamespace(role="assistant", name="coder", text="hello")]},
        thread_status={1: "running"},
    )

    monkeypatch.setattr(MainWindow, "_register_meta_commands", lambda self: None)

    window = MainWindow(state, _FakeBridge(root_context=root_context))
    window.thread_status_selector.setCurrentText("done")
    window._on_set_thread_status()

    assert thread_obj.status == "done"
    assert state.thread_status[1] == "done"
    assert "[done]" in window.thread_selector.currentText()


def test_channel_thread_meta_shows_roles_and_counts(monkeypatch) -> None:
    from omg_cli.gui.main_window import MainWindow
    from omg_cli.gui.state import GuiAppState

    _get_qapp()

    thread_obj = SimpleNamespace(
        id=1,
        title="Design",
        status="draft",
        assigned_role_names=["coder", "qa"],
        reviewer_role_names=["reviewer"],
    )
    root_context = SimpleNamespace(thread_map={1: thread_obj}, default_context=SimpleNamespace(_emit=None))

    state = GuiAppState(
        channel_mode=True,
        session_id="sid",
        active_thread_id=1,
        thread_messages={1: [SimpleNamespace(role="assistant", name="coder", text="m1")]},
        thread_status={1: "draft"},
    )

    monkeypatch.setattr(MainWindow, "_register_meta_commands", lambda self: None)

    window = MainWindow(state, _FakeBridge(root_context=root_context))

    meta_text = window.thread_meta.text()
    assert "roles=coder,qa" in meta_text
    assert "reviewers=reviewer" in meta_text
    assert "msgs=1" in meta_text


def test_channel_inspect_panel_renders_and_updates_role_activity(monkeypatch) -> None:
    from omg_cli.gui.main_window import MainWindow
    from omg_cli.gui.state import GuiAppState

    _get_qapp()

    record = SimpleNamespace(
        created_at=datetime.now(),
        activity_type="status",
        content="initial status",
    )
    root_context = SimpleNamespace(
        thread_map={1: SimpleNamespace(id=1, title="T1", assigned_role_names=["coder"], reviewer_role_names=[])},
        default_context=SimpleNamespace(_emit=None),
        roles=[SimpleNamespace(name="coder")],
    )
    state = GuiAppState(
        channel_mode=True,
        session_id="sid",
        active_thread_id=1,
        thread_messages={1: []},
        thread_status={1: "running"},
        role_activities={(1, "coder"): [record]},
    )

    monkeypatch.setattr(MainWindow, "_register_meta_commands", lambda self: None)

    window = MainWindow(state, _FakeBridge(root_context=root_context))

    inspect_text = window.chat_page.inspect_view.toPlainText()
    assert "initial status" in inspect_text

    window._on_role_activity(1, "coder", "status", "live update")
    inspect_text = window.chat_page.inspect_view.toPlainText()
    assert "live update" in inspect_text
