# PROJECT KNOWLEDGE BASE

**Generated:** 2026-10-02
**Commit:** 9c0c549
**Branch:** main

## OVERVIEW
A Hermes Agent plugin. Its `pre_llm_call` hook has a small model rewrite each user message and adds
the rewrite as context; the typed message is never replaced. It is Python (stdlib, PyYAML and
ruamel.yaml, all from Hermes' own environment) plus one unbundled ESM file for the desktop banner.

## STRUCTURE
```
hermes-prompt-optimizer/  # the repo root IS the plugin package; Hermes clones it to $HERMES_HOME/plugins/hermes-prompt-optimizer/
├── plugin.yaml           # manifest: name, version, provides_hooks
├── __init__.py           # register(): 1 hook + 2 commands
├── config.yaml.example   # settings template and every prompt; install copies it to config.yaml (gitignored)
├── after-install.md      # printed by `hermes plugins install`
├── optimizer/            # the Python half (own AGENTS.md)
├── desktop/plugin.js     # composer banner, loaded as-is by the desktop app
├── tests/                # self-check scripts (own AGENTS.md)
├── .github/workflows/    # CI on the oldest supported and a current Hermes release
└── .github/readme/       # README banner, cards and animated tiles; BRIEF.md is the art-direction log
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Add or change a setting | `optimizer/settings.py` `SETTINGS`, `config.yaml.example` | same order in both; `/optimizer` numbers follow it, so append at the end of a group |
| Prompts, a new model family | `config.yaml.example` `prompts` | `per_model` keys are comma-separated globs, first match wins; keep `{base}` |
| Which turns get optimized | `optimizer/hook.py` `skip_reason` | |
| Model calls, judge, time budget | `optimizer/engine.py` | |
| `/optimizer` chat UI | `optimizer/command.py` | plain text in and out, one complete command per step |
| `/optimized`, the banner's data | `optimizer/hook.py`, `optimizer/history.py` | `/optimized json <session_id>` is the banner's contract |
| Desktop banner | `desktop/plugin.js` | scored 7, so no AGENTS.md of its own; `tests/test_desktop.mjs` checks it |
| Release | `plugin.yaml` `version` | the README badge repeats it |
| CI and update bots | `.github/workflows/tests.yml`, `renovate.json` | actions pinned by SHA; Renovate automerges minor, patch, pin and digest |

## CODE MAP
Refs = ast-grep identifier matches in tracked `.py`, definition and imports included.

| Symbol | Type | Location | Refs | Role |
|--------|------|----------|------|------|
| `register` | fn | `__init__.py:16` | - | wires `pre_llm_call`, `/optimized`, `/optimizer` |
| `on_pre_llm_call` | fn | `optimizer/hook.py:116` | 13 | one user turn: skip, optimize, record, inject |
| `skip_reason` | fn | `optimizer/hook.py:36` | 17 | which turns are left alone |
| `optimized_command` | fn | `optimizer/hook.py:164` | 3 | `/optimized [json] [session_id]` |
| `optimize` | fn | `optimizer/engine.py:139` | 12 | N parallel candidates, then a judge |
| `call_model` | fn | `optimizer/engine.py:104` | 11 | one completion through Hermes' `call_llm` |
| `resolve_endpoint` | fn | `optimizer/engine.py:62` | 7 | picks provider, base_url and key |
| `load_config` | fn | `optimizer/config.py:56` | 11 | mtime-cached `config.yaml`; `{}` when broken |
| `pick_prompt` | fn | `optimizer/config.py:77` | 9 | per-model system prompt |
| `record`, `latest` | fn | `optimizer/history.py:43`, `:56` | 7, 3 | per-chat result history |
| `SETTINGS` | dict | `optimizer/settings.py:64` | 16 | setting schema; drives the menu and validation |
| `ConfigError` | class | `optimizer/settings.py:41` | 22 | validation error whose text the user sees |
| `fmt` | fn | `optimizer/settings.py:145` | 22 | one-line display form; strips URL credentials |
| `optimizer_command` | fn | `optimizer/command.py:29` | 4 | `/optimizer` entry; never raises |
| `Banner` | component | `desktop/plugin.js:44` | - | polls `/optimized json` while a turn runs |

## CONVENTIONS
- No dependency manifest on purpose (no pyproject, requirements or package.json). The runtime is
  the stdlib, PyYAML, ruamel.yaml and Hermes' modules, all from Hermes' environment.
- Relative imports only (`from .optimizer...`, `from . import PLUGIN_ID`): Hermes imports the folder
  as a package.
- The oldest supported Hermes is v0.20.1 (CI tag v2026.8.13). Newer Hermes APIs are used only behind
  a lazy import with a fallback, with the version noted in a comment (`_host_hook_timeout`,
  `history._sessions_dir`, the desktop `register`).
- `config.yaml` belongs to the user. `config.yaml.example` is the template and the source of
  defaults and resets. Every change applies from the next message; nothing may need a restart.
- Plugin state lives only in `$HERMES_HOME/plugin-data/hermes-prompt-optimizer/sessions/` (the
  last 10 turns per chat, mode 0600).
- Hook, history, `/optimized` and the banner share one status vocabulary: `running`, `applied`,
  `unchanged`, `late`, `error`, `skipped`.
- Desktop JS is plain ESM with no build step. It calls `jsx()`/`jsxs()` instead of using JSX,
  uses single quotes and no semicolons, and imports only `@hermes/plugin-sdk`, `react` and
  `react/jsx-runtime`, which the app supplies.
- Python uses double quotes and lines up to about 120 columns.

## ANTI-PATTERNS (THIS PROJECT)
- Replacing or editing the user's message. The hook may only return `{"context": INJECTION}`; the
  transcript keeps what was typed, and the original wins on conflict.
- A rewrite done by any model other than the configured optimizer, including Hermes' fallback to
  the main (paid) model.
- A failure that changes the turn. Every error or timeout sends the message as typed and is recorded
  for `/optimized`.
- API keys in `config.yaml` or in command replies. Store only env var names (`api_key_env`); the keys
  live in Hermes' `.env`.
- Answering `/optimized` or `/optimizer` inside the messaging gateway. Hermes doesn't say who is
  asking, and `_in_messaging_gateway()` fails closed.
- New third-party packages: the README promises "No extra Python packages".
- Moving the top-level files Hermes looks for: `plugin.yaml`, `__init__.py`, `config.yaml.example`,
  `after-install.md`, `desktop/plugin.js`.
- Committing `config.yaml`, `tests/node_modules/`, `brag-output/` or large media. Hermes installs
  plugins by cloning the repo, which is why the demo clip lives in GitHub user-attachments.

## UNIQUE STYLES
- `ponytail:` comments mark deliberate shortcuts, with their limit and upgrade path. There are 5
  today: `engine.MAX_ROUNDS`, the gateway refusal in `hook.py`, the lock-free save in
  `settings.py`, and two in `desktop/plugin.js`.
- User-facing text is plain and names the fix ("sent as typed", "Applies from your next message, no
  restart needed."). The README and the self-checks quote replies verbatim, so change all three
  together.

## COMMANDS
```bash
# README Contributing = CI (.github/workflows/tests.yml); CI also runs tag v2026.8.13 (v0.20.1)
git clone --depth 1 --branch v2026.9.24 https://github.com/NousResearch/hermes-agent ../hermes-agent  # v0.21.5
(cd ../hermes-agent && uv sync --locked)
for t in tests/test_*.py; do ../hermes-agent/.venv/bin/python "$t"; done   # each prints "ok: ..."
HERMES_HOME="$(mktemp -d)" ../hermes-agent/.venv/bin/hermes plugins doctor . --ci
npm install --prefix tests --no-save --no-package-lock react@19.2.7 react-dom@19.2.7 \
  @tanstack/react-query@5.101.2 jsdom@29.1.1
node tests/test_desktop.mjs
```

## NOTES
- Run tests and `plugins doctor` only with a separate Hermes release tree, as above. Never use the
  installed Hermes when it has a `pm/` directory (current main, not the tagged releases):
  - its `venv/bin/python`, if present, is a leftover pre-PM venv: imports fail with
    `No module named 'hermes_yaml'`;
  - run with a throwaway `HERMES_HOME`, it provisions a tool store inside that directory and can
    rebind the install's launchers (`~/.hermes/hermes-agent/.hermes/bin/hermes`, `hermes-acp`, also
    used by `hermes-gateway.service`) to it. Deleting the temp dir then breaks `hermes`.
- Hermes abandons the hook after `plugins.hook_callback_timeout` (default 30 s, enforced from
  v0.20.6). `rounds > 1` or a slow model needs it raised; `/optimizer` says so.
- `pre_llm_call` can only add context, so the main model sees both the original and the rewrite.
  With `api_mode: codex_app_server`, Hermes drops hook context and the plugin does nothing.
- The banner asks the active gateway only, so a chat owned by another profile shows no banner.
