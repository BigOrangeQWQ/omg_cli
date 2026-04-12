"""Simple event manager for pub/sub pattern."""

from collections.abc import Awaitable, Callable
import inspect
from typing import TypeVar

E = TypeVar("E")

Handler = Callable[[E], None | Awaitable[None]]


class EventManager[E]:
    """A simple publish/subscribe event manager."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[Handler]] = {}

    def on(self, event_type: type[E]) -> Callable[[Handler[E]], Handler[E]]:
        """Register a handler for a specific event type.

        Usage:
            @event_manager.on(MyEvent)
            async def handle_my_event(event: MyEvent) -> None:
                ...
        """

        def decorator(handler: Handler[E]) -> Handler[E]:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)
            return handler

        return decorator

    def register(self, event_type: type[E], handler: Handler[E]) -> None:
        """Register a handler for a specific event type (non-decorator way)."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        # Prevent duplicate registration of the same bound method
        for existing in self._handlers[event_type]:
            if (
                getattr(existing, "__self__", None) is getattr(handler, "__self__", None)
                and getattr(existing, "__func__", None) is getattr(handler, "__func__", None)
            ):
                return
        self._handlers[event_type].append(handler)

    async def publish(self, event: E) -> None:
        """Publish an event to all registered handlers.

        Handlers registered for base classes will also receive events from derived classes.
        """
        event_type = type(event)

        # Collect handlers for the exact type and all base types in MRO
        all_handlers: list[Handler] = []
        for cls in event_type.__mro__:
            if cls in self._handlers:
                all_handlers.extend(self._handlers[cls])

        for handler in all_handlers:
            result = handler(event)
            if inspect.isawaitable(result):
                await result

    def copy_handlers_from(self, other: "EventManager[E]") -> None:
        """Copy all handlers from another event manager into this one."""
        for event_type, handlers in other._handlers.items():
            for handler in handlers:
                self.register(event_type, handler)

    def clear(self) -> None:
        """Clear all registered handlers."""
        self._handlers.clear()
