import pytest

import omg_cli.__main__ as cli_main
from omg_cli.config.session_storage import SessionMetadata


class _AdapterManagerStub:
    default_adapter = None

    def get_adapter(self, model_name: str):
        raise ValueError(model_name)

    def list_adapters(self):
        return []


class _FakeContext:
    pass


def test_restore_channel_session_auto_enables_channel_mode(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(cli_main, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli_main, "get_adapter_manager", lambda: _AdapterManagerStub())

    metadata = SessionMetadata(
        session_id="sess-channel",
        chat_mode="channel",
        workspace=tmp_path,
    )

    class _Storage:
        def load_metadata(self, session_id: str):
            if session_id == "sess-channel":
                return metadata
            return None

    monkeypatch.setattr(cli_main, "ChatSessionStorage", lambda: _Storage())

    fake_context = _FakeContext()

    class _ChannelContextStub:
        @classmethod
        def from_session(cls, session_id: str):
            calls["from_session_id"] = session_id
            return fake_context

    monkeypatch.setattr("omg_cli.context.role.ChannelContext", _ChannelContextStub)

    def _run_terminal(context, *, channel: bool = False):
        calls["context"] = context
        calls["channel"] = channel

    monkeypatch.setattr(cli_main, "run_terminal", _run_terminal)
    monkeypatch.setattr(cli_main, "run_gui", lambda context, channel=False: None)

    cli_main.main(["-r", "sess-channel"])

    assert calls["from_session_id"] == "sess-channel"
    assert calls["context"] is fake_context
    assert calls["channel"] is True


def test_restore_channel_session_missing_roles_error(monkeypatch, tmp_path) -> None:
    errors: list[str] = []

    monkeypatch.setattr(cli_main, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli_main, "get_adapter_manager", lambda: _AdapterManagerStub())
    monkeypatch.setattr(cli_main.logger, "error", lambda msg: errors.append(msg))

    metadata = SessionMetadata(
        session_id="sess-channel-missing-role",
        chat_mode="channel",
        workspace=tmp_path,
    )

    class _Storage:
        def load_metadata(self, session_id: str):
            if session_id == "sess-channel-missing-role":
                return metadata
            return None

    monkeypatch.setattr(cli_main, "ChatSessionStorage", lambda: _Storage())

    class _ChannelContextStub:
        @classmethod
        def from_session(cls, session_id: str):
            raise ValueError(f"Session '{session_id}' cannot be restored without a default role")

    monkeypatch.setattr("omg_cli.context.role.ChannelContext", _ChannelContextStub)

    with pytest.raises(SystemExit) as exc_info:
        cli_main.main(["-r", "sess-channel-missing-role"])

    assert exc_info.value.code == 1
    assert errors
    assert "缺少可用角色" in errors[-1]


def test_restore_channel_session_corrupted_data_error(monkeypatch, tmp_path) -> None:
    errors: list[str] = []

    monkeypatch.setattr(cli_main, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli_main, "get_adapter_manager", lambda: _AdapterManagerStub())
    monkeypatch.setattr(cli_main.logger, "error", lambda msg: errors.append(msg))

    metadata = SessionMetadata(
        session_id="sess-channel-broken",
        chat_mode="channel",
        workspace=tmp_path,
    )

    class _Storage:
        def load_metadata(self, session_id: str):
            if session_id == "sess-channel-broken":
                return metadata
            return None

    monkeypatch.setattr(cli_main, "ChatSessionStorage", lambda: _Storage())

    class _ChannelContextStub:
        @classmethod
        def from_session(cls, session_id: str):
            raise ValueError("bad thread status")

    monkeypatch.setattr("omg_cli.context.role.ChannelContext", _ChannelContextStub)

    with pytest.raises(SystemExit) as exc_info:
        cli_main.main(["-r", "sess-channel-broken"])

    assert exc_info.value.code == 1
    assert errors
    assert "数据损坏" in errors[-1]
