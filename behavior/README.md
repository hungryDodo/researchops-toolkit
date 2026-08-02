# Behavior Runtime

The Behavior Runtime is the cross-cutting control plane of ResearchOps Toolkit. Skills describe **what workflow to perform**; the Behavior Runtime constrains **how any applicable task is performed**.

It is intentionally not a top-level Skill. It runs through lifecycle hooks or a middleware adapter before the model plans, before consequential tools execute, and when subagents start. Parent task classes and pack IDs can be inherited within the same session without persisting the raw parent prompt.

## Layers

1. **Kernel** — small universal rules: scope, evidence status, durable state, least privilege, and proposal-before-consequence.
2. **Behavior packs** — task-specific rules for coding, research, writing, hardware, hygiene, and delegation.
3. **Skills** — progressively loaded procedures, scripts, references, and artifact contracts.
4. **Specialist approval** — hardware, deletion, provider transfer, and similar operations retain their own explicit approval workflow.

## Modes

- `off`: runtime disabled.
- `observe`: metadata-only classification and audit.
- `guide`: default; injects compact relevant context and creates proposals, without hard-blocking ordinary work.
- `enforce`: additionally blocks deterministic high-risk operations without a matching content-bound approval.

The runtime never logs raw prompts or raw tool inputs by default. It records hashes, task classes, active packs, effects, and timestamps in `.research/runtime/`. High-risk approvals are exact-command, short-lived, concurrency-locked, and consumed once; normal approval creation requires a human-operated interactive terminal outside the Agent Harness.

## Why not MCP?

MCP is useful for external tools and shared state, but a model can choose not to call an MCP tool. Mandatory cross-cutting behavior therefore belongs in hooks, middleware, permissions, and compact always-on project policy—not in an optional tool call.
