"""Install the codex-man launcher without copying code into Codex runtime state."""

import os
from pathlib import Path


def main():
    source = Path(__file__).resolve().with_name("codex_session_manager.py")
    lock = source.with_name(source.name + ".lock")
    if not lock.is_file():
        raise SystemExit(f"Missing dependency lock: {lock}; use a complete checkout")
    destination = Path.home() / ".local" / "bin" / "codex-man"
    aliases = [destination]
    for candidate in (
        destination.with_name("codex-session-manager"),
        Path.home() / ".codex" / "bin" / source.name,
    ):
        if candidate.is_symlink() and candidate.resolve() == source:
            aliases.append(candidate)
    links = [(destination, source)] + [
        (alias.with_name(alias.name + ".lock"), lock) for alias in aliases
    ]
    # Check every path before changing anything; never take over foreign files.
    for link, target in links:
        if link.is_symlink() and link.resolve() == target:
            continue
        if link.exists() or link.is_symlink():
            raise SystemExit(f"Refusing to replace existing launcher or lock: {link}")
    source.chmod(source.stat().st_mode | 0o100)
    for link, target in links:
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink():
            link.symlink_to(target)
        print(f"Installed: {link} -> {target}")
    if str(destination.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        print('Add ~/.local/bin to PATH: export PATH="$HOME/.local/bin:$PATH"')
    print("Run codex-man for the terminal UI, or codex-man --help.")


if __name__ == "__main__":
    main()
