from datetime import UTC, datetime
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, Field

from omg_cli.types.channel import Thread
from omg_cli.types.message import (
    Message,
    MessageStreamCompleteEvent,
    MessageStreamEvent,
)


class BaseEvent(BaseModel):
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionMessageEvent(BaseEvent):
    message: Message
    type: Literal["message"] = "message"


class StatusLevel(IntEnum):
    """Status level aligned with standard logging levels.

    Compatible with Python's logging module:
    - DEBUG = 10
    - INFO = 20
    - SUCCESS = 25 (custom, between INFO and WARNING)
    - WARN = 30 (alias for WARNING)
    - ERROR = 40
    """

    DEBUG = 10
    INFO = 20
    SUCCESS = 25
    WARN = 30
    WARNING = 30
    ERROR = 40


class SessionStatusEvent(BaseEvent):
    type: Literal["status"] = "status"
    detail: str | None = None
    level: StatusLevel = StatusLevel.INFO


class SessionErrorEvent(BaseEvent):
    error: str
    type: Literal["error"] = "error"


class SessionResetEvent(BaseEvent):
    type: Literal["reset"] = "reset"


class SessionLoadedEvent(BaseEvent):
    type: Literal["loaded"] = "loaded"


class SessionCompactedEvent(BaseEvent):
    type: Literal["compacted"] = "compacted"


class SessionStreamDeltaEvent(BaseEvent):
    stream_event: MessageStreamEvent
    type: Literal["stream"] = "stream"


class SessionStreamCompletedEvent(BaseEvent):
    stream_event: MessageStreamCompleteEvent
    type: Literal["stream_completed"] = "stream_completed"


class AppExitEvent(BaseEvent):
    """Event to signal application exit."""

    type: Literal["app_exit"] = "app_exit"


class ThreadMessageEvent(BaseEvent):
    """Event emitted when a message is added to a specific thread in channel mode."""

    thread_id: int
    message: Message
    type: Literal["thread_message"] = "thread_message"


class ThreadSpawnedEvent(BaseEvent):
    """Event emitted when a new thread is spawned in channel mode."""

    thread: "Thread"
    first_message: Message
    type: Literal["thread_spawned"] = "thread_spawned"
