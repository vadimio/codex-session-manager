#!/usr/bin/env python3

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("codex_session_manager.py")
SPEC = importlib.util.spec_from_file_location("codex_session_manager", MODULE_PATH)
assert SPEC and SPEC.loader
manager = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = manager
SPEC.loader.exec_module(manager)


def response_message(
    role, text, phase=None, kinds=None, timestamp="2026-01-01T00:00:00Z"
):
    payload = {
        "type": "message",
        "role": role,
        "content": [
            {"type": "input_text" if role == "user" else "output_text", "text": text}
        ],
    }
    if phase:
        payload["phase"] = phase
    if kinds is not None:
        payload["internal_chat_message_metadata_passthrough"] = {
            "content_item_kinds": kinds
        }
    return {"timestamp": timestamp, "type": "response_item", "payload": payload}


class ParserTests(unittest.TestCase):
    def test_keeps_only_real_users_and_final_answers(self):
        records = [
            response_message(
                "user", "<environment_context>noise</environment_context>"
            ),
            response_message("user", "# AGENTS.md instructions for /tmp\nnoise"),
            response_message(
                "user", "<recommended_plugins>noise</recommended_plugins>"
            ),
            response_message("user", "<turn_aborted>noise</turn_aborted>"),
            response_message("user", "My actual question", kinds=["user.text"]),
            response_message("assistant", "working update", phase="commentary"),
            response_message("assistant", "The final decision", phase="final_answer"),
        ]
        data = b"\n".join(
            json.dumps(record, separators=(",", ":")).encode() for record in records
        )
        messages = manager.parse_jsonl_buffer(data)
        self.assertEqual(
            [(message.role, message.text) for message in messages],
            [("user", "My actual question"), ("assistant", "The final decision")],
        )

    def test_legacy_event_fallback(self):
        records = [
            {
                "timestamp": "1",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Q"},
            },
            {
                "timestamp": "2",
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "A"},
            },
        ]
        data = b"\n".join(
            json.dumps(record, separators=(",", ":")).encode() for record in records
        )
        messages = manager.parse_jsonl_buffer(data)
        self.assertEqual(
            [(item.role, item.text) for item in messages],
            [("user", "Q"), ("assistant", "A")],
        )

    def test_oversize_non_message_line_is_bounded_and_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            records = [
                json.dumps(
                    response_message("user", "Q", kinds=["user.text"]),
                    separators=(",", ":"),
                ),
                '{"payload":"' + ("x" * (manager.MAX_JSON_LINE + 10)) + '"}',
                json.dumps(
                    response_message("assistant", "A", phase="final_answer"),
                    separators=(",", ":"),
                ),
            ]
            path.write_text("\n".join(records) + "\n", encoding="utf-8")
            extracted = manager.extract_legacy_conversation(path)
            self.assertEqual(
                [(item.role, item.text) for item in extracted.messages],
                [("user", "Q"), ("assistant", "A")],
            )
            self.assertEqual(extracted.skipped_oversize_lines, 1)


class ConfigTests(unittest.TestCase):
    def test_adds_and_updates_memory_section_without_reformatting_others(self):
        original = 'model = "x"\n\n[features]\nmemories = true\n'
        added = manager.update_toml_section_value(
            original, "memories", "use_memories", "false"
        )
        self.assertIn("[features]\nmemories = true", added)
        self.assertIn("[memories]\nuse_memories = false", added)
        updated = manager.update_toml_section_value(
            added, "memories", "use_memories", "true"
        )
        self.assertEqual(updated.count("use_memories"), 1)
        self.assertIn("use_memories = true", updated)


class ArchiveTests(unittest.TestCase):
    def test_markdown_contains_provenance_and_only_selected_messages(self):
        session = manager.Session(
            id="00000000-0000-0000-0000-000000000001",
            rollout_path=Path("/tmp/source.jsonl"),
            created_ms=1,
            updated_ms=2,
            recency_ms=2,
            archived=False,
            pinned=False,
            name="Test",
            title="",
            preview="",
            cwd="/tmp",
            source="cli",
            history_mode="legacy",
        )
        extracted = manager.ExtractResult(
            [
                manager.Message("user", "Question"),
                manager.Message("assistant", "Decision"),
            ],
            sha256="abc",
        )
        output = manager.render_compact_archive(session, extracted)
        self.assertIn("Original SHA-256: `abc`", output)
        self.assertIn("### 1. User", output)
        self.assertIn("### 2. Assistant final answer", output)


class ResumeTests(unittest.TestCase):
    def test_resume_modes_are_explicit_and_use_saved_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            session = manager.Session(
                id="00000000-0000-0000-0000-000000000001",
                rollout_path=Path(directory) / "source.jsonl",
                created_ms=1,
                updated_ms=2,
                recency_ms=2,
                archived=False,
                pinned=False,
                name="Test",
                title="",
                preview="",
                cwd=directory,
                source="cli",
                history_mode="legacy",
            )
            safe = manager.SessionManager.resume_command(session)
            self.assertIn("workspace-write", safe)
            self.assertIn("on-request", safe)
            self.assertIn("--cd", safe)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", safe)

            unrestricted = manager.SessionManager.resume_command(
                session, unrestricted=True
            )
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", unrestricted)
            self.assertNotIn("workspace-write", unrestricted)
            self.assertNotIn("on-request", unrestricted)

    def test_delegated_commands_receive_selected_codex_home(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory).resolve()
            session_manager = manager.SessionManager(codex_home)
            session = manager.Session(
                id="00000000-0000-0000-0000-000000000001",
                rollout_path=codex_home / "source.jsonl",
                created_ms=1,
                updated_ms=2,
                recency_ms=2,
                archived=False,
                pinned=False,
                name="Test",
                title="",
                preview="",
                cwd=directory,
                source="cli",
                history_mode="legacy",
            )
            completed = manager.subprocess.CompletedProcess([], 0)
            with patch.object(manager.subprocess, "run", return_value=completed) as run:
                session_manager.resume(session)
                self.assertEqual(
                    run.call_args.kwargs["env"]["CODEX_HOME"], str(codex_home)
                )

                session_manager.run_codex_action(
                    "archive", session, yes=True, quiet=True
                )
                self.assertEqual(
                    run.call_args.kwargs["env"]["CODEX_HOME"], str(codex_home)
                )


if __name__ == "__main__":
    unittest.main()
