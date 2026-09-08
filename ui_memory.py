from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from rich.markup import escape
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
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

from ui_common import _short
from ui_dialogs import ConfirmDialog, PromptDialog
from ui_documents import DocumentScreen


@dataclass(frozen=True)
class MemoryEntry:
    path: Path
    category: str
    description: str
    project: str

    @property
    def modified(self) -> str:
        return (
            datetime.fromtimestamp(self.path.stat().st_mtime)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M")
        )


class MemoryScreen(Screen[None]):
    """Browse memory files, add corrections, and control injection/generation."""

    BINDINGS = [
        Binding("escape", "close", "Sessions"),
        Binding("q", "close", "Sessions"),
        Binding("enter", "open", "Full file"),
        Binding("v", "open", "Full file"),
        Binding("e", "edit", "Edit"),
        Binding("c", "correct", "Correct"),
        Binding("/", "search", "Search"),
        Binding("f1", "explain", "How memory works"),
    ]

    def __init__(self, memory_manager: Any, human_size: Callable[[int], str]) -> None:
        super().__init__()
        self.memories = memory_manager
        self.human_size = human_size
        self.entries: list[MemoryEntry] = []
        self.filtered_entries: list[MemoryEntry] = []
        self.selected_path: Path | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="memory-shell"):
            with Horizontal(id="memory-toolbar"):
                yield Input(placeholder="Search memory files…  /", id="memory-search")
                yield Select(
                    [
                        ("Overview", "overview"),
                        ("Evidence", "evidence"),
                        ("Corrections", "correction"),
                        ("All files", "all"),
                    ],
                    value="overview",
                    allow_blank=False,
                    id="memory-kind",
                )
                yield Button("How memory works", id="memory-help")
                yield Button("Back", id="memory-back")
            with Horizontal(id="memory-file-actions"):
                yield Button("Full file", id="memory-open")
                yield Button("Add correction", id="memory-correct", variant="primary")
                yield Button("Edit selected", id="memory-edit")
            yield Static(
                "[b]One global local memory store.[/b] It contains material from every project. "
                "Overview shows the recall layers; Evidence shows the source chat summaries.",
                id="memory-explainer",
            )
            yield Static(id="memory-config")
            with Horizontal(id="memory-config-actions"):
                yield Button("Use in future chats: …", id="toggle-use")
                yield Button("Learn from new chats: …", id="toggle-generate")
                yield Button("Exclude web/MCP learning: …", id="toggle-external")
            yield DataTable(id="memory-table", cursor_type="row", zebra_stripes=True)
            yield Markdown("Select a memory file to inspect it.", id="memory-preview")
            yield Static(
                "F1 explains the layers and controls. Generated files may overwrite direct edits; prefer a correction note.",
                id="memory-status",
            )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#memory-table", DataTable)
        table.add_columns("Type", "Project / source", "Modified", "Size", "File")
        self._reload()
        table.focus()

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 100, "narrow")
        self.set_class(event.size.height < 30, "short")

    def _all_entries(self) -> list[MemoryEntry]:
        root = self.memories.root
        core_files = (
            (
                "memory_summary.md",
                "summary",
                "Compact cross-project recall layer that Codex can inject into future sessions.",
            ),
            (
                "MEMORY.md",
                "registry",
                "Organized durable registry, grouped by task/project, with pointers to evidence.",
            ),
            (
                "raw_memories.md",
                "raw",
                "Generated extraction/staging material used to build the organized registry.",
            ),
        )
        entries: list[MemoryEntry] = []
        for name, category, description in core_files:
            path = root / name
            if path.is_file():
                entries.append(MemoryEntry(path, category, description, "all projects"))
        groups = (
            (
                root / "extensions" / "ad_hoc" / "notes",
                "correction",
                "User-authored memory correction.",
            ),
            (
                root / "rollout_summaries",
                "evidence",
                "Evidence summary behind durable memory.",
            ),
        )
        for directory, category, description in groups:
            if directory.exists():
                for path in directory.glob("*.md"):
                    project = (
                        "user-authored"
                        if category == "correction"
                        else self._evidence_project(path)
                    )
                    entries.append(MemoryEntry(path, category, description, project))
        overview_types = {"summary", "registry", "raw"}
        core = [item for item in entries if item.category in overview_types]
        rest = sorted(
            (item for item in entries if item.category not in overview_types),
            key=lambda item: item.path.stat().st_mtime,
            reverse=True,
        )
        return core + rest

    @staticmethod
    def _evidence_project(path: Path) -> str:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for _ in range(12):
                    line = handle.readline()
                    if not line:
                        break
                    if line.startswith("cwd:"):
                        cwd = line.partition(":")[2].strip()
                        home_prefix = str(Path.home()) + "/"
                        return cwd.removeprefix(home_prefix) or "home"
        except OSError:
            pass
        return "unknown"

    def _reload(self) -> None:
        self.entries = self._all_entries()
        self._update_config()
        self._filter()

    def _filter(self) -> None:
        needle = self.query_one("#memory-search", Input).value.casefold().strip()
        view = self._view_value()
        overview_types = {"summary", "registry", "raw"}

        def visible(item: MemoryEntry) -> bool:
            if view == "overview":
                return item.category in overview_types
            if view == "all":
                return True
            return item.category == view

        self.filtered_entries = [
            item
            for item in self.entries
            if visible(item)
            and (
                not needle
                or needle in str(item.path.relative_to(self.memories.root)).casefold()
                or needle in item.category.casefold()
                or needle in item.description.casefold()
                or needle in item.project.casefold()
            )
        ]
        table = self.query_one("#memory-table", DataTable)
        old = self.selected_path
        table.clear()
        for entry in self.filtered_entries:
            table.add_row(
                entry.category,
                _short(entry.project, 42),
                entry.modified,
                self.human_size(entry.path.stat().st_size),
                str(entry.path.relative_to(self.memories.root)),
                key=str(entry.path),
            )
        if self.filtered_entries:
            index = next(
                (i for i, item in enumerate(self.filtered_entries) if item.path == old),
                0,
            )
            table.move_cursor(row=index)
            self._select(self.filtered_entries[index])
        else:
            self.selected_path = None
            self.query_one("#memory-preview", Markdown).update(
                "No matching memory files."
            )

    def _view_value(self) -> str:
        value = self.query_one("#memory-kind", Select).value
        return value if isinstance(value, str) else "overview"

    @staticmethod
    def _config_state(value: Any, default: bool) -> str:
        if value is True:
            return "ON"
        if value is False:
            return "OFF"
        return f"{'ON' if default else 'OFF'} (default)"

    @staticmethod
    def _effective_config(value: Any, default: bool) -> bool:
        return value if isinstance(value, bool) else default

    def _update_config(self) -> None:
        try:
            values = self.memories.config_values()
        except RuntimeError as error:
            self.query_one("#memory-config", Static).update(str(error))
            for name in ("toggle-use", "toggle-generate", "toggle-external"):
                self.query_one(f"#{name}", Button).disabled = True
            return
        use = self._config_state(values["use_memories"], True)
        generate = self._config_state(values["generate_memories"], True)
        external = self._config_state(values["disable_on_external_context"], False)
        text = (
            "[b]Use[/b] controls recall in later chats.  "
            "[b]Learn[/b] controls whether new chats may become memory.  "
            "[b]Exclude web/MCP[/b] prevents externally sourced chats from becoming memory.  "
            f"Memory feature: {escape(str(values['feature']))}"
        )
        self.query_one("#memory-config", Static).update(text)
        use_button = self.query_one("#toggle-use", Button)
        use_button.label = f"Use in future chats: {use}"
        use_button.tooltip = (
            "Whether Codex injects stored memory into future chats. Click to set "
            f"{'OFF' if self._effective_config(values['use_memories'], True) else 'ON'}."
        )
        generate_button = self.query_one("#toggle-generate", Button)
        generate_button.label = f"Learn from new chats: {generate}"
        generate_button.tooltip = (
            "Whether eligible new chats may be summarized into memory. Click to set "
            f"{'OFF' if self._effective_config(values['generate_memories'], True) else 'ON'}."
        )
        external_button = self.query_one("#toggle-external", Button)
        external_button.label = f"Exclude web/MCP learning: {external}"
        external_button.tooltip = (
            "When ON, chats using external context such as MCP or web search are not learned from. "
            "Click to set "
            f"{'OFF' if self._effective_config(values['disable_on_external_context'], False) else 'ON'}."
        )

    def _select(self, entry: MemoryEntry) -> None:
        self.selected_path = entry.path
        size = entry.path.stat().st_size
        with entry.path.open("r", encoding="utf-8", errors="replace") as handle:
            content = handle.read(180_000)
            clipped = handle.read(1) != ""
        relative = entry.path.relative_to(self.memories.root)
        heading = (
            f"### {relative}\n\n{entry.description}\n\n"
            f"Size: {self.human_size(size)} · Modified: {entry.modified}\n\n---\n\n"
        )
        if clipped:
            content += "\n\n---\n\n*Preview limited to 180 KB. Press Enter to load the complete file.*"
        self.query_one("#memory-preview", Markdown).update(heading + content)

    def _selected_entry(self) -> MemoryEntry | None:
        if self.selected_path is None:
            return None
        return next(
            (item for item in self.entries if item.path == self.selected_path), None
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        path = Path(str(event.row_key.value))
        entry = next((item for item in self.entries if item.path == path), None)
        if entry:
            self._select(entry)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_open()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "memory-search":
            self._filter()

    def on_select_changed(self, event: Select.Changed) -> None:
        if self.is_mounted and event.select.id == "memory-kind":
            self._filter()

    def action_search(self) -> None:
        self.query_one("#memory-search", Input).focus()

    def action_close(self) -> None:
        self.dismiss(None)

    def action_open(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        try:
            content = entry.path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            self.app.notify(str(error), severity="error")
            return
        self.app.push_screen(
            DocumentScreen(str(entry.path.relative_to(self.memories.root)), content)
        )

    def action_explain(self) -> None:
        document = """# How Codex local memory works

This is **one local memory store shared by all of your Codex projects** within the selected Codex home. It is not a separate memory database per repository. Website work, an image experiment, and a personal notes app can therefore appear together.

## The four layers

1. **Summary (`memory_summary.md`)** — the compact cross-project recall layer. This is the easiest place to see what broad facts and preferences Codex may carry into a later chat.
2. **Registry (`MEMORY.md`)** — organized durable entries grouped by task/project. It includes keywords and pointers to supporting summaries.
3. **Raw extraction (`raw_memories.md`)** — generated staging material from the memory-building process. It is useful for diagnosis, but normally not what you should curate first.
4. **Evidence (`rollout_summaries/`)** — one supporting summary per remembered source chat. These files explain where registry entries came from; they are not all independently injected as one giant prompt.

The **Overview** filter intentionally shows only the first three files. Choose **Evidence** when you need to audit a particular remembered chat.

## The three controls

- **Use in future chats**: allows stored memories to be added to later Codex chats. Turn this OFF when you want no memory recall.
- **Learn from new chats**: allows eligible new chats to become inputs to future memory generation. Turning it OFF stops new learning; it does not erase existing memory.
- **Exclude web/MCP learning**: when ON, chats that used external context such as MCP or web search are excluded from future memory generation. This reduces the chance of copied or transient external information becoming durable memory.

`ON (default)` or `OFF (default)` means you have not explicitly set that option in `config.toml`; the effective built-in default is shown. Clicking a control writes an explicit ON or OFF setting and creates a configuration backup.

## Correcting wrong or irrelevant memory

Use **Add correction** to state what is obsolete and what should replace it. Directly editing generated core files is possible, with a backup, but Codex may regenerate them later. A correction note is therefore the safer durable instruction.

There is currently no project-isolation switch in this browser: its display filter does not change what Codex itself may recall. If cross-project recall is consistently unhelpful, turn **Use in future chats** OFF globally while we decide on a stricter policy.
"""
        self.app.push_screen(DocumentScreen("How Codex memory works", document))

    def action_edit(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        relative = str(entry.path.relative_to(self.memories.root))
        self.app.push_screen(
            ConfirmDialog(
                "Directly edit generated memory?",
                f"A timestamped backup will be created before opening your editor.\n\n{relative}\n\n"
                "Codex may regenerate core files later. Prefer a correction note when possible.",
                "Back up and edit",
            ),
            lambda confirmed: (
                self.app.exit(("edit-memory", relative)) if confirmed else None
            ),
        )

    def action_correct(self) -> None:
        self.app.push_screen(
            PromptDialog(
                "Add a durable memory correction",
                "State what is obsolete or irrelevant and what should replace it. A note is created under "
                "memories/extensions/ad_hoc/notes/.",
                placeholder="The old value is wrong; use …",
            ),
            self._create_correction,
        )

    def _create_correction(self, text: str | None) -> None:
        if not text:
            return
        try:
            path = self.memories.correct(text, quiet=True)
            self._reload()
            self.app.notify(f"Created {path.name}")
        except (OSError, ValueError, RuntimeError) as error:
            self.app.notify(str(error), severity="error")

    def _toggle(self, setting: str, key: str) -> None:
        current = self.memories.config_values()[key]
        defaults = {
            "use_memories": True,
            "generate_memories": True,
            "disable_on_external_context": False,
        }
        enabled = not self._effective_config(current, defaults[key])
        try:
            self.memories.set_config(setting, enabled, quiet=True)
            self._update_config()
            self.app.notify(
                f"Memory {setting} set to {'on' if enabled else 'off'}; config backup created"
            )
        except (OSError, ValueError, RuntimeError) as error:
            self.app.notify(str(error), severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "memory-back": self.action_close,
            "memory-help": self.action_explain,
            "memory-open": self.action_open,
            "memory-edit": self.action_edit,
            "memory-correct": self.action_correct,
            "toggle-use": lambda: self._toggle("use", "use_memories"),
            "toggle-generate": lambda: self._toggle("generate", "generate_memories"),
            "toggle-external": lambda: self._toggle(
                "exclude-external", "disable_on_external_context"
            ),
        }
        action = actions.get(event.button.id or "")
        if action:
            action()
