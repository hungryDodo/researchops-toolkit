# Behavior Runtime

Behavior Runtime applies cross-cutting policies without creating extra top-level Skills. Lifecycle hooks classify the current task, load only applicable Behavior Packs, and inspect exposed tool operations.

## Modes

- `off`: no injection, audit or decision;
- `observe`: metadata-only classification/audit;
- `guide`: compact guidance and proposals, no ordinary blocking;
- `enforce`: blocking for matched high/critical actions unless a content-bound one-use approval exists.

## Boundaries

- Hooks only cover lifecycle/tool paths exposed by the Harness.
- Platform sandbox, OS permissions, repository protection and hardware interlocks remain final authority.
- Logs retain hashes, categories and decisions rather than raw prompts/commands by default.
- A semantic reviewer may escalate but never clear deterministic risk.
- Prompt-mitigation approval is separate from operation approval.

## Project installation

A Preset's selected packs are copied into `.researchops/runtime/behavior/packs/`; the deterministic runtime and hooks live under `.researchops/runtime/` and can be replaced during upgrade without replacing project state.

Codex project installation also performs an idempotent merge into `.codex/hooks.json`; existing
operator hooks are preserved and only prior ResearchOps groups are refreshed. The user must review
and trust those hooks in Codex. Filtered native artifacts render the harness-specific conventional
hook file at package time so Codex and Gemini do not receive each other's event vocabulary.
