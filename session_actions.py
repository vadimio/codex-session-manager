from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from session_models import Session, confirm, human_size, safe_slug
from session_rpc import app_server_request
from session_transcript import atomic_write, render_compact_archive


class Actions:
    def run_codex_action(
        self, action: str, session: Session, yes: bool = False, quiet: bool = False
    ) -> None:
        if action not in {"archive", "unarchive", "delete"}:
            raise ValueError(f"Unsupported session action: {action}")
        if session.live or self._is_live(session.id):
            raise RuntimeError(
                f"refusing to {action} LIVE session {session.id}; finish or exit it first"
            )
        if action == "archive" and session.archived:
            raise RuntimeError("session is already archived")
        if action == "unarchive" and not session.archived:
            raise RuntimeError("session is not archived")
        if action == "delete":
            self._confirm_delete(session, yes=yes)
            command = ["codex", "delete", session.id, "--force"]
        else:
            if not yes and not confirm(
                f"{action.capitalize()} {session.id[:8]} ({session.display_name})?"
            ):
                if not quiet:
                    print("Cancelled.")
                return
            command = ["codex", action, session.id]
        if self._is_live(session.id):
            raise RuntimeError(
                "The session became LIVE during confirmation. Close it first."
            )
        completed = subprocess.run(
            command,
            check=False,
            capture_output=quiet,
            text=quiet,
            env=self._codex_environment(),
        )
        if completed.returncode:
            detail = (
                (completed.stderr or completed.stdout or "").strip() if quiet else ""
            )
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(
                f"{' '.join(command)} failed with exit code {completed.returncode}{suffix}"
            )
        if not quiet:
            print(f"{action.capitalize()}d {session.id}.")
        self.reload()

    @staticmethod
    def _confirm_delete(session: Session, yes: bool = False) -> None:
        if yes:
            return
        if not sys.stdin.isatty():
            raise RuntimeError("delete requires an interactive terminal or --yes")
        print("PERMANENT DELETE. Codex may also delete spawned descendant sessions.")
        print(
            f"Target: {session.id}  {session.display_name}  {human_size(session.size)}"
        )
        typed = input("Type the full session ID to confirm: ").strip()
        if typed != session.id:
            raise RuntimeError("confirmation did not match; nothing deleted")

    def rename(self, session: Session, new_name: str, quiet: bool = False) -> None:
        new_name = " ".join(new_name.split())
        if not new_name:
            raise ValueError("session name cannot be empty")
        app_server_request(
            self.home,
            "thread/name/set",
            {"threadId": session.id, "name": new_name},
            timeout=30,
        )
        if not quiet:
            print(f"Renamed {session.id} to {new_name!r}.")
        self.reload()

    @staticmethod
    def resume_command(session: Session, unrestricted: bool = False) -> list[str]:
        command = ["codex", "resume"]
        if unrestricted:
            command.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            command.extend(
                ["--sandbox", "workspace-write", "--ask-for-approval", "on-request"]
            )
        if session.cwd and Path(session.cwd).is_dir():
            command.extend(["--cd", session.cwd])
        command.append(session.id)
        return command

    def resume(self, session: Session, unrestricted: bool = False) -> None:
        if session.live or self._is_live(session.id):
            raise RuntimeError(
                "This session is already LIVE; close the existing Codex session first."
            )
        if session.cwd and not Path(session.cwd).is_dir():
            raise RuntimeError(
                f"Saved project directory no longer exists: {session.cwd}"
            )
        command = self.resume_command(session, unrestricted=unrestricted)
        completed = subprocess.run(command, check=False, env=self._codex_environment())
        if completed.returncode:
            raise RuntimeError(
                f"{' '.join(command)} failed with exit code {completed.returncode}"
            )
        self.reload()

    def compact_archive(
        self,
        session: Session,
        output: Path | None,
        delete_source: bool,
        yes: bool,
        quiet: bool = False,
    ) -> Path:
        if session.live or self._is_live(session.id):
            raise RuntimeError(
                "refusing to export a LIVE session because its transcript is still changing"
            )
        if not quiet:
            print(
                f"Extracting user messages and final answers from {human_size(session.size)}; "
                "legacy transcripts may take a while...",
                file=sys.stderr,
            )
        from session_rewind import fingerprint

        before = fingerprint(self, session)
        extracted = self.full_conversation(session, compute_hash=True)
        if before != fingerprint(self, session) or self._is_live(session.id):
            raise RuntimeError("Session changed during export; no archive was written.")
        if not extracted.messages:
            raise RuntimeError(
                "no user/final-answer messages were found; source was not changed"
            )
        if output is None:
            self.export_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.fromtimestamp(
                session.created_ms / 1000, tz=timezone.utc
            ).strftime("%Y%m%d")
            output = (
                self.export_dir
                / f"{stamp}-{safe_slug(session.display_name)}-{session.id[:8]}-{datetime.now().strftime('%Y%m%dT%H%M%S%f')}.md"
            )
        else:
            output = output.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
        markdown = render_compact_archive(session, extracted)
        atomic_write(output, markdown, overwrite=False)
        verify = output.read_text(encoding="utf-8")
        if verify != markdown:
            raise RuntimeError(
                "compact archive verification failed; source was not changed"
            )
        if not quiet:
            print(f"Wrote and verified: {output}")
            print(
                f"Archive size: {human_size(output.stat().st_size)}; original: {human_size(session.size)}"
            )
            self._print_extract_warnings(extracted)
        if delete_source:
            if extracted.skipped_oversize_lines or extracted.malformed_candidate_lines:
                raise RuntimeError(
                    f"Archive saved at {output}, but extraction had skipped or malformed records. Source was not deleted; review it manually."
                )
            self._confirm_delete(session, yes=yes)
            if before != fingerprint(self, session):
                raise RuntimeError(
                    "Session changed after export. Source was not deleted."
                )
            if not quiet:
                print(
                    "The readable compact archive is verified. The next step removes the resumable Codex transcript."
                )
            self.run_codex_action("delete", session, yes=True, quiet=quiet)
        return output
