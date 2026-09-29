"""Settings: config.yaml at the plugin root, re-read when it changes (no restart needed)."""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

import yaml

from . import PLUGIN_ID

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"  # created from config.yaml.example on install
_cache: dict = {}


def normalize(cfg: dict) -> dict:
    """Coerce hand-edited values so a typo degrades to a default instead of breaking every turn.
    A true/false or number setting that is missing, or that /optimizer would refuse, takes its
    config.yaml.example value, with a warning for the invalid ones; an invalid judge_model.* one is
    dropped, so it follows model.* as when unset. Names, URLs and prompts are used as written."""
    from .settings import SETTINGS, ConfigError, _parse, allowed, defaults, fmt

    cfg = dict(cfg)
    for section in ("model", "judge_model", "prompts"):
        if not isinstance(cfg.get(section) or {}, dict):
            logger.warning("%s: %s must be a mapping, ignoring it", PLUGIN_ID, section)
            cfg[section] = {}
        cfg[section] = dict(cfg.get(section) or {})
    try:
        template = defaults()
    except ConfigError as exc:  # config.yaml.example unreadable: invalid values are dropped instead
        logger.warning("%s: %s", PLUGIN_ID, exc)
        template = {}
    for key, spec in SETTINGS.items():
        if spec.kind not in ("bool", "int", "number"):
            continue
        section, _, leaf = key.rpartition(".")
        where = cfg[section] if section else cfg
        if leaf in where:
            try:
                where[leaf] = _parse(key, spec, where[leaf])  # the check /optimizer applies to a new value
                continue
            except ConfigError:
                use = f"model.{leaf}" if section == "judge_model" else fmt(template.get(key))
                logger.warning("%s: %s must be %s; using %s", PLUGIN_ID, key, allowed(spec), use)
        if section != "judge_model" and template.get(key) is not None:
            where[leaf] = template[key]
        else:
            where.pop(leaf, None)
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
