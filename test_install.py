from pathlib import Path

import pytest

import install


def fixture(tmp_path, monkeypatch):
    checkout = tmp_path / "project"
    checkout.mkdir()
    script = checkout / "codex_session_manager.py"
    script.write_text("# synthetic launcher\n")
    lock = checkout / "codex_session_manager.py.lock"
    lock.write_text("version = 1\n")
    home = tmp_path / "user"
    monkeypatch.setattr(install, "__file__", str(checkout / "install.py"))
    monkeypatch.setattr(Path, "home", lambda: home)
    return home, script, lock


def test_installer_links_lock_and_repairs_legacy_alias(tmp_path, monkeypatch):
    home, script, lock = fixture(tmp_path, monkeypatch)
    legacy = home / ".codex/bin/codex_session_manager.py"
    legacy.parent.mkdir(parents=True)
    legacy.symlink_to(script)
    install.main()
    install.main()
    assert (home / ".local/bin/codex-man").resolve() == script
    assert (home / ".local/bin/codex-man.lock").resolve() == lock
    assert legacy.with_name(legacy.name + ".lock").resolve() == lock


def test_installer_refuses_foreign_lock_without_partial_install(tmp_path, monkeypatch):
    home, _, _ = fixture(tmp_path, monkeypatch)
    existing = home / ".local/bin/codex-man.lock"
    existing.parent.mkdir(parents=True)
    existing.write_text("foreign lock")
    with pytest.raises(SystemExit, match="Refusing to replace"):
        install.main()
    assert existing.read_text() == "foreign lock"
    assert not (home / ".local/bin/codex-man").exists()
