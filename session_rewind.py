"""Rewind at explicit Codex turn boundaries, never by editing live JSONL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from session_models import Message, Session, connect_readonly
from session_rpc import AppServer


@dataclass(frozen=True)
class Exchange:
    id: str
    status: str
    timestamp: str
    messages: tuple[Message, ...]

    @property
    def question(self):
        return next(
            (m.text for m in self.messages if m.role == "user"), "(no human input)"
        )


@dataclass(frozen=True)
class RewindPlan:
    session_id: str
    history_mode: str
    fingerprint: tuple
    exchanges: tuple[Exchange, ...]


def fingerprint(manager, session):
    paths = [session.rollout_path]
    result = []
    for path in paths:
        try:
            info = path.stat()
            result.append((str(path), info.st_ino, info.st_size, info.st_mtime_ns))
        except FileNotFoundError:
            result.append((str(path), None))
    if session.history_mode == "paginated" and manager.history_db.exists():
        # Per-thread logical state works across WAL checkpoints and unrelated
        # sessions writing to the same database.
        with connect_readonly(manager.history_db) as db:
            turns = db.execute(
                "SELECT turn_id, status, rollout_ordinal, rollout_end_ordinal FROM thread_turns WHERE thread_id=? ORDER BY rollout_ordinal",
                (session.id,),
            ).fetchall()
            items = db.execute(
                "SELECT count(*), max(rollout_ordinal), max(updated_at_ordinal) FROM thread_items WHERE thread_id=?",
                (session.id,),
            ).fetchone()
        result.extend(tuple(row) for row in turns)
        result.append(tuple(items))
    return tuple(result)


def stored_turns(server, session):
    turns = []
    cursor = None
    seen = set()
    while True:
        params = {
            "threadId": session.id,
            "limit": 100,
            "itemsView": "summary",
            "sortDirection": "asc",
        }
        if cursor:
            params["cursor"] = cursor
        page = server.request("thread/turns/list", params)
        turns.extend(page["data"])
        cursor = page.get("nextCursor")
        if not cursor:
            break
        if cursor in seen:
            raise RuntimeError(
                "Codex returned a repeated history cursor; rewind cancelled."
            )
        seen.add(cursor)
    ids = [turn["id"] for turn in turns]
    if len(ids) != len(set(ids)):
        raise RuntimeError("History contains duplicate turn IDs; rewind cancelled.")
    return turns


def require_idle(manager, session):
    if session.live or manager._is_live(session.id):
        raise RuntimeError(
            "Close this session in Codex before rewinding it; it is LIVE."
        )
    if session.archived:
        raise RuntimeError("Restore this archived session before rewinding it.")
    if not session.rollout_path.is_file():
        raise RuntimeError("The session transcript is missing; rewind is unavailable.")


def read_plan(manager, session: Session) -> RewindPlan:
    require_idle(manager, session)
    with AppServer(manager.home) as server:
        turns = stored_turns(server, session)
        before = fingerprint(manager, session)
        # Read only meaningful content; tool/image payloads never enter the picker.
        messages = manager.full_conversation(session).messages
        if before != fingerprint(manager, session):
            raise RuntimeError(
                "History changed while loading. Refresh and choose the point again."
            )
    groups = {}
    for message in messages:
        groups.setdefault(message.turn_id, []).append(message)
    exchanges = []
    for turn in turns:
        stamp = (
            datetime.fromtimestamp(turn["startedAt"], tz=timezone.utc).isoformat()
            if turn.get("startedAt")
            else ""
        )
        matched = groups.get(turn["id"], [])
        if not stamp and matched:
            stamp = matched[0].timestamp
        if not matched and session.history_mode == "legacy":
            raise RuntimeError(
                "This legacy session lacks reliable turn boundaries. Rewind is unavailable."
            )
        exchanges.append(Exchange(turn["id"], turn["status"], stamp, tuple(matched)))
    if not exchanges:
        raise RuntimeError("No stored exchanges are available to rewind.")
    return RewindPlan(session.id, session.history_mode, before, tuple(exchanges))


def apply_rewind(manager, session: Session, plan: RewindPlan, keep: int) -> int:
    """Keep the first `keep` exchanges. Caller must obtain explicit confirmation."""
    require_idle(manager, session)
    if plan.session_id != session.id or plan.history_mode != session.history_mode:
        raise RuntimeError("The selected session changed. Reopen the rewind picker.")
    if not 0 <= keep < len(plan.exchanges):
        raise ValueError("Choose a point that removes at least one exchange.")
    if fingerprint(manager, session) != plan.fingerprint:
        raise RuntimeError(
            "History changed since the preview. Reopen the rewind picker."
        )
    remove = len(plan.exchanges) - keep
    expected = [e.id for e in plan.exchanges]
    with AppServer(manager.home) as server:
        current = stored_turns(server, session)
        if [t["id"] for t in current] != expected or any(
            t["status"] == "inProgress" for t in current
        ):
            raise RuntimeError(
                "The stored exchanges changed or are still running. Reopen the picker."
            )
        require_idle(manager, session)
        if fingerprint(manager, session) != plan.fingerprint:
            raise RuntimeError("History changed during confirmation; rewind cancelled.")
        if session.history_mode != "paginated" and any(
            sum(m.role == "user" for m in e.messages) != 1 for e in plan.exchanges
        ):
            raise RuntimeError(
                "Legacy rewind cannot safely split exchanges with multiple human inputs."
            )
        server.request("thread/resume", {"threadId": session.id, "excludeTurns": True})
        if session.history_mode == "paginated":
            server.request(
                "thread/revert",
                {"threadId": session.id, "beforeTurnId": expected[keep]},
            )
        else:
            # Legacy rollback counts human inputs internally. Never guess when
            # one app-server turn contains several steered user messages.
            server.request(
                "thread/rollback", {"threadId": session.id, "numTurns": remove}
            )
        remaining = stored_turns(server, session)
        if [t["id"] for t in remaining] != expected[:keep]:
            raise RuntimeError(
                "Codex changed history but verification did not match. Refresh and inspect before resuming."
            )
    manager._cache.get("sessions", {}).pop(session.id, None)
    manager._cache_changed = True
    manager.save_cache()
    manager.reload()
    return remove
