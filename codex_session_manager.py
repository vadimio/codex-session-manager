#!/usr/bin/env -S uv run --locked --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["textual==8.2.8"]
# ///
"""Readable, conservative management for local Codex sessions and memories.

The script reads Codex's compact SQLite index for metadata and touches rollout
JSONL only when a conversation preview or export is requested. Destructive
session operations are delegated to the installed ``codex`` CLI.
"""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from session_memory import MemoryManager, update_toml_section_value
from session_models import (
    MAX_JSON_LINE,
    VERSION,
    ExtractResult,
    Message,
    Session,
    default_codex_home,
    human_size,
    local_time,
)
from session_store import SessionManager
from session_transcript import (
    extract_legacy_conversation,
    parse_jsonl_buffer,
    render_compact_archive,
)

# Compatibility imports for existing callers of the original single-file tool.
__all__ = [
    "Session",
    "Message",
    "ExtractResult",
    "SessionManager",
    "MemoryManager",
    "MAX_JSON_LINE",
    "parse_jsonl_buffer",
    "extract_legacy_conversation",
    "render_compact_archive",
    "update_toml_section_value",
    "subprocess",
    "build_parser",
    "main",
]


def add_common_list_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state", choices=("all", "active", "archived", "live"), default="all"
    )
    parser.add_argument(
        "--search", default="", help="substring in id/name/preview/cwd/source"
    )
    parser.add_argument(
        "--sort", choices=("updated", "created", "size", "name"), default="updated"
    )
    parser.add_argument("--reverse", action="store_true")
    parser.add_argument(
        "--limit", type=int, default=30, help="0 means all (default: 30)"
    )
    parser.add_argument(
        "--preview", type=int, default=2, help="messages at each edge; 0 disables"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and safely manage local Codex sessions and memories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run without a subcommand for the terminal UI. Select a session and press W to rewind later exchanges.",
    )
    parser.add_argument("--codex-home", type=Path, default=default_codex_home())
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    commands = parser.add_subparsers(dest="command")

    listing = commands.add_parser("list", aliases=["ls"], help="list sessions")
    add_common_list_args(listing)

    commands.add_parser("stats", help="size and state summary")

    show = commands.add_parser("show", help="metadata plus conversation edges")
    show.add_argument("session")
    show.add_argument("--count", type=int, default=5)
    show.add_argument("--all", action="store_true", dest="full")

    transcript = commands.add_parser(
        "transcript", aliases=["more"], help="all user and final messages"
    )
    transcript.add_argument("session")

    rename = commands.add_parser("rename", help="set the real Codex session name")
    rename.add_argument("session")
    rename.add_argument("name", nargs="+")

    for action in ("archive", "unarchive", "delete"):
        action_parser = commands.add_parser(action)
        action_parser.add_argument("session")
        action_parser.add_argument(
            "--yes", action="store_true", help="skip this script's confirmation"
        )

    resume = commands.add_parser("resume")
    resume.add_argument("session")
    resume.add_argument(
        "--unrestricted",
        action="store_true",
        help="disable sandbox and approvals for this resumed session (dangerous)",
    )

    compact = commands.add_parser(
        "compact", help="export readable user/final-only Markdown"
    )
    compact.add_argument("session")
    compact.add_argument("--output", type=Path)
    compact.add_argument(
        "--delete-source",
        action="store_true",
        help="after verified export, permanently delete the resumable Codex transcript",
    )
    compact.add_argument("--yes", action="store_true", help="skip delete confirmation")

    commands.add_parser(
        "interactive", aliases=["shell"], help="full-screen Textual interface"
    )

    memory = commands.add_parser(
        "memory", help="inspect and control local Codex memories"
    )
    memory_commands = memory.add_subparsers(dest="memory_command")
    memory_commands.add_parser("list", aliases=["ls"])
    memory_show = memory_commands.add_parser("show")
    memory_show.add_argument("target", help="alias or relative path under memories/")
    memory_edit = memory_commands.add_parser("edit")
    memory_edit.add_argument("target", help="alias or relative path under memories/")
    memory_edit.add_argument("--direct", action="store_true")
    memory_edit.add_argument("--yes", action="store_true")
    memory_correct = memory_commands.add_parser("correct")
    memory_correct.add_argument("text", nargs="*")
    memory_commands.add_parser("config")
    memory_set = memory_commands.add_parser("set")
    memory_set.add_argument("setting", choices=("use", "generate", "exclude-external"))
    memory_set.add_argument("value", choices=("on", "off"))
    return parser


def interactive(manager: SessionManager, memories: MemoryManager) -> None:
    """Launch the modern full-screen TUI while keeping all backend logic here."""
    # Resolve the source directory explicitly so launchers may safely symlink this
    # script from ~/.local/bin or the legacy ~/.codex/bin location.
    source_dir = str(Path(__file__).resolve().parent)
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    try:
        from codex_session_tui import run_tui
    except ModuleNotFoundError as error:
        if error.name != "textual":
            raise
        raise RuntimeError(
            "The full-screen interface requires Textual. Run this executable directly "
            "(not `python codex_session_manager.py`) so uv can provide its pinned dependency."
        ) from error
    run_tui(
        manager,
        memories,
        {
            "human_size": human_size,
            "local_time": local_time,
        },
    )


def dispatch(parsed: argparse.Namespace) -> int:
    home = parsed.codex_home.expanduser().resolve()
    manager = SessionManager(home)
    memories = MemoryManager(home)
    command = parsed.command
    if command in {None, "interactive", "shell"}:
        if command is None and not sys.stdin.isatty():
            manager.list_sessions()
        else:
            interactive(manager, memories)
    elif command in {"list", "ls"}:
        manager.list_sessions(
            state=parsed.state,
            search=parsed.search,
            sort=parsed.sort,
            reverse=parsed.reverse,
            limit=parsed.limit,
            preview_count=parsed.preview,
        )
    elif command == "stats":
        manager.stats()
    elif command == "show":
        manager.show(
            manager.resolve(parsed.session), count=parsed.count, full=parsed.full
        )
    elif command in {"transcript", "more"}:
        manager.show(manager.resolve(parsed.session), full=True)
    elif command == "rename":
        manager.rename(manager.resolve(parsed.session), " ".join(parsed.name))
    elif command in {"archive", "unarchive", "delete"}:
        manager.run_codex_action(
            command, manager.resolve(parsed.session), yes=parsed.yes
        )
    elif command == "resume":
        manager.resume(
            manager.resolve(parsed.session), unrestricted=parsed.unrestricted
        )
    elif command == "compact":
        manager.compact_archive(
            manager.resolve(parsed.session),
            parsed.output,
            parsed.delete_source,
            parsed.yes,
        )
    elif command == "memory":
        memory_command = parsed.memory_command or "list"
        if memory_command in {"list", "ls"}:
            memories.inventory()
        elif memory_command == "show":
            memories.show(parsed.target)
        elif memory_command == "edit":
            memories.edit(parsed.target, direct=parsed.direct, yes=parsed.yes)
        elif memory_command == "correct":
            memories.correct(" ".join(parsed.text) or None)
        elif memory_command == "config":
            memories.show_config()
        elif memory_command == "set":
            memories.set_config(parsed.setting, parsed.value == "on")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(argv)
    try:
        return dispatch(parsed)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
