---
name: adaptive-agent-orchestration
description: >
  Use when research work can be split into independently verifiable subtasks, routed across models or providers, or when returned worker performance must be evaluated and learned from. Do not use for tiny edits, concurrent writes to shared state, or worker self-approval.
---
# Adaptive Agent Orchestration

## Trigger contract

Own decomposition, worker/model selection, handoff, independent acceptance, and task-specific performance profiles. Routing and evaluation are one Skill because every dispatch must close with an acceptance event before it can teach the router.

## Progressive loading

- task/model routing: `references/ROUTING_PROTOCOL.md`;
- bounded handoff: `references/HANDOFF_SCHEMA.md`;
- independent evaluation and profile updates: `references/EVALUATION_PROTOCOL.md`.

Use scripts only for the active operation:

- `scripts/agent_registry.py` initializes, recommends, and records outcomes;
- `scripts/render_native_agents.py` emits Codex/Claude/Gemini native agent files;
- `scripts/evaluate_dispatch.py` applies deterministic and verifier gates;
- `scripts/model_gateway.py` calls approved OpenAI-compatible providers.

## Procedure

1. Decompose only tasks with independent inputs, write scopes, resources, and acceptance tests.
2. Hard-filter privacy, tools, mutability, risk, hardware access, provider approval, and cost ceiling.
3. Select model and reasoning effort from task type plus verified history; low-risk deterministic tasks may explore cautiously.
4. Send minimum context and store large artifacts on disk.
5. Run deterministic checks, then an independent verifier when required. Worker self-score never accepts work.
6. Record corrections, disagreement, cost, latency, failure attribution, and disposition.
7. Update a profile only from accepted, independently evaluated events.

## Output contract

Produce task contract, selected worker/verifier, rationale, bounded handoff, artifacts, acceptance result, correction record, cost/latency, failure mode, and profile update.
