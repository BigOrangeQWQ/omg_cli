from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, DirectoryPath, Field

from omg_cli.types.channel_session import ChannelSessionState
from omg_cli.types.message import Message


class SessionMetadata(BaseModel):
    session_id: str
    chat_mode: Literal["chat", "channel"] = "chat"
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    workspace: DirectoryPath
    title: str | None = None
    model_name: str | None = None
    custom: dict[str, Any] = {}


class SessionStorage:
    """Manages persistent storage of chat sessions.

    Storage layout:
        ~/.omg_cli/sessions/
        └── <session_id>/
            ├── metadata.json  # Session metadata
            └── messages.jsonl # Messages in JSON Lines format
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        if config_dir is None:
            from omg_cli.config.manager import get_config_manager

            config_dir = get_config_manager().config_dir
        self.config_dir = config_dir
        self.sessions_dir = self.config_dir / "sessions"

    def _ensure_dir_exists(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.chmod(0o700)

    def _get_session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / session_id

    def _get_meta_path(self, session_id: str) -> Path:
        return self._get_session_dir(session_id) / "metadata.json"

    def _get_messages_path(self, session_id: str) -> Path:
        return self._get_session_dir(session_id) / "messages.jsonl"

    def _get_channel_state_path(self, session_id: str) -> Path:
        return self._get_session_dir(session_id) / "channel_state.json"

    def save_metadata(self, metadata: SessionMetadata) -> None:
        self._ensure_dir_exists()

        session_dir = self._get_session_dir(metadata.session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        meta_path = self._get_meta_path(metadata.session_id)

        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(metadata.model_dump_json(indent=2))

    def load_metadata(self, session_id: str) -> SessionMetadata | None:
        meta_path = self._get_meta_path(session_id)
        if not meta_path.exists():
            return None

        try:
            with open(meta_path, encoding="utf-8") as f:
                data = f.read()
            return SessionMetadata.model_validate_json(data)
        except Exception:
            return None

    def append_message(self, session_id: str, message: Message | list[Message]) -> None:
        """Append a single message to the session's messages file."""
        messages_path = self._get_messages_path(session_id)
        messages_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(message, Message):
            message = [message]

        with open(messages_path, "a", encoding="utf-8") as f:
            for msg in message:
                f.write(msg.model_dump_json() + "\n")

        metadata = self.load_metadata(session_id)
        if metadata:
            metadata.updated_at = datetime.now(tz=UTC)
            self.save_metadata(metadata)

    def save_messages(self, session_id: str, messages: list[Message]) -> None:
        """
        Overwrite the entire messages file for a session.
        Used for bulk updates like deletion or reordering.
        """
        messages_path = self._get_messages_path(session_id)
        messages_path.parent.mkdir(parents=True, exist_ok=True)

        with open(messages_path, "w", encoding="utf-8") as f:
            for message in messages:
                f.write(message.model_dump_json() + "\n")

    def save_channel_session(self, session_id: str, state: ChannelSessionState) -> None:
        """Persist a ChannelSessionState to the session's channel_state.json file."""
        channel_state_path = self._get_channel_state_path(session_id)
        channel_state_path.parent.mkdir(parents=True, exist_ok=True)

        with open(channel_state_path, "w", encoding="utf-8") as f:
            f.write(state.model_dump_json(indent=2))

        metadata = self.load_metadata(session_id)
        if metadata:
            metadata.updated_at = datetime.now(tz=UTC)
            self.save_metadata(metadata)

    def load_channel_session(self, session_id: str) -> ChannelSessionState | None:
        """Load a ChannelSessionState from the session's channel_state.json file."""
        channel_state_path = self._get_channel_state_path(session_id)
        if not channel_state_path.exists():
            return None

        try:
            with open(channel_state_path, encoding="utf-8") as f:
                data = f.read()
            return ChannelSessionState.model_validate_json(data)
        except Exception:
            return None

    def load_messages(self, session_id: str) -> list[Message]:
        messages_path = self._get_messages_path(session_id)
        if not messages_path.exists():
            return []

        messages: list[Message] = []
        try:
            with open(messages_path, encoding="utf-8") as f:
                for line in f:
                    if line := line.strip():
                        msg = Message.model_validate_json(line)
                        messages.append(msg)
        except Exception:
            pass

        return messages

    def delete(self, session_id: str) -> bool:
        session_dir = self._get_session_dir(session_id)

        if session_dir.exists():
            for file_path in session_dir.iterdir():
                file_path.unlink()
            session_dir.rmdir()
            return True
        return False

    def list_sessions(self) -> list[SessionMetadata]:
        if not self.sessions_dir.exists():
            return []

        sessions: list[SessionMetadata] = []
        for session_dir in self.sessions_dir.iterdir():
            if session_dir.is_dir():
                session_id = session_dir.name
                metadata = self.load_metadata(session_id)
                if metadata:
                    sessions.append(metadata)

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions
