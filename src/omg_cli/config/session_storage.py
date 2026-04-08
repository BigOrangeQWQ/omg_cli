from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.omg_cli.config.constants import DEFAULT_CONFIG_DIR
from src.omg_cli.types.message import Message, TextSegment


class SessionMetadata(BaseModel):
    """Session metadata for persistence (stored in meta.json)."""

    session_id: str
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    model_name: str | None = None
    custom: dict[str, Any] = {}


class SessionStorage:
    """Manages persistent storage of chat sessions.

    Storage layout:
        ~/.config/omg-cli/sessions/
        └── <session_id>/
            ├── meta.json      # Session metadata
            └── messages.jsonl # Messages in JSON Lines format
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self.sessions_dir = self.config_dir / "sessions"

    def _ensure_dir_exists(self) -> None:
        """Ensure sessions directory exists with secure permissions."""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        # Set restrictive permissions: only owner can access (rwx------)
        self.sessions_dir.chmod(0o700)

    def _get_session_dir(self, session_id: str) -> Path:
        """Get the directory path for a session."""
        return self.sessions_dir / session_id

    def _get_meta_path(self, session_id: str) -> Path:
        """Get the meta.json path for a session."""
        return self._get_session_dir(session_id) / "meta.json"

    def _get_messages_path(self, session_id: str) -> Path:
        """Get the messages.jsonl path for a session."""
        return self._get_session_dir(session_id) / "messages.jsonl"

    def save_metadata(self, metadata: SessionMetadata) -> None:
        """Save session metadata to disk."""
        self._ensure_dir_exists()
        metadata.updated_at = datetime.now(tz=UTC)

        session_dir = self._get_session_dir(metadata.session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        session_dir.chmod(0o700)

        meta_path = self._get_meta_path(metadata.session_id)
        temp_path = meta_path.with_suffix(".tmp")

        # Write to temp file first for atomic operation
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(metadata.model_dump_json(indent=2))

        # Set secure permissions
        temp_path.chmod(0o600)

        # Atomic rename
        temp_path.rename(meta_path)

    def load_metadata(self, session_id: str) -> SessionMetadata | None:
        """Load session metadata from disk."""
        meta_path = self._get_meta_path(session_id)
        if not meta_path.exists():
            return None

        try:
            with open(meta_path, encoding="utf-8") as f:
                data = f.read()
            return SessionMetadata.model_validate_json(data)
        except Exception:
            return None

    def append_message(self, session_id: str, message: Message) -> None:
        """Append a single message to the session's messages.jsonl."""
        messages_path = self._get_messages_path(session_id)

        # Append mode - creates file if not exists
        with open(messages_path, "a", encoding="utf-8") as f:
            f.write(message.model_dump_json() + "\n")

        # Set secure permissions if file was just created
        if messages_path.stat().st_size < 1000:  # Rough check for new file
            messages_path.chmod(0o600)

    def load_messages(self, session_id: str) -> list[Message]:
        """Load all messages from a session's messages.jsonl."""
        messages_path = self._get_messages_path(session_id)
        if not messages_path.exists():
            return []

        messages: list[Message] = []
        try:
            with open(messages_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            msg = Message.model_validate_json(line)
                            messages.append(msg)
                        except Exception:
                            continue
        except Exception:
            pass

        return messages

    def delete(self, session_id: str) -> bool:
        """Delete a session directory from disk."""
        session_dir = self._get_session_dir(session_id)
        if session_dir.exists():
            # Remove all files in the directory
            for file_path in session_dir.iterdir():
                file_path.unlink()
            # Remove the directory
            session_dir.rmdir()
            return True
        return False

    def list_sessions(self) -> list[SessionMetadata]:
        """List all saved sessions, sorted by updated_at (newest first)."""
        if not self.sessions_dir.exists():
            return []

        sessions: list[SessionMetadata] = []
        for session_dir in self.sessions_dir.iterdir():
            if session_dir.is_dir():
                session_id = session_dir.name
                metadata = self.load_metadata(session_id)
                if metadata:
                    sessions.append(metadata)

        # Sort by updated_at, newest first
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def generate_title(self, messages: list[Message]) -> str:
        """Generate a title from the first user message."""

        for msg in messages:
            if msg.role == "user":
                # Get text content from TextSegment
                content_text = ""
                for segment in msg.content:
                    if isinstance(segment, TextSegment):
                        content_text = segment.text
                        break

                # Truncate to reasonable length
                title = content_text.strip()[:50]
                if len(content_text) > 50:
                    title += "..."
                return title if title else "New Session"
        return "New Session"
