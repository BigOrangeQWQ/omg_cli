"""Command types - re-exported from context.command for backward compatibility."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from omg_cli.context import ChatContext

    type CommandHandler = Callable[["ChatContext", str], None | Awaitable[None]]
    type CompleterFn = Callable[["ChatContext", str], list[str]]
else:
    type CommandHandler = Any
    type CompleterFn = Any


class MetaCommand(BaseModel):
    """A meta command for the TUI interface.

    Meta commands are triggered by typing /command_name in the composer.

    Attributes:
        name: Command name (e.g., "new" for /new)
        description: Short description shown in command palette
        description_zh: Chinese description
        handler: Function to call when command is executed
        hidden: If True, command won't show in /help or palette
        completer: Optional function to provide argument completions
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    description_zh: str
    handler: CommandHandler = Field(description="Handler function for the command", exclude=True)
    hidden: bool = False
    completer: CompleterFn | None = Field(default=None, description="Optional completer for arguments", exclude=True)

    @property
    def full_name(self) -> str:
        """Full command name with / prefix."""
        return f"/{self.name}"

    def matches(self, text: str) -> bool:
        """Check if the given text matches this command."""
        return text.lower() == self.full_name.lower() or text.lower().startswith(f"{self.full_name.lower()} ")


class CommandRegistry:
    """Registry for meta commands.

    Deprecated: Use CommandProtocol from context.command instead.
    This class is kept for backward compatibility.
    """

    def __init__(self) -> None:
        self._commands: dict[str, MetaCommand] = {}

    def register(self, command: MetaCommand) -> None:
        """Register a meta command."""
        self._commands[command.name.lower()] = command

    def unregister(self, name: str) -> bool:
        """Unregister a meta command. Returns True if removed."""
        name = name.lower().lstrip("/")
        if name in self._commands:
            del self._commands[name]
            return True
        return False

    def get(self, name: str) -> MetaCommand | None:
        """Get a command by name (with or without / prefix)."""
        name = name.lower().lstrip("/")
        return self._commands.get(name)

    def get_all(self, include_hidden: bool = False) -> list[MetaCommand]:
        """Get all registered commands."""
        commands = list(self._commands.values())
        if not include_hidden:
            commands = [c for c in commands if not c.hidden]
        return commands

    def find_matches(self, prefix: str) -> list[MetaCommand]:
        """Find commands that start with the given prefix."""
        prefix = prefix.lower()
        return [cmd for cmd in self.get_all() if cmd.full_name.startswith(prefix)]


# Note: The real CommandProtocol is defined in context.command
# This alias is for backward compatibility only
CommandProtocol = CommandRegistry

__all__ = ["CommandHandler", "CommandProtocol", "CommandRegistry", "MetaCommand"]
