"""Base layout and message styles."""

BASE_CSS = """
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
"""
