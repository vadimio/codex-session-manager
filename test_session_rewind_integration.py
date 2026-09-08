"""Opt-in installed-Codex checks using synthetic data under a temporary home."""

import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from session_rewind import apply_rewind, read_plan
from session_rpc import AppServer
from session_store import SessionManager


def create_fixture(root, mode):
    sid = str(uuid.uuid4())
    path = root / "sessions" / f"rollout-2026-09-07T00-00-00-{sid}.jsonl"
    path.parent.mkdir(exist_ok=True)
    records = []

    def record(kind, payload):
        records.append(
            {"timestamp": "2026-09-07T00:00:00Z", "type": kind, "payload": payload}
        )

    record(
        "session_meta",
        {
            "id": sid,
            "timestamp": "2026-09-07T00:00:00Z",
            "cwd": str(root),
            "originator": "codex_cli_rs",
            "cli_version": "0.153.4",
            "source": "cli",
            "model_provider": "openai",
        },
    )
    boundaries = []
    for n in range(3):
        tid = f"turn-{n}"
        start = len(records)
        record(
            "event_msg",
            {"type": "task_started", "turn_id": tid, "model_context_window": 10000},
        )
        record(
            "event_msg",
            {
                "type": "user_message",
                "message": f"Question {n}",
                "images": [],
                "local_images": [],
            },
        )
        record(
            "response_item",
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": f"Question {n}"}],
            },
        )
        record(
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": f"Answer {n}"}],
            },
        )
        record(
            "event_msg",
            {
                "type": "agent_message",
                "message": f"Answer {n}",
                "phase": "final_answer",
            },
        )
        record(
            "event_msg",
            {
                "type": "task_complete",
                "turn_id": tid,
                "last_agent_message": f"Answer {n}",
            },
        )
        boundaries.append((start, len(records) - 1))
    lines = [(json.dumps(r) + "\n").encode() for r in records]
    path.write_bytes(b"".join(lines))
    with AppServer(root) as server:
        server.request("thread/resume", {"threadId": sid, "excludeTurns": True})
    if mode == "paginated":
        records[0]["payload"]["history_mode"] = "paginated"
        for ordinal, item in enumerate(records):
            item["ordinal"] = ordinal
        lines = [(json.dumps(r) + "\n").encode() for r in records]
        path.write_bytes(b"".join(lines))
        with sqlite3.connect(root / "state_5.sqlite") as db:
            db.execute("UPDATE threads SET history_mode='paginated' WHERE id=?", (sid,))
        with AppServer(root) as server:
            server.request("thread/turns/list", {"threadId": sid})
        with sqlite3.connect(root / "thread_history_1.sqlite") as db:
            for n, (start, end) in enumerate(boundaries):
                tid = f"turn-{n}"
                db.execute(
                    "INSERT OR REPLACE INTO thread_turns (thread_id,turn_id,rollout_ordinal,status,first_user_item_id,final_agent_item_id,rollout_byte_offset,rollout_end_ordinal,rollout_end_byte_offset) VALUES (?,?,?,'completed',?,?,?,?,?)",
                    (
                        sid,
                        tid,
                        start,
                        f"u{n}",
                        f"a{n}",
                        sum(map(len, lines[:start])),
                        end,
                        sum(map(len, lines[: end + 1])),
                    ),
                )
                for iid, ordinal, item in [
                    (
                        f"u{n}",
                        start + 1,
                        {
                            "type": "userMessage",
                            "id": f"u{n}",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Question {n}",
                                    "text_elements": [],
                                }
                            ],
                        },
                    ),
                    (
                        f"a{n}",
                        start + 4,
                        {
                            "type": "agentMessage",
                            "id": f"a{n}",
                            "text": f"Answer {n}",
                            "phase": "final_answer",
                        },
                    ),
                ]:
                    db.execute(
                        "INSERT OR REPLACE INTO thread_items (thread_id,turn_id,item_id,rollout_ordinal,created_at_ms,item_json,item_type) VALUES (?,?,?,?,?,?,?)",
                        (
                            sid,
                            tid,
                            iid,
                            ordinal,
                            1788739200000,
                            json.dumps(item),
                            item["type"],
                        ),
                    )
    return sid


@unittest.skipUnless(
    os.environ.get("CODEX_MAN_INTEGRATION") == "1", "opt-in: requires installed Codex"
)
class InstalledCodexRewindTests(unittest.TestCase):
    def test_legacy_and_paginated_rewind_persist_after_restart(self):
        for mode in ("legacy", "paginated"):
            with (
                self.subTest(mode=mode),
                tempfile.TemporaryDirectory(prefix="codex-man-test-") as directory,
            ):
                root = Path(directory)
                sid = create_fixture(root, mode)
                manager = SessionManager(root)
                session = manager.resolve(sid)
                plan = read_plan(manager, session)
                self.assertEqual(
                    [e.question for e in plan.exchanges],
                    [f"Question {n}" for n in range(3)],
                )
                self.assertEqual(apply_rewind(manager, session, plan, 1), 2)
                with AppServer(root) as server:
                    page = server.request(
                        "thread/turns/list", {"threadId": sid, "itemsView": "summary"}
                    )
                    self.assertEqual([t["id"] for t in page["data"]], ["turn-0"])
                manager.reload()
                self.assertEqual(
                    [
                        m.text
                        for m in manager.full_conversation(
                            manager.resolve(sid)
                        ).messages
                    ],
                    ["Question 0", "Answer 0"],
                )
                session = manager.resolve(sid)
                plan = read_plan(manager, session)
                apply_rewind(manager, session, plan, 0)
                session = manager.resolve(sid)
                self.assertEqual(manager.full_conversation(session).messages, [])
                self.assertEqual(manager.quick_preview(session)[0], [])
