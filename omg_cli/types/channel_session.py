"""Types for channel session persistence."""

from pydantic import BaseModel

from omg_cli.types.channel import Thread
from omg_cli.types.message import Message


class ThreadState(BaseModel):
    """Persisted state for a single thread."""

    thread: Thread


class ChannelSessionState(BaseModel):
    """Full persisted state for a Channel session."""

    channel_name: str
    default_role_name: str | None
    role_names: list[str]
    threads: list[ThreadState]
    role_messages: dict[str, list[Message]] = {}
