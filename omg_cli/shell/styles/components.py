"""Shared component styles: approval dialog, command palette, footer, pending messages."""

COMPONENTS_CSS = """
.approval-dialog {
    width: 100%;
    height: auto;
    border: solid $warning;
    padding: 0 1;
    background: $surface-darken-1;
}

.approval-title {
    text-style: bold;
    color: $warning;
}

.approval-args {
    color: $text-muted;
    text-style: italic;
}

.approval-option {
    height: 1;
    padding: 0 1;
    color: $text;
}

.approval-option:hover {
    background: $primary 20%;
}

/* Pending Messages Display */
.pending-messages-display {
    width: 100%;
    height: auto;
    border: solid $primary-darken-2;
    padding: 0 1;
    background: $surface-darken-1;
    margin: 0 0 1 0;
    display: none;
}

.pending-messages-title {
    text-style: bold;
    color: $primary;
    height: 1;
}

.pending-messages-content {
    width: 100%;
    height: auto;
}

.pending-message-item {
    color: $text-muted;
    height: 1;
    text-style: italic;
}

#confirmation-bar {
    width: 1fr;
    height: auto;
    align-horizontal: left;
    padding: 0 1 0 1;
    margin: 0;
    display: none;
}

#confirmation-bar.-show {
    display: block;
}

#confirmation-bar .confirm-btn {
    margin: 0 1 0 0;
    height: 1;
    width: auto;
    padding: 0 1;
    content-align: center middle;
    text-align: center;
    border: round $success;
    color: $success;
    text-style: none;
}

#confirmation-bar .confirm-btn:hover {
    background: $success 20%;
}

#confirmation-bar .confirm-btn-no {
    border: round $error;
    color: $error;
}

#confirmation-bar .confirm-btn-no:hover {
    background: $error 20%;
}

#confirmation-bar .confirm-btn-session {
    border: round $primary;
    color: $primary;
}

#confirmation-bar .confirm-btn-session:hover {
    background: $primary 20%;
}

#command-palette {
    width: auto;
    min-width: 40;
    max-width: 80;
    height: auto;
    max-height: 10;
    border: none;
    margin: 0 0 0 1;
    padding: 0;
    display: none;
    scrollbar-visibility: hidden;
}

#command-palette.visible {
    display: block;
}

.command-item {
    height: 1;
    padding: 0 1;
    color: $text;
}

.command-item:hover {
}

.command-item.--highlight {
    color: $primary;
    text-style: bold;
}

/* Custom footer with context status */
ContextFooter {
    layout: horizontal;
    color: $footer-foreground;
    background: $footer-background;
    dock: bottom;
    height: 1;
    scrollbar-size: 0 0;
}

ContextFooter .footer-content {
    width: 1fr;
    height: 1;
    align: left middle;
}

ContextFooter .context-status {
    width: auto;
    height: 1;
    align: right middle;
    color: $text-muted;
    text-style: dim;
    padding: 0 1;
}
"""
