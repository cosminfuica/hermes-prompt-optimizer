"""/optimizer: view and change config.yaml from the chat, a text front end for settings.py.

Hermes gives plugin commands plain text in and out: no buttons, pickers or follow-up prompts, and
argument completion covers built-in commands only. So the menu is a numbered list and every step is
one complete command (`/optimizer 2 3` sets setting 2 to 3). Saves apply from the next message.
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path

from . import settings
from .config import CONFIG_PATH
from .engine import _secret
from .hook import _host_hook_timeout, _in_messaging_gateway
from .settings import ConfigError, fmt

logger = logging.getLogger(__name__)

MENU = [key for key in settings.SETTINGS if not key.startswith("prompts.")]  # prompts are multi-line: file only
WORDS = ["show", "status", "set", "reset", "on", "off", "help"]
LIVE = "Applies from your next message, no restart needed."
REFUSAL = ("/optimizer is only available in the CLI, TUI and desktop app: on messaging platforms Hermes doesn't "
           "tell plugin commands who is asking, so anyone in the chat could change it.")


def optimizer_command(raw_args: str = "", path: Path = CONFIG_PATH) -> str:
    """Hermes calls this with the text after /optimizer. Always returns text, never raises: Hermes'
    desktop dispatch swallows exceptions and reports the command as unknown."""
    if _in_messaging_gateway():  # the gateway doesn't say who is asking; any group member could change it
        return REFUSAL
    try:
        return _run((raw_args or "").split(None, 1), path)
    except ConfigError as exc:
        return str(exc)
    except Exception as exc:
        logger.exception("/optimizer failed")
        return f"/optimizer failed: {exc}"


def _run(args: list, path: Path) -> str:
    word = args[0].lower() if args else ""
    rest = args[1].strip() if len(args) > 1 else ""
    if word in ("", "show", "status"):
        return _detail(_key(rest), path) if rest else _menu(path)
    if word == "help":
        return _help(path)
    if word in ("on", "off"):
        return _set("enabled", word, path)
    if word == "set":
        pair = rest.split(None, 1)
        if len(pair) < 2:
            return "/optimizer set needs a key and a value, e.g. /optimizer set rounds 3."
        return _set(_key(pair[0]), pair[1], path)
    if word == "reset":
        return _reset(rest, path)
    return _set(_key(args[0]), rest, path) if rest else _detail(_key(args[0]), path)


def _key(token: str) -> str:
    """A menu number or a setting name -> the setting's key; ConfigError with a suggestion otherwise."""
    t = token.strip().lower()
    if t.isdecimal():
        if 1 <= int(t) <= len(MENU):
            return MENU[int(t) - 1]
        raise ConfigError(f"There is no setting {t}: the numbers go from 1 to {len(MENU)}. Type /optimizer for the list.")
    if t in MENU:
        return t
    if t.startswith("prompts."):
        raise ConfigError(f"{t} is multi-line text: edit it in the settings file (see /optimizer help).")
    close = difflib.get_close_matches(t, MENU + [w for w in WORDS if w != t], n=1)  # never "reset? did you mean reset"
    hint = f" Did you mean {close[0]}?" if close else ""
    raise ConfigError(f'Unknown setting "{token.strip()}".{hint} Type /optimizer for the list.')


def _effective(v: dict, key: str):
    """The value the optimizer uses: an unset judge_model.X falls back to model.X."""
    if key.startswith("judge_model.") and v[key] is None:
        return v["model." + key.split(".", 1)[1]]
    return v[key]


def _menu(path: Path) -> str:
    v = settings.get_all(path)
    state = "on" if v["enabled"] is not False else "off (turn it on: /optimizer on)"
    if not path.exists():
        state = "idle, the settings file doesn't exist. Any change below creates it from config.yaml.example."
    lines = [f"Prompt optimizer: {state}", f"Settings file: {path}"]
    group = None
    for n, key in enumerate(MENU, 1):
        if key.rpartition(".")[0] != group:  # a blank line between general, model.* and judge_model.*
            group = key.rpartition(".")[0]
            lines.append("")
        value = fmt(v[key])
        if v[key] is None and key.startswith("judge_model.") and _effective(v, key) is not None:
            value += f" (uses {fmt(_effective(v, key))})"
        lines.append(f"{n:>3}. {key} = {value} — {settings.SETTINGS[key].help.split(';')[0].rstrip('.')}")
    return "\n".join(lines + [
        "",
        "Change: /optimizer <number or key> <value>, e.g. /optimizer 2 3",
        "Details and choices: /optimizer <number or key> · Reset: /optimizer reset [key] · Help: /optimizer help",
        "Prompts (prompts.*) are multi-line: edit them in the settings file."])


def _how(key: str) -> str:
    """The ready-to-type commands for a setting: every choice when there are few, else a template."""
    spec = settings.SETTINGS[key]
    if spec.kind == "bool":
        choices = ["on", "off"]
    elif spec.kind == "int" and spec.hi - spec.lo < 10:
        choices = range(int(spec.lo), int(spec.hi) + 1)
    else:
        empty = ' (or "" for empty)' if spec.kind in ("str", "url", "env") else ""
        return f"  Change it: /optimizer {key} <new value>{empty}"
    return "  Choose: " + " · ".join(f"/optimizer {key} {c}" for c in choices)


def _detail(key: str, path: Path) -> str:
    return "\n".join([f"{MENU.index(key) + 1}. {settings.describe(key, path=path)}", _how(key),
                      f"  Reset: /optimizer reset {key}"])


def _set(key: str, raw: str, path: Path) -> str:
    try:
        old, new = settings.set(key, raw, path=path)
    except ConfigError as exc:  # nothing was written; the reply says how to retry
        return f"Not saved: {exc}\n{_how(key)}"
    if old == new:
        return f"{key} is already {fmt(new)}. Nothing changed."
    return "\n".join([f"Saved {key}: {fmt(old)} → {fmt(new)}. {LIVE}", *_notes(key, settings.get_all(path))])


def _notes(key: str, v: dict) -> list:
    """Valid, saved, but probably not what the user wants."""
    notes = []
    group, _, leaf = key.rpartition(".")
    if key == "enabled" and v["enabled"] is False:
        notes.append("The optimizer is off: messages are sent as typed. Turn it back on: /optimizer on")
    url = _effective(v, f"{group}.base_url") if group else None
    if leaf in ("provider", "base_url") and url and _effective(v, f"{group}.provider"):
        notes.append(f"Note: {group}.provider is ignored while a base_url is set ({fmt(url)}). "
                     f'To use the provider: /optimizer {group}.base_url ""')
    if leaf == "api_key_env" and v[key] and not _secret(v[key]):  # presence only; the value is never shown
        notes.append(f"Note: {v[key]} is not set in Hermes' environment. Add {v[key]}=<your key> to your Hermes .env "
                     "file, then run /reload or restart Hermes.")
    if leaf in ("rounds", "timeout"):
        budget = _host_hook_timeout()  # Hermes abandons the hook after this; the engine stops 1.5s earlier
        judge = float(_effective(v, "judge_model.timeout") or 20) if (v["rounds"] or 1) > 1 else 0.0
        worst = float(v["model.timeout"] or 20) + judge
        if 0 < budget < worst + 1.5:
            notes.append(f"Note: a run can take up to {worst:g}s, but Hermes allows plugins {budget:g}s. Raise the limit: "
                         f"hermes config set plugins.hook_callback_timeout {int(worst) + 10}")
    return notes


def _reset(arg: str, path: Path) -> str:
    if arg.lower() == "all":
        changed = settings.reset(path=path)
        if not changed:
            return "All settings already have their default values."
        return "\n".join([f"Reset {len(changed)} setting(s) to their defaults:", *_changes(changed), LIVE])
    if arg:
        key = _key(arg)
        changed = settings.reset(key, path=path)
        if not changed:
            return f"{key} already has its default value."
        return "\n".join([f"Reset {key}: {fmt(changed[key][0])} → {fmt(changed[key][1])}. {LIVE}",
                          *_notes(key, settings.get_all(path))])
    v, d = settings.get_all(path), settings.defaults(path)
    todo = {k: (v[k], d[k]) for k in MENU if v[k] != d[k]}  # MENU = every setting reset() touches
    if not todo:
        return "All settings already have their default values."
    return "\n".join(["/optimizer reset all would change:", *_changes(todo),
                      "Type /optimizer reset all to confirm (prompts are not touched), or /optimizer reset <key> for one."])


def _changes(changed: dict) -> list:
    return [f"  {k}: {fmt(old)} → {fmt(new)}" for k, (old, new) in changed.items()]


def _help(path: Path) -> str:
    return "\n".join([
        "/optimizer shows and changes the prompt optimizer's settings from the chat.",
        "  /optimizer: every setting, numbered, with its current value",
        "  /optimizer <number or key>: what it does, allowed values, ready-to-type choices",
        "  /optimizer <number or key> <value>, or /optimizer set <number or key> <value>: change it",
        "  /optimizer on, /optimizer off: turn the optimizer on or off",
        "  /optimizer reset <number or key>: put one setting back to its default",
        "  /optimizer reset: preview resetting every setting; /optimizer reset all does it (prompts excluded)",
        '  "" is an empty value, e.g. /optimizer model.base_url ""',
        f"Changes are saved to {path} and apply from your next message, no restart needed.",
        "Editing that file by hand works too; prompts (multi-line) are edited only there. Last result: /optimized"])
