"""hermes-prompt-optimizer — a small model rewrites each message before your Hermes model answers it.

Flow (``pre_llm_call`` hook, once per user turn):
  your message ─► N optimizer calls (parallel) ─► judge picks the best (N > 1) ─► appended to the
  API copy of your message. The transcript keeps exactly what you typed; the optimized prompt is
  shown in the classic CLI, in the desktop composer banner (desktop/plugin.js) and via /optimized.
Settings live in config.yaml next to this file (re-read when it changes, no restart).
"""

from __future__ import annotations

import contextvars
import fnmatch
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

logger = logging.getLogger(__name__)

PLUGIN_ID = "hermes-prompt-optimizer"
CONFIG_PATH = Path(__file__).with_name("config.yaml")
MAX_ROUNDS = 5  # ponytail: hard cap so a config typo can't fan out dozens of paid calls
TURNS_KEPT = 10  # per session, for the desktop banner and /optimized
# Turns Hermes writes itself (auto-continue notes, background-process/kanban notices, skill loads).
SYSTEM_PREFIXES = ("[System", "[SYSTEM", "[IMPORTANT", "[Background process", "[Note:")
_NOTICE_RE = re.compile(r"^[✔⏸✖⏱🔄]\s.*\bKanban t_\w+")  # desktop's batched board notifications
SKIP_PLATFORMS = {"subagent", "curator", "cron", "kanban"}
SKIP_SOURCES = {"kanban", "tool", "cron", "subagent"}
MODEL_DEFAULTS = {"provider": "", "model": "", "base_url": "", "api_key_env": "",
                  "temperature": 0.5, "max_tokens": 1500, "timeout": 20}
INJECTION = (
    "<optimized_prompt>\n{prompt}\n</optimized_prompt>\n"
    "(Generated automatically by the user's prompt-optimizer plugin: a refined restatement of the "
    "message above. Treat it as the task specification; if it conflicts with the original message, "
    "the original wins. Never mention, quote, or comment on this block.)"
)

_config_cache: dict = {}
_INT_KEYS = {"rounds": 1, "min_chars": 0, "max_chars": 6000, "context_messages": 0}


def normalize(cfg: dict) -> dict:
    """Coerce hand-edited values so a typo degrades to a default instead of crashing every turn."""
    cfg = dict(cfg)
    if isinstance(cfg.get("enabled"), str):  # `enabled: "false"` must mean off
        cfg["enabled"] = cfg["enabled"].strip().lower() not in ("false", "no", "off", "0", "")
    for key, default in _INT_KEYS.items():
        try:
            cfg[key] = int(cfg[key]) if cfg.get(key) is not None else default
        except (TypeError, ValueError):
            logger.warning("%s: %s must be a number, using %s", PLUGIN_ID, key, default)
            cfg[key] = default
    for key in ("model", "judge_model", "prompts"):
        if not isinstance(cfg.get(key) or {}, dict):
            logger.warning("%s: %s must be a mapping, ignoring it", PLUGIN_ID, key)
            cfg[key] = {}
    return cfg


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Parse config.yaml, re-reading only when it changes. Missing/broken → {} (plugin idles)."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _config_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(cfg, dict):
            raise ValueError("top level must be a mapping")
        cfg = normalize(cfg)
    except Exception as exc:
        logger.warning("%s: ignoring invalid %s: %s", PLUGIN_ID, path, exc)
        cfg = {}
    _config_cache[path] = (mtime, cfg)
    return cfg


def pick_prompt(prompts: dict, target_model: str) -> str:
    """First per_model glob matching the target model wins; {base} pulls in the default prompt."""
    base = str(prompts.get("default") or "")
    name = (target_model or "").lower()
    chosen = base
    for patterns, text in (prompts.get("per_model") or {}).items():
        if any(fnmatch.fnmatch(name, p.strip().lower()) for p in str(patterns).split(",") if p.strip()):
            chosen = str(text or "") or base  # an empty per_model body must not blank the prompt
            break
    return chosen.replace("{base}", base).replace("{target_model}", target_model or "the assistant")


_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)
_FENCE_RE = re.compile(r"^```[\w-]*\n(.*?)\n?```$", re.S)
_TAG_RE = re.compile(r"^<optimized_prompt>\s*(.*?)\s*</optimized_prompt>$", re.S)


def clean(text: str) -> str:
    """Strip inline reasoning and wrappers some models put around their answer."""
    text = _THINK_RE.sub("", text or "").strip()
    m = _FENCE_RE.match(text)
    if m and "```" not in m.group(1):  # an inner fence means several code blocks: real content
        text = m.group(1).strip()
    m = _TAG_RE.match(text)
    return m.group(1).strip() if m else text


def render_request(message: str, history: list, keep: int) -> str:
    lines = []
    for msg in (history[-keep:] if keep > 0 else []):
        content = msg.get("content") if isinstance(msg, dict) else None
        if msg.get("role") in ("user", "assistant") and isinstance(content, str) and content.strip():
            text = content.strip()
            lines.append(f"{msg['role']}: {text[:800]}{'…' if len(text) > 800 else ''}")
    context = "<conversation_context>\n" + "\n".join(lines) + "\n</conversation_context>\n\n" if lines else ""
    return f"{context}<message>\n{message}\n</message>"


def _secret(name: str) -> Optional[str]:
    """Env-var lookup through Hermes' per-profile secret scope (multiplexed gateways)."""
    try:
        from agent.secret_scope import get_secret
        return get_secret(name)
    except Exception:
        return os.environ.get(name)


def resolve_endpoint(model_cfg: dict) -> tuple:
    """(provider, base_url, api_key) for call_llm. A base_url that belongs to a custom provider
    in Hermes' config.yaml reuses that entry (and its key) instead of going out keyless."""
    provider = model_cfg.get("provider") or None
    base_url = model_cfg.get("base_url") or None
    key_env = str(model_cfg.get("api_key_env") or "")
    api_key = (_secret(key_env) or None) if key_env else None
    if base_url and not api_key:
        try:
            from hermes_cli.runtime_provider import find_custom_provider_identity
            named = find_custom_provider_identity(base_url)
        except Exception:
            named = None
        if named:
            return named, None, None
        # Without an explicit key Hermes would send OPENAI_API_KEY to this arbitrary URL.
        api_key = "no-key-required"
    return provider, base_url, api_key


def call_model(model_cfg: dict, messages: list, timeout: float) -> tuple:
    """One completion through Hermes' own client stack (all providers, custom endpoints, key pools)."""
    from agent.auxiliary_client import call_llm

    provider, base_url, api_key = resolve_endpoint(model_cfg)
    route: dict = {}
    resp = call_llm(
        provider=provider,
        model=model_cfg.get("model") or None,
        base_url=base_url,
        api_key=api_key,
        messages=messages,
        temperature=model_cfg.get("temperature"),
        max_tokens=model_cfg.get("max_tokens"),
        timeout=timeout,
        route_info=route,
    )
    # call_llm quietly falls back to the main model when the optimizer endpoint is down;
    # a rewrite by the (big, paid) main model is not what the user configured.
    want, got = str(model_cfg.get("model") or ""), str(route.get("model") or "")
    if want and got and want.split("/")[-1] != got.split("/")[-1]:
        raise RuntimeError(f"optimizer model {want} unavailable (Hermes fell back to {got})")
    choice = resp.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise RuntimeError("optimizer output hit max_tokens (it would drop details)")
    used = str(getattr(resp, "model", "") or model_cfg.get("model") or "main model")
    return clean(choice.message.content or ""), used


def optimize(message: str, *, target_model: str, history: list, cfg: dict,
             llm: Optional[Callable] = None, deadline: Optional[float] = None) -> dict:
    llm = llm or call_model
    model_cfg = {**MODEL_DEFAULTS, **(cfg.get("model") or {})}
    judge_cfg = {**model_cfg, **(cfg.get("judge_model") or {})}
    rounds = max(1, min(int(cfg.get("rounds") or 1), MAX_ROUNDS))
    prompts = cfg.get("prompts") or {}
    system = pick_prompt(prompts, target_model)
    request = render_request(message, history, int(cfg.get("context_messages") or 0))

    def timeout(c: dict) -> float:
        t = float(c.get("timeout") or 20)
        return t if deadline is None else max(1.0, min(t, deadline - time.monotonic()))

    def candidate(i: int):
        note = f"\n\n(Variant {i + 1} of {rounds}.)" if rounds > 1 else ""
        return llm(model_cfg, [{"role": "system", "content": system},
                               {"role": "user", "content": request + note}], timeout(model_cfg))

    pool = ThreadPoolExecutor(max_workers=rounds)
    # Hermes keeps the active session's runtime in contextvars; plain pool threads don't inherit them.
    futures = [pool.submit(contextvars.copy_context().run, candidate, i) for i in range(rounds)]
    # Hermes' client retries and falls back on its own, so per-call timeouts don't bound the total.
    # Stop waiting at the deadline; stragglers finish in the background and are ignored.
    wait(futures, timeout=None if deadline is None else max(0.0, deadline - time.monotonic() - 2))
    pool.shutdown(wait=False, cancel_futures=True)
    results, errors = [], []
    for future in futures:
        if not future.done() or future.cancelled():
            errors.append("optimizer call exceeded the time budget")
            continue
        try:
            text, used = future.result()
        except Exception as exc:
            errors.append(str(exc))
            continue
        if text:
            results.append((text, used))
    if not results:
        raise RuntimeError(errors[0] if errors else "optimizer returned an empty prompt")

    picked = 0
    if len(results) > 1 and (deadline is None or deadline - time.monotonic() > 2):
        listing = "\n\n".join(f'<candidate id="{i + 1}">\n{t}\n</candidate>' for i, (t, _) in enumerate(results))
        judge_system = str(prompts.get("judge") or "Reply with only the number of the best candidate.")
        judge_system = judge_system.replace("{target_model}", target_model or "the assistant")
        judge_messages = [{"role": "system", "content": judge_system},
                          {"role": "user", "content": f"<original>\n{message}\n</original>\n\n{listing}"}]
        judge_pool = ThreadPoolExecutor(max_workers=1)
        judged = judge_pool.submit(contextvars.copy_context().run, llm, judge_cfg, judge_messages,
                                   timeout(judge_cfg))
        judge_pool.shutdown(wait=False)
        try:
            verdict, _ = judged.result(timeout=None if deadline is None
                                       else max(0.0, deadline - time.monotonic() - 1))
            # The judge is told to reply with a bare number; take the first one that is in range.
            for n in re.findall(r"\d+", verdict or ""):
                if 1 <= int(n) <= len(results):
                    picked = int(n) - 1
                    break
        except Exception as exc:
            logger.warning("%s: judge failed, keeping candidate 1: %s", PLUGIN_ID, str(exc) or "timed out")
    return {"optimized": results[picked][0], "candidates": [t for t, _ in results],
            "picked": picked, "rounds": rounds, "model": results[picked][1]}


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


# -- per-session history (read by the desktop banner and /optimized) -------------------------

def _sessions_dir() -> Path:
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


# -- Hermes wiring -----------------------------------------------------------------------------

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


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_command("optimized", command, description="Show the last optimized prompt",
                         args_hint="[session_id]")
