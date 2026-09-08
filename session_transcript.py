from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from session_models import (
    MAX_JSON_LINE,
    ExtractResult,
    Message,
    Session,
    human_size,
    is_real_user_text,
    local_time,
)


def parse_jsonl_buffer(data: bytes) -> list[Message]:
    collector = ConversationCollector()
    for ordinal, raw in enumerate(data.splitlines()):
        if len(raw) > MAX_JSON_LINE or not is_message_candidate(raw):
            continue
        try:
            record = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        collector.add(record, ordinal)
    return collector.messages()


class ConversationCollector:
    def __init__(self):
        self.sources = {
            name: []
            for name in ("response_user", "response_final", "event_user", "event_agent")
        }
        self.turn_id = ""

    def add(self, record, ordinal):
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            return
        if (
            record.get("type") == "turn_context"
            or payload.get("type") == "task_started"
        ):
            self.turn_id = payload.get("turn_id") or self.turn_id
        if payload.get("type") == "thread_rolled_back":
            count = payload.get("num_turns", 0)
            if not isinstance(count, int) or count < 1:
                raise RuntimeError(
                    "Invalid legacy rollback marker; history cannot be reconstructed."
                )
            for users, finals in (
                ("response_user", "response_final"),
                ("event_user", "event_agent"),
            ):
                inputs = self.sources[users]
                cutoff = inputs[max(0, len(inputs) - count)].ordinal if inputs else -1
                self.sources[users] = [m for m in inputs if m.ordinal < cutoff]
                self.sources[finals] = [
                    m for m in self.sources[finals] if m.ordinal < cutoff
                ]
            self.turn_id = ""
            return
        classified = classify_record(record, ordinal)
        if classified:
            source, message = classified
            message.turn_id = self.turn_id
            self.sources[source].append(message)

    def messages(self):
        return combine_message_sources(*self.sources.values())


def is_message_candidate(raw: bytes) -> bool:
    return any(
        token in raw
        for token in (
            b'"role":"user"',
            b'"role": "user"',
            b'"phase":"final_answer"',
            b'"phase": "final_answer"',
            b'"type":"user_message"',
            b'"type": "user_message"',
            b'"type":"agent_message"',
            b'"type": "agent_message"',
            b'"task_started"',
            b'"turn_context"',
            b'"thread_rolled_back"',
        )
    )


def classify_record(record: dict[str, Any], ordinal: int) -> tuple[str, Message] | None:
    timestamp = str(record.get("timestamp", ""))
    payload = record.get("payload") or {}
    if record.get("type") == "response_item" and payload.get("type") == "message":
        role = payload.get("role")
        if role == "user":
            metadata = payload.get("internal_chat_message_metadata_passthrough") or {}
            kinds = metadata.get("content_item_kinds") or []
            text = "\n".join(
                part.get("text", "")
                for part in payload.get("content", [])
                if part.get("type") in {"input_text", "text"} and part.get("text")
            ).strip()
            if not is_real_user_text(text, kinds):
                return None
            return "response_user", Message("user", text, timestamp, ordinal)
        if role == "assistant" and payload.get("phase") == "final_answer":
            text = "\n".join(
                part.get("text", "")
                for part in payload.get("content", [])
                if part.get("type") in {"output_text", "text"} and part.get("text")
            ).strip()
            if text:
                return "response_final", Message("assistant", text, timestamp, ordinal)
    if record.get("type") == "event_msg":
        event_type = payload.get("type")
        if event_type == "user_message":
            text = str(payload.get("message") or payload.get("text") or "").strip()
            if is_real_user_text(text):
                return "event_user", Message("user", text, timestamp, ordinal)
        if event_type == "agent_message":
            if payload.get("phase") not in (None, "final_answer"):
                return None
            text = str(payload.get("message") or payload.get("text") or "").strip()
            if text:
                return "event_agent", Message("assistant", text, timestamp, ordinal)
    return None


def combine_message_sources(
    response_users: list[Message],
    response_finals: list[Message],
    event_users: list[Message],
    event_agents: list[Message],
) -> list[Message]:
    # Prefer response records within each turn, not across the whole file:
    # older turns can legitimately have event-only history.
    selected = []
    by_turn = {}
    for index, group in enumerate(
        (response_users, response_finals, event_users, event_agents)
    ):
        for message in group:
            by_turn.setdefault(message.turn_id, [[], [], [], []])[index].append(message)
    for groups in by_turn.values():
        selected.extend((groups[0] or groups[2]) + (groups[1] or groups[3]))
    selected.sort(key=lambda item: item.ordinal)
    return selected


def extract_legacy_conversation(
    path: Path, compute_hash: bool = False
) -> ExtractResult:
    collector = ConversationCollector()
    skipped = malformed = ordinal = 0
    digest = hashlib.sha256() if compute_hash else None
    with path.open("rb") as handle:
        while True:
            raw = handle.readline(MAX_JSON_LINE + 1)
            if not raw:
                break
            if digest:
                digest.update(raw)
            ordinal += 1
            if len(raw) > MAX_JSON_LINE and not raw.endswith(b"\n"):
                skipped += 1
                while raw and not raw.endswith(b"\n"):
                    raw = handle.readline(MAX_JSON_LINE + 1)
                    if digest:
                        digest.update(raw)
                continue
            if len(raw) > MAX_JSON_LINE or not is_message_candidate(raw):
                continue
            try:
                record = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                malformed += 1
                continue
            collector.add(record, ordinal)
    messages = collector.messages()
    return ExtractResult(
        messages, skipped, malformed, digest.hexdigest() if digest else None
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def print_message(message: Message, index: int) -> None:
    label = "USER" if message.role == "user" else "ASSISTANT FINAL"
    stamp = f" — {message.timestamp}" if message.timestamp else ""
    print(f"\n[{index}] {label}{stamp}")
    print(message.text.rstrip())


def render_compact_archive(session: Session, extracted: ExtractResult) -> str:
    lines = [
        f"# {session.display_name}",
        "",
        "> Compact, conversation-only archive. This is readable history, not a resumable Codex rollout.",
        "",
        f"- Session ID: `{session.id}`",
        f"- State at export: `{session.state}`",
        f"- Created: {local_time(session.created_ms)}",
        f"- Last used: {local_time(session.recency_ms)}",
        f"- Working directory: `{session.cwd or '(unknown)'}`",
        f"- Original path: `{session.rollout_path}`",
        f"- Original size: {human_size(session.size)} ({session.size:,} bytes)",
        f"- Original SHA-256: `{extracted.sha256 or 'not computed'}`",
        f"- Preserved messages: {len(extracted.messages)}",
        f"- Oversized JSONL records skipped: {extracted.skipped_oversize_lines}",
        "",
        "## Conversation",
        "",
    ]
    for index, message in enumerate(extracted.messages, 1):
        role = "User" if message.role == "user" else "Assistant final answer"
        stamp = f" — {message.timestamp}" if message.timestamp else ""
        lines.extend((f"### {index}. {role}{stamp}", "", message.text.rstrip(), ""))
    return "\n".join(lines).rstrip() + "\n"


def atomic_write(path: Path, content: str, *, overwrite: bool = True) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temp = Path(handle.name)
    try:
        if overwrite:
            if path.exists():
                temp.chmod(path.stat().st_mode & 0o777)
            temp.replace(path)
        else:
            # Atomic create-if-absent, including protection against symlink targets.
            os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)
