"""Command management protocol for ChatContext."""

from __future__ import annotations

from pygtrie import Trie

from omg_cli.types.command import MetaCommand

# Re-export for convenience
CommandHandler = MetaCommand  # Type alias for backward compatibility


class CommandProtocol:
    """Protocol for command management.

    Provides command registration, lookup and matching for TUI interfaces.
    Uses Trie for efficient prefix matching.
    """

    def __init__(self) -> None:
        self._commands: dict[str, MetaCommand] = {}
        # Trie for efficient prefix matching: key=command_name, value=has_value_marker
        self._trie: Trie = Trie()
        self._HAS_VALUE = object()  # Marker for trie values

    def register_command(self, command: MetaCommand) -> None:
        """Register a meta command.

        Example:
            protocol.register_command(MetaCommand(
                name="custom",
                description="Custom command",
                description_zh="自定义命令",
                handler=lambda ctx, args: print(f"Args: {args}")
            ))
        """
        name = command.name.lower()
        self._commands[name] = command
        self._trie[name] = self._HAS_VALUE

    def unregister_command(self, name: str) -> bool:
        """Unregister a meta command. Returns True if removed."""
        name = name.lower().lstrip("/")
        if name in self._commands:
            del self._commands[name]
            # Trie doesn't support deletion, so we rebuild or mark as deleted
            # For small command sets, rebuilding is acceptable
            self._rebuild_trie()
            return True
        return False

    def _rebuild_trie(self) -> None:
        """Rebuild the trie after deletion."""
        self._trie = Trie()
        for name in self._commands:
            self._trie[name] = self._HAS_VALUE

    def get_command(self, name: str) -> MetaCommand | None:
        """Get a command by name (with or without / prefix)."""
        name = name.lower().lstrip("/")
        return self._commands.get(name)

    def list_commands(self, include_hidden: bool = False) -> list[MetaCommand]:
        """Get all registered commands."""
        commands = list(self._commands.values())
        if not include_hidden:
            commands = [c for c in commands if not c.hidden]
        return commands

    def find_commands(self, prefix: str) -> list[MetaCommand]:
        """Find commands that start with the given prefix.

        Uses Trie for O(prefix_length) prefix matching.
        """
        prefix = prefix.lower().lstrip("/")
        if not prefix:
            return self.list_commands()

        # Use trie to find matching keys (pygtrie returns tuples)
        try:
            matching_keys = list(self._trie.keys(prefix=prefix))
        except KeyError:
            return []

        result = []
        for key in matching_keys:
            # Convert tuple key back to string
            name = "".join(key) if isinstance(key, tuple) else key
            if name in self._commands:
                cmd = self._commands[name]
                if not cmd.hidden:
                    result.append(cmd)
        return result

    def has_command(self, name: str) -> bool:
        """Check if a command exists."""
        return self.get_command(name) is not None

    # Backward compatible aliases (matching CommandRegistry interface)
    find_matches = find_commands
    get_all = list_commands
    get = get_command
    unregister = unregister_command
    register = register_command
