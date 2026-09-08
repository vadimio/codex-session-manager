from scripts.check_repository import private_path


def test_private_runtime_files_are_rejected():
    for path in (
        ".codex/auth.json",
        "sessions/example.jsonl",
        "nested/memories/MEMORY.md",
        "config.toml",
        ".env.production",
        "state_5.sqlite-wal",
        "history.db-shm",
        "backup.bundle",
        "private.pem",
        "output.log",
    ):
        assert private_path(path), path


def test_source_and_synthetic_screenshots_are_allowed():
    for path in (
        "session_memory.py",
        "docs/screenshots/memories.svg",
        "uv.lock",
        "pyproject.toml",
        "scripts/screenshots.py",
        "test_session_rpc.py",
    ):
        assert not private_path(path), path
