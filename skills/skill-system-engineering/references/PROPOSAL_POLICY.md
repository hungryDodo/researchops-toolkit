# Proposal policy for consequential capabilities

Use a proposal broker instead of either extreme:

- implicit execution risks accidental destructive/high-cost actions;
- explicit-only invocation hides useful capabilities and depends on memory.

The broker keeps a compact registry loaded by the orchestrator only at stage hinges. It emits proposals with reason, scope, cost, prerequisites, and approval needs. It supports dismiss/snooze to avoid repeated prompts. It never loads the full target Skill or executes it.

Use `propose_before_execute` for hardware, independent publication decisions, large cleanup, external model providers with private data, and irreversible operations. Use `explicit_only` for final purge/force-like actions. Low-risk skills may remain semantic/implicit.
