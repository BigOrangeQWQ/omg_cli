"""Qt bridge that forwards context events into QObject signals."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from omg_cli.types.event import (
    BaseEvent,
    RoleActivityEvent,
    SessionErrorEvent,
    SessionStatusEvent,
    ThreadMessageEvent,
    ThreadSpawnedEvent,
    ThreadStatusChangedEvent,
)


class ContextEventBridge(QObject):
    """Forward context events to Qt signals so UI layers remain event-driven and thread-safe."""

    eventReceived = Signal(object)
    threadMessageReceived = Signal(int, object)
    threadSpawned = Signal(object)
    threadStatusChanged = Signal(int, str)
    roleActivityReceived = Signal(int, str, str, str)
    statusReceived = Signal(str)
    errorReceived = Signal(str)

    _dispatchRequested = Signal(object)

    def __init__(self, context: Any | None, parent: QObject | None = None) -> None:
        super().__init__(parent=parent)
        self.context = context
        self._dispatchRequested.connect(self._dispatch_event)
        self._bind_context()

    def _bind_context(self) -> None:
        if self.context is None:
            return

        event_source = self.context
        if hasattr(self.context, "default_context"):
            event_source = self.context.default_context

        register = getattr(event_source, "register_event_handler", None)
        if callable(register):
            register(BaseEvent, self._on_event)

    async def _on_event(self, event: BaseEvent) -> None:
        self._dispatchRequested.emit(event)

    def _dispatch_event(self, event: BaseEvent) -> None:
        self.eventReceived.emit(event)

        if isinstance(event, ThreadMessageEvent):
            self.threadMessageReceived.emit(event.thread_id, event.message)
            return

        if isinstance(event, ThreadSpawnedEvent):
            self.threadSpawned.emit(event.thread)
            return

        if isinstance(event, ThreadStatusChangedEvent):
            self.threadStatusChanged.emit(event.thread_id, event.status)
            return

        if isinstance(event, RoleActivityEvent):
            self.roleActivityReceived.emit(
                event.thread_id,
                event.role_name,
                str(event.activity_type),
                event.content,
            )
            return

        if isinstance(event, SessionStatusEvent):
            self.statusReceived.emit(event.detail or "")
            return

        if isinstance(event, SessionErrorEvent):
            self.errorReceived.emit(event.error)
