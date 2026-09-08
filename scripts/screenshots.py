"""Capture the real TUI with synthetic data; never open a user's Codex home.

Run from the repository: uv run --locked python scripts/screenshots.py
Only the SVG screenshots under docs/screenshots are retained.
"""

import asyncio
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from textual.widgets import DataTable, Markdown, Select

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from codex_session_tui import SessionManagerApp  # noqa: E402
from session_memory import MemoryManager  # noqa: E402
from session_models import (  # noqa: E402
    ExtractResult,
    Message,
    Session,
    human_size,
    local_time,
)
from session_rewind import Exchange, RewindPlan  # noqa: E402
from session_store import SessionManager  # noqa: E402
from ui_documents import ConversationScreen  # noqa: E402
from ui_memory import MemoryScreen  # noqa: E402
from ui_rewind import RewindScreen  # noqa: E402

STAMP = int(datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc).timestamp())
DEMO_HOME = Path("/home/demo")
EXCHANGES = (
    (
        "The checkout asks people to create an account before they can pay. Can we make guest checkout the default?",
        "Yes. Keep the existing sign-in option, but lead with guest checkout. Collect only the email and delivery details needed for the order.\n\nOffer account creation after payment, when it no longer blocks the purchase.",
    ),
    (
        "Keep saved addresses for returning customers. What needs to change?",
        "Keep the signed-in flow as it is. For guests, replace the account form with contact and delivery fields.\n\nThe order API already accepts a guest email, so no database migration is needed. Add tests for both paths before changing the page.",
    ),
    (
        "Good. Implement that plan and run the checkout tests.",
        "Implemented guest checkout while preserving saved addresses for signed-in customers.\n\nAll 18 checkout tests pass, including guest payment, address validation, and existing customer sign-in.\n\nDecision: account creation remains optional and appears only after a successful payment.",
    ),
    (
        "Let's also replace the payment provider while we are here.",
        "That is a separate migration: payment tokens, webhooks, and refunds would all need changes. I have outlined the migration steps, but have not changed the provider.",
    ),
    (
        "Actually, that is outside this task. I want to return to the guest-checkout decision.",
        "The guest-checkout implementation is complete. The payment-provider discussion can be removed from this session's resumed history without changing the checkout files.",
    ),
)


@dataclass
class DemoSession(Session):
    demo_size: int = 0

    @property
    def size(self):
        # Illustrative sizes, without creating large files or sparse payloads.
        return self.demo_size


class DemoManager(SessionManager):
    def __init__(self, root):
        super().__init__(root)  # This is an empty, temporary directory only.
        rows = (
            ("Website - checkout redesign", "website", 24_000_000, "ACTIVE"),
            ("API - rate limit debugging", "api", 87_000_000, "LIVE"),
            ("Image lab - model experiments", "image-lab", 2_800_000_000, "ACTIVE"),
            (
                "Home automation - heating schedule",
                "home-automation",
                6_200_000,
                "ACTIVE",
            ),
            ("Website - accessibility review", "website", 12_400_000, "ACTIVE"),
            ("Notes app - offline sync", "notes-app", 164_000_000, "ACTIVE"),
            ("Recipe book - weekly meal planner", "recipe-book", 940_000, "ACTIVE"),
            ("API - authentication migration", "api", 41_000_000, "ACTIVE"),
            (
                "Image lab - discarded experiments",
                "image-lab",
                1_600_000_000,
                "ARCHIVED",
            ),
            ("Portfolio - first layout", "portfolio", 3_100_000, "ARCHIVED"),
            ("Notes app - export format", "notes-app", 7_600_000, "ACTIVE"),
            ("Website - launch checklist", "website", 1_800_000, "ARCHIVED"),
        )
        self.sessions = [
            DemoSession(
                id=f"{0xDE000001 + index:08x}-0000-4000-8000-000000000001",
                rollout_path=root / f"demo-{index}.jsonl",
                created_ms=(STAMP - 86400 * (index + 2)) * 1000,
                updated_ms=(STAMP - 3600 * index) * 1000,
                recency_ms=(STAMP - 3600 * index) * 1000,
                archived=state == "ARCHIVED",
                pinned=False,
                name=name,
                title="",
                preview=EXCHANGES[0][0],
                cwd=str(DEMO_HOME / "projects" / directory),
                source="cli",
                history_mode="paginated",
                live=state == "LIVE",
                demo_size=size,
            )
            for index, (name, directory, size, state) in enumerate(rows)
        ]
        for session in self.sessions:
            session.rollout_path.touch()

    def full_conversation(self, session, compute_hash=False):
        messages = []
        for index, (question, answer) in enumerate(EXCHANGES):
            for offset, (role, text) in enumerate(
                (("user", question), ("assistant", answer))
            ):
                messages.append(
                    Message(
                        role,
                        text,
                        f"2026-09-07T14:{index * 5 + offset:02d}:00Z",
                        turn_id=f"demo-turn-{index}",
                    )
                )
        return ExtractResult(messages)

    def quick_preview(self, session, count):
        messages = self.full_conversation(session).messages
        return messages[:count], messages[-count:], ""


def demo_memories(root):
    files = {
        "config.toml": "[features]\nmemories = true\n[memories]\nuse_memories = true\ngenerate_memories = true\ndisable_on_external_context = false\n",
        "memories/memory_summary.md": "# Working preferences\n\nKeep changes small and run the relevant tests.\n\n# Recent projects\n\n- Website: guest checkout is the default; account creation is optional\n- Notes app: offline editing must work without signing in\n- Image lab: record the model and settings for each experiment\n",
        "memories/MEMORY.md": "# Project memory registry\n\n## Website\n\nGuest checkout is the default. Keep saved addresses for signed-in customers.\n\n## Notes app\n\nOffline edits sync when connectivity returns.\n",
        "memories/raw_memories.md": "# Extracted notes\n\nWebsite: guest checkout should not require account creation.\n\nNotes app: local edits must survive a restart.\n",
        "memories/rollout_summaries/website-checkout.md": "cwd: /home/demo/projects/website\n\n# Guest checkout\n\nDecision: offer account creation only after payment.\n",
        "memories/rollout_summaries/notes-offline-sync.md": "cwd: /home/demo/projects/notes-app\n\n# Offline sync\n\nKeep pending edits locally until the server acknowledges them.\n",
        "memories/rollout_summaries/image-experiments.md": "cwd: /home/demo/projects/image-lab\n\n# Model experiments\n\nRecord model version, seed, and settings alongside each output.\n",
        "memories/extensions/ad_hoc/notes/20260907-checkout.md": "# Memory correction\n\nWebsite: the old account-required checkout is obsolete. Use guest checkout as the default.\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        os.utime(path, (STAMP, STAMP))
    return MemoryManager(root)


def save_screen(app, destination, name):
    # Rich's SVG template contains blank lines with trailing spaces.
    svg = "\n".join(line.rstrip() for line in app.export_screenshot().splitlines())
    (destination / name).write_text(svg + "\n", encoding="utf-8")


async def capture(root):
    manager = DemoManager(root)
    app = SessionManagerApp(
        manager,
        demo_memories(root),
        {
            "human_size": human_size,
            "local_time": local_time,
        },
    )
    destination = REPO / "docs" / "screenshots"
    destination.mkdir(parents=True, exist_ok=True)
    async with app.run_test(size=(150, 40)) as pilot:
        await pilot.pause(0.4)
        assert app.query_one("#session-table", DataTable).row_count == 12
        save_screen(app, destination, "sessions.svg")

        await pilot.press("v")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConversationScreen)
        save_screen(app, destination, "conversation.svg")
        await pilot.press("escape")

        session = manager.sessions[0]
        messages = manager.full_conversation(session).messages
        plan = RewindPlan(
            session.id,
            "paginated",
            (),
            tuple(
                Exchange(
                    f"demo-turn-{index}",
                    "completed",
                    messages[index * 2].timestamp,
                    tuple(messages[index * 2 : index * 2 + 2]),
                )
                for index in range(len(EXCHANGES))
            ),
        )
        with patch("ui_rewind.read_plan", return_value=plan):
            await pilot.press("w")
            await pilot.pause(0.3)
            assert isinstance(app.screen, RewindScreen)
            app.screen.query_one(DataTable).move_cursor(row=2)
            await pilot.pause()
            assert app.screen.selected == 2
            save_screen(app, destination, "rewind.svg")
            await pilot.press("escape")

        await pilot.press("m")
        await pilot.pause()
        assert isinstance(app.screen, MemoryScreen)
        app.screen.query_one("#memory-kind", Select).value = "all"
        await pilot.pause()
        app.screen.query_one("#memory-preview", Markdown).scroll_end(animate=False)
        await pilot.pause()
        save_screen(app, destination, "memories.svg")
    print(f"Captured four real UI screens with fictional data in {destination}")


def main():
    os.environ.pop("NO_COLOR", None)
    os.environ["TERM"] = "xterm-256color"
    os.environ["COLORTERM"] = "truecolor"
    os.environ["TZ"] = "UTC"
    time.tzset()
    with (
        tempfile.TemporaryDirectory(prefix="codex-man-screenshots-") as directory,
        patch.object(Path, "home", return_value=DEMO_HOME),
        patch("session_inventory.time.time", return_value=STAMP),
        patch(
            "subprocess.Popen",
            side_effect=AssertionError(
                "Demo must not launch Codex or other subprocesses"
            ),
        ),
    ):
        asyncio.run(capture(Path(directory)))


if __name__ == "__main__":
    main()
