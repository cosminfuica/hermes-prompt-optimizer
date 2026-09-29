"""Recent results per chat, read by /optimized and the desktop banner.

Stored in Hermes' per-plugin data dir (<HERMES_HOME>/plugin-data/hermes-prompt-optimizer/), which
follows the active profile and survives plugin updates and removal. The files hold your prompts, so
only you can read them.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from . import PLUGIN_ID

logger = logging.getLogger(__name__)

TURNS_KEPT = 10  # per session


def _sessions_dir() -> Path:
    # The documented per-plugin data root; plugin_storage.plugin_data_dir() builds the same path
    # but only exists since Hermes v0.20.4.
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "plugin-data" / PLUGIN_ID / "sessions"


def _session_file(session_id: str) -> Path:
    return _sessions_dir() / (re.sub(r"[^\w.-]", "_", session_id or "none") + ".json")


def _read_turns(path: Path) -> list:
    """The recorded turns; a damaged file (hand edit, crash, older format) reads as the part that is intact."""
    try:
        turns = json.loads(path.read_text(encoding="utf-8")).get("turns")
    except (OSError, ValueError, AttributeError):
        return []
    return [t for t in turns if isinstance(t, dict)] if isinstance(turns, list) else []


def record(entry: dict) -> None:
    """Best effort: a history that can't be written never stops the optimizer."""
    path = _session_file(entry["session_id"])
    try:
        from utils import atomic_write_text  # Hermes': unique temp file (mode 0600) + fsync + rename

        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        turns = [t for t in _read_turns(path) if t.get("id") != entry["id"]] + [dict(entry)]
        atomic_write_text(path, json.dumps({"turns": turns[-TURNS_KEPT:]}, ensure_ascii=False))
    except Exception as exc:
        logger.warning("%s: could not save history: %s", PLUGIN_ID, exc)


def latest(session_id: str) -> Optional[dict]:
    turns = _read_turns(_session_file(session_id))
    return turns[-1] if turns else None


def describe(entry: dict) -> str:
    bits = [entry.get("model") or "?", f"{entry.get('seconds', '?')}s"]
    if len(entry.get("candidates") or []) > 1:
        bits.append(f"best of {len(entry['candidates'])}: #{entry.get('picked', 0) + 1}")
    body = "\n".join(f"  │ {line}" for line in (entry.get("optimized") or "").splitlines())
    return f"✦ optimized prompt · {' · '.join(bits)}\n{body}"
