from __future__ import annotations

import os
import re
import sqlite3
import sys
import textwrap
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

VERSION = tomllib.loads(Path(__file__).with_name("pyproject.toml").read_text())[
    "project"
]["version"]
CACHE_VERSION = 5
UUID_RE = re.compile(
    r"(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
ROLLOUT_DATE_RE = re.compile(r"rollout-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})")
EDGE_BYTES = 8 * 1024 * 1024
MAX_JSON_LINE = 8 * 1024 * 1024
HUGE_BYTES = 100 * 1024 * 1024
GIANT_BYTES = 1024 * 1024 * 1024


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else Path.home() / ".codex"
    )


@dataclass
class Session:
    id: str
    rollout_path: Path
    created_ms: int
    updated_ms: int
    recency_ms: int
    archived: bool
    pinned: bool
    name: str
    title: str
    preview: str
    cwd: str
    source: str
    history_mode: str
    indexed: bool = True
    live: bool = False

    @property
    def display_name(self) -> str:
        if self.name.strip():
            return self.name.strip()
        for candidate in (self.title, self.preview):
            if is_real_user_text(candidate):
                return candidate.strip()
        return "(unnamed session)"

    @property
    def size(self) -> int:
        try:
            return self.rollout_path.stat().st_size
        except OSError:
            return 0

    @property
    def mtime_ns(self) -> int:
        try:
            return self.rollout_path.stat().st_mtime_ns
        except OSError:
            return 0

    @property
    def state(self) -> str:
        if self.live:
            return "LIVE"
        if self.archived:
            return "ARCHIVED"
        if not self.indexed:
            return "UNINDEXED"
        return "ACTIVE"


@dataclass
class Message:
    role: str
    text: str
    timestamp: str = ""
    ordinal: int = 0
    turn_id: str = ""


@dataclass
class ExtractResult:
    messages: list[Message]
    skipped_oversize_lines: int = 0
    malformed_candidate_lines: int = 0
    sha256: str | None = None


def human_size(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return (
                f"{number:.0f} {unit}"
                if unit in {"B", "KiB"}
                else f"{number:.1f} {unit}"
            )
        number /= 1024
    return f"{value} B"


def local_time(ms: int) -> str:
    if not ms:
        return "unknown"
    return (
        datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M")
    )


def compact_text(text: str, width: int = 120) -> str:
    cleaned = " ".join(text.replace("\x00", "").split())
    return (
        textwrap.shorten(cleaned, width=max(width, 10), placeholder=" …")
        if cleaned
        else "(empty)"
    )


def is_real_user_text(text: str, content_kinds: Sequence[str] = ()) -> bool:
    """Reject Codex-injected context that is serialized with a user role."""
    stripped = text.lstrip()
    injected_prefixes = (
        "<environment_context>",
        "<skills_instructions>",
        "<permissions instructions>",
        "<collaboration_mode>",
        "<apps_instructions>",
        "<plugins_instructions>",
        "<user_instructions>",
        "<recommended_plugins>",
        "<turn_aborted>",
        "<developer",
        "<system",
        "# AGENTS.md instructions for ",
    )
    if stripped.startswith(injected_prefixes):
        return False
    if content_kinds and not any(
        str(kind).startswith("user.") for kind in content_kinds
    ):
        return False
    return bool(stripped)


def safe_slug(value: str, fallback: str = "session") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return (slug[:80] or fallback).lower()


def connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(f"{prompt} [y/N] ").strip().casefold() in {"y", "yes"}
