from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from session_models import (
    EDGE_BYTES,
    MAX_JSON_LINE,
    ExtractResult,
    Message,
    Session,
    connect_readonly,
    human_size,
    is_real_user_text,
    local_time,
)
from session_transcript import (
    extract_legacy_conversation,
    parse_jsonl_buffer,
    print_message,
    sha256_file,
)


class History:
    def quick_preview(
        self, session: Session, count: int = 2
    ) -> tuple[list[Message], list[Message], str]:
        key = f"{session.size}:{session.mtime_ns}:{session.history_mode}:{count}"
        if session.history_mode == "paginated":
            from session_rewind import fingerprint

            key += repr(fingerprint(self, session))
        cached = self._cache.get("sessions", {}).get(session.id)
        if cached and cached.get("key") == key:
            beginning = [Message(**item) for item in cached.get("beginning", [])]
            ending = [Message(**item) for item in cached.get("ending", [])]
            return beginning, ending, cached.get("note", "")

        note = ""
        if session.history_mode == "paginated":
            messages = self._paginated_messages(session.id)
            beginning, ending = messages[:count], messages[-count:]
        else:
            beginning, ending, complete = self._edge_messages(
                session.rollout_path, count
            )
            if not complete:
                note = "approximate file-edge preview; may include rewound legacy content. Full conversation reconstructs history."

        self._cache.setdefault("sessions", {})[session.id] = {
            "key": key,
            "beginning": [asdict(item) for item in beginning],
            "ending": [asdict(item) for item in ending],
            "note": note,
        }
        self._cache_changed = True
        return beginning, ending, note

    def _edge_messages(
        self, path: Path, count: int
    ) -> tuple[list[Message], list[Message], bool]:
        if not path.exists():
            return [], [], True
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size <= EDGE_BYTES * 2:
                data = handle.read()
                messages = parse_jsonl_buffer(data)
                return messages[:count], messages[-count:], True
            prefix = handle.read(EDGE_BYTES)
            handle.seek(max(0, size - EDGE_BYTES))
            suffix = handle.read(EDGE_BYTES)
        prefix = prefix[: prefix.rfind(b"\n") + 1] if b"\n" in prefix else b""
        suffix = suffix[suffix.find(b"\n") + 1 :] if b"\n" in suffix else b""
        if b'"thread_rolled_back"' in suffix:
            # A suffix-only parse cannot apply a rollback to unseen earlier
            # turns. Do not present its endpoints as the retained conversation.
            return [], [], False
        first = parse_jsonl_buffer(prefix)[:count]
        last = parse_jsonl_buffer(suffix)[-count:]
        return first, last, False

    def _paginated_messages(self, session_id: str) -> list[Message]:
        if not self.history_db.exists():
            raise RuntimeError(
                f"Paginated history database is missing: {self.history_db}"
            )
        from session_rewind import stored_turns
        from session_rpc import AppServer

        # A reverted paginated rollout may inherit only a prefix of an older
        # projection. The raw SQLite tables can retain removed turns. Ask Codex
        # which turns are effective before selecting meaningful content.
        session = next(item for item in self.sessions if item.id == session_id)
        with AppServer(self.home) as server:
            active_ids = {turn["id"] for turn in stored_turns(server, session)}
        query = """
            WITH conversation AS (
                SELECT rollout_ordinal AS ordinal, created_at_ms, item_json, turn_id
                FROM thread_items
                WHERE thread_id = ? AND item_type = 'userMessage'
                UNION ALL
                SELECT ti.rollout_ordinal AS ordinal, ti.created_at_ms, ti.item_json, ti.turn_id
                FROM thread_turns tt
                JOIN thread_items ti
                  ON ti.thread_id = tt.thread_id AND ti.turn_id = tt.turn_id AND ti.item_id = tt.final_agent_item_id
                WHERE tt.thread_id = ? AND tt.final_agent_item_id IS NOT NULL
            )
            SELECT ordinal, created_at_ms, item_json, turn_id FROM conversation ORDER BY ordinal
        """
        result: list[Message] = []
        try:
            with connect_readonly(self.history_db) as db:
                for row in db.execute(query, (session_id, session_id)):
                    if row["turn_id"] not in active_ids:
                        continue
                    try:
                        item = json.loads(row["item_json"])
                    except json.JSONDecodeError as error:
                        raise RuntimeError(
                            "A stored conversation message is corrupt; reading stopped."
                        ) from error
                    if not isinstance(item, dict):
                        raise RuntimeError(
                            "A stored conversation message is not an object; reading stopped."
                        )
                    if item.get("type") == "userMessage":
                        text = "\n".join(
                            part.get("text", "")
                            for part in item.get("content", [])
                            if part.get("type") == "text" and part.get("text")
                        )
                        role = "user"
                        if not is_real_user_text(text):
                            continue
                    elif item.get("type") == "agentMessage" and item.get("phase") in (
                        None,
                        "final_answer",
                    ):
                        text = item.get("text", "")
                        role = "assistant"
                    else:
                        continue
                    if text:
                        timestamp = (
                            datetime.fromtimestamp(
                                int(row["created_at_ms"] or 0) / 1000, tz=timezone.utc
                            ).isoformat()
                            if row["created_at_ms"]
                            else ""
                        )
                        result.append(
                            Message(
                                role,
                                text,
                                timestamp,
                                int(row["ordinal"]),
                                row["turn_id"],
                            )
                        )
        except sqlite3.Error as error:
            raise RuntimeError(f"Cannot read paginated history: {error}") from error
        return result

    def full_conversation(
        self, session: Session, compute_hash: bool = False
    ) -> ExtractResult:
        if session.history_mode == "paginated":
            messages = self._paginated_messages(session.id)
            digest = (
                sha256_file(session.rollout_path)
                if compute_hash and session.rollout_path.exists()
                else None
            )
            return ExtractResult(messages=messages, sha256=digest)
        return extract_legacy_conversation(
            session.rollout_path, compute_hash=compute_hash
        )

    def show(self, session: Session, count: int = 5, full: bool = False) -> None:
        print(f"Name:       {session.display_name}")
        print(f"ID:         {session.id}")
        print(f"State:      {session.state} ({self.flags(session)})")
        print(f"Created:    {local_time(session.created_ms)}")
        print(f"Last used:  {local_time(session.recency_ms)}")
        print(f"Size:       {human_size(session.size)} ({session.size:,} bytes)")
        print(f"Source:     {session.source}; history={session.history_mode}")
        print(f"Directory:  {session.cwd or '(unknown)'}")
        print(f"Transcript: {session.rollout_path}")
        if session.name:
            print(f"Saved name: {session.name}")
        if session.title and session.title != session.name:
            print(f"Auto title: {session.title}")

        if full:
            print(
                "\nReading the full conversation; very large legacy files can take a while...",
                file=sys.stderr,
            )
            extracted = self.full_conversation(session)
            messages = extracted.messages
            print(f"\nConversation ({len(messages)} user/final-answer messages):")
            for index, message in enumerate(messages, 1):
                print_message(message, index)
            self._print_extract_warnings(extracted)
            return

        beginning, ending, note = self.quick_preview(session, count)
        print("\nBeginning:")
        for index, message in enumerate(beginning, 1):
            print_message(message, index)
        print("\nEnd:")
        for index, message in enumerate(ending, max(1, len(beginning) + 1)):
            print_message(message, index)
        if note:
            print(f"\nNote: {note}")

    @staticmethod
    def _print_extract_warnings(extracted: ExtractResult) -> None:
        if extracted.skipped_oversize_lines:
            print(
                f"Warning: skipped {extracted.skipped_oversize_lines} JSONL lines larger than "
                f"{human_size(MAX_JSON_LINE)}; these are normally tool/image payloads.",
                file=sys.stderr,
            )
        if extracted.malformed_candidate_lines:
            print(
                f"Warning: {extracted.malformed_candidate_lines} candidate message lines were malformed.",
                file=sys.stderr,
            )
