"""Self-check for hermes-prompt-optimizer. Run: <hermes venv>/bin/python test_optimizer.py"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="po-test-")
os.environ.pop("HERMES_SESSION_SOURCE", None)  # a kanban/cron parent would make the hook skip
spec = importlib.util.spec_from_file_location("po", HERE / "__init__.py")
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)

CFG = po.load_config(HERE / "config.yaml.example")


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


def run(rounds, llm, msg="pls fix the bug in utils.py thx"):
    return po.optimize(msg, target_model="claude-opus-5-5", history=[], cfg={**CFG, "rounds": rounds}, llm=llm)


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
assert run(99, FakeLLM(["x"] * 5))["rounds"] == po.MAX_ROUNDS  # capped

# Per-model prompts: {base} + {target_model} substitution, fallback to default.
p = CFG["prompts"]
assert "OpenAI GPT" in po.pick_prompt(p, "gpt-6-astra") and "gpt-6-astra" in po.pick_prompt(p, "gpt-6-astra")
assert "Gemini" in po.pick_prompt(p, "google/gemini-3-pro")
assert po.pick_prompt(p, "llama-4").startswith("You are a prompt optimizer") and "{" not in po.pick_prompt(p, "llama-4")
assert all("{base}" in text for text in p["per_model"].values())

# Output cleanup.
assert po.clean("<think>hmm</think>\n```text\nDo X.\n```") == "Do X."
assert po.clean("<optimized_prompt>Do Y.</optimized_prompt>") == "Do Y."
two_blocks = "```py\na()\n```\nthen\n```py\nb()\n```"
assert po.clean(two_blocks) == two_blocks  # several code blocks are content, not a wrapper

# Empty per_model body falls back to the default prompt.
assert po.pick_prompt({"default": "D", "per_model": {"*x*": ""}}, "x1") == "D"

# Hand-edited config values are coerced instead of crashing every turn.
n = po.normalize({"enabled": "false", "rounds": "3", "min_chars": "ten", "prompts": "oops", "model": "x"})
assert n["enabled"] is False and n["rounds"] == 3 and n["min_chars"] == 0
assert n["prompts"] == {} and n["model"] == {}
assert po.skip_reason(n, "refactor the parser module")  # disabled, no crash

# Deadline: a hanging candidate is abandoned; the fast one is used without waiting.
import time  # noqa: E402


def slow_or_fast(model_cfg, messages, timeout):
    if "<candidate" in messages[-1]["content"]:
        time.sleep(5)  # hanging judge → keep candidate 1
        return "2", "m"
    if "Variant 1" in messages[-1]["content"]:
        time.sleep(5)
        return "SLOW", "m"
    return "FAST", "m"


t0 = time.monotonic()
out = po.optimize("pls fix the bug in utils.py thx", target_model="m", history=[],
                  cfg={**CFG, "rounds": 2}, llm=slow_or_fast, deadline=time.monotonic() + 4)
assert out["optimized"] == "FAST" and time.monotonic() - t0 < 3.5, (out, time.monotonic() - t0)
t0 = time.monotonic()
out = po.optimize("pls fix the bug in utils.py thx", target_model="m", history=[],
                  cfg={**CFG, "rounds": 3}, llm=slow_or_fast, deadline=time.monotonic() + 6)
assert out["candidates"] == ["FAST", "FAST"] and out["picked"] == 0 and time.monotonic() - t0 < 5.5
# Hanging judge (candidates all fast): abandoned at the deadline, candidate 1 kept.
t0 = time.monotonic()
out = po.optimize("pls fix the bug in utils.py thx", target_model="m", history=[], cfg={**CFG, "rounds": 2},
                  llm=lambda c, m, t: slow_or_fast(c, m, t) if "<candidate" in m[-1]["content"] else ("F", "m"),
                  deadline=time.monotonic() + 4)
assert out["picked"] == 0 and time.monotonic() - t0 < 3.5, time.monotonic() - t0
# Judge verdict: first in-range number wins ("Candidate 3 of 3" → 3, not an out-of-range lead).
assert run(3, FakeLLM(["A", "B", "C"], verdict="Among 10 options, candidate 3"))["optimized"] == "C"

# Fallback detection: Hermes answering with a different model is an error, not a rewrite.
import agent.auxiliary_client as ac  # noqa: E402


class _Resp:
    def __init__(self, model):
        msg = type("M", (), {"content": "Rewritten."})()
        self.choices, self.model = [type("C", (), {"message": msg, "finish_reason": "stop"})()], model


def fake_call_llm(route_model):
    def f(**kw):
        kw["route_info"]["model"] = route_model
        return _Resp(route_model)
    return f


ac.call_llm = fake_call_llm("claude-opus-5-5")
try:
    po.call_model({"model": "small-model", "base_url": "http://x:1/v1"}, [], 5)
    raise AssertionError("fallback to the main model was accepted")
except RuntimeError as exc:
    assert "fell back" in str(exc)
ac.call_llm = fake_call_llm("small-model")
assert po.call_model({"model": "small-model", "base_url": "http://x:1/v1"}, [], 5)[0] == "Rewritten."

# Skip rules.
assert po.skip_reason(CFG, "/optimized 20260924_150452") == "slash command"
assert po.skip_reason(CFG, "ok") == "too short"
assert po.skip_reason(CFG, "[System note: resumed] please continue the work") == "Hermes-generated turn"
assert po.skip_reason(CFG, "✔ [board] @dev Kanban t_1a2b3c done — build it") == "Hermes-generated turn"
assert po.skip_reason(CFG, "refactor the parser module", parent_session_id="abc")
assert po.skip_reason(CFG, "refactor the parser module", platform="subagent")
assert po.skip_reason(CFG, "refactor the parser module", source="kanban")
assert po.skip_reason(CFG, "refactor the parser module", display_kind="auto_continue")
assert po.skip_reason({**CFG, "enabled": False}, "refactor the parser module")
assert po.skip_reason(CFG, [{"type": "text", "text": "image turn"}]) == "non-text message"
assert po.skip_reason(CFG, "refactor the parser module", platform="desktop") == ""

# Hook end to end (LLM faked): context injected, original untouched, history + /optimized feed.
po.call_model = lambda cfg, messages, timeout: ("Refactor the parser module; keep the public API.", "fake-small")
po.load_config = lambda path=po.CONFIG_PATH: {**CFG, "show_in_cli": False}
history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "done"},
           {"role": "user", "content": "refactor the parser module pls"},
           {"role": "user", "content": "[todo snapshot] 1. parse"}]  # compression can append after it
seen = []
po.call_model = lambda cfg, messages, timeout: (seen.append(messages[-1]["content"]) or
                                                "Refactor the parser module; keep the public API.", "fake-small")
ret = po.on_pre_llm_call(session_id="s1", user_message="refactor the parser module pls",
                         conversation_history=history, model="claude-opus-5-5", platform="desktop")
assert ret and "<optimized_prompt>\nRefactor the parser module; keep the public API.\n</optimized_prompt>" in ret["context"]
assert seen[0].count("refactor the parser module pls") == 1  # current turn not duplicated as context
entry = json.loads(po.command("json s1"))
assert entry["status"] == "applied" and entry["original"] == "refactor the parser module pls"
os.environ["HERMES_SESSION_ID"] = "s1"
assert "Refactor the parser module" in po.command("")  # /optimized with no args → current session
os.environ["HERMES_SESSION_ID"] = "other"
assert po.command("") == "No optimized prompt yet."  # …never another session's prompt

po.call_model = lambda cfg, messages, timeout: ("refactor the parser  module pls", "fake-small")
assert po.on_pre_llm_call(session_id="s1", user_message="refactor the parser module pls",
                          conversation_history=history, model="m", platform="cli") is None
assert json.loads(po.command("json s1"))["status"] == "unchanged"
assert "sent as typed (unchanged)" in po.command("s1")

po.call_model = lambda cfg, messages, timeout: (_ for _ in ()).throw(RuntimeError("endpoint down"))
assert po.on_pre_llm_call(session_id="s2", user_message="refactor the parser module pls",
                          conversation_history=[], model="m", platform="cli") is None
assert json.loads(po.command("json s2"))["error"] == "endpoint down"
assert po.command("json nope") == "null"

# A base_url that belongs to a custom provider reuses that entry (and its key); others stay as-is.
import hermes_cli.runtime_provider as rp
rp.find_custom_provider_identity = lambda url: "custom:local" if "11434" in url else None
assert po.resolve_endpoint({"base_url": "http://127.0.0.1:11434/v1"}) == ("custom:local", None, None)
assert po.resolve_endpoint({"base_url": "http://other:1/v1"}) == (None, "http://other:1/v1", "no-key-required")
os.environ["PO_TEST_KEY"] = "sk-test"
assert po.resolve_endpoint({"base_url": "http://127.0.0.1:11434/v1", "api_key_env": "PO_TEST_KEY"}) == (
    None, "http://127.0.0.1:11434/v1", "sk-test")

print("ok: all self-checks passed", file=sys.stderr)
import shutil  # noqa: E402

shutil.rmtree(os.environ["HERMES_HOME"], ignore_errors=True)
