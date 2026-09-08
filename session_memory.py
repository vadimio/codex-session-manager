from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from session_models import confirm, human_size, safe_slug
from session_transcript import atomic_write


class MemoryManager:
    ALIASES = {
        "summary": "memory_summary.md",
        "durable": "MEMORY.md",
        "registry": "MEMORY.md",
        "raw": "raw_memories.md",
    }

    def __init__(self, codex_home: Path):
        self.home = codex_home
        self.root = self.home / "memories"
        self.config = self.home / "config.toml"

    def inventory(self) -> None:
        print("Local Codex memory store")
        print(f"Path: {self.root}")
        print("\nCore generated files:")
        descriptions = {
            "memory_summary.md": "short summary commonly injected into future chats",
            "MEMORY.md": "durable searchable registry",
            "raw_memories.md": "raw extracted memory material",
        }
        for name, description in descriptions.items():
            path = self.root / name
            if path.exists():
                modified = (
                    datetime.fromtimestamp(path.stat().st_mtime)
                    .astimezone()
                    .strftime("%Y-%m-%d %H:%M")
                )
                print(
                    f"  {name:<22} {human_size(path.stat().st_size):>10}  {modified}  {description}"
                )
            else:
                print(f"  {name:<22} (missing)             {description}")
        rollouts = list((self.root / "rollout_summaries").glob("*.md"))
        print(
            f"  {'rollout_summaries/':<22} {human_size(sum(p.stat().st_size for p in rollouts)):>10}  "
            f"{len(rollouts)} evidence summaries"
        )
        notes = list((self.root / "extensions" / "ad_hoc" / "notes").glob("*.md"))
        print(
            f"  {'correction notes':<22} {len(notes):>10}  user-authored update/correction requests"
        )
        self.show_config()
        print(
            "\nUse `memory show summary|durable|raw`, `memory correct`, or "
            "`memory edit TARGET --direct`. Direct edits are generated state and may be overwritten."
        )

    def resolve(self, target: str) -> Path:
        relative = self.ALIASES.get(target.casefold(), target)
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root.resolve())
        except ValueError as error:
            raise ValueError(
                "memory target must stay inside the local memories directory"
            ) from error
        if not path.exists() or not path.is_file():
            raise ValueError(f"memory file does not exist: {path}")
        return path

    def show(self, target: str) -> None:
        path = self.resolve(target)
        print(f"# {path}\n")
        print(path.read_text(encoding="utf-8"), end="")

    def edit(self, target: str, direct: bool = False, yes: bool = False) -> None:
        if not direct:
            raise RuntimeError(
                "direct memory editing requires --direct; prefer `memory correct` because generated files may be overwritten"
            )
        path = self.resolve(target)
        if not yes and not confirm(
            f"Back up and directly edit generated memory file {path.name}?"
        ):
            print("Cancelled.")
            return
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%f")
        backup = path.with_name(f"{path.name}.bak.{stamp}")
        shutil.copy2(path, backup)
        launch_editor(path)
        print(f"Edited {path}; backup: {backup}")

    def correct(self, text: str | None = None, quiet: bool = False) -> Path:
        notes = self.root / "extensions" / "ad_hoc" / "notes"
        notes.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone()
        if text:
            slug = safe_slug(text, "memory-correction")[:50]
        else:
            slug = "memory-correction"
        path = notes / f"{now.strftime('%Y%m%dT%H%M%S%f%z')}-{slug}.md"
        content = (
            "# Memory correction\n\n"
            f"Created: {now.isoformat()}\n\n"
            "Describe what is wrong, what should replace it, and (if known) which source/session supports the change.\n\n"
            f"{text or ''}\n"
        )
        atomic_write(path, content)
        if text is None:
            launch_editor(path)
        if not quiet:
            print(f"Created memory correction note: {path}")
        return path

    def config_values(self) -> dict[str, Any]:
        try:
            with self.config.open("rb") as handle:
                data = tomllib.load(handle)
        except FileNotFoundError:
            data = {}
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise RuntimeError(f"Cannot read memory configuration: {error}") from error
        memory = data.get("memories") or {}
        features = data.get("features") or {}
        return {
            "feature": features.get("memories", "not set"),
            "use_memories": memory.get("use_memories", "not set (Codex default: on)"),
            "generate_memories": memory.get(
                "generate_memories", "not set (Codex default: on)"
            ),
            "disable_on_external_context": memory.get(
                "disable_on_external_context", "not set (Codex default: off)"
            ),
        }

    def show_config(self) -> None:
        values = self.config_values()
        print("\nMemory controls in config.toml:")
        for key, value in values.items():
            print(f"  {key:<30} {value}")
        print("  Per-chat control:              use /memories inside Codex")

    def set_config(self, setting: str, enabled: bool, quiet: bool = False) -> None:
        mapping = {
            "use": "use_memories",
            "generate": "generate_memories",
            "exclude-external": "disable_on_external_context",
        }
        key = mapping[setting]
        value = "true" if enabled else "false"
        source = self.config.read_text(encoding="utf-8") if self.config.exists() else ""
        tomllib.loads(source)
        updated = update_toml_section_value(source, "memories", key, value)
        parsed = tomllib.loads(updated)
        if parsed.get("memories", {}).get(key) is not enabled:
            raise RuntimeError(
                "Configuration validation failed; the original was not changed."
            )
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S%f")
        backup = self.config.with_name(f"{self.config.name}.bak.{stamp}")
        if self.config.exists():
            shutil.copy2(self.config, backup)
        atomic_write(self.config, updated)
        if not quiet:
            print(f"Set memories.{key} = {value} in {self.config}")
            if backup.exists():
                print(f"Backup: {backup}")


def update_toml_section_value(source: str, section: str, key: str, value: str) -> str:
    lines = source.splitlines()
    header = f"[{section}]"
    section_start = next(
        (i for i, line in enumerate(lines) if line.strip() == header), None
    )
    key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend((header, f"{key} = {value}"))
        return "\n".join(lines) + "\n"
    section_end = len(lines)
    for index in range(section_start + 1, len(lines)):
        if re.match(r"^\s*\[.+]\s*$", lines[index]):
            section_end = index
            break
    for index in range(section_start + 1, section_end):
        if key_pattern.match(lines[index]):
            lines[index] = f"{key} = {value}"
            return "\n".join(lines) + "\n"
    lines.insert(section_end, f"{key} = {value}")
    return "\n".join(lines) + "\n"


def launch_editor(path: Path) -> None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    command = shlex.split(editor) + [str(path)]
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise RuntimeError(f"editor exited with status {completed.returncode}")
