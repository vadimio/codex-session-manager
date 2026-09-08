from __future__ import annotations

from typing import Any, Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    Static,
)


class PromptDialog(ModalScreen[str | None]):
    """Single-line prompt which returns text or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self, title: str, prompt: str, initial: str = "", placeholder: str = ""
    ) -> None:
        super().__init__()
        self.dialog_title = title
        self.prompt = prompt
        self.initial = initial
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog prompt-dialog"):
            yield Label(self.dialog_title, classes="dialog-title")
            yield Static(self.prompt, classes="dialog-copy")
            yield Input(
                value=self.initial, placeholder=self.placeholder, id="dialog-input"
            )
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="accept", variant="primary")

    def on_mount(self) -> None:
        field = self.query_one("#dialog-input", Input)
        field.focus()
        field.action_end()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "accept":
            value = self.query_one("#dialog-input", Input).value.strip()
            self.dismiss(value or None)
        else:
            self.dismiss(None)


class ConfirmDialog(ModalScreen[bool]):
    """Explicit yes/no dialog."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self, title: str, body: str, confirm_label: str, danger: bool = False
    ) -> None:
        super().__init__()
        self.dialog_title = title
        self.body = body
        self.confirm_label = confirm_label
        self.danger = danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog confirm-dialog"):
            yield Label(self.dialog_title, classes="dialog-title")
            yield Static(self.body, classes="dialog-copy", markup=False)
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(
                    self.confirm_label,
                    id="accept",
                    variant="error" if self.danger else "primary",
                )

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "accept")


class DeleteDialog(ModalScreen[bool]):
    """Permanent delete confirmation requiring the complete session UUID."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session: Any, human_size: Callable[[int], str]) -> None:
        super().__init__()
        self.session = session
        self.human_size = human_size

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog delete-dialog"):
            yield Label("Permanent deletion", classes="dialog-title danger-title")
            yield Static(
                "This removes the resumable Codex transcript and may also remove spawned descendants.\n\n"
                f"{self.session.display_name}\n{self.session.id}\n{self.human_size(self.session.size)}\n\n"
                "Type the complete session ID to enable deletion.",
                classes="dialog-copy",
            )
            yield Input(placeholder=self.session.id, id="delete-id")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(
                    "Delete permanently", id="accept", variant="error", disabled=True
                )

    def on_mount(self) -> None:
        self.query_one("#delete-id", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.query_one("#accept", Button).disabled = (
            event.value.strip() != self.session.id
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip() == self.session.id:
            self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "accept" and not event.button.disabled)
