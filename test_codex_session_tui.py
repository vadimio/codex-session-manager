#!/usr/bin/env python3

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from textual.containers import VerticalScroll
from textual.widgets import Button, DataTable, Input, Markdown, Select, Static

BIN = Path(__file__).parent
sys.path.insert(0, str(BIN))

BACKEND_SPEC = importlib.util.spec_from_file_location(
    "codex_session_manager", BIN / "codex_session_manager.py"
)
assert BACKEND_SPEC and BACKEND_SPEC.loader
backend = importlib.util.module_from_spec(BACKEND_SPEC)
sys.modules[BACKEND_SPEC.name] = backend
BACKEND_SPEC.loader.exec_module(backend)

from codex_session_tui import (  # noqa: E402
    ConversationScreen,
    DocumentScreen,
    MemoryScreen,
    SessionManagerApp,
)


class FakeManager:
    def __init__(self, root: Path):
        first = root / "first.jsonl"
        second = root / "second.jsonl"
        first.write_bytes(b"x" * 2048)
        second.write_bytes(b"x" * 8192)
        self.sessions = [
            backend.Session(
                "00000000-0000-0000-0000-000000000001",
                first,
                1000,
                3000,
                3000,
                False,
                False,
                "Active design session",
                "",
                "",
                str(Path.home() / "projects" / "website"),
                "cli",
                "legacy",
            ),
            backend.Session(
                "00000000-0000-0000-0000-000000000002",
                second,
                2000,
                2000,
                2000,
                True,
                False,
                "Archived huge payload",
                "",
                "",
                "/tmp/archive",
                "cli",
                "legacy",
            ),
        ]

    def flags(self, session):
        return "-"

    def filter_sessions(self, state="all", search="", sort="updated", reverse=False):
        result = self.sessions
        if state == "active":
            result = [item for item in result if not item.archived]
        elif state == "archived":
            result = [item for item in result if item.archived]
        elif state == "live":
            result = [item for item in result if item.live]
        if search:
            result = [
                item
                for item in result
                if search.casefold() in item.display_name.casefold()
            ]
        keys = {
            "updated": lambda item: item.recency_ms,
            "created": lambda item: item.created_ms,
            "size": lambda item: item.size,
            "name": lambda item: item.display_name.casefold(),
        }
        return sorted(result, key=keys[sort], reverse=not reverse)

    def quick_preview(self, session, count):
        messages = [
            backend.Message("user", f"Question about {session.display_name}"),
            backend.Message("assistant", "Final decision"),
        ]
        return messages[:count], messages[-count:], ""

    def full_conversation(self, session):
        return backend.ExtractResult(
            [
                backend.Message("user", "Human input", "2026-07-12T17:44:17.291Z"),
                backend.Message(
                    "assistant", "Final answer only", "2026-07-12T17:45:00Z"
                ),
            ]
            + [
                backend.Message(
                    "assistant",
                    f"Additional final answer {index}",
                    "2026-07-12T18:00:00Z",
                )
                for index in range(40)
            ]
        )

    def save_cache(self):
        pass

    def reload(self):
        pass


class TuiTests(unittest.IsolatedAsyncioTestCase):
    async def test_responsive_table_search_and_memory_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory_root = root / "memories"
            memory_root.mkdir()
            (memory_root / "memory_summary.md").write_text(
                "# Summary\n\n"
                + "\n\n".join(f"Memory line {index}" for index in range(200))
            )
            (memory_root / "MEMORY.md").write_text("# Durable\n\nRegistry.\n")
            evidence = memory_root / "rollout_summaries"
            evidence.mkdir()
            (evidence / "example.md").write_text("# Evidence\n\nSource chat.\n")
            manager = FakeManager(root)
            memories = backend.MemoryManager(root)
            app = SessionManagerApp(
                manager,
                memories,
                {"human_size": backend.human_size, "local_time": backend.local_time},
            )
            async with app.run_test(size=(82, 24), notifications=True) as pilot:
                await pilot.pause(0.2)
                table = app.query_one("#session-table", DataTable)
                self.assertEqual(table.row_count, 2)
                self.assertEqual(str(table.get_row_at(0)[5]), "…/projects/website")
                self.assertEqual(
                    app.query_one("#memory-button", Button).variant, "default"
                )
                self.assertEqual(
                    app.query_one("#transcript", Button).variant, "default"
                )
                self.assertTrue(app.has_class("narrow"))
                self.assertTrue(app.has_class("short"))

                app.query_one("#search", Input).value = "archived"
                await pilot.pause()
                self.assertEqual(table.row_count, 1)

                table.focus()
                app.action_memory()
                await pilot.pause()
                self.assertIsInstance(app.screen, MemoryScreen)
                memory_table = app.screen.query_one("#memory-table", DataTable)
                self.assertEqual(memory_table.row_count, 2)
                self.assertIn(
                    "ON (default)",
                    str(app.screen.query_one("#toggle-use", Button).label),
                )
                self.assertIn(
                    "set OFF", str(app.screen.query_one("#toggle-use", Button).tooltip)
                )
                self.assertIn(
                    "set ON",
                    str(app.screen.query_one("#toggle-external", Button).tooltip),
                )
                app.screen._toggle("use", "use_memories")
                await pilot.pause()
                self.assertIn(
                    "OFF", str(app.screen.query_one("#toggle-use", Button).label)
                )

                app.screen.query_one("#memory-kind", Select).value = "evidence"
                await pilot.pause()
                self.assertEqual(memory_table.row_count, 1)
                app.screen.query_one("#memory-kind", Select).value = "overview"
                await pilot.pause()
                self.assertEqual(memory_table.row_count, 2)

                app.screen.action_explain()
                await pilot.pause()
                self.assertIsInstance(app.screen, DocumentScreen)
                self.assertIn("one local memory store", app.screen.document)
                await pilot.press("escape")

                memory_table.focus()
                app.screen.action_open()
                await pilot.pause(0.2)
                self.assertIsInstance(app.screen, DocumentScreen)
                document = app.screen.query_one("#document", Markdown)
                await pilot.press("end")
                await pilot.pause()
                self.assertGreater(document.scroll_y, 0)
                await pilot.press("home")
                await pilot.pause()
                self.assertEqual(document.scroll_y, 0)

                await pilot.press("escape")
                await pilot.press("escape")

                table.focus()
                app.action_transcript()
                await pilot.pause(0.2)
                self.assertIsInstance(app.screen, ConversationScreen)
                self.assertEqual(app.screen.messages[0].text, "Human input")
                self.assertEqual(app.screen.messages[1].text, "Final answer only")
                user_message = app.screen.query_one(".conversation-user", Static)
                self.assertIn("Human input", str(user_message.render()))
                conversation = app.screen.query_one("#conversation", VerticalScroll)
                await pilot.press("end")
                await pilot.pause()
                self.assertGreater(conversation.scroll_y, 0)
                await pilot.press("home")
                await pilot.pause()
                self.assertEqual(conversation.scroll_y, 0)

                await pilot.press("escape")
                app.exit()


if __name__ == "__main__":
    unittest.main()
