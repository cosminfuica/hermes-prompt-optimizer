# tests/ - self-check scripts

Score 10, but it gets its own file because it is a separate domain: script-style asserts, package
aliasing, Hermes' interpreter, hand-made fakes. How to run them is under COMMANDS in the root file.

## OVERVIEW
Each file is a script that runs top to bottom and prints `ok: all ... passed` as its last line.
There is no pytest, no fixtures and no external network: models are always faked. CI runs every
`tests/test_*.py` as `python "$t"`, so a new test file must be a runnable script.

## WHERE TO LOOK
| File | Covers | Harness |
|------|--------|---------|
| `test_optimizer.py` | engine, prompt pick, normalize, skip rules, hook end to end, history, `register()` | `FakeLLM`, `fake_call_llm`, `Ctx` |
| `test_settings.py` | settings parse/save/reset, byte-exact YAML | `fresh()`, `diff()`, `rejected()` |
| `test_command.py` | every `/optimizer` reply, menu numbers 1-20 | `run(args)` |
| `test_integration.py` | Hermes' own loader, `command.dispatch`, `pre_llm_call`, real `call_llm` | local OpenAI-compatible server and a refused port |
| `test_desktop.mjs` | `desktop/plugin.js` banner in jsdom | fake `@hermes/plugin-sdk`, `data:` URL import shims |

## CONVENTIONS
- Header order matters:
  1. Set `HERMES_HOME` to a fresh `tempfile.mkdtemp()`.
  2. Where the hook runs, pop `HERMES_SESSION_SOURCE` (and `HERMES_SESSION_ID` in integration):
     a kanban or cron parent would make the hook skip.
  3. Only then import Hermes modules (`# noqa: E402`).
- The unit scripts load the repo as package `po`:
  1. `spec_from_file_location("po", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])`
  2. `sys.modules["po"] = ...`
  3. `import_module("po.optimizer.<name>")`
- `test_integration.py` copies the repo to `$HERMES_HOME/plugins/hermes-prompt-optimizer/` (minus
  `.git`, `__pycache__` and `config.yaml`) and enables it in a generated Hermes `config.yaml`. It
  puts Hermes' source root on `sys.path` the way `hermes_cli/main.py` does (v0.20.x needs that).
- `FakeLLM` picks its scripted text by the `(Variant N of M.)` suffix, not by call order, because
  candidates run in parallel (commit c2e13ef fixed that flake). A message containing `<candidate`
  is the judge call.
- Fakes are plain module-attribute swaps (`ac.call_llm`, `hook.load_config`, `engine.call_model`).
  Restore the real attribute before any later section needs it, as done for
  `sys.modules["gateway.run"]` and `utils.atomic_replace`.
- The settings checks compare files byte for byte with `config.yaml.example`; `reset all` must
  restore it exactly. Editing the template means updating these expectations.
- The deadline checks (around `test_optimizer.py:140-176`) use real sleeps with monotonic bounds.
  Keep their margins.
- The React stack (react, react-dom, @tanstack/react-query, jsdom) mirrors Hermes' desktop app and
  installs to `tests/node_modules` (gitignored). Its versions are pinned in three places:
  `tests.yml`, the `test_desktop.mjs` header and README Contributing. There is no package.json, so
  bump all three by hand.
- Warnings printed during a run are expected: they come from the deliberate bad-config cases.

## ANTI-PATTERNS
- Switching to pytest, or adding fixtures, a conftest or a framework.
- `import optimizer`, or importing Hermes modules before `HERMES_HOME` is set: they would read and
  write the real `~/.hermes`.
- Real network or model calls.
- Relying on the order of candidate calls.
- Leaking a fake into a later section that expects the real attribute.
