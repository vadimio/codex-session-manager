from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def _short(text: str, width: int = 90) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= width else clean[: width - 1].rstrip() + "…"


def _path_tail(path: str, width: int = 34) -> str:
    """Compact a path relative to home, preserving the most useful trailing part."""
    clean = path.strip() or "(unknown)"
    home = str(Path.home())
    if clean == home:
        clean = "~"
    elif clean.startswith(home + "/"):
        clean = "…/" + clean[len(home) + 1 :]
    elif clean.startswith("~/"):
        clean = "…/" + clean[2:]
    if len(clean) <= width:
        return clean
    return "…" + clean[-(width - 1) :]


def _compact_timestamp(value: str) -> str:
    if not value:
        return "--/--/-- --:-- > "
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%m/%d/%y %H:%M > ")
    except ValueError:
        return _short(value, 17) + " > "


def _code(text: Any) -> str:
    return "`" + str(text).replace("`", "\\`") + "`"


def _message_excerpt(message: Any, limit: int = 3500) -> str:
    text = message.text.strip()
    if len(text) > limit:
        text = (
            text[:limit].rstrip()
            + "\n\n[…message shortened in preview; press **T** for the full conversation]"
        )
    role = "You" if message.role == "user" else "Codex final answer"
    stamp = f" — {message.timestamp}" if message.timestamp else ""
    return f"#### {role}{stamp}\n\n{text or '*(empty)*'}"
