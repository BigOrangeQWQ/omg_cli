from datetime import UTC, datetime, timedelta

from omg_cli.config.session_storage import (
    ChannelSessionStorage,
    ChannelThreadMetadata,
    ChatSessionStorage,
    SessionMetadata,
)
from omg_cli.types.channel import RoleActivityRecord
from omg_cli.types.message import Message, TextSegment


def _make_metadata(session_id: str, workspace, chat_mode: str = "chat") -> SessionMetadata:
    return SessionMetadata(
        session_id=session_id,
        chat_mode=chat_mode,
        workspace=workspace,
        created_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        updated_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )


def test_chat_storage_uses_shared_metadata_ops(tmp_path) -> None:
    storage = ChatSessionStorage(config_dir=tmp_path)
    metadata = _make_metadata("chat-1", tmp_path, chat_mode="chat")
    storage.save_metadata(metadata)

    loaded = storage.load_metadata("chat-1")
    assert loaded is not None
    assert loaded.session_id == "chat-1"

    sessions = storage.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].session_id == "chat-1"


def test_channel_storage_uses_shared_metadata_ops(tmp_path) -> None:
    storage = ChannelSessionStorage(config_dir=tmp_path)
    metadata = _make_metadata("channel-1", tmp_path, chat_mode="channel")
    storage.save_metadata(metadata)

    loaded = storage.load_metadata("channel-1")
    assert loaded is not None
    assert loaded.chat_mode == "channel"

    sessions = storage.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].session_id == "channel-1"


def test_channel_messages_append_save_and_load(tmp_path) -> None:
    storage = ChannelSessionStorage(config_dir=tmp_path)
    session_id = "channel-msg"
    thread_id = 1
    storage.save_metadata(_make_metadata(session_id, tmp_path, chat_mode="channel"))

    thread_metadata = ChannelThreadMetadata(
        thread_id=thread_id,
        title="Thread Title",
        description="Thread description",
        assigned_role_names=["coder"],
        reviewer_role_names=["reviewer"],
    )
    storage.save_thread_metadata(session_id, thread_metadata)

    msg1 = Message(role="user", content=[TextSegment(text="first")])
    msg2 = Message(role="assistant", name="coder", content=[TextSegment(text="second")])

    storage.append_message(session_id, thread_id, msg1)
    storage.append_message(session_id, thread_id, [msg2])

    loaded = storage.load_messages(session_id, thread_id)
    assert [m.text for m in loaded] == ["first", "second"]

    loaded_thread_metadata = storage.load_thread_metadata(session_id, thread_id)
    assert loaded_thread_metadata is not None
    assert loaded_thread_metadata.thread_id == thread_id
    assert loaded_thread_metadata.title == "Thread Title"

    thread_dir = tmp_path / "sessions" / session_id / "threads" / str(thread_id)
    assert (thread_dir / "metadata.json").exists()
    assert (thread_dir / "messages.jsonl").exists()

    replacement = Message(role="assistant", content=[TextSegment(text="replacement")])
    storage.save_messages(session_id, thread_id, [replacement])
    loaded_after_save = storage.load_messages(session_id, thread_id)
    assert [m.text for m in loaded_after_save] == ["replacement"]


def test_channel_role_activity_append_save_and_load(tmp_path) -> None:
    storage = ChannelSessionStorage(config_dir=tmp_path)
    session_id = "channel-activity"
    thread_id = 2
    role_name = "coder"
    storage.save_metadata(_make_metadata(session_id, tmp_path, chat_mode="channel"))

    item1 = RoleActivityRecord(activity_type="status", content="working")
    item2 = RoleActivityRecord(activity_type="error", content="failed")

    storage.append_role_activity(session_id, role_name, thread_id, item1)
    storage.append_role_activity(session_id, role_name, thread_id, [item2])

    loaded = storage.load_role_activities(session_id, role_name, thread_id)
    assert [a.activity_type for a in loaded] == ["status", "error"]

    thread_dir = tmp_path / "sessions" / session_id / "threads" / str(thread_id)
    assert (thread_dir / f"{role_name}_activity.json").exists()

    replacement = RoleActivityRecord(activity_type="message", content="done")
    storage.save_role_activities(session_id, role_name, thread_id, [replacement])
    loaded_after_save = storage.load_role_activities(session_id, role_name, thread_id)
    assert [a.activity_type for a in loaded_after_save] == ["message"]
    assert [a.content for a in loaded_after_save] == ["done"]


def test_channel_role_context_save_and_load(tmp_path) -> None:
    storage = ChannelSessionStorage(config_dir=tmp_path)
    session_id = "channel-context"
    thread_id = 3
    role_name = "reviewer"
    storage.save_metadata(_make_metadata(session_id, tmp_path, chat_mode="channel"))

    context = {"last_round": 5, "note": "need review", "flags": ["a", "b"]}
    storage.save_role_context(session_id, role_name, thread_id, context)

    loaded = storage.load_role_context(session_id, role_name, thread_id)
    assert loaded == context

    thread_dir = tmp_path / "sessions" / session_id / "threads" / str(thread_id)
    assert (thread_dir / f"{role_name}_context.json").exists()


def test_delete_removes_nested_session_dir(tmp_path) -> None:
    storage = ChannelSessionStorage(config_dir=tmp_path)
    session_id = "channel-delete"
    storage.save_metadata(_make_metadata(session_id, tmp_path, chat_mode="channel"))
    storage.save_role_context(session_id, "coder", 1, {"foo": "bar"})

    assert storage.delete(session_id) is True
    assert storage.load_metadata(session_id) is None
    assert storage.delete(session_id) is False
