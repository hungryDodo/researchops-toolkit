---
name: adaptive-agent-orchestration
description: >
  Use when research work can be split into independently verifiable subtasks, routed across models or providers, when a provider/model must be onboarded, or when worker performance must be evaluated and learned from. Do not use for tiny edits, concurrent writes to shared state, secret collection in chat, or worker self-approval.
---
# Adaptive Agent Orchestration

## Trigger contract

Own decomposition, provider/model onboarding, worker selection, bounded handoff, independent acceptance, and evidence-backed model dossiers. Routing and evaluation remain together because a dispatch must close with an acceptance event before it can teach the router.

Provider setup is a low-frequency `provider-onboarding` mode of this Skill. It is not another always-visible top-level Skill. Secret-safe protocol mechanics live in the Model Control Plane component.

## Progressive loading

Read only the reference needed for the active operation:

- provider/model setup: `references/PROVIDER_ONBOARDING.md`;
- task/model routing: `references/ROUTING_PROTOCOL.md`;
- bounded handoff: `references/HANDOFF_SCHEMA.md`;
- independent evaluation: `references/EVALUATION_PROTOCOL.md`;
- model dossiers and prompt overlays: `references/MODEL_PROFILE_PROTOCOL.md`.

Use scripts only for the active operation:

- `python3 -m rops models ...` performs provider onboarding, secret-safe diagnostics, probes, enrollment, dispatch, smoke tests, and dossier maintenance;
- `scripts/agent_registry.py` initializes, recommends, records verified outcomes, and refreshes dossiers;
- `scripts/render_native_agents.py` emits Codex/Claude/Gemini agent files with only approved model overlays;
- `scripts/evaluate_dispatch.py` applies deterministic and independent-verifier gates;
- `scripts/model_gateway.py` is retained as a minimal OpenAI-compatible adapter example; prefer the Model Control Plane for normal operation.

## Procedure

1. For a new provider/model, verify current official documentation and create a non-secret onboarding plan. Never request or store the raw key in chat, Git, Skills, or `.research/`.
2. After the user installs the key locally, run doctor, model discovery when available, connectivity probe, enrollment, and smoke tests.
3. Decompose only tasks with independent inputs, write scopes, resources, and acceptance tests.
4. Hard-filter privacy, tools, mutability, risk, hardware access, provider approval, and cost ceiling.
5. Select model and reasoning effort from task type plus verified history. Low-risk deterministic tasks may explore cautiously while evidence is sparse.
6. Send minimum context and store large artifacts on disk. External dispatch is a Behavior Runtime policy event.
7. Run deterministic checks, then an independent verifier when required. Worker self-score never accepts work.
8. Record corrections, disagreement, cost, latency, failure attribution, and disposition.
9. Update profiles only from independently evaluated real tasks. Generate model-specific prompt changes as proposals and require human approval before injection.

## Output contract

For onboarding, produce official-doc findings, non-secret provider/model plan, exact secret location, probe/smoke records, trust/risk limits, and candidate-agent registration.

For dispatch, produce task contract, selected worker/verifier, rationale, bounded handoff, artifacts, acceptance result, correction record, cost/latency, failure mode, routing-profile update, and model-dossier/prompt-overlay status.
