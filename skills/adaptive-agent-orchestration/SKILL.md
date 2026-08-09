---
name: adaptive-agent-orchestration
description: >
  Use when research work can be split into independently verifiable subtasks, routed across models or providers, or when returned worker performance must be evaluated and learned from. Do not use for tiny edits, concurrent writes to shared state, or worker self-approval.
---
# Adaptive Agent Orchestration

## Trigger contract

Own task-space decomposition, coordination topology, Lead/worker execution-arm selection, handoff, independent acceptance, and task-specific performance profiles. Routing and evaluation are one Skill because every dispatch must close with an acceptance event before it can teach the router. An execution arm is a model plus effort and the rest of its behaviorally meaningful configuration, not just a marketing model name.

## Progressive loading

- task/model routing: `references/ROUTING_PROTOCOL.md`;
- external provider/API onboarding: `references/PROVIDER_ONBOARDING.md`;
- bounded handoff: `references/HANDOFF_SCHEMA.md`;
- independent evaluation and profile updates: `references/EVALUATION_PROTOCOL.md`.

Use scripts only for the active operation:

- `scripts/agent_registry.py` initializes, recommends, and records outcomes; use `recommend --no-write --compact` for sandbox-safe, context-efficient route inspection;
- `scripts/render_native_agents.py` emits Codex/Claude/Gemini native agent files;
- `scripts/evaluate_dispatch.py` applies deterministic and verifier gates;
- `scripts/model_gateway.py` calls approved OpenAI-compatible providers.

## Procedure

1. Characterize reasoning demand, decomposability, dependency structure, tool intensity, shared state, risk, and acceptance evidence.
2. Keep sequential or shared-state work in one context. Split only independent work units with distinct inputs, write scopes, resources, and acceptance tests.
3. Use a session Lead for a justified fan-out, not as a permanent business department. Route the Lead itself with operation `orchestrate`.
4. Hard-filter privacy, tools, mutability, risk, hardware access, provider approval, model/effort support, and cost ceiling.
5. Select a model × reasoning-effort arm from declared priors plus verified history. Low-risk deterministic tasks may explore cautiously; maximum effort is never automatic.
6. Send minimum context and store large artifacts on disk. Descendant delegation requires an explicit handoff grant and depth/budget limit.
7. Run deterministic checks, then a fresh-context independent verifier when required. Worker self-score never accepts work.
8. Record the exact arm, corrections, disagreement, cost, latency, failure attribution, and disposition.
9. Update a profile only from accepted, independently evaluated events.

## Output contract

Produce topology, task contract, selected Lead/worker/verifier execution arms (including model and effort), rationale, bounded handoff, artifacts, acceptance result, correction record, cost/latency, failure mode, and profile update.
