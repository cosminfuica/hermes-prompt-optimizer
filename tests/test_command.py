"""Self-check for optimizer/command.py, the /optimizer chat command (no network, no real config).

Run from anywhere with Hermes' Python:  ~/.hermes/hermes-agent/venv/bin/python tests/test_command.py
"""

import importlib
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="po-command-"))
os.environ["HERMES_HOME"] = str(TMP / "home")  # Hermes' hook budget is read from here: the default 30s

# Load the plugin the way Hermes does: a package rooted at the repo, so its relative imports resolve.
spec = importlib.util.spec_from_file_location("po", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules["po"] = plugin
spec.loader.exec_module(plugin)
config, command, settings = (importlib.import_module(f"po.optimizer.{name}") for name in ("config", "command", "settings"))

TEMPLATE = (ROOT / "config.yaml.example").read_text(encoding="utf-8")
CFG = TMP / "config.yaml"  # a plugin folder of its own: config.yaml next to config.yaml.example
shutil.copy(ROOT / "config.yaml.example", TMP / "config.yaml.example")


def run(args=""):
    """What Hermes shows after the user types `/optimizer <args>` and presses Enter."""
    reply = command.optimizer_command(args, path=CFG)
    assert isinstance(reply, str) and reply, (args, reply)
    return reply


def fresh(text=TEMPLATE):
    CFG.write_text(text, encoding="utf-8")
    config._cache.clear()


def saved(key):
    value = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    for part in key.split("."):
        value = value[part]
    return value


# Bare command: every setting, numbered, with its value and a description. The numbers are part of the
# UI (/optimizer 2 3), so the order is pinned: a new setting goes at the end of its group.
fresh()
menu = run()
rows = re.findall(r"^ *(\d+)\. (\S+) = (.+) — .+$", menu, re.M)
MODEL = ("provider", "model", "base_url", "api_key_env", "temperature", "max_tokens", "timeout")
assert [key for _, key, _ in rows] == command.MENU == ["enabled", "rounds", *[f"model.{k}" for k in MODEL],
                                                       *[f"judge_model.{k}" for k in MODEL], "min_chars",
                                                       "max_chars", "context_messages", "show_in_cli"], rows
assert [int(n) for n, _, _ in rows] == list(range(1, 21))
assert ("2", "rounds", "1") in rows and ("10", "judge_model.provider", 'unset (uses "")') in rows
assert ("11", "judge_model.model", 'unset (uses "qwen2.5:7b")') in rows  # inherited from model.model
assert menu.startswith("Prompt optimizer: on\nSettings file: ") and "/optimizer 2 3" in menu
assert run("show") == run("status") == run("  ") == menu

# Selecting a setting: allowed values, the default, and ready-to-type commands (choices when there are few).
card = run("2")
assert card.startswith("2. rounds = 1\n") and "from 1 to 5" in card and "Default: 1." in card, card
assert " · ".join(f"/optimizer rounds {n}" for n in range(1, 6)) in card and "/optimizer reset rounds" in card
assert run("rounds") == run("ROUNDS") == run("show 2") == card
assert "Choose: /optimizer enabled on · /optimizer enabled off" in run("enabled")
assert 'Change it: /optimizer model.base_url <new value> (or "" for empty)' in run("model.base_url")

# Every exposed setting can be changed from the chat, by number, and lands in config.yaml. Each save
# is seen by the loader the hook calls on every message, with no cache reset (no restart).
typed = {"enabled": ("off", False), "rounds": ("3", 3), "model.provider": ("openrouter", "openrouter"),
         "model.model": ("llama3:8b", "llama3:8b"), "model.base_url": ('""', ""),
         "model.api_key_env": ("PO_TEST_KEY_NAME", "PO_TEST_KEY_NAME"), "model.temperature": ("0.25", 0.25),
         "model.max_tokens": ("2000", 2000), "model.timeout": ("45", 45),
         "judge_model.provider": ("anthropic", "anthropic"), "judge_model.model": ("off", "off"),
         "judge_model.base_url": ("http://10.0.0.5:8000/v1", "http://10.0.0.5:8000/v1"),
         "judge_model.api_key_env": ("JUDGE_KEY", "JUDGE_KEY"), "judge_model.temperature": ("1.5", 1.5),
         "judge_model.max_tokens": ("300", 300), "judge_model.timeout": ("2.5", 2.5), "min_chars": ("20", 20),
         "max_chars": ("5000", 5000), "context_messages": ("6", 6), "show_in_cli": ("no", False)}
assert list(typed) == command.MENU
for n, (key, (text, value)) in enumerate(typed.items(), 1):
    old = settings.get(key, path=CFG)
    reply = run(f"{n} {text}")
    assert reply.startswith(f"Saved {key}: {settings.fmt(old)} → {settings.fmt(value)}. Applies from your next "
                            "message, no restart needed."), reply
    assert saved(key) == value and settings.get(key, path=CFG) == value, key
assert settings.get_all(path=CFG) == {**{k: v for k, (_, v) in typed.items()}, **{
    k: settings.get(k, path=CFG) for k in settings.SETTINGS if k.startswith("prompts.")}}
assert run("set max_chars 4000").startswith("Saved max_chars: 5000 → 4000.")  # `set` spelled out
assert run("max_chars 4000") == "max_chars is already 4000. Nothing changed."

# Invalid input: nothing written, the reply says what's allowed and how to retry.
fresh()
before = CFG.read_bytes()
for args, expect in [("rounds 9", "Not saved: rounds must be a whole number from 1 to 5.\n  Choose: /optimizer rounds 1"),
                     ("2 three", "whole number"), ("enabled maybe", "true or false"),
                     ("model.temperature hot", "a number from 0 to 2"), ("model.model two words", "without spaces"),
                     ("model.base_url localhost:11434", "http(s) URL"),
                     ("model.base_url http://me:hunter2@10.0.0.5/v1", "api_key_env"),
                     ("min_chars 7000", "min_chars (7000) must be lower than max_chars (6000)"),
                     ("modle.model x", 'Unknown setting "modle.model". Did you mean model.model? Type /optimizer'),
                     ("hlep", "Did you mean help?"), ("21 x", "the numbers go from 1 to 20"), ("0", "from 1 to 20"),
                     ("set rounds", "/optimizer set needs a key and a value, e.g. /optimizer set rounds 3."),
                     ("prompts.default Be brief.", "multi-line text: edit it in the settings file"),
                     ("reset nope", 'Unknown setting "nope"'), ("reset help", 'Unknown setting "help". Type')]:
    reply = run(args)
    assert expect in reply and not reply.startswith("Saved"), (args, reply)
    assert CFG.read_bytes() == before, args
assert "hunter2" not in run("model.base_url http://me:hunter2@10.0.0.5/v1")  # a pasted credential is never echoed

# Shortcuts and the notes shown after a valid but probably unintended change.
reply = run("off")
assert reply.startswith("Saved enabled: true → false.") and "Turn it back on: /optimizer on" in reply
assert run().startswith("Prompt optimizer: off (turn it on: /optimizer on)")
assert run("on").startswith("Saved enabled: false → true.")
assert "model.provider is ignored while a base_url is set" in run("model.provider openrouter")
assert "model.provider is ignored" in run("model.base_url http://127.0.0.1:8080/v1")  # either order
assert 'To use the provider: /optimizer judge_model.base_url ""' in run("judge_model.provider anthropic")
assert "ignored" not in run('model.base_url ""')  # the fix the note suggests
assert "PO_UNSET_NAME is not set" in run("model.api_key_env PO_UNSET_NAME")  # only its presence is checked
assert "then run /reload or restart Hermes" in run("model.api_key_env PO_UNSET_OTHER")
os.environ["PO_SET_NAME"] = "x"
assert "not set" not in run("model.api_key_env PO_SET_NAME")
assert "hermes config set plugins.hook_callback_timeout 50" in run("rounds 3")  # 20s + 20s judge > 30s budget
assert "hook_callback_timeout" not in run("rounds 1")

# Reset: one key, a preview of everything, then `reset all` (the prompts are never touched).
fresh()
run("rounds 4")
run("judge_model.model gpt-4o-mini")
run("context_messages 0")
assert run("reset rounds").startswith("Reset rounds: 4 → 1. Applies from your next message")
assert run("reset 2") == "rounds already has its default value."
preview = run("reset")
assert preview.splitlines() == ["/optimizer reset all would change:", '  judge_model.model: "gpt-4o-mini" → unset',
                                "  context_messages: 0 → 4", preview.splitlines()[-1]], preview
assert "Type /optimizer reset all to confirm" in preview and saved("context_messages") == 0  # nothing written
assert run("reset ALL").startswith("Reset 2 setting(s) to their defaults:\n")
assert CFG.read_text(encoding="utf-8") == TEMPLATE  # judge_model back to {}, byte for byte
assert run("reset") == run("reset all") == "All settings already have their default values."

assert "/optimizer reset all" in run("help") and str(CFG) in run("help")

# The handler never raises (Hermes' desktop dispatch would report the command as unknown instead).
fresh("rounds: [1\n")
assert "config.yaml line" in run() and "Fix it by hand" in run("rounds 3") and "Fix it by hand" in run("reset all")
assert CFG.read_text(encoding="utf-8") == "rounds: [1\n"
real_get_all, settings.get_all = settings.get_all, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
command.logger.disabled = True  # the traceback goes to Hermes' log; keep this run's output clean
assert run() == "/optimizer failed: boom"
settings.get_all, command.logger.disabled = real_get_all, False

# No config.yaml: the menu says so; the first change recreates it from the template.
CFG.unlink()
config._cache.clear()
assert "idle, the settings file doesn't exist" in run() and "(uses" not in run()
assert run("rounds 2").startswith("Saved rounds: unset → 2.") and saved("rounds") == 2

# Messaging gateway (Telegram, Discord …): refused, since Hermes doesn't tell plugin commands who is asking.
real_run = sys.modules.get("gateway.run")
sys.modules["gateway.run"] = types.SimpleNamespace(_gateway_runner_ref=lambda: object())
before = CFG.read_bytes()
assert run("rounds 5") == run() == command.REFUSAL and CFG.read_bytes() == before
if real_run is None:
    del sys.modules["gateway.run"]
else:
    sys.modules["gateway.run"] = real_run

print("ok: all command self-checks passed", file=sys.stderr)
shutil.rmtree(TMP, ignore_errors=True)
