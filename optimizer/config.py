"""Settings: config.yaml at the plugin root, re-read when it changes (no restart needed)."""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

import yaml

from . import PLUGIN_ID

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"  # created from config.yaml.example on install
MODEL_DEFAULTS = {"provider": "", "model": "", "base_url": "", "api_key_env": "",
                  "temperature": 0.5, "max_tokens": 1500, "timeout": 20}
_INT_KEYS = {"rounds": 1, "min_chars": 0, "max_chars": 6000, "context_messages": 0}
_cache: dict = {}


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
    cached = _cache.get(path)
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
    _cache[path] = (mtime, cfg)
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
