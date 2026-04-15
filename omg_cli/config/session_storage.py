from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, DirectoryPath, Field

from omg_cli.types.channel import RoleActivityRecord, Thread
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

    class Config:
        extra = "allow"


class ChannelThreadMetadata(BaseModel):
    thread_id: int
    title: str
    description: str = ""
    assigned_role_names: list[str] = Field(default_factory=list)
    reviewer_role_names: list[str] = Field(default_factory=list)
    status: str = "draft"
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @classmethod
    def from_thread(cls, thread: Thread) -> "ChannelThreadMetadata":
        return cls(
            thread_id=thread.id,
            title=thread.title,
            description=thread.description,
            assigned_role_names=thread.assigned_role_names,
            reviewer_role_names=thread.reviewer_role_names,
            status=thread.status.value,
            created_at=thread.created_at,
        )


class SessionStorageBase:
    """Shared metadata and session directory operations for all session storage variants."""

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

    def _touch_metadata_updated_at(self, session_id: str) -> None:
        metadata = self.load_metadata(session_id)
        if metadata:
            metadata.updated_at = datetime.now(tz=UTC)
            self.save_metadata(metadata)

    def delete(self, session_id: str) -> bool:
        session_dir = self._get_session_dir(session_id)

        if not session_dir.exists():
            return False

        # Remove deepest files/dirs first so both flat and nested layouts are supported.
        for path in sorted(session_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        session_dir.rmdir()
        return True

    def list_sessions(self) -> list[SessionMetadata]:
        if not self.sessions_dir.exists():
            return []

        sessions: list[SessionMetadata] = []
        for session_dir in self.sessions_dir.iterdir():
            if session_dir.is_dir():
                metadata = self.load_metadata(session_dir.name)
                if metadata:
                    sessions.append(metadata)

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions


class ChatSessionStorage(SessionStorageBase):
    """Manages persistent storage of chat sessions.

    Storage layout:
        ~/.omg_cli/sessions/
        └── <session_id>/
            ├── metadata.json  # Session metadata
            └── messages.jsonl # Messages in JSON Lines format
    """

    def _get_messages_path(self, session_id: str) -> Path:
        return self._get_session_dir(session_id) / "messages.jsonl"

    def _get_channel_state_path(self, session_id: str) -> Path:
        return self._get_session_dir(session_id) / "channel_state.json"

    def append_message(self, session_id: str, message: Message | list[Message]) -> None:
        """Append a single message to the session's messages file."""
        messages_path = self._get_messages_path(session_id)
        messages_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(message, Message):
            message = [message]

        with open(messages_path, "a", encoding="utf-8") as f:
            for msg in message:
                f.write(msg.model_dump_json() + "\n")

        self._touch_metadata_updated_at(session_id)

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


class ChannelSessionStorage(SessionStorageBase):
    """
    Manages persistent storage of channel sessions.

    Storage layout:
        ~/.omg_cli/sessions/
        └── <session_id>/
            ├── metadata.json  # Session metadata (chat_mode="channel")
            └── threads/
                └──<thread_id>/
                    ├── metadata.json  # Thread metadata list
                    ├── messages.jsonl  # Thread-specific data
                    ├── <role_name>_activity.jsonl  # Role activity history
                    └── <role_name>_context.jsonl  # Role-specific context data
    """

    def _get_threads_dir(self, session_id: str) -> Path:
        return self._get_session_dir(session_id) / "threads"

    def _get_thread_dir(self, session_id: str, thread_id: int) -> Path:
        return self._get_threads_dir(session_id) / str(thread_id)

    def _get_thread_meta_path(self, session_id: str, thread_id: int) -> Path:
        return self._get_thread_dir(session_id, thread_id) / "metadata.json"

    def _get_thread_messages_path(self, session_id: str, thread_id: int) -> Path:
        return self._get_thread_dir(session_id, thread_id) / "messages.jsonl"

    def _get_role_activity_path(self, session_id: str, thread_id: int, role_name: str) -> Path:
        return self._get_thread_dir(session_id, thread_id) / f"{role_name}_activity.json"

    def _get_role_context_path(self, session_id: str, thread_id: int, role_name: str) -> Path:
        return self._get_thread_dir(session_id, thread_id) / f"{role_name}_context.json"

    @staticmethod
    def _thread_key(thread_id: int) -> str:
        return str(thread_id)

    def _load_json_dict(self, file_path: Path) -> dict[str, Any]:
        if not file_path.exists():
            return {}

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass

        return {}

    def _save_json_dict(self, file_path: Path, data: dict[str, Any]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save_thread_metadata(self, session_id: str, metadata: ChannelThreadMetadata) -> None:
        path = self._get_thread_meta_path(session_id, metadata.thread_id)
        self._save_json_dict(path, metadata.model_dump(mode="json"))
        self._touch_metadata_updated_at(session_id)

    def load_thread_metadata(self, session_id: str, thread_id: int) -> ChannelThreadMetadata | None:
        path = self._get_thread_meta_path(session_id, thread_id)
        if not path.exists():
            return None

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return ChannelThreadMetadata.model_validate(data)
        except Exception:
            return None

    def list_thread_metadata(self, session_id: str) -> list[ChannelThreadMetadata]:
        threads_dir = self._get_threads_dir(session_id)
        if not threads_dir.exists():
            return []

        metadata_list: list[ChannelThreadMetadata] = []
        for thread_dir in threads_dir.iterdir():
            if not thread_dir.is_dir():
                continue
            meta_path = thread_dir / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                with open(meta_path, encoding="utf-8") as f:
                    data = json.load(f)
                metadata_list.append(ChannelThreadMetadata.model_validate(data))
            except Exception:
                continue

        metadata_list.sort(key=lambda item: item.updated_at, reverse=True)
        return metadata_list

    def append_message(self, session_id: str, thread_id: int, message: Message | list[Message]) -> None:
        """Append messages into threads/<thread_id>/messages.jsonl."""
        path = self._get_thread_messages_path(session_id, thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        messages = [message] if isinstance(message, Message) else message
        with open(path, "a", encoding="utf-8") as f:
            for msg in messages:
                f.write(msg.model_dump_json() + "\n")

        self._touch_metadata_updated_at(session_id)

    def save_messages(self, session_id: str, thread_id: int, messages: list[Message]) -> None:
        """Overwrite threads/<thread_id>/messages.jsonl."""
        path = self._get_thread_messages_path(session_id, thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            for message in messages:
                f.write(message.model_dump_json() + "\n")

        self._touch_metadata_updated_at(session_id)

    def load_messages(self, session_id: str, thread_id: int) -> list[Message]:
        path = self._get_thread_messages_path(session_id, thread_id)
        messages: list[Message] = []
        if not path.exists():
            return messages

        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line := line.strip():
                        messages.append(Message.model_validate_json(line))
        except Exception:
            pass

        return messages

    def append_role_activity(
        self,
        session_id: str,
        role_name: str,
        thread_id: int,
        activity: RoleActivityRecord | list[RoleActivityRecord],
    ) -> None:
        """Append activity records into threads/<thread_id>/<role_name>_activity.json."""
        path = self._get_role_activity_path(session_id, thread_id, role_name)
        payload = self._load_json_dict(path)

        existing = payload.get("activities", [])
        if not isinstance(existing, list):
            existing = []

        activities = [activity] if isinstance(activity, RoleActivityRecord) else activity
        existing.extend(item.model_dump(mode="json") for item in activities)
        payload["activities"] = existing

        self._save_json_dict(path, payload)
        self._touch_metadata_updated_at(session_id)

    def save_role_activities(
        self,
        session_id: str,
        role_name: str,
        thread_id: int,
        activities: list[RoleActivityRecord],
    ) -> None:
        """Overwrite threads/<thread_id>/<role_name>_activity.json."""
        path = self._get_role_activity_path(session_id, thread_id, role_name)
        payload = {"activities": [item.model_dump(mode="json") for item in activities]}
        self._save_json_dict(path, payload)
        self._touch_metadata_updated_at(session_id)

    def load_role_activities(self, session_id: str, role_name: str, thread_id: int) -> list[RoleActivityRecord]:
        path = self._get_role_activity_path(session_id, thread_id, role_name)
        payload = self._load_json_dict(path)

        items = payload.get("activities", [])
        if not isinstance(items, list):
            return []

        activities: list[RoleActivityRecord] = []
        for item in items:
            try:
                activities.append(RoleActivityRecord.model_validate(item))
            except Exception:
                continue
        return activities

    def save_role_context(
        self,
        session_id: str,
        role_name: str,
        thread_id: int,
        context: dict[str, Any],
    ) -> None:
        """Persist threads/<thread_id>/<role_name>_context.json."""
        path = self._get_role_context_path(session_id, thread_id, role_name)
        self._save_json_dict(path, context)
        self._touch_metadata_updated_at(session_id)

    def load_role_context(self, session_id: str, role_name: str, thread_id: int) -> dict[str, Any] | None:
        path = self._get_role_context_path(session_id, thread_id, role_name)
        context = self._load_json_dict(path)
        return context if isinstance(context, dict) else None
