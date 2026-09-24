"""Read, validate, update and save config.yaml from code (backend of the in-chat config command).

    get_all() / get(key)   values as the running plugin's loader returns them (None = not set)
    defaults()             the config.yaml.example values, which reset() writes back
    set(key, raw_value)    parse text such as "3" or "off" into the setting's type, validate,
                           save; returns (old, new)
    reset(key=None)        one setting back to its default; no key = every setting except the prompts
    describe(key)          value, meaning, allowed values and default, as text

Keys are dotted paths (model.timeout). Anything invalid raises ConfigError, whose text is written
for the user, and leaves the file untouched. Saves are atomic (temp file + rename), keep comments,
key order and quoting (ruamel.yaml), and are checked to read back through the plugin's own PyYAML
loader with only the requested change. Changes apply from the next message: the hook re-reads
config.yaml every turn and a save drops the cached copy. No setting needs a restart.
"""

from __future__ import annotations

import copy
import difflib
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import CommentMark
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, LiteralScalarString, PlainScalarString
from ruamel.yaml.tokens import CommentToken

from .config import CONFIG_PATH, _cache, load_config, normalize
from .engine import MAX_ROUNDS


class ConfigError(ValueError):
    """Unknown key, invalid value, or a config.yaml that can't be read or written. Text is for the user."""


@dataclass(frozen=True)
class Setting:
    kind: str  # one of: bool, int, number, str, url, env, text, mapping
    help: str
    lo: Optional[float] = None
    hi: Optional[float] = None


_MODEL = {
    "provider": Setting("str", "Hermes provider (openrouter, anthropic, custom:<name>, …); empty = your "
                               "main provider. Ignored when base_url is set."),
    "model": Setting("str", "Model name."),
    "base_url": Setting("url", "OpenAI-compatible endpoint, e.g. http://127.0.0.1:11434/v1; empty = use provider."),
    "api_key_env": Setting("env", "Name of the env var holding the API key (the key itself goes in your Hermes .env)."),
    "temperature": Setting("number", "Sampling temperature.", 0, 2),
    "max_tokens": Setting("int", "Output token limit per call.", 64, 32768),
    "timeout": Setting("number", "Seconds per call, also bounded by plugins.hook_callback_timeout.", 1, 600),
}

SETTINGS: dict[str, Setting] = {  # same order as config.yaml.example
    "enabled": Setting("bool", "Master switch."),
    "rounds": Setting("int", "Optimized candidates per message; above 1, a judge call picks the best.", 1, MAX_ROUNDS),
    **{f"model.{k}": s for k, s in _MODEL.items()},
    **{f"judge_model.{k}": Setting(s.kind, f"Judge override of model.{k} (rounds > 1); unset = same as model.{k}.",
                                   s.lo, s.hi) for k, s in _MODEL.items()},
    "min_chars": Setting("int", "Shorter messages are sent untouched.", 0, 100000),
    "max_chars": Setting("int", "Longer messages are sent untouched.", 1, 100000),
    "context_messages": Setting("int", "Recent chat messages the optimizer sees.", 0, 20),
    "show_in_cli": Setting("bool", "Print the optimized prompt in the classic CLI."),
    "prompts.default": Setting("text", "Optimizer system prompt; {target_model} = the model that answers."),
    "prompts.per_model": Setting("mapping", "Per-model prompts: comma-separated globs -> prompt text."),
    "prompts.judge": Setting("text", "Judge system prompt (rounds > 1)."),
}

_BOOLS = {"true": True, "yes": True, "on": True, "1": True, "false": False, "no": False, "off": False, "0": False}
_NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)", re.ASCII)  # no 1e3, nan, inf, 0x10, 1_000
_MISSING = object()


def get_all(path: Path = CONFIG_PATH) -> dict:
    cfg = load_config(path)
    if not cfg and path.exists():
        _load(path)  # load_config() swallows parse errors; raise one the user can act on
    return {key: _dig(cfg, key) for key in SETTINGS}


def get(key: str, path: Path = CONFIG_PATH) -> Any:
    _spec(key)
    return get_all(path)[key]


def defaults(path: Path = CONFIG_PATH) -> dict:
    data = _template(path)[0]
    return {key: _dig(data, key) for key in SETTINGS}


def set(key: str, raw_value: Any, path: Path = CONFIG_PATH) -> tuple:  # noqa: A001 (name from the spec)
    value = _parse(key, _spec(key), raw_value)
    old = get(key, path)
    if key in ("min_chars", "max_chars"):
        span = {**normalize(_load(path)[0]), key: value}  # the template's values while config.yaml is missing
        if span["min_chars"] >= span["max_chars"]:
            raise ConfigError(f"min_chars ({span['min_chars']}) must be lower than max_chars ({span['max_chars']}).")
    _save(path, {key: value})
    return old, value


def reset(key: Optional[str] = None, path: Path = CONFIG_PATH) -> dict:
    """Back to the config.yaml.example value; keys the template lacks (judge_model.*) are removed.
    No key: every setting except the prompts, which are your own text and only reset by name.
    One save either way. Returns {key: (old, new)} for the settings that changed."""
    if key is not None:
        _spec(key)
    keys = [key] if key is not None else [k for k in SETTINGS if not k.startswith("prompts.")]
    before = get_all(path)
    data, doc = _template(path)
    nodes = {}
    for k in keys:  # the template's own nodes, so its quoting, blocks and inner comments come back too
        node = _dig(doc, k)
        nodes[k] = PlainScalarString(node) if type(node) is str else node  # else ruamel keeps the old quotes
    _save(path, {k: _dig(data, k) for k in keys}, nodes)
    after = get_all(path)
    return {k: (before[k], after[k]) for k in keys if before[k] != after[k]}


def describe(key: str, path: Path = CONFIG_PATH) -> str:
    spec = _spec(key)
    return (f"{key} = {fmt(get(key, path))}\n  {spec.help}\n"
            f"  Allowed: {allowed(spec)}. Default: {fmt(defaults(path)[key])}.")


def allowed(spec: Setting) -> str:
    span = f" from {spec.lo} to {spec.hi}" if spec.hi is not None else ""
    return {"bool": "true or false", "int": "a whole number" + span, "number": "a number" + span,
            "str": "a name without spaces, or empty", "url": "an http(s) URL without user:password@, or empty",
            "env": "an environment variable name like OPENROUTER_API_KEY, or empty",
            "text": "non-empty text without control characters",
            "mapping": "a mapping, edited in config.yaml (reset works)"}[spec.kind]


def fmt(value: Any) -> str:
    """One-line display form. Strings are quoted and cut at 60 characters; URLs lose user:password@
    and the query string, which can carry credentials (Hermes' redactor masks neither)."""
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return f"{len(value)} entries"
    if not isinstance(value, str):
        return str(value)
    flat = " ".join(value.split())
    if re.match(r"\w+://", flat):
        try:
            u = urlparse(flat)
            host = ("***@" if "@" in u.netloc else "") + u.netloc.rpartition("@")[2]
            flat = u._replace(netloc=host, query="***" if u.query else "", fragment="").geturl()
        except ValueError:
            flat = "***"
    return json.dumps(flat if len(flat) <= 60 else flat[:59] + "…", ensure_ascii=False)


def _spec(key: str) -> Setting:
    if key in SETTINGS:
        return SETTINGS[key]
    close = difflib.get_close_matches(str(key), list(SETTINGS), n=1)
    raise ConfigError(f"Unknown setting {key!r}." + (f" Did you mean {close[0]!r}?" if close else ""))


def _parse(key: str, spec: Setting, raw: Any) -> Any:
    """Text from the user -> typed value. The raw text is never echoed (it could be a pasted key)."""
    s = str(raw).strip()
    if spec.kind != "text" and len(s) > 1 and s[0] == s[-1] in "'\"":  # set model.model "llama3:8b"
        s = s[1:-1]
    value: Any = None
    hint = ""
    control = [c for c in s if unicodedata.category(c) == "Cc"]  # \x00, \r, \t, \n, … (not NBSP, emoji)
    if spec.kind == "text":
        s = s.replace("\r\n", "\n")
        value = s if s and all(c in "\n\t" for c in control) else None
    elif spec.kind == "mapping" or control:  # single-line settings: no newlines, tabs, control characters
        value = None
    elif spec.kind == "bool":
        value = _BOOLS.get(s.lower())
    elif spec.kind in ("int", "number") and _NUMBER.fullmatch(s):
        # 2 decimals at most: PyYAML reads an exponent form like 1e-05 back as a string
        value = int(s) if s.lstrip("+-").isdigit() else round(float(s), 2) if spec.kind == "number" else None
        if value is not None and not spec.lo <= value <= spec.hi:
            value = None
    elif spec.kind == "url":
        try:
            parts = urlparse(s)
            ok = parts.scheme in ("http", "https") and bool(parts.hostname) and " " not in s
        except ValueError:
            parts, ok = None, False
        value = s if not s or ok else None
        if parts and "@" in parts.netloc:
            value = None
            hint = (" config.yaml is plain text: put the key in your Hermes .env file and its name in "
                    f"{key.split('.')[0]}.api_key_env.")
    elif spec.kind == "env":
        value = s if not s or re.fullmatch(r"[A-Z_][A-Z0-9_]*", s) else None  # keys have lowercase/dashes
        hint = " Put the key itself in your Hermes .env file, never in config.yaml."
    elif spec.kind == "str":
        value = s if " " not in s else None
    if value is None:
        raise ConfigError(f"{key} must be {allowed(spec)}.{hint}")
    return value


def _dig(data: Any, key: str, default: Any = None) -> Any:
    for part in key.split("."):
        if not isinstance(data, dict) or part not in data:
            return default
        data = data[part]
    return data


def _put(root: dict, key: str, value: Any) -> None:
    """Set a dotted key, creating parent mappings as needed; None deletes it."""
    if value is None and isinstance(root, CommentedMap):
        return _drop(root, key)
    *parents, leaf = key.split(".")
    for part in parents:
        if not isinstance(root.get(part), dict):
            if value is None:
                return  # nothing to delete
            root[part] = CommentedMap()
        root = root[part]
    if value is None:
        root.pop(leaf, None)
    else:
        root[leaf] = value


def _drop(doc: CommentedMap, key: str) -> None:
    """Delete a dotted key from a ruamel document, keeping the blank lines and comments below it.

    ruamel files the lines between a key and the next one on the key's own comment token, so a plain
    `del` would drop them (e.g. the blank line and `# about min_chars` after `judge_model.model`).
    They move above the next key in document order, or to the end of the file. A map left empty is
    written `{}`, without the comments that were inside it."""
    *parents, leaf = key.split(".")
    maps = [doc]
    for part in parents:
        if not isinstance(maps[-1].get(part), CommentedMap):
            return
        maps.append(maps[-1][part])
    m = maps[-1]
    if leaf not in m:
        return
    token = (m.ca.items.pop(leaf, None) or [None] * 4)[2]
    rest = token.value.partition("\n")[2] if token is not None else ""  # minus the key's own # comment
    following = None
    for owner, k in reversed(list(zip(maps, parents + [leaf]))):
        keys = list(owner)
        if keys.index(k) + 1 < len(keys):
            following = owner, keys[keys.index(k) + 1]
            break
    del m[leaf]
    if not m and len(maps) > 1:
        m.fa.set_flow_style()
        if m.ca.comment:
            m.ca.comment[1:] = [None] * (len(m.ca.comment) - 1)
        slot = maps[-2].ca.items.get(parents[-1])
        if slot:
            slot[3] = None
    if rest:
        lines = CommentToken(rest, CommentMark(0), None)
        if following:
            slot = following[0].ca.items.setdefault(following[1], [None] * 4)
            slot[1] = [lines] + (slot[1] or [])
        else:
            doc.ca.comment = doc.ca.comment or [None, None]  # ruamel only writes ca.end when this is set
            doc.ca.end = [lines] + (doc.ca.end or [])


def _node(value: Any) -> Any:
    """The ruamel form of a value, written so that PyYAML (the plugin's loader) reads it back unchanged."""
    if not isinstance(value, str):
        return value
    if "\n" in value:
        return LiteralScalarString(value)  # multi-line prompts stay readable `|` blocks
    try:
        if yaml.safe_load(value) == value:
            return value
    except yaml.YAMLError:
        pass
    return DoubleQuotedScalarString(value)  # "off", "yes", "3:4", "" would change type unquoted


def _rt() -> YAML:
    rt = YAML()  # round-trip mode: comments, key order and quoting survive
    rt.preserve_quotes = True
    rt.width = 4096  # never re-wrap long lines
    rt.indent(mapping=2, sequence=4, offset=2)  # the template's layout (and Hermes' own config writer's)
    return rt


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Could not read {path}: {getattr(exc, 'strerror', None) or exc}") from exc


def _parse_yaml(text: str, name: str) -> tuple:
    """(PyYAML view, ruamel document) of a config file."""
    try:
        data = yaml.safe_load(text) or {}
        doc = _rt().load(text) or CommentedMap()
    except Exception as exc:  # PyYAML / ruamel parse errors; ruamel also rejects duplicate keys
        mark = getattr(exc, "problem_mark", None)
        where = f" line {mark.line + 1}" if mark else ""
        problem = str(getattr(exc, "problem", None) or exc).split(" with value")[0]  # no values in chat
        raise ConfigError(f"{name}{where}: {problem}. Fix it by hand, then retry.") from exc
    if not isinstance(data, dict) or not isinstance(doc, dict):
        raise ConfigError(f"{name} must be a YAML mapping (key: value lines). Fix it by hand, then retry.")
    return data, doc


def _template(path: Path) -> tuple:
    example = path.with_name(path.name + ".example")
    return _parse_yaml(_read(example), example.name)


def _load(path: Path) -> tuple:
    """config.yaml, or the template while config.yaml is missing (the first save recreates it)."""
    return _parse_yaml(_read(path), path.name) if path.exists() else _template(path)


def _save(path: Path, changes: dict, nodes: Optional[dict] = None) -> None:
    """Apply {dotted key: value (None = delete)} and leave every other byte of the file as it was.
    `nodes` gives the ruamel form to write for a key, if not the default one."""
    # ponytail: read-modify-write without a lock, so two saves in the same instant can drop one.
    # Wrap it in fcntl.flock if several processes ever edit config.yaml concurrently.
    before, doc = _load(path)
    todo = {k: v for k, v in changes.items() if _dig(before, k, _MISSING) != (_MISSING if v is None else v)}
    if not todo and path.exists():
        return  # nothing changes: leave the file alone
    expected = copy.deepcopy(before)
    for key, value in todo.items():
        _put(expected, key, value)
        node = (nodes or {}).get(key)
        _put(doc, key, _node(value) if node is None else node)
    out = io.StringIO()
    try:
        _rt().dump(doc, out)
        ok = yaml.safe_load(out.getvalue()) == expected
    except Exception:
        ok = False
    if not ok:
        raise ConfigError(f"Can't save {', '.join(todo)} so that it reads back unchanged; edit {path.name} by hand.")
    _write(path, out.getvalue())


def _write(path: Path, text: str) -> None:
    from utils import atomic_write_text  # Hermes': temp file + fsync + rename, keeps symlinks and mode

    try:
        atomic_write_text(path, text, preserve_mode=True)
    except OSError as exc:
        raise ConfigError(f"Could not save {path}: {exc.strerror or exc}") from exc
    _cache.pop(path, None)  # the hook re-reads on its next call even if the mtime didn't move
