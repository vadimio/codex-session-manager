from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Callable

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Markdown,
    Select,
    Static,
)

from ui_common import _code, _message_excerpt, _path_tail, _short
from ui_documents import ConversationScreen, DocumentScreen
from ui_memory import MemoryScreen
from ui_session_actions import SessionActions
from ui_styles import CSS

__all__ = [
    "ConversationScreen",
    "DocumentScreen",
    "MemoryScreen",
    "SessionManagerApp",
    "run_tui",
]


class SessionManagerApp(SessionActions, App[tuple[str, str] | None]):
    """Responsive, SSH-compatible session browser."""

    TITLE = "Codex Session Manager (unofficial)"

    SUB_TITLE = "personal session, compact-history, and memory utility"

    ENABLE_COMMAND_PALETTE = True

    CSS = CSS
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("/", "search", "Search"),
        Binding(":", "command", "Command"),
        Binding("enter", "details", "Summary"),
        Binding("v", "transcript", "Full conversation"),
        Binding("t", "transcript", "Full conversation", show=False),
        Binding("s", "resume_safe", "Resume safe"),
        Binding("u", "resume_unrestricted", "Resume unrestricted", show=False),
        Binding("r", "rename", "Rename"),
        Binding("w", "rewind", "Rewind"),
        Binding("a", "archive", "Archive"),
        Binding("c", "compact", "Compact"),
        Binding("d", "delete", "Delete"),
        Binding("m", "memory", "Memory"),
        Binding("ctrl+r", "refresh", "Refresh", show=False),
        Binding("f1", "help", "Help", show=False),
    ]

    def __init__(
        self, manager: Any, memories: Any, helpers: dict[str, Callable[..., Any]]
    ) -> None:
        super().__init__()
        self.manager = manager
        self.memories = memories
        self.human_size = helpers["human_size"]
        self.local_time = helpers["local_time"]
        self.flags = manager.flags
        self.filtered_sessions: list[Any] = []
        self.selected_id: str | None = None
        self.reverse = False
        self.preview_generation = 0
        self.mutation_busy = False
        self.preview_timer = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="app-shell"):
            yield Static(id="summary")
            with Horizontal(id="filters"):
                yield Input(
                    placeholder="Search name, ID, path, prompt…  /", id="search"
                )
                yield Select(
                    [
                        ("All sessions", "all"),
                        ("Active", "active"),
                        ("Live", "live"),
                        ("Archived", "archived"),
                    ],
                    value="all",
                    allow_blank=False,
                    id="state-select",
                )
                yield Select(
                    [
                        ("Last used", "updated"),
                        ("Size", "size"),
                        ("Created", "created"),
                        ("Name", "name"),
                    ],
                    value="updated",
                    allow_blank=False,
                    id="sort-select",
                )
                yield Button("↓", id="direction", tooltip="Reverse sort direction")
                yield Button("Refresh", id="refresh")
                yield Button("Memories", id="memory-button")
            yield DataTable(id="session-table", cursor_type="row", zebra_stripes=True)
            yield Markdown(
                "Select a session to see its beginning and ending.", id="preview"
            )
            with Horizontal(id="actions"):
                yield Button("Summary", id="details")
                yield Button("Full conversation", id="transcript")
                yield Button("Rename", id="rename")
                yield Button("Rewind…", id="rewind")
                yield Button("Archive", id="archive")
                yield Button(
                    "Export",
                    id="compact",
                    tooltip="Save a readable archive; source size stays the same.",
                )
                yield Button(
                    "Resume safe",
                    id="resume-safe",
                    variant="success",
                    tooltip="Workspace-write sandbox with on-request approvals.",
                )
                yield Button(
                    "Resume unrestricted",
                    id="resume-unrestricted",
                    variant="error",
                    tooltip="No sandbox and no approval prompts. Requires confirmation.",
                )
                yield Button("Delete", id="delete", variant="error")
            yield Static("Ready", id="status")
            yield Input(placeholder=":command  (try :help)", id="command")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#session-table", DataTable)
        table.add_columns(
            "State", "Last used", "Size", "ID", "Flags", "Directory", "Name"
        )
        self.refresh_rows()
        table.focus()

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 100, "narrow")
        self.set_class(event.size.height < 30, "short")

    def _state_value(self) -> str:
        value = self.query_one("#state-select", Select).value
        return value if isinstance(value, str) else "all"

    def _sort_value(self) -> str:
        value = self.query_one("#sort-select", Select).value
        return value if isinstance(value, str) else "updated"

    def refresh_rows(self, reload_backend: bool = False) -> None:
        descending = (self._sort_value() != "name") != self.reverse
        self.query_one("#direction", Button).label = "↓" if descending else "↑"
        if reload_backend:
            try:
                self.manager.reload()
            except (OSError, ValueError, RuntimeError) as error:
                self.notify(str(error), severity="error")
                return
        search = self.query_one("#search", Input).value
        self.filtered_sessions = self.manager.filter_sessions(
            state=self._state_value(),
            search=search,
            sort=self._sort_value(),
            reverse=self.reverse,
        )
        table = self.query_one("#session-table", DataTable)
        old_id = self.selected_id
        table.clear()
        for session in self.filtered_sessions:
            table.add_row(
                session.state,
                self.local_time(session.recency_ms),
                self.human_size(session.size),
                session.id[:8],
                self.flags(session),
                _path_tail(session.cwd),
                _short(session.display_name, 78),
                key=session.id,
            )
        total = sum(item.size for item in self.filtered_sessions)
        all_total = sum(item.size for item in self.manager.sessions)
        live = sum(1 for item in self.manager.sessions if item.live)
        archived = sum(1 for item in self.manager.sessions if item.archived)
        self.query_one("#summary", Static).update(
            f"{len(self.filtered_sessions)} shown / {len(self.manager.sessions)} total · "
            f"{self.human_size(total)} shown / {self.human_size(all_total)} total · "
            f"{live} live · {archived} archived"
        )
        if self.filtered_sessions:
            row = next(
                (
                    i
                    for i, item in enumerate(self.filtered_sessions)
                    if item.id == old_id
                ),
                0,
            )
            table.move_cursor(row=row)
            self._select(self.filtered_sessions[row])
        else:
            self.selected_id = None
            self.query_one("#preview", Markdown).update(
                "No sessions match the current filter."
            )
            self._update_action_state(None)
        self.manager.save_cache()

    def _selected(self) -> Any | None:
        if not self.selected_id:
            return None
        return next(
            (item for item in self.manager.sessions if item.id == self.selected_id),
            None,
        )

    def _select(self, session: Any) -> None:
        self.selected_id = session.id
        self._update_action_state(session)
        self.preview_generation += 1
        generation = self.preview_generation
        self.query_one("#status", Static).update(
            f"Selected {session.id} · loading edge preview…"
        )
        if self.preview_timer:
            self.preview_timer.stop()
        self.preview_timer = self.set_timer(
            0.12, lambda: self._start_preview_worker(session, generation)
        )

    def _start_preview_worker(self, session: Any, generation: int) -> None:
        self.run_worker(
            partial(self._load_preview, session, generation),
            name="edge-preview",
            group="preview",
            exclusive=True,
            exit_on_error=False,
        )

    async def _load_preview(self, session: Any, generation: int) -> None:
        try:
            beginning, ending, note = await asyncio.to_thread(
                self.manager.quick_preview, session, 3
            )
        except (OSError, ValueError, RuntimeError) as error:
            if generation == self.preview_generation:
                self.query_one("#preview", Markdown).update(f"Preview error: {error}")
            return
        if generation != self.preview_generation or session.id != self.selected_id:
            return
        metadata = (
            f"### {session.display_name}\n\n"
            f"**{session.state}** · {self.human_size(session.size)} ({session.size:,} bytes) · "
            f"last used {self.local_time(session.recency_ms)} · created {self.local_time(session.created_ms)}\n\n"
            f"ID: {_code(session.id)}  \n"
            f"Directory: {_code(session.cwd or '(unknown)')}  \n"
            f"Source: {_code(session.source)} · history {_code(session.history_mode)} · flags {_code(self.flags(session))}"
        )
        sections = [metadata, "---", "### Beginning"]
        sections.extend(_message_excerpt(item) for item in beginning)
        sections.append("---\n\n### End")
        sections.extend(_message_excerpt(item) for item in ending)
        if note:
            sections.append(f"*{note}*")
        await self.query_one("#preview", Markdown).update("\n\n".join(sections))
        self.query_one("#status", Static).update(
            "↑/↓ select · Enter summary · V full conversation · S safe resume · : command"
        )
        self.manager.save_cache()

    def _update_action_state(self, session: Any | None) -> None:
        for button_id in (
            "details",
            "transcript",
            "rename",
            "rewind",
            "archive",
            "compact",
            "resume-safe",
            "resume-unrestricted",
            "delete",
        ):
            self.query_one(f"#{button_id}", Button).disabled = session is None
        if session:
            archive = self.query_one("#archive", Button)
            archive.label = "Restore" if session.archived else "Archive"
            archive.disabled = session.live
            self.query_one("#compact", Button).disabled = session.live
            self.query_one("#delete", Button).disabled = session.live
            self.query_one("#rewind", Button).disabled = (
                session.live or session.archived
            )
            self.query_one("#resume-safe", Button).disabled = session.live
            self.query_one("#resume-unrestricted", Button).disabled = session.live
        if self.mutation_busy:
            for button_id in (
                "rename",
                "rewind",
                "archive",
                "compact",
                "delete",
                "resume-safe",
                "resume-unrestricted",
            ):
                self.query_one(f"#{button_id}", Button).disabled = True

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        session = next(
            (item for item in self.manager.sessions if item.id == event.row_key.value),
            None,
        )
        if session:
            self._select(session)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_details()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.refresh_rows()

    def on_select_changed(self, event: Select.Changed) -> None:
        if self.is_mounted and event.select.id in {"state-select", "sort-select"}:
            self.refresh_rows()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "command":
            self._execute_command(event.value)
            event.input.value = ""
            event.input.remove_class("visible")
            self.query_one("#session-table", DataTable).focus()

    def action_search(self) -> None:
        field = self.query_one("#search", Input)
        field.focus()
        field.action_end()

    def action_command(self) -> None:
        field = self.query_one("#command", Input)
        field.add_class("visible")
        field.value = ":"
        field.focus()
        field.action_end()

    def action_refresh(self) -> None:
        self.refresh_rows(reload_backend=True)
        self.notify("Session inventory refreshed")

    def action_quit(self) -> None:
        if self.mutation_busy or getattr(self.screen, "busy", False):
            self.notify("Wait for the current operation to finish before quitting.")
            return
        self.exit()


def run_tui(
    manager: Any, memories: Any, helpers: dict[str, Callable[..., Any]]
) -> None:
    """Run the TUI, temporarily yielding the terminal to Codex/editor when requested."""
    while True:
        result = SessionManagerApp(manager, memories, helpers).run()
        if not result:
            return
        action, target = result
        if action in {"resume-safe", "resume-unrestricted"}:
            manager.resume(
                manager.resolve(target),
                unrestricted=action == "resume-unrestricted",
            )
        elif action == "edit-memory":
            memories.edit(target, direct=True, yes=True)
        manager.reload()
