"""Fail CI when tracked files include Codex state or private export containers.

This filename gate complements a secret scanner; it is not a content audit.
Synthetic fixtures are kept as source strings, never as runtime dumps.
"""

import subprocess
from pathlib import PurePosixPath

PRIVATE_DIRECTORIES = {
    ".codex",
    "sessions",
    "archived_sessions",
    "memories",
    "compact_session_archives",
    "thread-writer-locks",
}
PRIVATE_NAMES = {"auth.json", "config.toml", ".session-manager-cache.json", ".env"}
PRIVATE_SUFFIXES = {".jsonl", ".db", ".log", ".pem", ".key", ".bundle"}


def private_path(name):
    path = PurePosixPath(name)
    return (
        bool(PRIVATE_DIRECTORIES.intersection(path.parts))
        or path.name in PRIVATE_NAMES
        or path.name.startswith(".env.")
        or path.suffix in PRIVATE_SUFFIXES
        or ".sqlite" in path.name
        or path.name.endswith((".db-wal", ".db-shm"))
    )


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    rejected = sorted(name for name in names if name and private_path(name))
    if rejected:
        raise SystemExit(
            "Private/runtime paths must not be tracked:\n" + "\n".join(rejected)
        )
    print("Tracked-file privacy gate passed.")


if __name__ == "__main__":
    main()
