---
name: research-validation
description: >
  Use when results, artifacts, claims, or a mature manuscript need an independent reproduction, audit, or venue-style red-team review. Do not use from the same context that proposed and implemented the work, or as a substitute for missing experiments.
---
# Research Validation

## Trigger contract

Own independent challenge work. Reproduction and manuscript review share the same isolation requirement, severity model, evidence access, and prohibition on author self-approval, so they are modes rather than separate top-level Skills.

## Progressive loading

- `reproduce` or `artifact-audit`: `references/REPRODUCTION_PROTOCOL.md`;
- `paper-review`: `references/PEER_REVIEW_PROTOCOL.md`.

Load one mode and use a fresh context or explicitly independent agent.

## Reproduce / artifact-audit

Rebuild the environment from declared manifests, rerun representative and headline claims, compare exact artifacts and statistical conclusions, inspect leakage and exclusions, and distinguish reproducibility failure from scientific disagreement.

## Paper-review

Classify paper paradigm and target venue, then evaluate problem significance, novelty, technical soundness, evidence adequacy, attribution, reproducibility, limitations, writing, figures, citation completeness, and venue fit. Use CRITICAL/MAJOR/MINOR findings with attack paths and rebuttal risk.

## Rules

- Do not inherit the author's conclusion as a premise.
- Do not turn absence of retrieved work into proof of novelty.
- Do not call prose polish a scientific fix.
- A paper review cannot replace reproduction of central numeric claims.
- Findings link to evidence and exact locations.

## Output contract

Return mode, independent context identity, scope, reproduced checks, discrepancies, severity findings, confidence, missing evidence, acceptance/blocking decision, and required next actions.
