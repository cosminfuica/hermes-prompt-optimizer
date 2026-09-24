"""Self-check for optimizer/settings.py, the config read/update/save layer (no network, no real config).

Run from anywhere with Hermes' Python:  ~/.hermes/hermes-agent/venv/bin/python tests/test_settings.py
"""

import difflib
import importlib
import importlib.util
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="po-settings-"))
os.environ["HERMES_HOME"] = str(TMP / "home")
os.environ.pop("HERMES_SESSION_SOURCE", None)  # a kanban/cron parent would make the hook skip

# Load the plugin the way Hermes does: a package rooted at the repo, so its relative imports resolve.
spec = importlib.util.spec_from_file_location("po", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules["po"] = plugin
spec.loader.exec_module(plugin)
config, hook, settings = (importlib.import_module(f"po.optimizer.{name}") for name in ("config", "hook", "settings"))
import utils  # noqa: E402  Hermes' utils: settings saves through its atomic_write_text

ConfigError = settings.ConfigError
TEMPLATE = (ROOT / "config.yaml.example").read_text(encoding="utf-8")
CFG = TMP / "config.yaml"  # a plugin folder of its own: config.yaml next to config.yaml.example
shutil.copy(ROOT / "config.yaml.example", TMP / "config.yaml.example")


def fresh(text=TEMPLATE):
    CFG.write_text(text, encoding="utf-8")
    config._cache.clear()


def text():
    return CFG.read_text(encoding="utf-8")


def diff(expected=TEMPLATE):
    """(removed, added) lines of config.yaml against `expected`."""
    lines = list(difflib.unified_diff(expected.splitlines(), text().splitlines(), lineterm="", n=0))[2:]
    return [x[1:] for x in lines if x[0] == "-"], [x[1:] for x in lines if x[0] == "+"]


def fails(call, *expect):
    """call() raises ConfigError with every `expect` in its message; returns the message."""
    try:
        call()
    except ConfigError as exc:
        assert all(e in str(exc) for e in expect), str(exc)
        return str(exc)
    raise AssertionError(f"no ConfigError, expected one containing {expect}")


def rejected(key, raw, *expect):
    """set() refuses the value with a message containing `expect`, and config.yaml is untouched."""
    before = CFG.read_bytes()
    message = fails(lambda: settings.set(key, raw, path=CFG), *expect)
    assert CFG.read_bytes() == before, (key, raw)
    return message


# The schema covers every setting in config.yaml.example (a new template key needs an entry).
def leaves(data, prefix=""):
    for key, value in data.items():
        if isinstance(value, dict) and value and f"{prefix}{key}" != "prompts.per_model":
            yield from leaves(value, f"{prefix}{key}.")
        else:
            yield f"{prefix}{key}"


assert set(leaves(yaml.safe_load(TEMPLATE))) - {"judge_model"} <= set(settings.SETTINGS)
assert {f"judge_model.{k}" for k in yaml.safe_load(TEMPLATE)["model"]} <= set(settings.SETTINGS)
assert all(s.lo is not None and s.hi is not None for s in settings.SETTINGS.values() if s.kind in ("int", "number"))

# Read: the values the running plugin sees; a fresh install is all defaults.
fresh()
values = settings.get_all(path=CFG)
assert values["enabled"] is True and values["rounds"] == 1 and values["model.model"] == "qwen2.5:7b"
assert values["judge_model.model"] is None and settings.get("model.timeout", path=CFG) == 20
assert settings.defaults(path=CFG) == values

# Type coercion: chat text -> the setting's type, read back through the plugin's own loader.
assert settings.set("rounds", " 3 ", path=CFG) == (1, 3)
assert settings.set("enabled", "OFF", path=CFG) == (True, False)
assert settings.set("show_in_cli", "no", path=CFG) == (True, False)
assert settings.set("model.temperature", ".7", path=CFG) == (0.5, 0.7)
assert settings.set("model.temperature", "0.123456", path=CFG) == (0.7, 0.12)  # 2 decimals: never 1e-05
assert settings.set("model.timeout", "45", path=CFG) == (20, 45)
assert settings.set("model.timeout", "2.5", path=CFG) == (45, 2.5)
assert settings.set("model.model", "llama3:70b", path=CFG)[1] == "llama3:70b"
assert settings.set("model.provider", '"off"', path=CFG)[1] == "off"  # surrounding quotes dropped
assert settings.set("model.base_url", "", path=CFG)[1] == ""
assert settings.set("model.api_key_env", "OPENROUTER_API_KEY", path=CFG)[1] == "OPENROUTER_API_KEY"
assert settings.set("judge_model.model", "gpt-4o-mini", path=CFG) == (None, "gpt-4o-mini")
judge = "Pick the best candidate.\n  Reply with its number only:  1, 2 or 3.\n"
assert settings.set("prompts.judge", judge, path=CFG)[1] == judge.strip()
loaded = config.load_config(CFG)
assert loaded["rounds"] == 3 and loaded["enabled"] is False and loaded["show_in_cli"] is False
assert loaded["model"] == {"provider": "off", "model": "llama3:70b", "base_url": "", "api_key_env": "OPENROUTER_API_KEY",
                           "temperature": 0.12, "max_tokens": 1500, "timeout": 2.5}  # "off" stays a string
assert loaded["judge_model"] == {"model": "gpt-4o-mini"} and loaded["prompts"]["judge"] == judge.strip()
assert 'provider: "off"' in text() and "  judge: |" in text()  # quoted only where needed; prompts stay blocks
inode = CFG.stat().st_ino
assert settings.set("rounds", "3", path=CFG) == (3, 3) and CFG.stat().st_ino == inode  # same value: no write
# Values that were plain: quoted where PyYAML would read another type, multi-line text as a `|` block.
fresh(TEMPLATE.split("  judge: |")[0] + "  judge: Reply with a number.\n")
settings.set("model.model", "3:4", path=CFG)
settings.set("prompts.judge", "Pick the best one.\nReply with its number.", path=CFG)
assert config.load_config(CFG)["model"]["model"] == "3:4"  # unquoted, PyYAML would read 184
assert text().endswith("  judge: |-\n    Pick the best one.\n    Reply with its number.\n")

# Validation failures: a clear message, and the file is never touched.
fresh()
rejected("rounds", "9", "rounds must be a whole number from 1 to 5")
for bad in ("0", "2.5", "1e3", "three", "", "0x2"):
    rejected("rounds", bad, "whole number")
rejected("enabled", "maybe", "true or false")
rejected("model.temperature", "3", "from 0 to 2")
rejected("model.temperature", "nan", "a number")
rejected("model.max_tokens", "10", "from 64 to 32768")
rejected("context_messages", "21", "from 0 to 20")
rejected("model.model", "two words", "without spaces")
rejected("model.model", "two\nlines", "without spaces")
rejected("model.base_url", "ftp://host/v1", "http(s) URL")
rejected("model.base_url", "localhost:11434", "http(s) URL")
assert "hunter2" not in rejected("model.base_url", "http://me:hunter2@10.0.0.5:8000/v1", "api_key_env")
pasted = "sk-or-v1-" + "0123456789abcdef"  # built in two parts: Hermes' install scan flags key-like literals
assert pasted not in rejected("model.api_key_env", pasted, "Hermes .env")  # a pasted key is never echoed
rejected("prompts.judge", "  \n ", "non-empty")
rejected("prompts.judge", "a\x00b", "control characters")
rejected("model.model", "a\tb", "without spaces")
assert settings.set("prompts.judge", "Pick one\u00a0now 👩\u200d💻", path=CFG)[1] == "Pick one\u00a0now 👩\u200d💻"
settings.reset("prompts.judge", path=CFG)
rejected("prompts.per_model", "*x*: y", "edited in config.yaml")
rejected("min_chars", "7000", "min_chars (7000) must be lower than max_chars (6000)")
rejected("max_chars", "12", "must be lower than")  # equal isn't allowed either
assert "Did you mean 'rounds'?" in rejected("round", "2")
for call in (settings.get, settings.describe, settings.reset):
    fails(lambda: call("nope", path=CFG), "Unknown setting 'nope'")
# Safety net: a value that wouldn't read back as written is refused (simulated: quoting rule removed).
real_node, settings._node = settings._node, lambda value: value
rejected("model.model", "off", "reads back unchanged")
settings._node = real_node

# A config.yaml broken by hand is explained and never overwritten, by set or reset.
fresh(TEMPLATE + "rounds: 2\n")
assert "with value" not in rejected("rounds", "3", "config.yaml line", "duplicate key", "Fix it by hand")
fresh("rounds: [1\n")
fails(lambda: settings.get_all(path=CFG), "config.yaml line", "Fix it by hand")  # not "everything unset"
rejected("rounds", "3", "config.yaml line")
fails(lambda: settings.reset(path=CFG), "config.yaml line")
assert text() == "rounds: [1\n"

# Round trip: only the changed value moves; comments, prompts, order and quoting stay byte for byte.
fresh()
settings.set("rounds", "3", path=CFG)
assert diff() == (["rounds: 1"], ["rounds: 3"]), diff()
fresh()
settings.set("model.model", "llama3.1:8b-instruct", path=CFG)
settings.set("model.timeout", "25", path=CFG)
removed, added = diff()
assert [x.split("#")[0].strip() for x in added] == ["model: llama3.1:8b-instruct", "timeout: 25"], added
assert [x.split("#", 1)[1] for x in added] == [x.split("#", 1)[1] for x in removed]  # line comments kept
custom = TEMPLATE.replace("rounds: 1\n", "rounds: 1   # my note\n") + "\n# my own notes\nextra: [a, b]   # kept\n"
fresh(custom)
settings.set("rounds", "2", path=CFG)
assert text() == custom.replace("rounds: 1   #", "rounds: 2   #")  # the user's own content too

# Reset one key: the template's value and formatting; keys the template lacks are removed.
fresh()
settings.set("rounds", "4", path=CFG)
settings.set("judge_model.model", "gpt-4o-mini", path=CFG)
settings.set("prompts.default", "Rewrite the message.", path=CFG)
assert settings.reset("rounds", path=CFG) == {"rounds": (4, 1)}
assert settings.reset("judge_model.model", path=CFG) == {"judge_model.model": ("gpt-4o-mini", None)}
assert settings.reset("prompts.default", path=CFG)["prompts.default"][1].startswith("You are a prompt optimizer")
assert text() == TEMPLATE, diff()
assert settings.reset("rounds", path=CFG) == {}
fresh(TEMPLATE.replace("model: qwen2.5:7b", 'model: "llama3:8"'))  # same width, so the # comment stays put
settings.reset("model.model", path=CFG)
assert text() == TEMPLATE, diff()  # the template's plain style, not the old quotes
nested = TEMPLATE.replace("judge_model: {}\n", "judge_model:\n  # cheaper judge\n  model: gpt-4o-mini   # j\n  timeout: 9\n")
fresh(nested)
settings.reset("judge_model.timeout", path=CFG)
assert text() == nested.replace("  timeout: 9\n", ""), diff()
settings.reset("judge_model.model", path=CFG)
assert text() == TEMPLATE, diff()  # back to `judge_model: {}`, the blank line after it kept
fresh(TEMPLATE.replace('"*gpt*, *codex*, openai/*"', '"*gpt*"'))
assert list(settings.reset("prompts.per_model", path=CFG)) == ["prompts.per_model"]
assert text() == TEMPLATE, diff()

# Reset everything: all settings in one save, except the prompts (your own text, reset by name only).
fresh(nested)
settings.set("enabled", "off", path=CFG)
settings.set("min_chars", "20", path=CFG)
settings.set("prompts.judge", "Reply with a number.", path=CFG)
changed = settings.reset(path=CFG)
assert changed == {"enabled": (False, True), "min_chars": (20, 12), "judge_model.model": ("gpt-4o-mini", None),
                   "judge_model.timeout": (9, None)}, changed
assert text() == TEMPLATE.split("  judge: |")[0] + "  judge: |-\n    Reply with a number.\n", diff()
settings.reset("prompts.judge", path=CFG)
inode = CFG.stat().st_ino
assert text() == TEMPLATE and settings.reset(path=CFG) == {} and CFG.stat().st_ino == inode

# describe() and the display form (URL credentials never shown).
desc = settings.describe("rounds", path=CFG)
assert desc.startswith("rounds = 1\n") and "from 1 to 5" in desc and desc.endswith("Default: 1."), desc
assert settings.describe("judge_model.model", path=CFG).endswith("Default: unset.")
assert settings.fmt("http://user:hunter2@10.0.0.5:8000/v1?key=abc") == '"http://***@10.0.0.5:8000/v1?***"'
assert settings.fmt("x" * 80).endswith('…"') and settings.fmt(None) == "unset" and settings.fmt(False) == "false"

# No config.yaml (deleted by hand): nothing set, the plugin idles; the first save recreates it.
CFG.unlink()
config._cache.clear()
assert settings.get("rounds", path=CFG) is None
settings.set("rounds", "2", path=CFG)
assert diff() == (["rounds: 1"], ["rounds: 2"])

# Atomic save: a new file is renamed over config.yaml (never rewritten in place), permissions kept;
# a failure at the last step leaves the old file intact and no temp file behind.
fresh()
os.chmod(CFG, 0o640)
inode = CFG.stat().st_ino
settings.set("rounds", "2", path=CFG)
assert CFG.stat().st_ino != inode and stat.S_IMODE(CFG.stat().st_mode) == 0o640


def disk_full(tmp, target):
    raise OSError(28, "No space left on device")


utils.atomic_replace, real_replace = disk_full, utils.atomic_replace
rejected("rounds", "3", "Could not save", "No space left on device")
utils.atomic_replace = real_replace
assert not list(TMP.glob(".tmp_*")), list(TMP.iterdir())

# Live: the running hook re-reads config.yaml on each message, so a save applies to the next one.
fresh()
seen = []
hook.load_config = lambda *_: config.load_config(CFG)
hook.optimize = lambda message, **kw: seen.append(kw["cfg"]["rounds"]) or {
    "optimized": "Refactor the parser module.", "candidates": ["x"], "picked": 0, "rounds": 1, "model": "fake"}
turn = dict(session_id="s1", user_message="refactor the parser module please", conversation_history=[],
            model="m", platform="desktop")
assert hook.on_pre_llm_call(**turn) and seen == [1]
mtime = CFG.stat().st_mtime_ns
settings.set("rounds", "3", path=CFG)
os.utime(CFG, ns=(mtime, mtime))  # same mtime as the cached copy (coarse clock): the save still wins
assert hook.on_pre_llm_call(**turn) and seen == [1, 3], seen
settings.set("enabled", "off", path=CFG)
assert hook.on_pre_llm_call(**turn) is None and seen == [1, 3]  # switched off, no restart

print("ok: all settings self-checks passed", file=sys.stderr)
shutil.rmtree(TMP, ignore_errors=True)
