# optimizer/ - the Python half

Score 26: package boundary, 67 defs in 7 files, `ConfigError`/`fmt`/`skip_reason` 15+ refs each.
The root AGENTS.md has the product rules and commands. This file covers module internals.

## OVERVIEW
`hook` drives each turn, `engine` calls the models, `history` records results, `config` reads
config.yaml, `settings` validates and saves it, `command` is `/optimizer`.

## IMPORT GRAPH
- `hook` imports config, engine, history. `command` imports settings, config, engine, hook.
  `settings` imports config and engine. `engine` imports config.
- `config.normalize()` imports `settings` inside the function. That is the only thing breaking the
  config/settings cycle: keep it lazy.
- `engine` imports `tools.daemon_pool` at module level, and `hook`, `settings`, `command` and the
  root `__init__` all import `engine`: loading the plugin needs Hermes on `sys.path`.

## WHERE TO LOOK
| Task | Symbol | Notes |
|------|--------|-------|
| New skip rule | `hook.skip_reason` | Hermes-generated checks run before config checks; reasons with a `NOT_TYPED` prefix are not recorded |
| Turn status | `hook.on_pre_llm_call` | `running` -> `applied`/`unchanged`/`late`/`error`, or `skipped`; only `applied` returns context |
| Time budget | `hook._host_hook_timeout`, `engine.optimize` | deadline = start + budget - 1.5 s; with rounds > 1 candidates stop 2 s early; judge runs only with > 2 s left |
| Endpoint and key | `engine.resolve_endpoint` | `base_url` beats `provider`; a matching custom_provider reuses its key; else `no-key-required` |
| Main-model fallback guard | `engine._Route`, end of `call_model` | raises in `__setitem__`, before Hermes sends; the post-check stays as a safety net |
| Output cleanup | `engine.clean` | strips think tags, one wrapping fence, `<optimized_prompt>` |
| Setting schema | `settings.SETTINGS`, `Setting(kind, help, lo, hi)` | int/number need `lo` and `hi` (test_settings asserts it) |
| Value parsing | `settings._parse` | no exponents, at most 2 decimals, surrounding quotes dropped, control chars rejected |
| Comment-preserving save | `settings._save`, `_drop`, `_node` | ruamel round-trip; the PyYAML read-back must equal the expected dict |
| `/optimizer` replies | `command._run`, `_notes` | menu = `SETTINGS` minus `prompts.*`, numbered 1-20 |

## CONVENTIONS
- Logging: a module `logger` with lazy args, mostly `logger.warning("%s: ...", PLUGIN_ID, ...)`.
  Degraded paths warn.
- Hermes imports sit inside the function that uses them; only `tools.daemon_pool` is top-level.
  This keeps the v0.20.x fallbacks (`except ImportError`), and tests can patch
  `agent.auxiliary_client.call_llm` and `hermes_cli.runtime_provider.find_custom_provider_identity`
  because they are looked up at call time.
- Tests rebind `hook.load_config`, `hook.optimize` and `engine.call_model`. Call these by their
  module-global name; never alias them, bind them as default arguments or capture them at import.
- Threads: `DaemonThreadPoolExecutor` + `contextvars.copy_context().run` (Hermes keeps session state
  in contextvars), `shutdown(wait=False)`. Never wait past the deadline.
- `ConfigError` text is shown to the user verbatim: a sentence that names the fix.
- Writes go through Hermes' `utils.atomic_write_text`:
  - history: dir 0700, files 0600;
  - config: `preserve_mode=True`, then `config._cache.pop(path)` so the next turn re-reads it.
- `tests/test_optimizer.py`'s `FakeLLM` parses the `(Variant N of M.)` suffix and the
  `<candidate id="N">` judge listing. Change those formats together with it.

## ANTI-PATTERNS
- Raising out of `on_pre_llm_call`, `optimized_command` or `optimizer_command`. The hook records
  `error` and returns None; commands return text (desktop dispatch shows an exception as an
  unknown command).
- Accepting output that is empty or cut off (`finish_reason == "length"`): it would drop details.
- A judge with its own `provider`/`base_url` inheriting any of model's `ENDPOINT_KEYS`: model's key
  would go to another host.
- Echoing raw `/optimizer` input in an error (it may be a pasted key), or showing a URL without
  `fmt()`.
- Writing config.yaml with `yaml.dump`, skipping the read-back check, or writing when nothing
  changed (tests check the inode).
- A write path that skips `_check_span`: `min_chars` must stay below `max_chars`.
- Printing to stdout: the CLI block goes to stderr so `hermes chat -q` output stays clean.
