"""Hermes wiring: the pre_llm_call hook, which turns it skips, and the /optimized command."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from typing import Any, Optional

from . import PLUGIN_ID
from .config import load_config
from .engine import optimize
from .history import describe, latest, record

logger = logging.getLogger(__name__)

# Turns Hermes writes itself (auto-continue notes, background-process/kanban notices, skill loads).
SYSTEM_PREFIXES = ("[System", "[SYSTEM", "[IMPORTANT", "[Background process", "[Note:")
_NOTICE_RE = re.compile(r"^[✔⏸✖⏱🔄]\s.*\bKanban t_\w+")  # desktop's batched board notifications
SKIP_PLATFORMS = {"subagent", "curator", "cron", "kanban"}
SKIP_SOURCES = {"kanban", "tool", "cron", "subagent"}
INJECTION = (
    "<optimized_prompt>\n{prompt}\n</optimized_prompt>\n"
    "(Generated automatically by the user's prompt-optimizer plugin: a refined restatement of the "
    "message above. Treat it as the task specification; if it conflicts with the original message, "
    "the original wins. Never mention, quote, or comment on this block.)"
)


def skip_reason(cfg: dict, message: Any, *, platform: str = "", parent_session_id: str = "",
                source: str = "", display_kind: str = "") -> str:
    if not cfg.get("enabled", True):
        return "disabled in config.yaml"
    if display_kind:  # auto-continue notes, model switches, widget sends: typed by Hermes, not you
        return f"synthesized turn ({display_kind})"
    if not (cfg.get("prompts") or {}).get("default"):
        return "config.yaml missing or has no prompts.default"
    if not isinstance(message, str):
        return "non-text message"
    text = message.strip()
    if len(text) < int(cfg.get("min_chars") or 0):
        return "too short"
    if len(text) > int(cfg.get("max_chars") or 6000):
        return "too long"
    if text.startswith(SYSTEM_PREFIXES) or _NOTICE_RE.match(text):
        return "Hermes-generated turn"
    if text.startswith("/"):  # slash commands / skill invocations reaching the model as text
        return "slash command"
    if parent_session_id:  # background review / side-question forks and subagents
        return "forked or child agent"
    if str(platform).lower() in SKIP_PLATFORMS or str(source).lower() in SKIP_SOURCES:
        return f"non-interactive surface ({platform or source})"
    return ""


def _session_source() -> str:
    try:
        from gateway.session_context import get_session_env
        return get_session_env("HERMES_SESSION_SOURCE", "")
    except Exception:
        return os.environ.get("HERMES_SESSION_SOURCE", "")


def _current_session_id() -> str:
    try:
        from gateway.session_context import get_session_env
        return get_session_env("HERMES_SESSION_ID", "")
    except Exception:
        return os.environ.get("HERMES_SESSION_ID", "")


def _host_hook_timeout() -> float:
    """Hermes abandons a pre_llm_call callback after plugins.hook_callback_timeout (default 30s)."""
    try:
        from hermes_cli.plugins import _resolve_hook_callback_timeout  # same clamping as Hermes
        return float(_resolve_hook_callback_timeout())
    except Exception:
        return 30.0


def _in_messaging_gateway() -> bool:
    """True inside `hermes gateway` (Telegram, Discord …), where many users share one process."""
    run = sys.modules.get("gateway.run")
    try:
        return bool(run and run._gateway_runner_ref() is not None)
    except Exception:
        return False


def _redact(text: str) -> str:
    try:
        from agent.redact import redact_sensitive_text
        return redact_sensitive_text(text, force=True)
    except Exception:
        return text


def on_pre_llm_call(session_id: str = "", user_message: Any = None, conversation_history: Any = None,
                    model: str = "", platform: str = "", parent_session_id: str = "",
                    **_: Any) -> Optional[dict]:
    cfg = load_config()
    history = [m for m in (conversation_history or []) if isinstance(m, dict)]
    # Drop this turn from the context. After compression it is not always the last row
    # (a todo snapshot can follow it), so match on content like Hermes' own re-anchoring does.
    current: dict = {}
    for i in range(len(history) - 1, -1, -1):
        if history[i].get("role") == "user" and history[i].get("content") == user_message:
            current = history.pop(i)
            break
    reason = skip_reason(cfg, user_message, platform=platform, parent_session_id=parent_session_id,
                         source=_session_source(), display_kind=str(current.get("display_kind") or ""))
    if reason:
        logger.debug("%s: skipped (%s)", PLUGIN_ID, reason)
        return None
    budget = _host_hook_timeout()
    started = time.monotonic()
    entry = {"id": str(time.time_ns()), "session_id": session_id or "", "ts": time.time(),
             "status": "running", "original": user_message, "target_model": model or ""}
    record(entry)
    try:
        entry.update(optimize(user_message, target_model=model, history=history, cfg=cfg,
                              deadline=started + budget - 1.5 if budget > 0 else None))
    except Exception as exc:
        entry.update(status="error", error=_redact(str(exc))[:500], seconds=round(time.monotonic() - started, 1))
        record(entry)
        logger.warning("%s: optimization failed, sending the original message: %s", PLUGIN_ID, exc)
        return None
    entry["seconds"] = round(time.monotonic() - started, 1)
    if budget > 0 and entry["seconds"] >= budget:
        entry["status"] = "late"  # Hermes already gave up on this hook and sent the original
    elif " ".join(entry["optimized"].split()) == " ".join(user_message.split()):
        entry["status"] = "unchanged"
    else:
        entry["status"] = "applied"
    record(entry)
    if entry["status"] != "applied":
        return None
    if platform == "cli" and cfg.get("show_in_cli", True):
        print(describe(entry), file=sys.stderr, flush=True)  # stderr keeps `hermes chat -q` stdout clean
    return {"context": INJECTION.format(prompt=entry["optimized"])}


def command(raw_args: str = "") -> str:
    """/optimized [session_id]  — `json <session_id>` is the desktop banner's data feed."""
    if _in_messaging_gateway():
        # ponytail: the gateway hands plugin commands only the args, not who is asking, so any
        # answer here could be another user's prompt. Re-enable once Hermes passes the caller.
        return "/optimized is only available in the CLI, TUI and desktop app."
    args = (raw_args or "").split()
    as_json = bool(args) and args[0] == "json"
    if as_json:
        args = args[1:]
    entry = latest(args[0] if args else (_current_session_id() or None))
    if as_json:
        return json.dumps(entry, ensure_ascii=False)
    if not entry:
        return "No optimized prompt yet."
    if entry.get("status") != "applied":
        detail = f": {entry['error']}" if entry.get("error") else ""
        return f"Last message was sent as typed ({entry.get('status')}{detail})."
    return describe(entry)
