hermes-prompt-optimizer installed.

1. Point it at your optimizer model: in a chat, type `/optimizer` and set `model.model` and
   `model.base_url` (or `model.provider`, with `model.base_url ""`). Or edit `config.yaml` in the
   installed plugin folder (`$HERMES_HOME/plugins/hermes-prompt-optimizer/config.yaml`), the
   `model:` section.
2. Enable it if you didn't at the prompt: `hermes plugins enable hermes-prompt-optimizer`
3. For `rounds > 1` or a slow optimizer: `hermes config set plugins.hook_callback_timeout 90`
4. Desktop banner (optional): Capabilities → Plugins (Settings → Plugins before Hermes v0.21.2) → enable Prompt Optimizer.

Check it: send a message of 12+ characters and run `/optimized`.
