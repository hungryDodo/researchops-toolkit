---
name: research-engineering
description: >
  Use when a code change can alter research results, measurement, data transformation, baselines, cleanup, or reproducibility and therefore needs a specification, observed failure, risk-calibrated tests, and fresh evidence. Do not use for trivial formatting or disposable exploration.
---
# Research Engineering

## Trigger contract

Own high-assurance research code changes. It adapts the strongest useful old-coder/Ponytail patterns: approved specification, observed RED, minimum sufficient GREEN, risk-calibrated gauntlet, fresh evidence, and dependency restraint.

## Progressive loading

Read `references/GAUNTLET_PROTOCOL.md` for the full evidence requirements. Use `scripts/gauntlet.py` to create and validate specs and evidence bundles.

## Procedure

1. Write a compact SPEC: intended behavior, forbidden behavior, affected claims, interfaces, risk, and validation commands.
2. Obtain approval when the change affects frozen protocols or consequential data.
3. Observe a relevant failing case or explain why a RED state cannot safely be produced.
4. Prefer existing code, standard library, platform capability, installed dependency, consolidation, or deletion before adding infrastructure.
5. Implement the minimum sufficient change.
6. Run tests proportional to risk: unit, integration, differential, property, performance, hardware-in-loop, or recovery tests as applicable.
7. Capture freshly executed evidence; do not cite stale terminal output.
8. Reject gaming: weakening tests, changing metrics, skipping failures, or passing irrelevant checks.

## Output contract

Produce SPEC, approval, RED observation, implementation diff, dependency impact, executed checks, artifacts, residual risks, and affected claim/evidence links.
