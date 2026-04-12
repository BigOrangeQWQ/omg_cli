"""Channel mode styles: thread create, thread list, thread planning, mention palette."""

CHANNEL_CSS = """
/* Thread Create Widget */
.thread-create-widget {
    width: 1fr;
    height: auto;
    border: solid $primary-darken-2;
    background: $surface-darken-1;
    padding: 1;
    margin: 0 1 1 1;
}

.thread-create-widget Input {
    margin: 0 0 1 0;
}

.thread-create-widget TextArea {
    height: 8;
    margin: 0 0 1 0;
}

/* Thread List View */
.thread-list-view {
    width: 1fr;
    height: 1fr;
    border: solid $primary-darken-2;
    background: $surface-darken-1;
    padding: 1;
}

.thread-list-title {
    text-style: bold;
    color: $primary;
    height: 1;
    text-align: center;
    margin: 0 0 1 0;
}

.thread-list-items {
    width: 100%;
    height: 1fr;
    overflow-y: auto;
}

.thread-list-empty {
    width: 100%;
    height: 1fr;
    text-align: center;
    color: $text-muted;
    content-align: center middle;
}

.thread-list-header {
    width: 100%;
    height: 1;
    color: $text-muted;
    text-style: bold;
    margin: 1 0 0 0;
}

.thread-list-item {
    width: 100%;
    height: auto;
    padding: 0 1;
    color: $text;
}

.thread-list-item:hover {
    background: $primary 20%;
}

.thread-list-item--selected {
    background: $primary 30%;
    text-style: bold;
}

.thread-list-item--selected .thread-list-item-meta {
    color: $text;
}

.thread-list-item--running {
    color: $success;
}

.thread-list-item--draft {
    color: $warning;
}

.thread-list-item--review {
    color: $primary;
}

.thread-list-item--done {
    color: $text-muted;
}

.thread-list-item--error {
    color: $error;
}

.thread-list-item-icon {
    width: 2;
    content-align: center middle;
}

.thread-list-item-title {
    width: 1fr;
    text-style: bold underline;
    padding: 0 1;
}

.thread-list-item-meta {
    width: auto;
    color: $text-muted;
}

/* Thread Planning Widget */
.thread-planning-widget {
    width: 1fr;
    height: auto;
    max-height: 20;
    border: solid $primary-darken-2;
    background: $surface-darken-1;
    padding: 0 1;
    margin: 0 1 1 1;
}

.thread-planning-title {
    text-style: bold;
    color: $primary;
    height: 1;
    text-align: center;
}

.thread-planning-header {
    width: 100%;
    height: 1;
}

.plan-header {
    text-style: bold;
    color: $text-muted;
    height: 1;
}

.plan-header-title {
    width: 50%;
}

.plan-header-assign {
    width: 25%;
}

.plan-header-review {
    width: 20%;
}

.plan-header-del {
    width: 5%;
}

.thread-planning-rows {
    width: 100%;
    height: auto;
}

.thread-planning-row {
    width: 100%;
    height: auto;
    margin: 0 0 1 0;
}

.plan-input {
    height: 1;
    margin: 0 1 0 0;
}

.plan-title {
    width: 50%;
}

.plan-assign {
    width: 25%;
}

.plan-review {
    width: 20%;
}

.plan-del-btn {
    width: 5%;
    min-width: 3;
    height: 1;
    padding: 0;
    content-align: center middle;
}

.thread-planning-buttons {
    width: 100%;
    height: auto;
    align: center middle;
    margin: 1 0 0 0;
}

.thread-planning-buttons Button {
    margin: 0 1;
    height: 1;
    min-width: 10;
}

/* Mention Palette */
.mention-palette {
    width: auto;
    min-width: 15;
    max-width: 30;
    height: auto;
    max-height: 8;
    border: none;
    display: none;
    background: $surface-darken-1;
    layer: above;
}

.mention-item {
    height: 1;
    padding: 0 1;
    color: $text;
}

.mention-item:hover {
    background: $primary 20%;
}

/* Footer channel status */
.channel-status {
    width: auto;
    height: 1;
    align: right middle;
    color: $primary;
    text-style: bold;
    padding: 0 1;
}

/* Inspect Widget */
.inspect-widget {
    width: 1fr;
    height: 1fr;
    border: solid $primary-darken-2;
    background: $surface-darken-1;
    padding: 1;
}

.inspect-title {
    text-style: bold;
    color: $primary;
    height: 1;
    text-align: center;
    margin: 0 0 1 0;
}

.inspect-records {
    width: 100%;
    height: 1fr;
    overflow-y: auto;
}

.inspect-record {
    width: 100%;
    height: auto;
    padding: 0 1;
    color: $text;
}

.inspect-record--error {
    color: $error;
}

.inspect-record--thinking {
    color: $warning;
}

.inspect-record--tool_call {
    color: $primary;
}

.inspect-record--status {
    color: $text-muted;
}

.inspect-record--stream {
    color: $success;
}
"""
