"""The rewrite: N optimizer calls in parallel, then (N > 1) one judge call picks the best candidate.

Calls go through Hermes' own client stack (call_llm), so every provider, custom endpoint and
credential pool Hermes knows about works without extra setup.
"""

from __future__ import annotations

import contextvars
import logging
import re
import sys
import time
from concurrent.futures import wait
from typing import Callable, Optional

from tools.daemon_pool import DaemonThreadPoolExecutor  # Hermes': an abandoned call never delays exit

from . import PLUGIN_ID
from .config import pick_prompt

logger = logging.getLogger(__name__)

MAX_ROUNDS = 5  # ponytail: hard cap so a config typo can't fan out dozens of paid calls
ENDPOINT_KEYS = ("provider", "base_url", "api_key_env")  # where a model is called, and with which key

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
    # The last `keep` chat messages with text. Tool calls and results don't count: a turn that used
    # tools would otherwise push the message that "fix it" refers to out of the window.
    turns = [m for m in history if isinstance(m, dict) and m.get("role") in ("user", "assistant")
             and isinstance(m.get("content"), str) and m["content"].strip()]
    lines = []
    for msg in (turns[-keep:] if keep > 0 else []):
        text = msg["content"].strip()
        lines.append(f"{msg['role']}: {text[:800]}{'…' if len(text) > 800 else ''}")
    context = "<conversation_context>\n" + "\n".join(lines) + "\n</conversation_context>\n\n" if lines else ""
    return f"{context}<message>\n{message}\n</message>"


def _secret(name: str) -> Optional[str]:
    """Env-var lookup through Hermes' per-profile secret scope. In a multiplexed gateway it raises
    rather than read another profile's key; the message is then sent as typed."""
    from agent.secret_scope import get_secret
    return get_secret(name)


def resolve_endpoint(model_cfg: dict) -> tuple:
    """(provider, base_url, api_key) for call_llm. A base_url replaces the provider: Hermes would send a
    first-class provider's requests, and this key, to that provider's own API instead. A base_url that
    belongs to a custom provider in Hermes' config.yaml reuses that entry (and its key)."""
    base_url = model_cfg.get("base_url") or None
    provider = None if base_url else (model_cfg.get("provider") or None)
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


def _tail(model: str) -> str:
    return str(model or "").split("/")[-1].lower()  # openrouter's "vendor/name" vs a provider's "name"


class _Route(dict):
    """call_llm's route_info. Hermes records each route here right before sending the request, so a
    record naming another model (its fallback to your main model when the optimizer endpoint is down
    or has no key) raises before that paid request is made."""

    def __init__(self, want: str):
        super().__init__()
        self.want = want

    def __setitem__(self, key, value):
        if key == "model" and ("model" in self or (self.want and _tail(value) != _tail(self.want))):
            cause = sys.exc_info()[1]  # the error Hermes is falling back from, if any
            raise RuntimeError(f"optimizer model {self.want or '(default)'} unavailable"
                               f"{f' ({cause})' if cause else ''}; stopped Hermes from using {value} instead")
        super().__setitem__(key, value)


def call_model(model_cfg: dict, messages: list, timeout: float) -> tuple:
    """One completion through Hermes' own client stack (all providers, custom endpoints, key pools)."""
    from agent.auxiliary_client import call_llm
    from utils import model_forces_max_completion_tokens

    provider, base_url, api_key = resolve_endpoint(model_cfg)
    want, limit = str(model_cfg.get("model") or ""), model_cfg.get("max_tokens")
    # Hermes drops max_tokens for plain OpenAI-compatible endpoints; in the request body it stays.
    name = "max_completion_tokens" if model_forces_max_completion_tokens(want) else "max_tokens"
    cap = {name: limit} if limit else None

    def ask(extra_body: Optional[dict]) -> tuple:
        route = _Route(want)
        resp = call_llm(provider=provider, model=want or None, base_url=base_url, api_key=api_key,
                        messages=messages, temperature=model_cfg.get("temperature"), max_tokens=limit,
                        extra_body=extra_body, timeout=timeout, route_info=route)
        return resp, route

    try:
        resp, route = ask(cap)
    except Exception as exc:
        if not cap or not re.search(r"max_(completion_)?tokens", str(exc)):
            raise
        resp, route = ask(None)  # this endpoint rejects an output limit: ask without one
    # Safety net should a Hermes version stop recording the route first: never use another model's rewrite.
    got = str(route.get("model") or "")
    if want and got and _tail(want) != _tail(got):
        raise RuntimeError(f"optimizer model {want} unavailable (Hermes fell back to {got})")
    choice = resp.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise RuntimeError("optimizer output hit max_tokens (it would drop details)")
    used = str(getattr(resp, "model", "") or want or "main model")
    return clean(choice.message.content or ""), used


def optimize(message: str, *, target_model: str, history: list, cfg: dict,
             llm: Optional[Callable] = None, deadline: Optional[float] = None) -> dict:
    llm = llm or call_model
    model_cfg = dict(cfg.get("model") or {})  # load_config() filled in the template's numbers
    judge = cfg.get("judge_model") or {}
    # A judge with an endpoint of its own inherits none of model's: model's key belongs to model's host.
    own_endpoint = any(k in judge for k in ("provider", "base_url"))
    judge_cfg = {**{k: v for k, v in model_cfg.items() if not (own_endpoint and k in ENDPOINT_KEYS)}, **judge}
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

    pool = DaemonThreadPoolExecutor(max_workers=rounds)
    # Hermes keeps the active session's runtime in contextvars; plain pool threads don't inherit them.
    futures = [pool.submit(contextvars.copy_context().run, candidate, i) for i in range(rounds)]
    # Hermes' client retries on its own, so per-call timeouts don't bound the total. Stop waiting at the
    # deadline, less 2 s for the judge when one runs; stragglers finish in the background, ignored.
    reserve = 2 if rounds > 1 else 0
    wait(futures, timeout=None if deadline is None else max(0.0, deadline - time.monotonic() - reserve))
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
        judge_pool = DaemonThreadPoolExecutor(max_workers=1)
        judged = judge_pool.submit(contextvars.copy_context().run, llm, judge_cfg, judge_messages,
                                   timeout(judge_cfg))
        judge_pool.shutdown(wait=False)
        try:
            verdict, _ = judged.result(timeout=None if deadline is None else max(0.0, deadline - time.monotonic()))
            # The judge is told to reply with a bare number; take the first one that is in range.
            for n in re.findall(r"\d+", verdict or ""):
                if 1 <= int(n) <= len(results):
                    picked = int(n) - 1
                    break
        except Exception as exc:
            logger.warning("%s: judge failed, keeping candidate 1: %s", PLUGIN_ID, str(exc) or "timed out")
    return {"optimized": results[picked][0], "candidates": [t for t, _ in results],
            "picked": picked, "rounds": rounds, "model": results[picked][1]}
