# Skills, progressive loading, and Presets

## Discovery model

A Harness initially sees a compact catalog containing each top-level Skill's name, description, and path. It loads the full `SKILL.md` only after semantic matching or explicit invocation. The Skill then loads only references, scripts and assets required for the current mode.

`SKILL.md` is a routing/execution page, not a complete handbook.

## Top-level granularity

Create a new top-level Skill only when most conditions hold:

1. users recognize a distinct intent;
2. it owns a clear artifact/acceptance family;
3. its tools, permissions or risk boundary differ materially;
4. positive and negative trigger fixtures can isolate it;
5. delayed loading saves meaningful context;
6. it is not almost always invoked together with another Skill.

Closely related actions become modes. Deterministic cross-workflow services become components. Cross-cutting execution constraints become Behavior Packs.

## Current owners

| Skill | Modes / outputs |
|---|---|
| `research-program-orchestrator` | lifecycle, Gate, next owner, progress, proposal |
| `research-discovery` | survey, closest work, source ledger, synthesis |
| `research-route-evaluator` | fatal flaw, bounded routes, decisive test |
| `experimental-research` | design contract, run, analysis, evidence |
| `research-engineering` | research-led code and result validity |
| `software-development` | development-led investigation, implementation, debug, refactor, review, release |
| `adaptive-agent-orchestration` | work-unit contract, route, dispatch, independent acceptance |
| `research-validation` | reproduction, artifact audit, red-team review |
| `research-writing` | evidence-gated draft, LaTeX and feedback ledger |
| `research-communication` | paper figure, result plot, research deck |
| `hardware-experiment-loop` | topology, preflight, calibration, lease, restore |
| `project-hygiene` | inventory, archive, restore, quarantine, purge |
| `skill-system-engineering` | Skill/Pack design, triggers, hooks, provenance, release |

## Internal operation codes

Research discovery, problem formulation, route design, experiment analysis, failure diagnosis, validation, writing and figure design do not each become a user-facing plugin name. Internal operation codes are attached to work units for routing/evaluation. The Harness or orchestrator infers them, and the Dashboard may display them for explanation.

Users can still explicitly choose a Skill when they want control, but normal natural-language requests should not require taxonomy memorization.

## Behavior Packs

Behavior Packs apply across Skills and are selected by task signals and the installed Preset:

- coding minimal change;
- coding evidence;
- research integrity;
- writing claim discipline;
- hardware safety;
- archive-first hygiene;
- delegation quality;
- visual consistency.

They do not compete in the top-level Skill catalog.

## Presets

Presets limit installation surface and produce tested product combinations:

```bash
python3 -m rops presets
```

`Bundle` remains a compatibility alias because v1 used that term. See [`presets-and-distribution.md`](presets-and-distribution.md) for the difference between a Preset, Git bundle, submodule, and release artifact.

## Trigger evaluation

Descriptions include positive and negative boundaries. Structural fixtures check ownership coverage:

```bash
python3 -m rops validate
```

These fixtures do not prove empirical routing accuracy for every Harness/model release. Production traces should be evaluated separately through Model Intelligence.
