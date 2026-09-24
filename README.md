# hermes-prompt-optimizer

A Hermes Agent plugin: **you → a small model rewrites your message → your Hermes model answers.**

Before each message reaches your main model, a smaller model (any provider or any OpenAI-compatible
endpoint) rewrites it into a clearer prompt tuned for the model that will answer. With `rounds: N > 1`
it writes N candidates in parallel and one extra judge call picks the best one. Your chat still shows
exactly what you typed; the optimized version is shown to you separately and never appears in the reply.

## Contents

| File                  | Purpose                                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------- |
| `plugin.yaml`         | Plugin manifest (name, version, `pre_llm_call` hook).                                                         |
| `__init__.py`         | The hook, optimizer + judge, history, and the `/optimized` command.                                           |
| `config.yaml.example` | Settings template. Hermes copies it to `config.yaml` on install; your copy is never committed or overwritten. |
| `after-install.md`    | Next steps Hermes prints after `hermes plugins install`.                                                      |
| `desktop/plugin.js`   | Desktop-app banner above the composer (optional).                                                             |
| `test_optimizer.py`   | Self-check (no network, no real model calls).                                                                 |

## How it works

1. You send a message. Hermes fires the plugin's `pre_llm_call` hook once per user turn.
2. The plugin decides whether to optimize it (see "Never optimized" below). If not, nothing happens.
3. It sends your message, plus the last `context_messages` chat turns (so "fix it" / "that file"
   resolve correctly), to the optimizer model with a system prompt picked for the answering model:
   `prompts.per_model` has Claude, GPT and Gemini variants based on each vendor's prompting guide,
   with `prompts.default` as the fallback.
4. `rounds: 1` uses that single rewrite. `rounds: N` runs N calls in parallel, then a judge call
   (optionally a different model, `judge_model`) picks the best candidate.
5. The result is appended to the **API copy** of your message inside an `<optimized_prompt>` block,
   with a note telling the model to treat it as the task spec and to let your original message win
   on conflicts. The transcript keeps what you typed; the bytes actually sent are stored alongside,
   so prompt caching and session resume keep working.
6. The attempt is recorded (last 10 per chat) under
   `$HERMES_HOME/plugin-data/hermes-prompt-optimizer/sessions/`, which feeds the banner and `/optimized`.

If anything fails (endpoint down, bad key, timeout, output truncated at `max_tokens`) your message is
sent exactly as typed and the error is recorded. If Hermes' client silently falls back to your main
model because the optimizer endpoint is unreachable, the plugin treats that as a failure too, so the
main (paid) model never does the rewrite.

**Time budget.** Hermes gives a `pre_llm_call` hook `plugins.hook_callback_timeout` seconds (default
30). The whole optimization, judge included, stops 1.5s before that limit; if it can't finish, the
original message goes through. For `rounds > 1` or a slow optimizer model, raise the limit:

```bash
hermes config set plugins.hook_callback_timeout 90
```

### Where you see the optimized prompt

| Surface                | How                                                                                                                                                          |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Classic CLI (`hermes`) | A `✦ optimized prompt · <model> · <seconds>s` block printed above the answer (on stderr, so `hermes chat -q` stdout stays clean). Toggle with `show_in_cli`. |
| Desktop app            | Banner above the composer: `✦ Optimized · <model> · 2.7s` with the first line inline; ▸ expands the full text, copy button, × dismisses.                     |
| CLI, TUI, desktop      | `/optimized` shows the last result for the current chat; `/optimized <session_id>` for a specific chat.                                                      |

`/optimized` is disabled in the messaging gateway (Telegram, Discord, …): Hermes doesn't tell plugin
commands who is asking, so it could show another user's prompt. Messages on those platforms are still
optimized; there is just no banner.

### Never optimized

- Messages shorter than `min_chars` or longer than `max_chars`
- Images / non-text messages, slash commands
- Turns Hermes writes itself (auto-continue, background-process and kanban notices, model switches)
- Subagents, background review and `/btw` forks, cron jobs and kanban workers

### Known limits

- `pre_llm_call` can only _add_ context. The main model sees your original message **and** the
  optimized block; Hermes has no hook that replaces only the API copy.
- With `api_mode: codex_app_server`, Hermes drops hook context, so the plugin has no effect there.
- The desktop banner asks the active gateway only; a chat owned by another profile shows no banner.

## Requirements

- Hermes Agent with plugin support (the plugin uses Hermes' own client stack, `call_llm`, so every
  provider, custom endpoint and credential pool Hermes knows about works).
- An optimizer model you can reach. The template points at a local Ollama server
  (`qwen2.5:7b` on `http://127.0.0.1:11434/v1`); **change `model:` to your own before use.**
- No extra Python packages (only `pyyaml`, already in Hermes' venv).

## Install

1. Install and enable it with Hermes' plugin manager (add `-p <profile>` for a named profile):

   ```bash
   hermes plugins install cosminfuica/hermes-prompt-optimizer --enable
   ```

   Hermes clones the repo into `$HERMES_HOME/plugins/hermes-prompt-optimizer/`, runs its security
   scan, creates `config.yaml` from `config.yaml.example` and prints the next steps.
   For a reproducible install, pin a commit: `--ref <40-character commit SHA>`.

   Desktop app alternative: Settings → Plugins → Install from Git, or open
   `hermes://plugin/install?repo=cosminfuica/hermes-prompt-optimizer&enable=1`.

2. Point it at your optimizer model: edit `$HERMES_HOME/plugins/hermes-prompt-optimizer/config.yaml`
   (see [Configure](#configure) below).

3. Optional, desktop banner: in the desktop app open Settings → Plugins and enable
   **Prompt Optimizer**. The desktop half of a plugin is opt-in.

4. If you have another prompt-optimizing plugin enabled (for example a third-party
   `prompt-optimizer`), disable it, or every message gets rewritten twice:

   ```bash
   hermes plugins disable prompt-optimizer
   ```

5. Try it: start `hermes`, send a message of at least `min_chars` characters and look for the
   `✦ optimized prompt` block, or run `/optimized`. `hermes plugins list` should show it enabled.

### Update / uninstall

- Update: `hermes plugins update hermes-prompt-optimizer`. Your `config.yaml` is kept; new keys in
  `config.yaml.example` fall back to built-in defaults until you copy them over.
- Disable: `hermes plugins disable hermes-prompt-optimizer`
- Remove: `hermes plugins remove hermes-prompt-optimizer`, plus
  `$HERMES_HOME/plugin-data/hermes-prompt-optimizer/` if you want the history gone.

## Configure

Settings live in `config.yaml` inside the installed plugin folder, created from
`config.yaml.example` on install.

The file is re-read when it changes: edits apply to your next message, no restart needed. Invalid
values fall back to defaults with a warning in the log instead of breaking your chat.

| Key                                            | What it does                                                                                                                                                               |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `enabled`                                      | Master switch.                                                                                                                                                             |
| `rounds`                                       | 1 = one optimizer call. N > 1 = N parallel calls + 1 judge call (capped at 5).                                                                                             |
| `model.model`                                  | Optimizer model name.                                                                                                                                                      |
| `model.provider`                               | Any Hermes provider (`openrouter`, `anthropic`, `nous`, `custom:<name>`, …). Empty = your main provider. Ignored when `base_url` is set.                                   |
| `model.base_url`                               | Any OpenAI-compatible endpoint (vLLM, Ollama, LM Studio, a proxy, …). If it matches one of your `custom_providers`, that entry and its key are reused.                     |
| `model.api_key_env`                            | The _name_ of an env var holding the key. Put the secret in `~/.hermes/.env`, never in this file. Empty with a `base_url` that isn't a custom provider = no key is sent.   |
| `model.temperature` / `max_tokens` / `timeout` | Per-call settings (`timeout` in seconds, still bounded by the hook budget).                                                                                                |
| `judge_model`                                  | Optional different model for the judge; unset keys inherit from `model`.                                                                                                   |
| `prompts.default`                              | The optimizer's system prompt. `{target_model}` = the model that will answer.                                                                                              |
| `prompts.per_model`                            | Comma-separated globs → prompt, matched case-insensitively against the answering model (`"*claude*, anthropic/*"`). First match wins. `{base}` inserts the default prompt. |
| `prompts.judge`                                | The judge's system prompt.                                                                                                                                                 |
| `min_chars` / `max_chars`                      | Messages outside this range are sent untouched.                                                                                                                            |
| `context_messages`                             | How many recent chat messages the optimizer sees.                                                                                                                          |
| `show_in_cli`                                  | Print the optimized prompt in the classic CLI.                                                                                                                             |

Example: use a model through OpenRouter with the key Hermes already has:

```yaml
model:
  provider: openrouter
  model: google/gemini-2.5-flash
  base_url: ""
  api_key_env: ""
```

Example: a local Ollama server:

```yaml
model:
  provider: ""
  model: qwen2.5:7b
  base_url: http://127.0.0.1:11434/v1
  api_key_env: ""
```

## Test

The self-check uses fake model calls and a temporary `HERMES_HOME`, so it touches no real data:

```bash
git clone https://github.com/cosminfuica/hermes-prompt-optimizer && cd hermes-prompt-optimizer
~/.hermes/hermes-agent/venv/bin/python test_optimizer.py    # prints "ok: all self-checks passed"
hermes plugins doctor .                                      # manifest, import and registration
```

The warnings printed during the self-check are expected: they come from the bad-config and
failure cases it exercises.

## Troubleshooting

- **Nothing happens.** Check `hermes plugins list` shows it enabled in the profile you're chatting
  with, the message is at least `min_chars` long, and `enabled: true`. `/optimized` shows the last
  status and error.
- **"sent as typed (error: …)".** The optimizer endpoint, model name or key is wrong; the error text
  says which. Test the endpoint directly with `curl <base_url>/models`.
- **"sent as typed (late)" or time-budget errors.** Raise `plugins.hook_callback_timeout`, lower
  `rounds`, or use a faster optimizer model.
- **Every message rewritten twice.** Another optimizer plugin is enabled; disable it (Install step 4).

## License

MIT, see `LICENSE`.
