"""Shell TUI module for omg-cli."""

from .app import ChatTerminalApp, run_terminal
from .channel_app import ChannelTerminalApp
from .channel_widgets import (
    MentionPalette,
    ThreadCreateWidget,
    ThreadListView,
    ThreadPlanningWidget,
)
from .import_wizard import ImportWizard
from .meta_app import MetaApp
from .role_wizard import RoleWizard, RoleWizardResult
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
    "ApprovalDialog",
    "ChannelTerminalApp",
    "ChatTerminalApp",
    "CommandPalette",
    "ComposerTextArea",
    "ContextStatusWidget",
    "ImportWizard",
    "MentionPalette",
    "MessageHistoryView",
    "MessageRow",
    "MetaApp",
    "PendingMessagesDisplay",
    "RoleWizard",
    "RoleWizardResult",
    "SafeStatic",
    "StatusWidget",
    "ThreadCreateWidget",
    "ThreadListView",
    "ThreadPlanningWidget",
    "ToolPreviewRow",
    "run_terminal",
]
