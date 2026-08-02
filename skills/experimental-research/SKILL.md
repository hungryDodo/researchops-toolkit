---
name: experimental-research
description: >
  Use when freezing an experiment contract, executing approved software experiments, analyzing results, and registering reproducible evidence. Do not use for physical hardware actuation, unapproved protocol changes, or retrofitting metrics after results are visible.
---
# Experimental Research

## Trigger contract

Own the software experiment lifecycle. Design and execution remain distinct **modes inside one Skill** because they share the same hypothesis, contract, run manifest, and evidence artifacts, while a hard gate prevents design drift.

## Progressive loading

- `design` mode: `references/DESIGN_PROTOCOL.md`;
- `execute` and `analyze` modes: `references/EXECUTION_PROTOCOL.md`.

Load only one mode at a time. Execution requires an approved design hash.

## Design mode

Define hypothesis, units, independent/dependent/control variables, baselines, metrics, workload, environment, repetitions, statistics, ablations, budgets, stop/kill criteria, artifact retention, and analysis plan. Distinguish exploratory from confirmatory work.

## Execute mode

1. Verify the approved contract and environment.
2. Use `scripts/capture_run.py` to record commands, code/data/config hashes, environment, timestamps, failures, and artifacts.
3. Do not silently change metrics, exclusions, seeds, or baselines.
4. Record failed and negative runs.
5. Isolate parallel runs by output directory and resource lease.

## Analyze mode

Apply the frozen analysis plan, quantify uncertainty, check sensitivity and attribution, generate compact derived tables/figure data, and register evidence. Any post-hoc analysis is labeled exploratory and cannot replace the confirmatory result.

## Escalation

Physical devices, power, radios, profilers, exclusive boards, or unsafe actuation route to `hardware-experiment-loop`. Research-critical code changes may invoke `research-engineering` before execution.

## Output contract

Produce an experiment contract, design hash, run manifests, structured results, analysis artifacts, deviations, failed-run ledger, evidence links, and next decision.
