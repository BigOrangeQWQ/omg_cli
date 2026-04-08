"""Autocomplete framework for shell TUI.

Provides a generic autocomplete system that can be extended for:
- Commands (prefix: /)
- File paths (prefix: @)
- Variables (prefix: $)
- Emojis (prefix: :)
- And more...
"""

from dataclasses import dataclass
from typing import Any, Protocol

# TYPE_CHECKING imports are not used at runtime


@dataclass(frozen=True)
class CompletionItem:
    """A single completion item."""

    label: str  # Display text
    value: str  # Insert value
    description: str = ""  # Optional description
    icon: str = ""  # Optional icon


class CompletionSource(Protocol):
    """Protocol for completion sources.

    Each source provides completions for a specific prefix (e.g., "/", "@", "$").
    """

    @property
    def prefix(self) -> str:
        """Trigger prefix for this source (e.g., "/", "@", ":")."""
        ...

    def get_completions(self, query: str) -> list[CompletionItem]:
        """Get completion items for the given query (without prefix)."""
        ...


class CommandCompletionSource:
    """Completion source for meta commands."""

    def __init__(self, registry: Any) -> None:
        self.registry = registry

    @property
    def prefix(self) -> str:
        return "/"

    def get_completions(self, query: str) -> list[CompletionItem]:
        """Get command completions."""
        commands = self.registry.find_matches(query)
        return [
            CompletionItem(
                label=f"{cmd.full_name} - {cmd.description_zh}",
                value=cmd.full_name + " ",
                description=cmd.description_zh,
            )
            for cmd in commands
        ]


class CompletionRegistry:
    """Registry for completion sources.

    Manages multiple completion sources and routes queries to the appropriate source.
    """

    def __init__(self) -> None:
        self._sources: dict[str, CompletionSource] = {}
        self._fallback: CompletionSource | None = None

    def register(self, source: CompletionSource) -> None:
        """Register a completion source."""
        self._sources[source.prefix] = source

    def unregister(self, prefix: str) -> None:
        """Unregister a completion source by prefix."""
        self._sources.pop(prefix, None)

    def get_source_for(self, text: str) -> CompletionSource | None:
        """Get the appropriate source for the given text."""
        for prefix in sorted(self._sources.keys(), key=len, reverse=True):
            if text.startswith(prefix):
                return self._sources[prefix]
        return None

    def get_prefixes(self) -> set[str]:
        """Get all registered prefixes."""
        return set(self._sources.keys())

    def complete(self, text: str) -> tuple[str, list[CompletionItem]] | None:
        """Get completions for the given text.

        Returns:
            Tuple of (prefix, items) or None if no matching source.
        """
        for prefix in sorted(self._sources.keys(), key=len, reverse=True):
            if text.startswith(prefix):
                source = self._sources[prefix]
                query = text[len(prefix) :]
                items = source.get_completions(query)
                return (prefix, items)
        return None


class AutocompleteController:
    """Controller for autocomplete functionality.

    Manages the completion registry and updates the UI list view.
    """

    def __init__(self, list_view: Any, registry: CompletionRegistry | None = None) -> None:
        self.list_view = list_view
        self.registry = registry or CompletionRegistry()
        self._current_items: list[CompletionItem] = []
        self._current_prefix: str = ""

    def update(self, text: str) -> bool:
        """Update completions based on current text.

        Returns:
            True if completions are available and should be shown.
        """
        result = self.registry.complete(text)

        if result is None:
            self._current_items = []
            self._current_prefix = ""
            return False

        prefix, items = result
        self._current_prefix = prefix
        self._current_items = items

        # Update the list view
        self._update_list_view(items)
        return bool(items)

    def _update_list_view(self, items: list[CompletionItem]) -> None:
        """Update the list view with completion items."""
        from textual.widgets import ListItem, Static

        self.list_view.clear()
        for item in items:
            display = f"{item.icon} {item.label}" if item.icon else item.label
            self.list_view.append(ListItem(Static(display), classes="completion-item"))

    def select(self, index: int | None = None) -> str | None:
        """Select the current or specified item and return its value."""
        if index is None:
            index = self.list_view.index

        if index is None or not (0 <= index < len(self._current_items)):
            return None

        return self._current_items[index].value

    def get_current_word(self, text: str, cursor_pos: int) -> str:
        """Extract the current word at cursor position."""
        # Find start of current word
        start = cursor_pos
        while start > 0 and text[start - 1] not in (" ", "\n"):
            start -= 1
        return text[start:cursor_pos]

    def should_trigger(self, word: str) -> bool:
        """Check if the word should trigger autocomplete."""
        return any(word.startswith(prefix) for prefix in self.registry.get_prefixes())


# Global registry instance (for shared completions)
_global_registry: CompletionRegistry | None = None


def get_global_registry() -> CompletionRegistry:
    """Get or create the global completion registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = CompletionRegistry()
    return _global_registry
