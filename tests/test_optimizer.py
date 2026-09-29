"""Self-check for hermes-prompt-optimizer (no network, no real model calls).

Run from anywhere with Hermes' Python:  ~/.hermes/hermes-agent/venv/bin/python tests/test_optimizer.py
"""

import importlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="po-test-")
os.environ.pop("HERMES_SESSION_SOURCE", None)  # a kanban/cron parent would make the hook skip

# Load the plugin the way Hermes does: a package rooted at the repo, so its relative imports resolve.
spec = importlib.util.spec_from_file_location("po", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules["po"] = plugin
spec.loader.exec_module(plugin)
config, engine, history, hook = (importlib.import_module(f"po.optimizer.{name}")
                                 for name in ("config", "engine", "history", "hook"))

CFG = config.load_config(ROOT / "config.yaml.example")
MSG = "pls fix the bug in utils.py thx"


class FakeLLM:
    """Candidate calls return scripted texts; the judge call returns `verdict`."""

    def __init__(self, texts, verdict="1", fail=()):
        self.texts, self.verdict, self.fail, self.calls = list(texts), verdict, set(fail), []

    def __call__(self, model_cfg, messages, timeout):
        self.calls.append(messages)
        if "<candidate" in messages[-1]["content"]:
            return self.verdict, "judge"
        i = len([c for c in self.calls if "<candidate" not in c[-1]["content"]]) - 1
        if i in self.fail:
            raise RuntimeError(f"boom {i}")
        return self.texts[i], "fake-small"


def run(rounds, llm, msg=MSG):
    return engine.optimize(msg, target_model="claude-opus-5-5", history=[], cfg={**CFG, "rounds": rounds}, llm=llm)


# rounds=1 → one call, no judge; the system prompt is the claude-tailored one.
llm = FakeLLM(["Fix the bug in utils.py."])
out = run(1, llm)
assert out["optimized"] == "Fix the bug in utils.py." and out["picked"] == 0 and len(llm.calls) == 1
assert "Claude model" in llm.calls[0][0]["content"] and "prompt optimizer" in llm.calls[0][0]["content"]

# rounds=3 → 3 candidates + 1 judge call that sees all of them; its pick wins.
llm = FakeLLM(["A", "B", "C"], verdict="Candidate 2 is best")
out = run(3, llm)
assert out["optimized"] == "B" and out["picked"] == 1 and len(llm.calls) == 4
judge_input = llm.calls[-1][-1]["content"]
assert all(f'<candidate id="{i}">' in judge_input for i in (1, 2, 3)) and "<original>" in judge_input

# Unparseable / out-of-range verdicts fall back to candidate 1; a failed candidate is skipped.
assert run(2, FakeLLM(["A", "B"], verdict="dunno"))["optimized"] == "A"
assert run(2, FakeLLM(["A", "B"], verdict="7"))["optimized"] == "A"
assert run(3, FakeLLM(["A", "B", "C"], verdict="1", fail={0}))["candidates"] == ["B", "C"]
try:
    run(2, FakeLLM(["A", "B"], fail={0, 1}))
    raise AssertionError("all candidates failed but no error")
except RuntimeError:
    pass
assert run(99, FakeLLM(["x"] * 5))["rounds"] == engine.MAX_ROUNDS  # capped

# Per-model prompts: {base} + {target_model} substitution, fallback to default.
p = CFG["prompts"]
assert "OpenAI GPT" in config.pick_prompt(p, "gpt-6-astra") and "gpt-6-astra" in config.pick_prompt(p, "gpt-6-astra")
assert "Gemini" in config.pick_prompt(p, "google/gemini-3-pro")
assert config.pick_prompt(p, "llama-4").startswith("You are a prompt optimizer") and "{" not in config.pick_prompt(p, "llama-4")
assert all("{base}" in text for text in p["per_model"].values())

# Output cleanup.
assert engine.clean("<think>hmm</think>\n```text\nDo X.\n```") == "Do X."
assert engine.clean("<optimized_prompt>Do Y.</optimized_prompt>") == "Do Y."
two_blocks = "```py\na()\n```\nthen\n```py\nb()\n```"
assert engine.clean(two_blocks) == two_blocks  # several code blocks are content, not a wrapper

# Empty per_model body falls back to the default prompt.
assert config.pick_prompt({"default": "D", "per_model": {"*x*": ""}}, "x1") == "D"

# Hand-edited config values are coerced instead of breaking every turn: a true/false or number value that
# is missing, or that /optimizer would refuse, takes its config.yaml.example value; an invalid
# judge_model.* one is dropped, so it follows model.*. Names, URLs and prompts are used as written.
n = config.normalize({"enabled": "false", "rounds": "3", "min_chars": "ten", "prompts": "oops", "model": "x"})
assert n["enabled"] is False and n["rounds"] == 3 and n["min_chars"] == 12 and n["context_messages"] == 4
assert n["prompts"] == {} and n["model"] == {"temperature": 0.5, "max_tokens": 1500, "timeout": 20}, n
assert hook.skip_reason(n, "refactor the parser module")  # disabled, no crash
n = config.normalize({"enabled": None, "show_in_cli": "false", "judge_model": {"timeout": "x", "model": "j"},
                      "model": {"timeout": "20s", "temperature": "hot", "max_tokens": "2000", "model": "m"}})
assert n["enabled"] is True and n["show_in_cli"] is False and n["judge_model"] == {"model": "j"}, n
assert n["model"] == {"timeout": 20, "temperature": 0.5, "max_tokens": 2000, "model": "m"}, n["model"]
assert engine.optimize(MSG, target_model="m", history=[], cfg=n, llm=FakeLLM(["X"]))["optimized"] == "X"

# Context: the last context_messages chat messages with text. Tool calls and their output don't count,
# so a turn that used tools can't push out the message that "fix it" refers to.
rows = [{"role": "user", "content": "the csv export in app/export.py is broken"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]}, {"role": "tool", "content": "x" * 50},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "2"}]}, {"role": "tool", "content": "done"},
        {"role": "assistant", "content": "Found it: dates are written as epoch seconds."}]
request = engine.render_request("fix it", rows, 2)
assert "user: the csv export in app/export.py" in request and "epoch seconds" in request, request
assert "x" * 50 not in request and "done" not in request
assert engine.render_request("fix it", rows, 0).startswith("<message>")

# The judge inherits model.*, except that a judge with an endpoint of its own takes none of model's
# endpoint keys: model's key is for model's host.
seen = []


def endpoint_llm(c, m, t):
    seen.append((c.get("provider"), c.get("base_url"), c.get("api_key_env"), c.get("model")))
    return ("1", "j") if "<candidate" in m[-1]["content"] else ("X", "m")


own = {**CFG, "rounds": 2, "model": {**CFG["model"], "base_url": "http://host-a:1/v1", "api_key_env": "A_KEY"},
       "judge_model": {"base_url": "http://host-b:9000/v1", "model": "j"}}
engine.optimize(MSG, target_model="m", history=[], cfg=own, llm=endpoint_llm)
assert seen[-1] == (None, "http://host-b:9000/v1", None, "j"), seen
engine.optimize(MSG, target_model="m", history=[], cfg={**own, "judge_model": {"model": "j2"}}, llm=endpoint_llm)
assert seen[-1] == ("", "http://host-a:1/v1", "A_KEY", "j2"), seen  # same host, another model: model's key


# Deadline: a hanging candidate is abandoned; the fast one is used without waiting.
def slow_or_fast(model_cfg, messages, timeout):
    if "<candidate" in messages[-1]["content"]:
        time.sleep(5)  # hanging judge → keep candidate 1
        return "2", "m"
    if "Variant 1" in messages[-1]["content"]:
        time.sleep(5)
        return "SLOW", "m"
    return "FAST", "m"


t0 = time.monotonic()
out = engine.optimize(MSG, target_model="m", history=[], cfg={**CFG, "rounds": 2}, llm=slow_or_fast,
                      deadline=time.monotonic() + 4)
assert out["optimized"] == "FAST" and time.monotonic() - t0 < 3.5, (out, time.monotonic() - t0)
t0 = time.monotonic()
out = engine.optimize(MSG, target_model="m", history=[], cfg={**CFG, "rounds": 3}, llm=slow_or_fast,
                      deadline=time.monotonic() + 6)
assert out["candidates"] == ["FAST", "FAST"] and out["picked"] == 0 and time.monotonic() - t0 < 5.5
# Hanging judge (candidates all fast): abandoned at the deadline, candidate 1 kept.
t0 = time.monotonic()
out = engine.optimize(MSG, target_model="m", history=[], cfg={**CFG, "rounds": 2},
                      llm=lambda c, m, t: slow_or_fast(c, m, t) if "<candidate" in m[-1]["content"] else ("F", "m"),
                      deadline=time.monotonic() + 4)
assert out["picked"] == 0 and time.monotonic() - t0 < 4.3, time.monotonic() - t0
# One round, no judge: it waits for the model right up to the deadline the hook gives it (1.5 s before
# Hermes' limit), not 2 s earlier.
t0 = time.monotonic()
try:
    engine.optimize(MSG, target_model="m", history=[], cfg={**CFG, "rounds": 1},
                    llm=lambda c, m, t: time.sleep(5) or ("SLOW", "m"), deadline=time.monotonic() + 1.5)
    raise AssertionError("a model slower than the deadline was waited for")
except RuntimeError as exc:
    assert "time budget" in str(exc) and 1.3 < time.monotonic() - t0 < 1.9, (str(exc), time.monotonic() - t0)
# Abandoned calls run on daemon threads, so they never hold the process open once Hermes exits.
stuck = [t.name for t in threading.enumerate() if t.is_alive() and not t.daemon and t is not threading.main_thread()]
assert not stuck, stuck
# Judge verdict: first in-range number wins ("Candidate 3 of 3" → 3, not an out-of-range lead).
assert run(3, FakeLLM(["A", "B", "C"], verdict="Among 10 options, candidate 3"))["optimized"] == "C"

# The model call, through Hermes' client (faked here; test_integration.py drives the real one).
import agent.auxiliary_client as ac  # noqa: E402


class _Resp:
    def __init__(self, model):
        msg = type("M", (), {"content": "Rewritten."})()
        self.choices, self.model = [type("C", (), {"message": msg, "finish_reason": "stop"})()], model


requests = []  # (model, extra_body) of every request the fake client "sends"


def fake_call_llm(serve_as=None, reject_cap=False):
    """Hermes' order of events: record the route, send the request; on a connection error, record the
    fallback route (your main model) and send the request again, there."""
    def f(**kw):
        kw["route_info"]["provider"], kw["route_info"]["model"] = "custom", serve_as or kw["model"]
        if reject_cap and kw.get("extra_body"):
            raise RuntimeError("Error code: 400 - Unsupported parameter: 'max_tokens' is not supported")
        if serve_as is None and "down" in (kw.get("base_url") or ""):
            try:
                raise ConnectionError("Connection refused")
            except ConnectionError:
                kw["route_info"]["provider"], kw["route_info"]["model"] = "main-agent", "claude-opus-5-5"
                requests.append(("claude-opus-5-5", kw.get("extra_body")))
                return _Resp("claude-opus-5-5")
        requests.append((serve_as or kw["model"], kw.get("extra_body")))
        return _Resp(serve_as or kw["model"])
    return f


# Endpoint down: Hermes' client would retry on your main model; the plugin stops it before that request.
ac.call_llm = fake_call_llm()
try:
    engine.call_model({"model": "small-model", "base_url": "http://down:1/v1"}, [], 5)
    raise AssertionError("fallback to the main model was accepted")
except RuntimeError as exc:
    assert requests == [] and "Connection refused" in str(exc) and "claude-opus-5-5" in str(exc), (requests, exc)
# A route that is another model from the start (e.g. no credentials for the optimizer's provider): same.
ac.call_llm = fake_call_llm(serve_as="claude-opus-5-5")
try:
    engine.call_model({"model": "small-model", "base_url": "http://x:1/v1"}, [], 5)
    raise AssertionError("another model's rewrite was accepted")
except RuntimeError as exc:
    assert requests == [] and "unavailable" in str(exc), (requests, exc)
# max_tokens goes in the request body, where Hermes keeps it for every endpoint (by the name newer OpenAI
# models need); an endpoint that rejects it is asked again without one.
ac.call_llm = fake_call_llm()
reply = engine.call_model({"model": "small-model", "base_url": "http://x:1/v1", "max_tokens": 1500}, [], 5)
assert reply[0] == "Rewritten."
engine.call_model({"model": "openai/gpt-5-mini", "max_tokens": 900}, [], 5)
assert requests == [("small-model", {"max_tokens": 1500}),
                    ("openai/gpt-5-mini", {"max_completion_tokens": 900})], requests
requests.clear()
ac.call_llm = fake_call_llm(reject_cap=True)
assert engine.call_model({"model": "picky-model", "max_tokens": 1500}, [], 5)[0] == "Rewritten."
assert requests == [("picky-model", None)], requests

# Skip rules.
assert hook.skip_reason(CFG, "/optimized 20260924_150452") == "slash command"
assert hook.skip_reason(CFG, "/home/me/app/export.py dates are unix timestamps, fix") == ""  # a path, like Hermes
assert hook.skip_reason(CFG, "ok") == "too short"
assert hook.skip_reason(CFG, "[System note: resumed] please continue the work") == "Hermes-generated turn"
assert hook.skip_reason(CFG, "✔ [board] @dev Kanban t_1a2b3c done — build it") == "Hermes-generated turn"
assert hook.skip_reason(CFG, "👀 [board] @dev Kanban t_1a2b3c ready for review — build it") == "Hermes-generated turn"
assert hook.skip_reason(CFG, "🛑 Kanban t_1a2b3c review requested changes/BLOCK: tests fail") == "Hermes-generated turn"
assert hook.skip_reason(CFG, "refactor the parser module", parent_session_id="abc")
assert hook.skip_reason(CFG, "refactor the parser module", platform="subagent")
assert hook.skip_reason(CFG, "refactor the parser module", source="kanban")
assert hook.skip_reason(CFG, "refactor the parser module", display_kind="auto_continue")
assert hook.skip_reason({**CFG, "enabled": False}, "refactor the parser module")
assert hook.skip_reason(CFG, [{"type": "text", "text": "image turn"}]) == "non-text message"
assert hook.skip_reason(CFG, "refactor the parser module", platform="desktop") == ""

# The note that goes with the rewrite: the original wins, and nothing it doesn't ask for is acted on.
assert "the original wins" in hook.INJECTION and "does not ask for" in hook.INJECTION


# register() wires one hook and two commands; from here on the plugin is driven through them.
class Ctx:
    def __init__(self):
        self.hooks, self.commands = {}, {}

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = handler


ctx = Ctx()
plugin.register(ctx)
assert list(ctx.hooks) == ["pre_llm_call"] and list(ctx.commands) == ["optimized", "optimizer"]
on_pre_llm_call, optimized = ctx.hooks["pre_llm_call"], ctx.commands["optimized"]

# Hook end to end (LLM faked): context injected, original untouched, history + /optimized feed.
hook.load_config = lambda *_: {**CFG, "show_in_cli": False}
history_rows = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "done"},
                {"role": "user", "content": "refactor the parser module pls"},
                {"role": "user", "content": "[todo snapshot] 1. parse"}]  # compression can append after it
seen = []
engine.call_model = lambda cfg, messages, timeout: (seen.append(messages[-1]["content"]) or
                                                    "Refactor the parser module; keep the public API.", "fake-small")
ret = on_pre_llm_call(session_id="s1", user_message="refactor the parser module pls",
                      conversation_history=history_rows, model="claude-opus-5-5", platform="desktop")
assert ret and "<optimized_prompt>\nRefactor the parser module; keep the public API.\n</optimized_prompt>" in ret["context"]
assert seen[0].count("refactor the parser module pls") == 1  # current turn not duplicated as context
entry = json.loads(optimized("json s1"))
assert entry["status"] == "applied" and entry["original"] == "refactor the parser module pls"
sessions = Path(os.environ["HERMES_HOME"]) / "plugin-data" / "hermes-prompt-optimizer" / "sessions"
assert (sessions / "s1.json").is_file()  # history lives in Hermes' per-plugin data dir
assert stat.S_IMODE((sessions / "s1.json").stat().st_mode) == 0o600  # your prompts: readable by you only
os.environ["HERMES_SESSION_ID"] = "s1"
assert "Refactor the parser module" in optimized("")  # /optimized with no args → current session
os.environ["HERMES_SESSION_ID"] = "other"
assert optimized("") == "No optimized prompt for this chat yet."  # …never another session's prompt
del os.environ["HERMES_SESSION_ID"]
assert optimized("") == "No optimized prompt for this chat yet."  # no chat to go by: not the newest of any chat

engine.call_model = lambda cfg, messages, timeout: ("refactor the parser  module pls", "fake-small")
assert on_pre_llm_call(session_id="s1", user_message="refactor the parser module pls",
                       conversation_history=history_rows, model="m", platform="cli") is None
assert json.loads(optimized("json s1"))["status"] == "unchanged"
assert "sent as typed (unchanged)" in optimized("s1")
# A message the optimizer skips is recorded too, so /optimized never passes off an older result as this one's.
assert on_pre_llm_call(session_id="s1", user_message="ok", conversation_history=[], model="m", platform="cli") is None
assert optimized("s1") == "Last message was sent as typed (skipped: too short)."
# …except turns you didn't type (cron, subagents, notices): they leave no trace.
assert on_pre_llm_call(session_id="cron1", user_message="ok", conversation_history=[], model="m",
                       platform="cron") is None
assert optimized("json cron1") == "null"
history.record({"id": "9", "session_id": "r1", "ts": 1.0, "status": "running", "original": "x"})
assert optimized("r1") == "Still optimizing the last message."

engine.call_model = lambda cfg, messages, timeout: (_ for _ in ()).throw(RuntimeError("endpoint down"))
assert on_pre_llm_call(session_id="s2", user_message="refactor the parser module pls",
                       conversation_history=[], model="m", platform="cli") is None
assert json.loads(optimized("json s2"))["error"] == "endpoint down"
assert optimized("json nope") == "null"

# A damaged history file (hand edit, crash) costs only its broken part, never the optimizer.
bad = sessions / "bad1.json"
bad.write_text('{"turns": ["x", 3, {"id": "0", "status": "applied"}]}', encoding="utf-8")
assert [t["id"] for t in history._read_turns(bad)] == ["0"]
bad.write_text('{"turns": ["x"]}', encoding="utf-8")
engine.call_model = lambda cfg, messages, timeout: ("Rewritten.", "fake-small")
assert on_pre_llm_call(session_id="bad1", user_message="refactor the parser module pls",
                       conversation_history=[], model="m", platform="cli")
assert json.loads(optimized("json bad1"))["status"] == "applied"

# A base_url that belongs to a custom provider reuses that entry (and its key); others stay as-is.
import hermes_cli.runtime_provider as rp  # noqa: E402

rp.find_custom_provider_identity = lambda url: "custom:local" if "11434" in url else None
assert engine.resolve_endpoint({"base_url": "http://127.0.0.1:11434/v1"}) == ("custom:local", None, None)
assert engine.resolve_endpoint({"base_url": "http://other:1/v1"}) == (None, "http://other:1/v1", "no-key-required")
os.environ["PO_TEST_KEY"] = "sk-test"
assert engine.resolve_endpoint({"base_url": "http://127.0.0.1:11434/v1", "api_key_env": "PO_TEST_KEY"}) == (
    None, "http://127.0.0.1:11434/v1", "sk-test")
# A base_url replaces the provider: Hermes would send the request, and this key, to the provider's own API.
both = {"provider": "openrouter", "base_url": "http://other:1/v1", "api_key_env": "PO_TEST_KEY"}
assert engine.resolve_endpoint(both) == (None, "http://other:1/v1", "sk-test")
assert engine.resolve_endpoint({"provider": "openrouter", "base_url": ""}) == ("openrouter", None, None)

# In a multiplexed gateway, a key is read only through the turn's profile scope, never another profile's.
from agent import secret_scope  # noqa: E402

secret_scope.set_multiplex_active(True)
try:
    engine._secret("PO_TEST_KEY")
    raise AssertionError("key read outside the profile scope")
except secret_scope.UnscopedSecretError:
    pass
finally:
    secret_scope.set_multiplex_active(False)

# Messaging gateway: /optimized and /optimizer refuse there. Should Hermes rename what that check reads,
# they refuse rather than answer anyone in a group chat.
real_run = sys.modules.get("gateway.run")
sys.modules["gateway.run"] = types.SimpleNamespace(_gateway_runner_ref=lambda: object())
assert hook._in_messaging_gateway() and optimized("s1").startswith("/optimized is only available")
sys.modules["gateway.run"] = types.SimpleNamespace()
assert hook._in_messaging_gateway()
if real_run is None:
    del sys.modules["gateway.run"]
else:
    sys.modules["gateway.run"] = real_run
assert not hook._in_messaging_gateway()

# The time budget: Hermes' plugins.hook_callback_timeout. Hermes before v0.20.6 doesn't apply it, so the
# plugin reads the setting itself.
import hermes_cli  # noqa: E402

# What `hermes` does at startup: put its source root on sys.path (v0.20.x's hermes_cli.plugins needs it).
sys.path.insert(0, str(Path(hermes_cli.__file__).resolve().parent.parent))
import hermes_cli.plugins as hermes_plugins  # noqa: E402

settings_file = Path(os.environ["HERMES_HOME"]) / "config.yaml"
settings_file.write_text("plugins:\n  hook_callback_timeout: 90\n", encoding="utf-8")
assert hook._host_hook_timeout() == 90.0
real_resolve = getattr(hermes_plugins, "_resolve_hook_callback_timeout", None)
if real_resolve:
    del hermes_plugins._resolve_hook_callback_timeout
try:
    assert hook._host_hook_timeout() == 90.0
    settings_file.write_text("plugins: {}\n", encoding="utf-8")
    assert hook._host_hook_timeout() == 30.0
finally:
    if real_resolve:
        hermes_plugins._resolve_hook_callback_timeout = real_resolve
settings_file.unlink()

print("ok: all self-checks passed")
shutil.rmtree(os.environ["HERMES_HOME"], ignore_errors=True)
