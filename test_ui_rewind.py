import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, DataTable, Input

from codex_session_tui import SessionManagerApp
from session_memory import MemoryManager
from session_models import Message, human_size, local_time
from session_rewind import Exchange, RewindPlan
from session_store import SessionManager
from test_codex_session_tui import FakeManager
from test_session_rewind_integration import create_fixture
from ui_dialogs import ConfirmDialog
from ui_rewind import RewindScreen


class RewindUiTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(
        os.environ.get("CODEX_MAN_INTEGRATION") == "1", "requires installed Codex"
    )
    async def test_real_codex_rewind_through_terminal_ui(self):
        with tempfile.TemporaryDirectory(prefix="codex-man-ui-") as directory:
            root = Path(directory)
            sid = create_fixture(root, "paginated")
            manager = SessionManager(root)
            app = SessionManagerApp(
                manager,
                MemoryManager(root),
                {"human_size": human_size, "local_time": local_time},
            )
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.press("w")
                await pilot.pause(0.4)
                screen = app.screen
                self.assertIsInstance(screen, RewindScreen)
                self.assertIsNotNone(screen.plan)
                screen.query_one(DataTable).move_cursor(row=0)
                await pilot.pause()
                screen.action_keep()
                await pilot.pause()
                await pilot.click("#accept")
                await pilot.pause(0.5)
                self.assertNotIsInstance(app.screen, RewindScreen)
                self.assertEqual(
                    [
                        m.text
                        for m in manager.full_conversation(
                            manager.resolve(sid)
                        ).messages
                    ],
                    ["Question 0", "Answer 0"],
                )

    async def test_choose_boundary_cancel_then_confirm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = FakeManager(root)
            session = manager.sessions[0]
            exchanges = tuple(
                Exchange(
                    f"turn-{n}",
                    "completed",
                    "",
                    (
                        Message("user", f"Question {n}"),
                        Message("assistant", f"Answer {n}"),
                    ),
                )
                for n in range(3)
            )
            plan = RewindPlan(session.id, "legacy", (), exchanges)
            app = SessionManagerApp(
                manager,
                MemoryManager(root),
                {"human_size": human_size, "local_time": local_time},
            )
            with (
                patch("ui_rewind.read_plan", return_value=plan),
                patch("ui_rewind.apply_rewind", return_value=1) as apply,
            ):
                async with app.run_test(size=(82, 24)) as pilot:
                    await pilot.press("w")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, RewindScreen)
                    screen = app.screen
                    table = screen.query_one(DataTable)
                    self.assertEqual(table.row_count, 3)
                    table.move_cursor(row=1)
                    await pilot.pause()
                    self.assertEqual(screen.selected, 1)
                    screen.action_keep()
                    await pilot.pause()
                    self.assertIsInstance(app.screen, ConfirmDialog)
                    self.assertIn("Keep 2 exchanges; remove 1", app.screen.body)
                    accept = app.screen.query_one("#accept", Button)
                    self.assertLessEqual(accept.region.bottom, 24)
                    await pilot.press("escape")
                    apply.assert_not_called()
                    screen.query_one(Input).value = "Question 2"
                    await pilot.pause()
                    self.assertEqual(table.row_count, 1)
                    self.assertTrue(screen.query_one("#rewind-keep", Button).disabled)
                    screen.action_before()
                    await pilot.pause()
                    self.assertIn("First removed input: Question 2", app.screen.body)
                    await pilot.click("#accept")
                    await pilot.pause()
                    apply.assert_called_once_with(manager, session, plan, 2)
                    self.assertIs(app.screen, app.screen_stack[0])
