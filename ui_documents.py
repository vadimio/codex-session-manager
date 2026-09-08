from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Label,
    Markdown,
    Static,
)

from ui_common import _compact_timestamp


class DocumentScreen(Screen[None]):
    """Scrollable full-screen Markdown document."""

    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("q", "close", "Back"),
        Binding("up", "line_up", "Scroll up", show=False, priority=True),
        Binding("down", "line_down", "Scroll down", show=False, priority=True),
        Binding("pageup", "page_up", "Page up", priority=True),
        Binding("pagedown", "page_down", "Page down", priority=True),
        Binding("home", "top", "Top", show=False, priority=True),
        Binding("end", "bottom", "Bottom", show=False, priority=True),
    ]

    def __init__(self, title: str, document: str) -> None:
        super().__init__()
        self.document_title = title
        self.document = document

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="document-shell"):
            with Horizontal(id="document-titlebar"):
                yield Label(self.document_title, id="document-title")
                yield Static(
                    "↑/↓ scroll · PgUp/PgDn · Home/End · mouse wheel",
                    id="document-scroll-help",
                )
                yield Button("Top", id="document-top")
                yield Button("Bottom", id="document-bottom")
                yield Button("Back  Esc", id="document-back")
            yield Markdown(self.document, id="document")
        yield Footer()

    def _document(self) -> Markdown:
        return self.query_one("#document", Markdown)

    def action_line_up(self) -> None:
        self._document().scroll_up(animate=False)

    def action_line_down(self) -> None:
        self._document().scroll_down(animate=False)

    def action_page_up(self) -> None:
        self._document().scroll_page_up(animate=False)

    def action_page_down(self) -> None:
        self._document().scroll_page_down(animate=False)

    def action_top(self) -> None:
        self._document().scroll_home(animate=False)

    def action_bottom(self) -> None:
        self._document().scroll_end(animate=False)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "document-top":
            self.action_top()
        elif event.button.id == "document-bottom":
            self.action_bottom()
        else:
            self.dismiss(None)


class ConversationScreen(Screen[None]):
    """Compact, scrollable user/final-answer conversation."""

    BINDINGS = [
        Binding("w", "rewind", "Rewind"),
        Binding("escape", "close", "Back"),
        Binding("q", "close", "Back"),
        Binding("up", "line_up", "Scroll up", show=False, priority=True),
        Binding("down", "line_down", "Scroll down", show=False, priority=True),
        Binding("pageup", "page_up", "Page up", priority=True),
        Binding("pagedown", "page_down", "Page down", priority=True),
        Binding("home", "top", "Top", show=False, priority=True),
        Binding("end", "bottom", "Bottom", show=False, priority=True),
    ]

    def __init__(
        self, title: str, messages: list[Any], metadata: str, rewind=None
    ) -> None:
        super().__init__()
        self.conversation_title = title
        self.messages = messages
        self.metadata = metadata
        self.rewind = rewind

    @staticmethod
    def _render_message(message: Any) -> Text:
        rendered = Text()
        rendered.append(
            _compact_timestamp(message.timestamp), style="bold bright_green"
        )
        rendered.append(message.text.rstrip() or "(empty)")
        return rendered

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="conversation-shell"):
            with Horizontal(id="conversation-titlebar"):
                yield Label(self.conversation_title, id="conversation-title")
                yield Static(
                    "↑/↓ scroll · PgUp/PgDn · Home/End · mouse wheel",
                    id="conversation-scroll-help",
                )
                yield Button("Top", id="conversation-top")
                yield Button("Bottom", id="conversation-bottom")
                yield Button("Back  Esc", id="conversation-back")
            yield Static(self.metadata, id="conversation-meta")
            if self.rewind:
                yield Button("Rewind… choose an exchange", id="conversation-rewind")
            with VerticalScroll(id="conversation"):
                for message in self.messages:
                    role_class = (
                        "conversation-user"
                        if message.role == "user"
                        else "conversation-assistant"
                    )
                    yield Static(
                        self._render_message(message),
                        classes=f"conversation-message {role_class}",
                    )
        yield Footer()

    def _conversation(self) -> VerticalScroll:
        return self.query_one("#conversation", VerticalScroll)

    def action_rewind(self):
        if self.rewind:
            self.dismiss(None)
            self.rewind()

    def action_line_up(self) -> None:
        self._conversation().scroll_up(animate=False)

    def action_line_down(self) -> None:
        self._conversation().scroll_down(animate=False)

    def action_page_up(self) -> None:
        self._conversation().scroll_page_up(animate=False)

    def action_page_down(self) -> None:
        self._conversation().scroll_page_down(animate=False)

    def action_top(self) -> None:
        self._conversation().scroll_home(animate=False)

    def action_bottom(self) -> None:
        self._conversation().scroll_end(animate=False)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "conversation-top":
            self.action_top()
        elif event.button.id == "conversation-bottom":
            self.action_bottom()
        elif event.button.id == "conversation-rewind":
            self.action_rewind()
        else:
            self.dismiss(None)
