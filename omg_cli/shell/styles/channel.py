"""Channel mode styles: thread sidebar, thread planning, mention palette."""

CHANNEL_CSS = """
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

/* Thread Sidebar */
.thread-sidebar {
    width: 25;
    min-width: 20;
    height: 1fr;
    border-right: solid $panel;
    background: $surface-darken-1;
    padding: 1 0;
    display: none;
}

.thread-sidebar.visible {
    display: block;
}

.thread-sidebar-title {
    text-style: bold;
    color: $primary;
    text-align: center;
    height: 1;
    margin: 0 0 1 0;
}

.thread-sidebar-list {
    width: 100%;
    height: auto;
}

.thread-item {
    width: 100%;
    height: 1;
    padding: 0 1;
    color: $text;
    text-align: left;
}

.thread-item:hover {
    background: $primary 20%;
}

.thread-item--active {
    background: $primary 30%;
    text-style: bold;
}
"""
