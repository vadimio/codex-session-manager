from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from session_models import (
    CACHE_VERSION,
    GIANT_BYTES,
    HUGE_BYTES,
    ROLLOUT_DATE_RE,
    UUID_RE,
    Message,
    Session,
    compact_text,
    connect_readonly,
    human_size,
    local_time,
)


class Inventory:
    def __init__(self, codex_home: Path):
        self.home = codex_home.resolve()
        self.state_db = self.home / "state_5.sqlite"
        self.history_db = self.home / "thread_history_1.sqlite"
        self.cache_path = self.home / ".session-manager-cache.json"
        self.export_dir = self.home / "compact_session_archives"
        self.sessions: list[Session] = []
        self.last_listing: list[Session] = []
        self._cache = self._load_cache()
        self._cache_changed = False
        self.reload()

    def _load_cache(self) -> dict[str, Any]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return (
                data
                if data.get("version") == CACHE_VERSION
                else {"version": CACHE_VERSION, "sessions": {}}
            )
        except (OSError, json.JSONDecodeError, AttributeError):
            return {"version": CACHE_VERSION, "sessions": {}}

    def _codex_environment(self) -> dict[str, str]:
        """Keep delegated Codex commands on the runtime tree being managed."""
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(self.home)
        return environment

    def save_cache(self) -> None:
        if not self._cache_changed:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.cache_path.parent, delete=False
        ) as handle:
            json.dump(self._cache, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self.cache_path)
        self._cache_changed = False

    def reload(self) -> None:
        indexed: dict[str, Session] = {}
        if self.state_db.exists():
            with connect_readonly(self.state_db) as db:
                query = """
                    SELECT id, rollout_path,
                           COALESCE(created_at_ms, created_at * 1000) AS created_ms,
                           COALESCE(updated_at_ms, updated_at * 1000) AS updated_ms,
                           CASE WHEN recency_at_ms > 0 THEN recency_at_ms
                                ELSE COALESCE(updated_at_ms, updated_at * 1000) END AS recency_ms,
                           archived, is_pinned, COALESCE(name, '') AS name,
                           COALESCE(title, '') AS title, COALESCE(preview, '') AS preview,
                           COALESCE(cwd, '') AS cwd, COALESCE(source, '') AS source,
                           COALESCE(history_mode, 'legacy') AS history_mode
                    FROM threads
                """
                for row in db.execute(query):
                    session = Session(
                        id=row["id"],
                        rollout_path=Path(row["rollout_path"]),
                        created_ms=int(row["created_ms"] or 0),
                        updated_ms=int(row["updated_ms"] or 0),
                        recency_ms=int(row["recency_ms"] or 0),
                        archived=bool(row["archived"]),
                        pinned=bool(row["is_pinned"]),
                        name=row["name"],
                        title=row["title"],
                        preview=row["preview"],
                        cwd=row["cwd"],
                        source=str(row["source"]),
                        history_mode=row["history_mode"],
                    )
                    session.live = self._is_live(session.id)
                    indexed[session.id] = session

        discovered: dict[str, Path] = {}
        for dirname in ("sessions", "archived_sessions"):
            root = self.home / dirname
            if root.exists():
                for path in root.rglob("*.jsonl"):
                    match = UUID_RE.search(path.name)
                    if match:
                        discovered[match.group("id").lower()] = path

        for session_id, path in discovered.items():
            if session_id in indexed:
                if not indexed[session_id].rollout_path.exists():
                    indexed[session_id].rollout_path = path
                continue
            stat = path.stat()
            created_ms = self._created_from_filename(path) or int(stat.st_mtime * 1000)
            session = Session(
                id=session_id,
                rollout_path=path,
                created_ms=created_ms,
                updated_ms=int(stat.st_mtime * 1000),
                recency_ms=int(stat.st_mtime * 1000),
                archived="archived_sessions" in path.parts,
                pinned=False,
                name="",
                title="",
                preview="",
                cwd="",
                source="unknown",
                history_mode="legacy",
                indexed=False,
            )
            session.live = self._is_live(session.id)
            indexed[session_id] = session

        self.sessions = sorted(
            indexed.values(), key=lambda item: (item.recency_ms, item.id), reverse=True
        )

    @staticmethod
    def _created_from_filename(path: Path) -> int:
        match = ROLLOUT_DATE_RE.search(path.name)
        if not match:
            return 0
        try:
            parsed = datetime.strptime(match.group(1), "%Y-%m-%dT%H-%M-%S").astimezone()
            return int(parsed.timestamp() * 1000)
        except ValueError:
            return 0

    def _is_live(self, session_id: str) -> bool:
        lock = self.home / "thread-writer-locks" / f"{session_id}.lock"
        if not lock.exists():
            return False
        try:
            with lock.open("rb") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    return False
        except OSError as error:
            raise RuntimeError(
                f"Cannot check writer lock for {session_id}: {error}"
            ) from error

    def filter_sessions(
        self,
        state: str = "all",
        search: str = "",
        sort: str = "updated",
        reverse: bool = False,
    ) -> list[Session]:
        result = self.sessions
        if state == "active":
            result = [item for item in result if not item.archived]
        elif state == "archived":
            result = [item for item in result if item.archived]
        elif state == "live":
            result = [item for item in result if item.live]
        if search:
            needle = search.casefold()
            result = [
                item
                for item in result
                if needle
                in " ".join(
                    (item.id, item.display_name, item.preview, item.cwd, item.source)
                ).casefold()
            ]
        keys = {
            "updated": lambda item: (item.recency_ms, item.id),
            "created": lambda item: (item.created_ms, item.id),
            "size": lambda item: (item.size, item.recency_ms),
            "name": lambda item: (item.display_name.casefold(), item.recency_ms),
        }
        descending = sort != "name"
        return sorted(result, key=keys[sort], reverse=descending != reverse)

    def resolve(self, reference: str) -> Session:
        reference = reference.strip()
        if reference.isdigit() and self.last_listing:
            index = int(reference) - 1
            if 0 <= index < len(self.last_listing):
                return self.last_listing[index]
            raise ValueError(f"list index {reference} is out of range")

        folded = reference.casefold()
        exact = [item for item in self.sessions if item.id.casefold() == folded]
        if exact:
            return exact[0]
        prefix = [
            item
            for item in self.sessions
            if len(reference) >= 4 and item.id.casefold().startswith(folded)
        ]
        if len(prefix) == 1:
            return prefix[0]
        names = [
            item for item in self.sessions if item.display_name.casefold() == folded
        ]
        if len(names) == 1:
            return names[0]
        partial = [
            item for item in self.sessions if folded in item.display_name.casefold()
        ]
        candidates = prefix or names or partial
        if not candidates:
            raise ValueError(f"no session matches {reference!r}")
        choices = ", ".join(
            f"{item.id[:8]} ({compact_text(item.display_name, 35)})"
            for item in candidates[:8]
        )
        raise ValueError(f"ambiguous session reference {reference!r}: {choices}")

    def flags(self, session: Session) -> str:
        flags: list[str] = []
        if session.live:
            flags.append("LIVE")
        if session.pinned:
            flags.append("PIN")
        if session.size >= GIANT_BYTES:
            flags.append("GIANT")
        elif session.size >= HUGE_BYTES:
            flags.append("HUGE")
        age_days = (
            max(0, int((time.time() * 1000 - session.recency_ms) / 86_400_000))
            if session.recency_ms
            else 0
        )
        if age_days >= 180:
            flags.append("OLD")
        if not session.rollout_path.exists():
            flags.append("MISSING")
        if not session.indexed:
            flags.append("UNINDEXED")
        return ",".join(flags) or "-"

    def list_sessions(
        self,
        state: str = "all",
        search: str = "",
        sort: str = "updated",
        reverse: bool = False,
        limit: int = 30,
        preview_count: int = 2,
    ) -> list[Session]:
        matches = self.filter_sessions(
            state=state, search=search, sort=sort, reverse=reverse
        )
        shown = matches if limit == 0 else matches[:limit]
        self.last_listing = shown
        print(
            f"{'#':>3}  {'STATE':<9} {'LAST USED':<16} {'SIZE':>10}  {'ID':<8}  {'FLAGS':<16} NAME"
        )
        print("-" * 116)
        for index, session in enumerate(shown, 1):
            name = compact_text(session.display_name, 55)
            print(
                f"{index:>3}  {session.state:<9} {local_time(session.recency_ms):<16} "
                f"{human_size(session.size):>10}  {session.id[:8]:<8}  {self.flags(session):<16} {name}"
            )
            if preview_count:
                beginning, ending, note = self.quick_preview(session, preview_count)
                if beginning:
                    print(
                        "     start: "
                        + " | ".join(self._one_line_message(item) for item in beginning)
                    )
                if ending:
                    print(
                        "       end: "
                        + " | ".join(self._one_line_message(item) for item in ending)
                    )
                if note:
                    print(f"            [{note}]")
        total_size = sum(item.size for item in matches)
        print(
            f"\nShowing {len(shown)} of {len(matches)} sessions; matching transcript size: {human_size(total_size)}"
        )
        if len(shown) < len(matches):
            print("Use --limit 0 to show all, or narrow with --search/--state.")
        self.save_cache()
        return shown

    def stats(self) -> None:
        groups = {
            "live": [item for item in self.sessions if item.live],
            "active (not live)": [
                item for item in self.sessions if item.state == "ACTIVE"
            ],
            "archived": [item for item in self.sessions if item.state == "ARCHIVED"],
            "unindexed files": [
                item for item in self.sessions if item.state == "UNINDEXED"
            ],
        }
        total = sum(item.size for item in self.sessions)
        print(
            f"Sessions: {len(self.sessions)}   Total rollout size: {human_size(total)}"
        )
        for label, sessions in groups.items():
            print(
                f"  {label:<18} {len(sessions):>3} sessions  {human_size(sum(item.size for item in sessions)):>10}"
            )
        large = sorted(self.sessions, key=lambda item: item.size, reverse=True)
        top_three = sum(item.size for item in large[:3])
        percentage = (top_three / total * 100) if total else 0
        print(
            f"\nLargest three hold {human_size(top_three)} ({percentage:.1f}% of all rollout bytes)."
        )
        print("\nLargest sessions:")
        for session in large[:10]:
            print(
                f"  {human_size(session.size):>10}  {session.state:<9} {session.id[:8]}  "
                f"{compact_text(session.display_name, 70)}"
            )

    @staticmethod
    def _one_line_message(message: Message) -> str:
        marker = "U" if message.role == "user" else "A"
        return f"{marker}: {compact_text(message.text, 78)}"
