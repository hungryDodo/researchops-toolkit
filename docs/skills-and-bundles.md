# Skills, progressive loading, and bundles

## Discovery model

The harness initially sees a compact catalog containing each Skill's name, description, and path. It should load the full `SKILL.md` only after semantic matching. The Skill then conditionally points to the references, scripts, and assets required by the current mode.

`SKILL.md` is therefore a routing and execution page, not a handbook. Long checklists and domain guidance belong in `references/`; deterministic operations belong in `scripts/`.

## Trigger design

Descriptions state both positive and negative boundaries:

```yaml
description: >
  Use when ...
  Do not use when ...
```

Keywords are useful for regression fixtures and diagnostics, but they are not the sole runtime trigger. The system combines semantic descriptions, owner boundaries, positive/negative fixtures, explicit invocation for consequential capabilities, and orchestrator-directed handoffs.

## Granularity rule

Create a new top-level Skill only when most of these are true:

1. users recognize it as a distinct intent;
2. it owns a clear authoritative artifact family;
3. it has different tools, permissions, or risk boundaries;
4. positive and negative trigger fixtures can isolate it;
5. delayed loading meaningfully reduces context;
6. it is not almost always invoked with another Skill.

Closely related operations become modes within one Skill. Always-on internal capabilities become components. Hardware remains separate because its physical permissions and recovery requirements are fundamentally different.

## Skill ownership

| Skill | Typical modes / outputs |
|---|---|
| `research-program-orchestrator` | phase owner, Gate, next action, proposal, dashboard patch |
| `research-discovery` | survey, closest work, related-work synthesis, source ledger |
| `research-route-evaluator` | fatal-flaw check, Top 1–3, minimum decisive experiment |
| `experimental-research` | design contract, run manifest, analysis, evidence registration |
| `hardware-experiment-loop` | topology, preflight, calibration, lease, safe restore |
| `research-engineering` | SPEC, observed failure, implementation, gauntlet evidence |
| `adaptive-agent-orchestration` | task contract, dispatch, verifier, model profile |
| `research-validation` | reproduction, artifact audit, venue-style red-team review |
| `research-writing` | evidence-gated draft, LaTeX revision, feedback ledger |
| `research-communication` | figure source, diagram, result plot, research deck |
| `project-hygiene` | inventory, archive, restore, quarantine, purge, worktree plan |
| `skill-system-engineering` | Skill design, trigger policy, evals, provenance, adapters |

The generated [`../catalog/README.md`](../catalog/README.md) is the authoritative catalog of current descriptions.

## Bundles

Bundles limit startup catalog context and installation surface. List them with:

```bash
python3 -m rops bundles
```

The installer defaults to `research-core`. Install `hardware`, `hygiene`, or `platform-dev` only when the project reaches those stages. Full installation is useful for maintainers and audits, not as a universal default.

## Explicit versus implicit invocation

Low-risk, narrow Skills may be invoked through semantic matching. High-risk or meta-level Skills prefer explicit invocation or a capability proposal. This is a discovery/execution trade-off, not a reason to hide functionality: the orchestrator surfaces relevant dormant capabilities at meaningful hinges without loading or executing them.

## Evaluation

Run structural trigger evaluation after changing names, descriptions, owner boundaries, bundles, or modes:

```bash
python3 -m rops validate
```

Fixtures verify coverage and overlap in the repository. Real routing accuracy must still be evaluated for each harness/model version used in production.
