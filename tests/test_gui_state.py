from omg_cli.gui.state import GuiAppState
from omg_cli.types.event import RoleActivityEvent, SessionMessageEvent, ThreadMessageEvent
from omg_cli.types.message import Message, TextSegment


def test_role_activity_isolated_from_message_history() -> None:
    state = GuiAppState(channel_mode=True, session_id="sid", active_thread_id=1)

    thread_message = Message(role="assistant", content=[TextSegment(text="hello")])
    state.apply_event(ThreadMessageEvent(thread_id=1, message=thread_message))

    state.apply_event(
        RoleActivityEvent(
            thread_id=1,
            role_name="coder",
            activity_type="status",
            content="internal status",
        )
    )

    assert len(state.thread_messages[1]) == 1
    assert state.thread_messages[1][0].text == "hello"
    assert (1, "coder") in state.role_activities


def test_session_message_appends_in_chat_mode() -> None:
    state = GuiAppState(channel_mode=False, session_id="sid")

    message = Message(role="assistant", content=[TextSegment(text="pong")])
    state.apply_event(SessionMessageEvent(message=message))

    assert len(state.messages) == 1
    assert state.messages[0].text == "pong"
