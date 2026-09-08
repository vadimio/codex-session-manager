from __future__ import annotations

import asyncio
import shlex
from typing import Any

from textual.widgets import (
    Button,
    Input,
    Select,
    Static,
)

from ui_common import _code, _message_excerpt
from ui_dialogs import ConfirmDialog, DeleteDialog, PromptDialog
from ui_documents import ConversationScreen, DocumentScreen
from ui_memory import MemoryScreen


class SessionActions:
    def action_rewind(self):
        session = self._selected()
        if session:
            self._open_rewind(session)

    def _open_rewind(self, session):
        from ui_rewind import RewindScreen

        if not self.mutation_busy:
            self.push_screen(
                RewindScreen(self.manager, session),
                lambda changed: (
                    self.refresh_rows(reload_backend=True) if changed else None
                ),
            )

    def _start_mutation(self, factory):
        if self.mutation_busy:
            self.notify("Wait for the current operation to finish.")
            return
        self.mutation_busy = True
        self._update_action_state(self._selected())

        async def perform():
            try:
                await factory()
            finally:
                self.mutation_busy = False
                self._update_action_state(self._selected())

        self.run_worker(
            perform(), group="mutation", exclusive=False, exit_on_error=False
        )

    def action_details(self) -> None:
        session = self._selected()
        if not session:
            return
        self.run_worker(
            self._load_details(session),
            group="document",
            exclusive=True,
            exit_on_error=False,
        )

    async def _load_details(self, session):
        try:
            beginning, ending, note = await asyncio.to_thread(
                self.manager.quick_preview, session, 8
            )
        except (OSError, ValueError, RuntimeError) as error:
            self.notify(str(error), severity="error")
            return
        parts = [
            f"# {session.display_name}",
            f"- ID: {_code(session.id)}",
            f"- State: **{session.state}** · flags {_code(self.flags(session))}",
            f"- Size: {self.human_size(session.size)} ({session.size:,} bytes)",
            f"- Created: {self.local_time(session.created_ms)}",
            f"- Last used: {self.local_time(session.recency_ms)}",
            f"- Directory: {_code(session.cwd or '(unknown)')}",
            f"- Transcript: {_code(session.rollout_path)}",
            "## Beginning",
        ]
        parts.extend(_message_excerpt(item, 12_000) for item in beginning)
        parts.append("## End")
        parts.extend(_message_excerpt(item, 12_000) for item in ending)
        if note:
            parts.append(f"*{note}*")
        self.push_screen(DocumentScreen(session.display_name, "\n\n".join(parts)))

    def action_transcript(self) -> None:
        session = self._selected()
        if not session:
            return
        self.query_one("#status", Static).update(
            f"Reading {self.human_size(session.size)} for user messages and final answers…"
        )
        self.run_worker(
            self._load_transcript(session),
            name="full-transcript",
            group="long-action",
            exclusive=True,
            exit_on_error=False,
        )

    async def _load_transcript(self, session: Any) -> None:
        try:
            extracted = await asyncio.to_thread(self.manager.full_conversation, session)
            metadata = (
                f"{len(extracted.messages)} human/final messages · "
                f"{self.human_size(session.size)} source · {session.id[:8]} · "
                "user shaded / Codex black"
            )
            if extracted.skipped_oversize_lines:
                metadata += f" · skipped {extracted.skipped_oversize_lines} oversized payload lines"
            if extracted.malformed_candidate_lines:
                metadata += f" · WARNING: {extracted.malformed_candidate_lines} malformed message records skipped"
            self.push_screen(
                ConversationScreen(
                    session.display_name,
                    extracted.messages,
                    metadata,
                    rewind=lambda: self._open_rewind(session),
                )
            )
            self.query_one("#status", Static).update(
                "Full conversation loaded: human inputs and Codex final answers only"
            )
        except (OSError, ValueError, RuntimeError) as error:
            self.notify(str(error), severity="error", timeout=8)
            self.query_one("#status", Static).update("Transcript load failed")

    def action_rename(self) -> None:
        session = self._selected()
        if not session:
            return
        self.push_screen(
            PromptDialog(
                "Rename session",
                "This is the real name Codex stores and displays.",
                session.display_name,
            ),
            lambda name: self._begin_rename(session, name),
        )

    def _begin_rename(self, session: Any, name: str | None) -> None:
        if not name or name == session.display_name:
            return
        self._start_mutation(lambda: self._rename(session, name))

    async def _rename(self, session: Any, name: str) -> None:
        try:
            await asyncio.to_thread(self.manager.rename, session, name, True)
            self.refresh_rows()
            self.notify(f"Renamed to {name}")
        except (OSError, ValueError, RuntimeError) as error:
            self.notify(str(error), severity="error", timeout=8)

    def action_archive(self) -> None:
        session = self._selected()
        if not session or session.live:
            return
        action = "unarchive" if session.archived else "archive"
        label = "Restore" if session.archived else "Archive"
        self.push_screen(
            ConfirmDialog(
                f"{label} session?",
                f"{session.display_name}\n{session.id}\n{self.human_size(session.size)}\n\n"
                + (
                    "It will return to the active Codex picker."
                    if session.archived
                    else "This hides it from the normal active picker but does not reclaim disk space."
                ),
                label,
            ),
            lambda confirmed: (
                self._begin_codex_action(action, session) if confirmed else None
            ),
        )

    def _begin_codex_action(self, action: str, session: Any) -> None:
        self._start_mutation(lambda: self._codex_action(action, session))

    async def _codex_action(self, action: str, session: Any) -> None:
        try:
            await asyncio.to_thread(
                self.manager.run_codex_action, action, session, True, True
            )
            self.selected_id = None
            self.refresh_rows()
            verb = {
                "archive": "Archived",
                "unarchive": "Restored",
                "delete": "Deleted",
            }[action]
            self.notify(f"{verb} {session.id[:8]}")
        except (OSError, ValueError, RuntimeError) as error:
            self.notify(str(error), severity="error", timeout=8)

    def action_delete(self) -> None:
        session = self._selected()
        if not session or session.live:
            return
        self.push_screen(
            DeleteDialog(session, self.human_size),
            lambda confirmed: (
                self._begin_codex_action("delete", session) if confirmed else None
            ),
        )

    def action_compact(self) -> None:
        session = self._selected()
        if not session or session.live:
            return
        self.push_screen(
            ConfirmDialog(
                "Create compact historical archive?",
                f"Read {self.human_size(session.size)} and preserve only your messages and Codex final answers.\n\n"
                "The verified Markdown is historical reference, not resumable. The original session remains unchanged.",
                "Create archive",
            ),
            lambda confirmed: self._begin_compact(session) if confirmed else None,
        )

    def _begin_compact(self, session: Any) -> None:
        self.query_one("#status", Static).update(
            f"Compacting {self.human_size(session.size)} in the background; the original remains untouched…"
        )
        self._start_mutation(lambda: self._compact(session))

    async def _compact(self, session: Any) -> None:
        try:
            path = await asyncio.to_thread(
                self.manager.compact_archive, session, None, False, True, True
            )
            self.notify(f"Verified compact archive: {path}", timeout=10)
            self.query_one("#status", Static).update(f"Compact archive written: {path}")
        except (OSError, ValueError, RuntimeError) as error:
            self.notify(str(error), severity="error", timeout=10)
            self.query_one("#status", Static).update(
                "Compact export failed; original unchanged"
            )

    def action_resume_safe(self) -> None:
        session = self._selected()
        if session and not session.live and not self.mutation_busy:
            self.exit(("resume-safe", session.id))

    def action_resume_unrestricted(self) -> None:
        session = self._selected()
        if not session or session.live or self.mutation_busy:
            return
        self.push_screen(
            ConfirmDialog(
                "Resume without sandbox or approvals?",
                f"{session.display_name}\n{session.id}\n\n"
                "This gives Codex unrestricted filesystem and network access and disables all "
                "approval prompts for the resumed session. A malicious or mistaken instruction "
                "could expose credentials, overwrite files, or run destructive commands.",
                "Resume unrestricted",
                danger=True,
            ),
            lambda confirmed: (
                self.exit(("resume-unrestricted", session.id)) if confirmed else None
            ),
        )

    def action_memory(self) -> None:
        self.push_screen(MemoryScreen(self.memories, self.human_size))

    def action_help(self) -> None:
        help_text = """# Session manager keys

| Key | Action |
|---|---|
| ↑ / ↓, PgUp / PgDn | Move through sessions |
| Enter | Summary: metadata plus larger beginning/end excerpts |
| V (or T) | Full conversation: every user message and Codex final answer |
| S | Resume safe: workspace-write sandbox with on-request approvals |
| U | Resume unrestricted after a danger confirmation |
| R | Rename the real Codex session |
| W | Choose an exchange and rewind later conversation history |
| A | Archive or restore (reversible, no disk space reclaimed) |
| C | Create a verified, readable compact archive |
| D | Permanently delete after typing the complete UUID |
| M | Browse and correct Codex memory |
| / | Focus live search |
| : | Open the command bar |
| Ctrl+R | Reload current Codex state |
| Ctrl+P | Textual command palette |
| Q | Quit |

Commands include `:filter active|live|archived|all`, `:sort size|updated|created|name`,
`:rename NEW NAME`, `:archive`, `:delete`, `:compact`, `:resume`,
`:resume-unrestricted`, `:memory`, `:refresh`, `:search WORDS`, and `:quit`.

All session previews and full views contain only genuine human inputs and assistant
final answers. Commentary, reasoning, tool calls/results, and intermediate AI messages
are excluded.
"""
        self.push_screen(DocumentScreen("Help", help_text))

    def _execute_command(self, raw: str) -> None:
        try:
            tokens = shlex.split(raw.lstrip(":"))
        except ValueError as error:
            self.notify(str(error), severity="error")
            return
        if not tokens:
            return
        command, args = tokens[0].casefold(), tokens[1:]
        actions = {
            "help": self.action_help,
            "details": self.action_details,
            "summary": self.action_details,
            "show": self.action_details,
            "transcript": self.action_transcript,
            "view": self.action_transcript,
            "full": self.action_transcript,
            "more": self.action_transcript,
            "archive": self.action_archive,
            "restore": self.action_archive,
            "unarchive": self.action_archive,
            "compact": self.action_compact,
            "rewind": self.action_rewind,
            "delete": self.action_delete,
            "resume": self.action_resume_safe,
            "resume-safe": self.action_resume_safe,
            "resume-unrestricted": self.action_resume_unrestricted,
            "memory": self.action_memory,
            "memories": self.action_memory,
            "refresh": self.action_refresh,
            "quit": self.action_quit,
            "exit": self.action_quit,
        }
        if command in actions:
            actions[command]()
        elif command == "rename" and args:
            session = self._selected()
            if session:
                self._begin_rename(session, " ".join(args))
        elif command == "search":
            self.query_one("#search", Input).value = " ".join(args)
        elif (
            command == "filter"
            and args
            and args[0] in {"all", "active", "live", "archived"}
        ):
            self.query_one("#state-select", Select).value = args[0]
        elif (
            command == "sort"
            and args
            and args[0] in {"updated", "size", "created", "name"}
        ):
            self.query_one("#sort-select", Select).value = args[0]
        else:
            self.notify(
                f"Unknown or incomplete command: {raw}. Try :help", severity="warning"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "direction": self._toggle_direction,
            "refresh": self.action_refresh,
            "memory-button": self.action_memory,
            "details": self.action_details,
            "transcript": self.action_transcript,
            "rename": self.action_rename,
            "rewind": self.action_rewind,
            "archive": self.action_archive,
            "compact": self.action_compact,
            "resume-safe": self.action_resume_safe,
            "resume-unrestricted": self.action_resume_unrestricted,
            "delete": self.action_delete,
        }
        action = actions.get(event.button.id or "")
        if action:
            action()

    def _toggle_direction(self) -> None:
        self.reverse = not self.reverse
        self.refresh_rows()
