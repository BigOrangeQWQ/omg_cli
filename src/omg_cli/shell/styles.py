"""CSS styles for the shell TUI."""

CSS = """

Screen {
    layout: vertical;
}

#body {
    layout: horizontal;
    height: 1fr;
}

#chat-panel {
    layout: vertical;
    width: 1fr;
    min-width: 0;
}

#messages {
    height: 1fr;
    padding: 1 1 0 1;
    scrollbar-visibility: hidden;
    scrollbar-size-vertical: 0;
    scrollbar-size-horizontal: 0;
}

#composer {
    width: 1fr;
    height: 3;
    min-height: 3;
    max-height: 10;
    margin: 1 1 -1 1;
    padding: 0 1;
    border: round $panel;
    border-left: none;
    border-right: none;
    background: transparent;
    color: $text;
    scrollbar-visibility: hidden;
    scrollbar-size-vertical: 0;
    scrollbar-size-horizontal: 0;
}

#composer:focus {
    background-tint: $foreground 5%;
}

#composer .text-area--cursor-line {
    background: transparent;
}

#composer .text-area--placeholder {
    color: $text-muted;
}

#composer TextArea {
    border: none;
    padding: 0;
    background: transparent;
}

.message-row,
.stream-row {
    width: 1fr;
    height: auto;
    margin: 0;
}

.message-row--user {
    align-horizontal: right;
}

.message-row--user .message {
    width: auto;
    max-width: 70;
    min-width: 0;
}

.message,
.stream-preview {
    width: 1fr;
    max-width: 80;
    min-width: 0;
    height: auto;
    padding: 0 1;
    border: round $panel;
    background: transparent;
}

.message {
    margin: 0 0 1 0;
}

.message__title,
.message__text,
.message__tool,
.message__thinking,
.stream-preview {
    margin: 0;
    width: auto;
    height: auto;
    background: transparent;
}

.message__text {
    padding: 0;
    text-style: none;
}

/* Ensure Markdown content wraps properly */
Markdown.message__text {
    width: 100%;
    height: auto;
    padding: 0;
}

.message__title {
    text-style: bold;
    color: $text-muted;
}

.message-row--user .message__title,
.message-row--user .message__text,
.message-row--user .message__tool,
.message-row--user .message__thinking {
    text-align: left;
}

.message-row--user .message__text {
    width: auto;
    min-width: 0;
    max-width: 60;
}

.message__thinking {
    color: $text-muted;
    text-style: italic dim;
    margin: 0;
    padding: 0;
    width: auto;
    height: auto;
    background: transparent;
}

.message__thinking:focus {
    color: $text;
    text-style: italic bold;
}

.message__tool {
    color: $warning;
}

.message__tool-result {
    color: $text-muted;
    background: transparent;
    padding: 0 1;
}

.message__tool-result:hover {
    color: $text;
    background: $surface-darken-1;
}

.status {
    color: $text-muted;
    margin: 0;
}

.status--error {
    color: $error;
    text-style: bold;
}

.status--success {
    color: #90EE90;
}

.stream-preview {
    color: $text;
}

.stream-preview--think {
    color: $text-muted;
    text-style: italic dim;
}

.stream-preview--tool {
    color: $warning;
}

.stream-preview--markdown {
    padding: 0 1;
}

.stream-preview--markdown MarkdownBlock {
    margin: 0;
}

#approval-container {
    width: 1fr;
    height: auto;
    margin: 0 1 0 1;
}

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

.import-wizard {
    width: 50;
    height: auto;
    max-height: 25;
    border: solid $warning;
    background: $surface-darken-1;
    padding: 0 1;
    margin: 0 1 0 1;
}

.wizard-spacer {
    height: 1;
}

.wizard-title {
    text-style: bold;
    color: $warning;
    text-align: center;
}

.wizard-label {
    color: $text;
    margin: 0;
    text-style: bold;
}

.wizard-label-small {
    color: $text-muted;
    margin: 0;
    height: 1;
    width: auto;
}

.wizard-option {
    height: 1;
    padding: 0 1;
    color: $text;
}

.wizard-option:hover {
    background: $primary 20%;
}

.wizard-hint {
    color: $text-muted;
    height: 1;
    margin: 0;
    text-style: italic;
}

.wizard-error {
    color: $error;
    height: 1;
    margin: 0;
}

.wizard-buttons {
    layout: horizontal;
    height: auto;
    align: center middle;
    margin: 1 0 0 0;
}

.wizard-buttons Button {
    margin: 0 1;
}

.wizard-header-row {
    height: 1;
    width: 100%;
}

.wizard-header-row > * {
    width: auto;
}

/* Wizard form - 90% width container */
.wizard-form {
    width: 90%;
    height: auto;
}

/* Each input row - flex layout */
.wizard-input-row {
    width: 100%;
    height: auto;
}

/* Input in row - fills remaining space */
.wizard-input-row > Input {
    width: 100%;
}
"""
