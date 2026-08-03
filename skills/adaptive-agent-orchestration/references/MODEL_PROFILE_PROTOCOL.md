# Model dossier and prompt-overlay protocol

## Purpose

Maintain an evidence-backed, evolving profile for each exact provider/model identity without allowing worker self-assessment or onboarding smoke tests to become capability claims.

## Storage

- Registry: `.research/agents/models.json`
- Provider configuration without secrets: `.research/agents/providers.json`
- Evaluated task events: `.research/agents/task-history.jsonl`
- Routing aggregates: `.research/agents/profiles.json`
- Model dossiers: `.research/agents/model-profiles/<provider-model>.json`
- Onboarding plans/probes: `.research/agents/onboarding/`
- Smoke tests: `.research/agents/smoke/`

## Evidence hierarchy

1. Independently evaluated real task with deterministic checks and, when required, an independent verifier.
2. Human-corrected real task outcome.
3. Repeated task-family observations.
4. Human-authored operational note.
5. Onboarding smoke or model self-description — connectivity evidence only, never a skill profile signal.

## Dossier fields

Track exact model ID/version where available, observations, acceptance rate, verified quality, correction burden, verifier disagreement, latency/cost, task-specific strengths and weaknesses, recurring failure modes, human notes, and prompt-overlay revisions.

## Prompt overlays

The generated overlay is a small operational delta, not a replacement system prompt. It should state recurring precautions such as completeness checks, edge-case requirements, output format, or known blind spots. It must:

- derive only from verified history or explicit human notes;
- be versioned and reviewable;
- remain proposed until a human approves it;
- be injected after the base agent role and before task-specific instructions;
- never contain secrets, raw private prompts, or unsupported personality claims;
- be retired when later evidence no longer supports it.

## Learning loop

1. Route a bounded task.
2. Execute using base agent prompt plus the active model overlay.
3. Apply deterministic acceptance tests.
4. Obtain an independent verifier where required.
5. Record corrections, disagreement, failure attribution, latency, and cost.
6. Update routing aggregates and the dossier.
7. Propose an overlay change if a repeated pattern is supported.
8. Require human approval before activation.

Low-risk exploration may be used while uncertainty is high. Exploration must be bounded by privacy, risk, cost, mutability, and deterministic acceptance constraints.
