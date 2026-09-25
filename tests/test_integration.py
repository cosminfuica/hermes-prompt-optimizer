"""Integration check: /optimizer driven through Hermes itself, end to end (no network, no real config).

The plugin is laid out in a throwaway HERMES_HOME the way `hermes plugins install … --enable` leaves
it, and loaded by Hermes' own plugin loader. Commands go through `command.dispatch`, the RPC method
the TUI and the desktop app call when you type a slash command. After each change a chat message goes
through Hermes' pre_llm_call dispatch with only the model client faked: the change applies to the very
next message, without a restart.

Run from anywhere with Hermes' Python:  ~/.hermes/hermes-agent/venv/bin/python tests/test_integration.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(tempfile.mkdtemp(prefix="po-integration-"))
os.environ["HERMES_HOME"] = str(HOME)
for name in ("HERMES_SESSION_SOURCE", "HERMES_SESSION_ID"):
    os.environ.pop(name, None)  # a kanban or cron parent would make the hook skip every message

# The installed layout: the plugin folder, config.yaml created from the template, the plugin enabled.
PLUGIN = HOME / "plugins" / "hermes-prompt-optimizer"
shutil.copytree(ROOT, PLUGIN, ignore=shutil.ignore_patterns(".git", "__pycache__", "config.yaml"))
CFG = PLUGIN / "config.yaml"
shutil.copy(PLUGIN / "config.yaml.example", CFG)
INSTALLED = CFG.read_bytes()
(HOME / "config.yaml").write_text("plugins:\n  enabled:\n    - hermes-prompt-optimizer\n", encoding="utf-8")

import hermes_cli  # noqa: E402

# What `hermes` does at startup (hermes_cli/main.py): put its source root on sys.path. Hermes v0.20.x
# ships modules there that its package metadata doesn't list, e.g. registration_lifecycle.
sys.path.insert(0, str(Path(hermes_cli.__file__).resolve().parent.parent))

import agent.auxiliary_client as aux  # noqa: E402  (Hermes modules: imported once HERMES_HOME is set)
import tui_gateway.methods_tools  # noqa: E402,F401  registers command.dispatch
from hermes_cli import plugins  # noqa: E402
from tui_gateway import server  # noqa: E402

plugins.discover_plugins(force=True)
commands = plugins.get_plugin_commands()
assert {"optimizer", "optimized"} <= set(commands), sorted(commands)
assert commands["optimizer"]["description"] == "View and change prompt-optimizer settings"


def run(args=""):
    """Type `/optimizer <args>` in the TUI or the desktop app and press Enter."""
    reply = server._methods["command.dispatch"]("it", {"name": "optimizer", "arg": args})
    assert reply.get("result", {}).get("type") == "plugin", reply  # an exception would read "unknown command"
    return reply["result"]["output"]


def saved():
    return yaml.safe_load(CFG.read_text(encoding="utf-8"))


calls = []  # every model call of the last message, as Hermes' client received it


def fake_call_llm(**kw):
    """Hermes' model client, the only fake: records the call and answers like a model would."""
    calls.append(kw)
    kw["route_info"]["model"] = kw["model"]  # answered by the model that was asked (no fallback)
    judge = "<candidate" in kw["messages"][-1]["content"]
    choice = SimpleNamespace(message=SimpleNamespace(content="2" if judge else "Refactor the parser module."),
                             finish_reason="stop")
    return SimpleNamespace(model=kw["model"], choices=[choice])


aux.call_llm = fake_call_llm


def send(message="refactor the parser module but keep the public API"):
    """Send a chat message: Hermes fires pre_llm_call. Returns the model calls it made
    [(judge or rewrite, model, temperature)] and whether the optimized prompt was added."""
    calls.clear()
    results = plugins.invoke_hook("pre_llm_call", session_id="it", user_message=message,
                                  conversation_history=[], model="main-model", platform="desktop")
    added = any(isinstance(r, dict) and "<optimized_prompt>" in str(r.get("context")) for r in results)
    kinds = ["judge" if "<candidate" in c["messages"][-1]["content"] else "rewrite" for c in calls]
    return [(kind, c["model"], c["temperature"]) for kind, c in zip(kinds, calls)], added


# Fresh install: the numbered menu shows the template's values, and a message uses the template's model.
menu = run()
assert menu.startswith(f"Prompt optimizer: on\nSettings file: {CFG}\n"), menu
assert "  2. rounds = 1 — " in menu and '  4. model.model = "qwen2.5:7b" — ' in menu and " 20. show_in_cli = true — " in menu
assert send() == ([("rewrite", "qwen2.5:7b", 0.5)], True)

# Selecting a setting: details and ready-to-type choices. The CLI's handler lookup gives the same reply.
card = run("2")
assert card.startswith("2. rounds = 1\n") and "Default: 1." in card and "/optimizer rounds 5" in card, card
assert run("show rounds") == card == plugins.get_plugin_command_handler("optimizer")("rounds")

# One setting of each kind, changed from the chat: saved to config.yaml, used by the very next message.
assert run("model.model llama3.1:8b").startswith(  # text
    'Saved model.model: "qwen2.5:7b" → "llama3.1:8b". Applies from your next message, no restart needed.')
assert saved()["model"]["model"] == "llama3.1:8b" and send() == ([("rewrite", "llama3.1:8b", 0.5)], True)
assert run("7 0.2").startswith("Saved model.temperature: 0.5 → 0.2.")  # a number, picked by its menu number
assert saved()["model"]["temperature"] == 0.2 and send() == ([("rewrite", "llama3.1:8b", 0.2)], True)
assert run("set rounds 3").startswith("Saved rounds: 1 → 3.")  # one of a fixed set of choices (1 to 5)
assert saved()["rounds"] == 3
assert send() == ([("rewrite", "llama3.1:8b", 0.2)] * 3 + [("judge", "llama3.1:8b", 0.2)], True)
assert run("judge_model.model gpt-4o-mini").startswith('Saved judge_model.model: unset → "gpt-4o-mini".')
assert send()[0][-1] == ("judge", "gpt-4o-mini", 0.2)  # only the judge moves; its unset keys follow model.*
assert run("model.base_url http://10.0.0.5:8000/v1").startswith("Saved model.base_url: ")  # an endpoint
assert send()[1] and {(c["provider"], c["base_url"]) for c in calls} == {(None, "http://10.0.0.5:8000/v1")}
assert run('model.base_url ""').startswith('Saved model.base_url: "http://10.0.0.5:8000/v1" → "".')  # no endpoint:
reply = run("model.provider openrouter")  # use a provider Hermes already has a key for
assert reply.startswith('Saved model.provider: "" → "openrouter".') and "ignored" not in reply, reply
assert send()[1] and {(c["provider"], c["base_url"]) for c in calls} == {("openrouter", None)}  # judge inherits it
assert run("off").startswith("Saved enabled: true → false.")  # on/off
assert saved()["enabled"] is False and send() == ([], False)  # sent as typed, no model call
assert run("enabled yes").startswith("Saved enabled: false → true.") and send()[1]

# Invalid input: explained, nothing written, and the next message still uses the saved settings.
before = CFG.read_bytes()
for args, expect in [("rounds 9", "Not saved: rounds must be a whole number from 1 to 5."),
                     ("7 hot", "Not saved: model.temperature must be a number from 0 to 2."),
                     ("enabled maybe", "Not saved: enabled must be true or false."),
                     ("model.base_url localhost:11434", "must be an http(s) URL"),
                     ("modle.model x", 'Unknown setting "modle.model". Did you mean model.model?'),
                     ("prompts.default Be brief.", "multi-line text: edit it in the settings file")]:
    reply = run(args)
    assert expect in reply, (args, reply)
assert CFG.read_bytes() == before and send()[0][0] == ("rewrite", "llama3.1:8b", 0.2)

reply = run("help")
assert f"Changes are saved to {CFG}" in reply and "Editing that file by hand works too" in reply, reply

# Editing config.yaml by hand still works: the menu and the next message both pick the edit up.
CFG.write_text(CFG.read_text(encoding="utf-8").replace("rounds: 3", "rounds: 2"), encoding="utf-8")
later = CFG.stat().st_mtime_ns + 10**9  # a person saves seconds after the last change, not in the same clock tick
os.utime(CFG, ns=(later, later))
assert "  2. rounds = 2 — " in run() and [kind for kind, *_ in send()[0]] == ["rewrite", "rewrite", "judge"]

# Reset: one setting, a preview of the rest (nothing written), then everything back to the template.
assert run("reset 7").startswith("Reset model.temperature: 0.2 → 0.5. Applies from your next message")
preview = run("reset")
assert preview.startswith("/optimizer reset all would change:\n") and saved()["rounds"] == 2, preview
assert run("reset all").startswith("Reset ") and CFG.read_bytes() == INSTALLED  # byte for byte: comments, prompts
assert send() == ([("rewrite", "qwen2.5:7b", 0.5)], True)

print("ok: all integration checks passed", file=sys.stderr)
shutil.rmtree(HOME, ignore_errors=True)
