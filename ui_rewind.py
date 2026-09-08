"""Select and review a conversation boundary before rewinding a session."""

import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from session_rewind import apply_rewind, read_plan
from ui_common import _compact_timestamp, _short
from ui_dialogs import ConfirmDialog
from ui_documents import ConversationScreen


class RewindScreen(Screen[bool]):
    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("q", "close", "Back", show=False),
        Binding("/", "search", "Search"),
        Binding("k", "keep", "Keep through selected"),
        Binding("b", "before", "Remove from selected"),
    ]
    DEFAULT_CSS = """
    RewindScreen { background: $surface; }
    #rewind-title, #rewind-status { height: auto; padding: 0 1; }
    #rewind-table { height: 1fr; min-height: 5; }
    #rewind-preview { height: 1fr; min-height: 4; border: solid $primary; }
    #rewind-actions { height: 3; overflow-x: auto; }
    #rewind-actions Button { margin-right: 1; }
    """

    def __init__(self, manager, session):
        super().__init__()
        self.manager = manager
        self.session = session
        self.plan = None
        self.selected = None
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"Rewind: {self.session.display_name}\n{self.session.id}",
            id="rewind-title",
            markup=False,
        )
        yield Input(
            placeholder="Find an exchange by your words or the final answer…",
            id="rewind-search",
        )
        yield DataTable(id="rewind-table", cursor_type="row", zebra_stripes=True)
        with VerticalScroll(id="rewind-preview"):
            yield Static("Loading conversation boundaries…", markup=False)
        yield Static("Loading…", id="rewind-status", markup=False)
        with Horizontal(id="rewind-actions"):
            yield Button(
                "Keep through selected",
                id="rewind-keep",
                variant="error",
                disabled=True,
            )
            yield Button(
                "Remove from selected",
                id="rewind-before",
                variant="error",
                disabled=True,
            )
            yield Button("Back", id="rewind-back")
        yield Footer()

    def on_mount(self):
        self.query_one(DataTable).add_columns("#", "Time", "Your input", "Final answer")
        self.query_one(DataTable).focus()
        self.run_worker(self._load(), exit_on_error=False)

    async def _load(self):
        try:
            self.plan = await asyncio.to_thread(read_plan, self.manager, self.session)
            self._filter()
        except Exception as error:
            self.query_one("#rewind-status", Static).update(f"Cannot rewind: {error}")

    def _filter(self):
        if not self.plan:
            return
        needle = self.query_one(Input).value.casefold().strip()
        table = self.query_one(DataTable)
        table.clear()
        self.selected = None
        width = max(10, min(55, (self.size.width - 30) // 2))
        for index, exchange in enumerate(self.plan.exchanges):
            if needle and not any(
                needle in m.text.casefold() for m in exchange.messages
            ):
                continue
            answer = next(
                (m.text for m in reversed(exchange.messages) if m.role == "assistant"),
                "(no final answer)",
            )
            table.add_row(
                str(index + 1),
                _compact_timestamp(exchange.timestamp).removesuffix(" > "),
                _short(exchange.question, width),
                _short(answer, width),
                key=str(index),
            )
        self._selection_state()
        if table.row_count:
            table.move_cursor(row=0)

    def _selection_state(self):
        selected = self.selected
        self.query_one("#rewind-keep", Button).disabled = (
            self.busy or selected is None or selected == len(self.plan.exchanges) - 1
        )
        self.query_one("#rewind-before", Button).disabled = (
            self.busy or selected is None
        )
        if selected is None:
            self.query_one("#rewind-status", Static).update(
                "Select an exchange. Rewind works at exchange boundaries."
            )
        else:
            total = len(self.plan.exchanges)
            self.query_one("#rewind-status", Static).update(
                f"Exchange {selected + 1}/{total}. Keep through it: remove {total - selected - 1}. "
                f"Remove from it: remove {total - selected}. Tab moves into the scrollable preview."
            )

    async def on_data_table_row_highlighted(self, event):
        if not self.plan or self.busy:
            return
        self.selected = int(event.row_key.value)
        self._selection_state()
        preview = self.query_one("#rewind-preview", VerticalScroll)
        await preview.remove_children()
        for message in self.plan.exchanges[self.selected].messages:
            await preview.mount(
                Static(
                    ConversationScreen._render_message(message),
                    classes="conversation-message "
                    + (
                        "conversation-user"
                        if message.role == "user"
                        else "conversation-assistant"
                    ),
                )
            )
        preview.scroll_home(animate=False)

    def on_input_changed(self, event):
        if event.input.id == "rewind-search" and not self.busy:
            self._filter()

    def on_resize(self):
        if self.is_mounted and self.plan and not self.busy:
            self._filter()

    def action_search(self):
        self.query_one(Input).focus()

    def action_keep(self):
        if self.selected is not None:
            self._confirm(self.selected + 1)

    def action_before(self):
        if self.selected is not None:
            self._confirm(self.selected)

    def _confirm(self, keep):
        if self.busy or not self.plan or keep >= len(self.plan.exchanges):
            return
        remove = len(self.plan.exchanges) - keep
        last = (
            self.plan.exchanges[keep - 1].question
            if keep
            else "(none: empty conversation)"
        )
        first = self.plan.exchanges[keep].question
        body = (
            f"Session: {self.session.display_name}\n{self.session.id}\n\n"
            f"Keep {keep} exchanges; remove {remove} exchanges.\n"
            f"Last retained input: {_short(last, 160)}\n"
            f"First removed input: {_short(first, 160)}\n\n"
            "Later exchanges will be excluded when this session resumes.\n"
            "This does not undo changed files, external actions, or existing memories. "
            "Old rollout data may remain on disk; this is not secure erasure or disk cleanup. "
            "There is no undo button."
        )
        self.app.push_screen(
            ConfirmDialog(
                "Rewind this session?", body, f"Remove {remove} exchanges", danger=True
            ),
            lambda confirmed: self._begin(keep) if confirmed else None,
        )

    def _begin(self, keep):
        if self.busy:
            return
        self.busy = True
        self._selection_state()
        self.query_one(Input).disabled = True
        self.query_one("#rewind-back", Button).disabled = True
        self.query_one("#rewind-status", Static).update(
            "Rewinding and verifying persisted history…"
        )
        self.run_worker(self._apply(keep), exit_on_error=False)

    async def _apply(self, keep):
        try:
            count = await asyncio.to_thread(
                apply_rewind, self.manager, self.session, self.plan, keep
            )
            self.app.notify(f"Rewound session: removed {count} exchanges.", timeout=8)
            self.dismiss(True)
        except Exception as error:
            self.query_one("#rewind-status", Static).update(str(error))
            self.plan = None  # Do not allow retries with a potentially stale plan.
            self.query_one("#rewind-back", Button).disabled = False
        finally:
            self.busy = False

    def action_close(self):
        if not self.busy:
            self.dismiss(False)

    def on_button_pressed(self, event):
        event.stop()
        actions = {
            "rewind-keep": self.action_keep,
            "rewind-before": self.action_before,
            "rewind-back": self.action_close,
        }
        action = actions.get(event.button.id)
        if action:
            action()
