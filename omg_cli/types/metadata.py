"""Metadata types for context storage."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionMetadata(BaseModel):
    """Metadata for a chat session.

    This model stores session-level information such as configuration,
    state, and other metadata that needs to be persisted alongside
    the conversation history.
    """

    # Session creation time
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    # Last updated time
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    # Session title or description
    title: str | None = None

    # Session type: "chat" or "channel"
    session_type: Literal["chat", "channel"] = "chat"

    # Session configuration (model settings, system prompt, etc.)
    config: dict[str, Any] = Field(default_factory=dict)

    # Session state (user preferences, context variables, etc.)
    state: dict[str, Any] = Field(default_factory=dict)

    # Custom metadata fields
    custom: dict[str, Any] = Field(default_factory=dict)

    # Allow additional arbitrary fields for extensibility
    model_config = ConfigDict(extra="allow")

    def touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now(tz=UTC)
