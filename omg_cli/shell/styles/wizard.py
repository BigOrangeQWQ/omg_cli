"""Wizard styles: import wizard, role wizard, role selector."""

WIZARD_CSS = """
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

/* Multi-line description textarea */
#rw-p2-desc {
    width: 100%;
    height: 4;
}

.role-wizard {
    width: 60;
    height: auto;
    max-height: 25;
    border: solid $warning;
    background: $surface-darken-1;
    padding: 0 1;
    margin: 0 1 0 1;
}

.role-wizard Input,
.role-wizard TextArea {
    border: none;
}

/* Role Selector Dialog */
.role-selector-dialog {
    width: 60;
    height: auto;
    max-height: 20;
    border: solid $primary;
    background: $surface-darken-1;
    padding: 0 1;
    margin: 0 1 0 1;
}

.role-selector-title {
    text-style: bold;
    color: $primary;
    text-align: center;
    height: 1;
}

.role-selector-hint {
    color: $text-muted;
    text-style: italic;
    height: 1;
    text-align: center;
}

.role-selector-item {
    height: 1;
    padding: 0 1;
    color: $text;
}

.role-selector-item:hover {
    background: $primary 20%;
}
"""
