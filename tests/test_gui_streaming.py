from contextlib import contextmanager
import os
import sys
from types import ModuleType, SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _get_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@contextmanager
def _fake_runtime_types():
    event_module = ModuleType("omg_cli.types.event")
    channel_module = ModuleType("omg_cli.types.channel")

    class BaseEvent:
        pass

    class SessionMessageEvent(BaseEvent):
        def __init__(self, message) -> None:
            self.message = message

    class SessionStatusEvent(BaseEvent):
        def __init__(self, detail=None) -> None:
            self.detail = detail

    class SessionErrorEvent(BaseEvent):
        def __init__(self, error) -> None:
            self.error = error

    class SessionStreamDeltaEvent(BaseEvent):
        def __init__(self, stream_event) -> None:
            self.stream_event = stream_event

    class SessionStreamCompletedEvent(BaseEvent):
        def __init__(self, stream_event) -> None:
            self.stream_event = stream_event

    class ThreadMessageEvent(BaseEvent):
        def __init__(self, thread_id, message) -> None:
            self.thread_id = thread_id
            self.message = message

    class ThreadSpawnedEvent(BaseEvent):
        def __init__(self, thread, first_message) -> None:
            self.thread = thread
            self.first_message = first_message

    class ThreadStatusChangedEvent(BaseEvent):
        def __init__(self, thread_id, status) -> None:
            self.thread_id = thread_id
            self.status = status

    class RoleActivityEvent(BaseEvent):
        def __init__(self, thread_id, role_name, activity_type, content) -> None:
            self.thread_id = thread_id
            self.role_name = role_name
            self.activity_type = activity_type
            self.content = content

    class RoleActivityRecord:
        def __init__(self, activity_type, content) -> None:
            self.activity_type = activity_type
            self.content = content

    class ThreadStatus:
        def __init__(self, value) -> None:
            self.value = value

    class Thread:
        def __init__(self, thread_id=0, messages=None, status=None, title="thread") -> None:
            self.id = thread_id
            self.messages = list(messages or [])
            self.status = status or ThreadStatus("active")
            self.title = title

    event_module.BaseEvent = BaseEvent
    event_module.SessionMessageEvent = SessionMessageEvent
    event_module.SessionStatusEvent = SessionStatusEvent
    event_module.SessionErrorEvent = SessionErrorEvent
    event_module.SessionStreamDeltaEvent = SessionStreamDeltaEvent
    event_module.SessionStreamCompletedEvent = SessionStreamCompletedEvent
    event_module.ThreadMessageEvent = ThreadMessageEvent
    event_module.ThreadSpawnedEvent = ThreadSpawnedEvent
    event_module.ThreadStatusChangedEvent = ThreadStatusChangedEvent
    event_module.RoleActivityEvent = RoleActivityEvent
    channel_module.RoleActivityRecord = RoleActivityRecord
    channel_module.Thread = Thread

    original_event = sys.modules.get("omg_cli.types.event")
    original_channel = sys.modules.get("omg_cli.types.channel")
    sys.modules["omg_cli.types.event"] = event_module
    sys.modules["omg_cli.types.channel"] = channel_module
    try:
        yield event_module, channel_module
    finally:
        if original_event is not None:
            sys.modules["omg_cli.types.event"] = original_event
        else:
            sys.modules.pop("omg_cli.types.event", None)

        if original_channel is not None:
            sys.modules["omg_cli.types.channel"] = original_channel
        else:
            sys.modules.pop("omg_cli.types.channel", None)


def test_chat_page_stream_preview_updates_and_clears() -> None:
    from omg_cli.gui.chat_page import ChatPage

    _get_qapp()
    page = ChatPage()

    page.append_stream_preview("[thinking] loading")

    assert "loading" in page.stream_view.toPlainText()

    page.clear_stream_preview()

    assert page.stream_view.toPlainText() == ""


def test_bridge_emits_stream_events_without_touching_messages() -> None:
    with _fake_runtime_types() as (event_module, _channel_module):
        from omg_cli.gui.bridge import ContextEventBridge
        from omg_cli.gui.state import GuiAppState

        class FakeContext:
            def __init__(self) -> None:
                self.handlers = []

            def register_event_handler(self, event_type, handler):
                self.handlers.append((event_type, handler))

        _get_qapp()
        state = GuiAppState(channel_mode=False, session_id="session-1")
        bridge = ContextEventBridge(FakeContext(), state, channel=False)

        deltas: list[str] = []
        completes: list[str] = []
        bridge.stream_delta_received.connect(lambda stream_event: deltas.append(stream_event.segment.text))
        bridge.stream_completed_received.connect(lambda stream_event: completes.append(stream_event.segment.text))

        delta_event = event_module.SessionStreamDeltaEvent(
            stream_event=SimpleNamespace(segment=SimpleNamespace(type="text_detail", text="partial"))
        )
        complete_event = event_module.SessionStreamCompletedEvent(
            stream_event=SimpleNamespace(segment=SimpleNamespace(type="text", text="final"))
        )

        bridge._apply_event(delta_event)
        bridge._apply_event(complete_event)

        assert deltas == ["partial"]
        assert completes == ["final"]
        assert state.messages == []


def test_main_window_tool_confirmation_round_trip() -> None:
    with _fake_runtime_types():
        from omg_cli.gui.bridge import ContextEventBridge
        from omg_cli.gui.main_window import MainWindow
        from omg_cli.gui.state import GuiAppState
        from omg_cli.gui.tool_confirmation import ToolConfirmationDecision

        class FakeContext:
            def __init__(self) -> None:
                self.handlers = []
                self.tool_confirmation_handler = None

            def register_event_handler(self, event_type, handler):
                self.handlers.append((event_type, handler))

            def set_tool_confirmation_handler(self, handler):
                self.tool_confirmation_handler = handler

            async def send(self, text):
                return text

            def interrupt(self):
                return None

        class FakeTool:
            def __init__(self) -> None:
                self.name = "demo"
                self.description = "demo tool"
                self.confirm = True

        tool_call = SimpleNamespace(function=SimpleNamespace(name="demo", arguments={"value": "x"}))

        _get_qapp()
        state = GuiAppState(channel_mode=False, session_id="session-2")
        bridge = ContextEventBridge(FakeContext(), state, channel=False)
        window = MainWindow(state, bridge)

        window.tool_confirmation_requested.disconnect()
        window.tool_confirmation_requested.connect(lambda request: request.approve(reason="allowed"))

        decision = window._confirm_tool_call(tool_call, FakeTool())

        assert isinstance(decision, ToolConfirmationDecision)
        assert decision.approved is True
        assert decision.reason == "allowed"
