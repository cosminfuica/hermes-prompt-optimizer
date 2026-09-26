"""hermes-prompt-optimizer — a small model rewrites each message before your Hermes model answers it.

Flow (``pre_llm_call`` hook, once per user turn):
  your message ─► N optimizer calls (parallel) ─► judge picks the best (N > 1) ─► appended to the
  API copy of your message. The transcript keeps exactly what you typed; the optimized prompt is
  shown in the classic CLI, in the desktop composer banner (desktop/plugin.js) and via /optimized.

This file only wires the plugin into Hermes; the code lives in optimizer/, the settings in
config.yaml (created from config.yaml.example on install).
"""

from .optimizer.command import optimizer_command
from .optimizer.hook import command, on_pre_llm_call


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_command("optimized", command, description="Show the last optimized prompt",
                         args_hint="[session_id]")
    # No argument_mode: that parameter only exists since Hermes v0.21.0 and would break v0.20.x.
    ctx.register_command("optimizer", optimizer_command, description="View and change prompt-optimizer settings",
                         args_hint="[show|set <key> <value>|reset [key]|on|off|help]")
