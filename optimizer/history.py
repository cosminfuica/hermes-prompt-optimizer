"""Recent results per chat, read by /optimized and the desktop banner.

Stored in Hermes' per-plugin data dir (<HERMES_HOME>/plugin-data/hermes-prompt-optimizer/), which
follows the active profile and survives plugin updates and removal.
"""

from __future__ import annotations

import json
import logging
import os
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
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("turns") or []
    except (OSError, ValueError, AttributeError):
        return []


def record(entry: dict) -> None:
    path = _session_file(entry["session_id"])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        turns = [t for t in _read_turns(path) if t.get("id") != entry["id"]] + [dict(entry)]
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"turns": turns[-TURNS_KEPT:]}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("%s: could not save history: %s", PLUGIN_ID, exc)


def latest(session_id: Optional[str] = None) -> Optional[dict]:
    if session_id:
        path = _session_file(session_id)
    else:
        files = sorted(_sessions_dir().glob("*.json"), key=lambda p: p.stat().st_mtime)
        path = files[-1] if files else None
    turns = _read_turns(path) if path else []
    return turns[-1] if turns else None


def describe(entry: dict) -> str:
    bits = [entry.get("model") or "?", f"{entry.get('seconds', '?')}s"]
    if len(entry.get("candidates") or []) > 1:
        bits.append(f"best of {len(entry['candidates'])}: #{entry.get('picked', 0) + 1}")
    body = "\n".join(f"  │ {line}" for line in (entry.get("optimized") or "").splitlines())
    return f"✦ optimized prompt · {' · '.join(bits)}\n{body}"
