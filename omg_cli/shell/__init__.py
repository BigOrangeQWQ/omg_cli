"""Shell TUI module for omg-cli."""

from .app import ChatTerminalApp, run_terminal
from .import_wizard import ImportWizard
from .widgets import (
    ApprovalDialog,
    CommandPalette,
    ComposerTextArea,
    ContextStatusWidget,
    MessageHistoryView,
    MessageRow,
    PendingMessagesDisplay,
    SafeStatic,
    StatusWidget,
    ToolPreviewRow,
)

__all__ = [
    # Widgets
    "ApprovalDialog",
    # Main app
    "ChatTerminalApp",
    "CommandPalette",
    "ComposerTextArea",
    "ContextStatusWidget",
    # Import wizard
    "ImportWizard",
    "MessageHistoryView",
    "MessageRow",
    "PendingMessagesDisplay",
    "SafeStatic",
    "StatusWidget",
    "ToolPreviewRow",
    "run_terminal",
]
