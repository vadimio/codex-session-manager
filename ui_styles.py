"""Shared Textual styles."""

CSS = """
    Screen {
        background: $surface;
    }
    #app-shell, #memory-shell {
        height: 1fr;
        padding: 0 1;
    }
    #summary {
        height: 1;
        color: $text-muted;
        margin: 0 1;
    }
    #filters, #actions, #memory-toolbar, #memory-file-actions, #memory-config-actions {
        height: 3;
        align-vertical: middle;
        overflow-x: auto;
    }
    #search, #memory-search {
        width: 1fr;
        min-width: 24;
    }
    #state-select, #memory-kind {
        width: 18;
        margin-left: 1;
    }
    #sort-select {
        width: 20;
        margin-left: 1;
    }
    #direction, #refresh, #memory-button, #memory-help, #memory-correct, #memory-edit, #memory-back,
    #toggle-use, #toggle-generate, #toggle-external {
        margin-left: 1;
    }
    #session-table, #memory-table {
        height: 2fr;
        min-height: 7;
        border: round $primary-darken-2;
    }
    #preview, #memory-preview {
        height: 1fr;
        min-height: 7;
        overflow-y: auto;
        border: round $primary-darken-2;
        padding: 0 1;
        background: $surface-darken-1;
    }
    #status, #memory-status {
        height: 1;
        color: $text-muted;
        padding-left: 1;
    }
    #command {
        display: none;
        dock: bottom;
        margin: 0 1 1 1;
        border: tall $accent;
        background: $surface;
    }
    #command.visible {
        display: block;
    }
    #actions Button {
        min-width: 12;
        margin-right: 1;
    }
    .narrow #filters, .narrow #memory-toolbar {
        height: 6;
        layout: grid;
        grid-size: 2 2;
        grid-columns: 1fr 1fr;
        grid-rows: 3 3;
    }
    .narrow #search, .narrow #memory-search,
    .narrow #state-select, .narrow #sort-select, .narrow #memory-kind {
        width: 1fr;
        min-width: 10;
        margin-left: 0;
    }
    .narrow #actions, .narrow #memory-file-actions, .narrow #memory-config-actions {
        overflow-x: auto;
    }
    .short #preview, .short #memory-preview {
        display: none;
    }
    .short #memory-explainer, .short #memory-config {
        display: none;
    }
    .dialog {
        width: 78;
        max-width: 90%;
        height: auto;
        max-height: 85%;
        background: $panel;
        border: thick $primary;
        padding: 1 2;
        align: center middle;
    }
    PromptDialog, ConfirmDialog, DeleteDialog {
        align: center middle;
        background: $background 70%;
    }
    .dialog-title {
        text-style: bold;
        color: $accent;
        height: 2;
    }
    .danger-title {
        color: $error;
    }
    .dialog-copy {
        height: auto;
        max-height: 14;
        margin-bottom: 1;
    }
    .confirm-dialog {
        height: 85%;
        max-height: 30;
    }
    .confirm-dialog .dialog-copy {
        height: 1fr;
        max-height: 100%;
        overflow-y: auto;
    }
    .dialog-buttons {
        height: 3;
        align-horizontal: right;
        margin-top: 1;
    }
    .dialog-buttons Button {
        margin-left: 1;
    }
    #document-shell, #conversation-shell {
        height: 1fr;
        padding: 0 1;
    }
    #document-titlebar, #conversation-titlebar {
        height: 3;
        align-vertical: middle;
        overflow-x: auto;
    }
    #document-title, #conversation-title {
        width: 1fr;
        min-width: 16;
        text-style: bold;
    }
    #document-scroll-help, #conversation-scroll-help {
        width: auto;
        color: $text-muted;
        margin-right: 1;
    }
    #document-top, #document-bottom, #conversation-top, #conversation-bottom {
        width: 10;
        margin-right: 1;
    }
    #document-back, #conversation-back {
        width: 14;
    }
    #document {
        height: 1fr;
        overflow-y: auto;
        border: round $primary-darken-2;
        padding: 1 2;
        background: $surface-darken-1;
    }
    #conversation-meta {
        height: 1;
        color: $text-muted;
        padding-left: 1;
    }
    #conversation {
        height: 1fr;
        border: round $primary-darken-2;
        background: black;
    }
    .conversation-message {
        height: auto;
        min-height: 1;
        padding: 0 1;
        color: $text;
    }
    .conversation-user {
        background: $surface-lighten-2;
    }
    .conversation-assistant {
        background: black;
    }
    #memory-config {
        height: 3;
        padding: 0 1;
        color: $text-muted;
    }
    #memory-explainer {
        height: 2;
        padding: 0 1;
        color: $text-muted;
    }
    """
