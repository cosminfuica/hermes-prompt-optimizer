"""The Python half of hermes-prompt-optimizer.

  config   config.yaml loading and the per-model prompt pick
  engine   the rewrite: N optimizer calls in parallel, a judge picks the best
  history  recent results per chat, read by /optimized and the desktop banner
  hook     Hermes wiring: the pre_llm_call hook, skip rules, the /optimized command
"""

PLUGIN_ID = "hermes-prompt-optimizer"
