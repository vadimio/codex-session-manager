import fcntl
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from session_memory import MemoryManager
from session_models import Message, Session
from session_rewind import Exchange, RewindPlan, apply_rewind, fingerprint
from session_store import SessionManager
from session_transcript import parse_jsonl_buffer


def sample(root):
    path = root / "sample.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Question"}],
                },
            }
        )
        + "\n"
    )
    return Session(
        "00000000-0000-0000-0000-000000000001",
        path,
        1,
        2,
        2,
        False,
        False,
        "Test",
        "",
        "",
        str(root),
        "cli",
        "legacy",
    )


class SafetyTests(unittest.TestCase):
    def test_export_cannot_overwrite_source_or_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = sample(root)
            manager = SessionManager(root)
            before = session.rollout_path.read_bytes()
            with self.assertRaises(FileExistsError):
                manager.compact_archive(
                    session, session.rollout_path, False, True, True
                )
            self.assertEqual(session.rollout_path.read_bytes(), before)

    def test_writer_lock_is_rechecked_after_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = sample(root)
            manager = SessionManager(root)
            locks = root / "thread-writer-locks"
            locks.mkdir()
            with (locks / f"{session.id}.lock").open("w") as writer:
                fcntl.flock(writer, fcntl.LOCK_EX)
                with self.assertRaisesRegex(RuntimeError, "LIVE"):
                    manager.run_codex_action("delete", session, yes=True)
                with self.assertRaisesRegex(RuntimeError, "LIVE"):
                    manager.compact_archive(session, None, False, True)

    def test_changed_rewind_plan_never_calls_codex(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = sample(root)
            manager = SessionManager(root)
            exchange = Exchange(
                "turn-0", "completed", "", (Message("user", "Question"),)
            )
            plan = RewindPlan(
                session.id, "legacy", fingerprint(manager, session), (exchange,)
            )
            with session.rollout_path.open("a") as handle:
                handle.write("changed\n")
            with patch("session_rewind.AppServer") as server:
                with self.assertRaisesRegex(RuntimeError, "changed since"):
                    apply_rewind(manager, session, plan, 0)
                server.assert_not_called()

    def test_corrupt_config_is_not_shown_as_defaults_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.toml"
            config.write_text("[memories\ninvalid")
            memories = MemoryManager(root)
            with self.assertRaisesRegex(RuntimeError, "Cannot read"):
                memories.config_values()
            with self.assertRaises(ValueError):
                memories.set_config("use", False)
            self.assertEqual(config.read_text(), "[memories\ninvalid")

    def test_missing_paginated_database_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = sample(root)
            session.history_mode = "paginated"
            with self.assertRaisesRegex(RuntimeError, "database is missing"):
                SessionManager(root).full_conversation(session)

    def test_legacy_rollback_and_repeated_inputs(self):
        records = []
        for n in range(3):
            records.extend(
                [
                    {
                        "type": "event_msg",
                        "payload": {"type": "task_started", "turn_id": f"turn-{n}"},
                    },
                    {
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "repeat"},
                    },
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "agent_message",
                            "message": f"Answer {n}",
                            "phase": "final_answer",
                        },
                    },
                ]
            )
        records.append(
            {
                "type": "event_msg",
                "payload": {"type": "thread_rolled_back", "num_turns": 1},
            }
        )
        records.append(
            {
                "type": "event_msg",
                "payload": {
                    "type": "agent_message",
                    "message": "working…",
                    "phase": "commentary",
                },
            }
        )
        messages = parse_jsonl_buffer(
            b"\n".join(json.dumps(r).encode() for r in records)
        )
        self.assertEqual(
            [m.text for m in messages], ["repeat", "Answer 0", "repeat", "Answer 1"]
        )
        self.assertEqual(
            [m.turn_id for m in messages], ["turn-0", "turn-0", "turn-1", "turn-1"]
        )
