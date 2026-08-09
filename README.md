# ResearchOps Toolkit

ResearchOps Toolkit is a modular **Research and Development workflow plugin** for Codex, Claude Code, Gemini CLI, and optional third-party model workers. It combines progressively loaded Skills, deterministic runtime services, task-aware behavior policies, evidence/state management, and project-scoped model evaluation and routing.

> It does not try to make one Agent “write a paper automatically.” It gives questions, work units, artifacts, evidence, model assignments, failures, costs, decisions, risks, and human approvals explicit owners and durable records.

Version 2.1 contains 13 top-level Skills, eight Behavior Packs, seven internal components, one SQLite-backed Model Intelligence core, native hook adapters, and filtered release Presets.

## Send this to your Agent

> Clone `git@github.com:hungryDodo/researchops-toolkit.git`, enter the repository, run `python3 -m rops inspect /path/to/project`, then `python3 -m rops bootstrap /path/to/project --title "My Project" --mode auto --upgrade`, install the `research-routed` Preset for your Harness, and use `python3 -m rops up --root /path/to/project --open` to review the adopted project state and Dashboard.

Replace `codex` with `claude`, `gemini`, `portable`, or `all` where appropriate.

## Quick start

```bash
git clone git@github.com:hungryDodo/researchops-toolkit.git
cd researchops-toolkit

python3 -m rops inspect /path/to/project

python3 -m rops bootstrap /path/to/project \
  --title "My Project" \
  --mode auto \
  --upgrade

python3 -m rops install \
  --target codex \
  --scope project \
  --project /path/to/project \
  --mode link \
  --preset research-routed \
  --with-agents \
  --with-behavior \
  --behavior-mode guide

python3 -m rops doctor --target codex --project /path/to/project
python3 -m rops up --root /path/to/project --open
```

On Codex, project installation preserves existing `.codex/hooks.json` groups while adding the
selected Behavior handlers. Codex still requires its normal user trust decision for new or changed
hooks.

The project receives one hidden root:

```text
.researchops/
├── state/          project designs, runs, evidence, decisions, dashboard state
├── governance/     project policies, registries, routing configuration
├── intelligence/   authoritative SQLite database and generated projections
├── runtime/        replaceable hooks, Behavior Runtime, and local runtime copy
├── artifacts/      large or generated local artifacts
├── cache/
└── logs/
```

There is no second `.research/` state directory in v2. Legacy projects are migrated into this single root.

ResearchOps does not assume that installing the plugin means starting from zero. `rops inspect` runs before writes. A non-empty repository is adopted without overwriting its files or adding root policy files by default; the deterministic inventory is then interpreted by the Research Program Orchestrator at a light, standard, or deep adoption depth. The inferred phase is visible immediately but remains explicitly reviewable.

## The important architectural distinction

Research, Development, and Routing are **not three equivalent workflow domains**:

- **Research-led R&D** and **Development-led R&D** are user-facing workflow orientations with different objective functions and acceptance rules.
- **Model Intelligence and Routing** are cross-cutting services that can support either workflow, Visual Communication, Hardware work, or a custom external task family.
- Communication/Visual, Hardware, Hygiene, and Skill-system maintenance remain separate domains where their artifacts, permissions, or risk boundaries differ materially.

```text
                         Installation Preset / native plugin
                                      │
                 ┌────────────────────┴────────────────────┐
                 │                                         │
        User-facing workflow Skills                 Behavior Runtime
 Research-led R&D · Development-led R&D       scope · evidence · risk · approval
 Communication · Hardware · Hygiene                         │
                 │                                         │
                 └────────────────────┬────────────────────┘
                                      │
                         Deterministic ROPS runtime
       Model Gateway · Model Intelligence · Engineering Assurance · Evidence
                                      │
                         canonical `.researchops/` state
                                      │
        routing · dossier · dashboard · benchmark · audit projections
                                      │
                      optional local/external recall adapters
```

## Why SQLite from the first event

Model evaluation records are relational, time-dependent, frequently updated, and queried by project, work-unit operation, model execution configuration, endpoint, Judge, failure pattern, and mitigation. ResearchOps therefore uses:

```text
.researchops/intelligence/state.sqlite
```

as the authoritative source from the first Evaluation Event. JSONL is supported only for import, export, audit, and reproducible research exchange:

```bash
python3 -m rops intelligence --root /path/to/project export-jsonl \
  --out /tmp/evaluation-events.jsonl

python3 -m rops intelligence --root /path/to/project import-jsonl \
  /tmp/evaluation-events.jsonl
```

One deterministic profile engine reads canonical events and regenerates all projections. Routing profiles and model dossiers no longer maintain separate aggregation logic.

## Model Intelligence at a glance

The independently installable Model Intelligence module provides:

- canonical live, shadow, and anchor Evaluation Events;
- finite task-conditioned profile slices rather than a high-dimensional Cartesian product;
- joint model × reasoning-effort arms, effort-demand fit, hard effort bounds, and executable Codex dispatch fields;
- task-conditioned single/Lead-worker/centralized-fanout topology instead of fixed company-style model personas;
- posterior success estimates, verified progress, quality, cost, latency, human correction, and uncertainty;
- separate endpoint-health, pricing, and declared/observed model-identity signals;
- project warmup, soft transfer, zero-start comparison, and negative-transfer rejection;
- aggregated failure patterns and scoped mitigation revisions;
- blind/pairwise Judge observations with task-family-conditioned calibration;
- black-box behavior-drift alerts and deployment epochs;
- read-only routing, dossier, dashboard, benchmark, and audit views;
- lifecycle-aware four-layer local Memory with scoped deduplication, temporal validity, supersession, provenance, project synchronization, and optional external adapters that never replace authoritative facts.

Connectivity probes and smoke tests update endpoint/identity telemetry only. They never teach the router that a model is competent.

## Project dashboard

`python3 -m rops up --root /path/to/project --open` is the one-command adoption/status/Dashboard path. The project-progress dashboard includes compact Intake, Memory, Routing, and Model Intelligence panels. It shows only information useful to a human operator:

- the current model preference and concise reason;
- recent model assignments and completed work;
- verified observations, success trend, cost, and service health;
- project adaptation/warmup progress;
- active behavior-drift warnings;
- selected failure patterns and mitigations when actionable.

Low-level score factors, posterior parameters, policy internals, and complete audit evidence remain available in generated projections rather than crowding the main view.

## Installation Presets

A Preset is an installation and packaging recipe. It is not a Git bundle, Git submodule, or code-ownership boundary.

```bash
python3 -m rops presets
python3 -m rops presets routing-core --format json
```

| Preset | Purpose |
|---|---|
| `routing-core` | Model gateway, evaluation, routing, drift, Judge calibration, warmup, and dashboard support |
| `development-core` | Development-led technical investigation, implementation, debugging, review, and release assurance |
| `research-base` | Research-led workflow without requiring dynamic multi-model routing |
| `research-routed` | `research-base` plus `routing-core`; default source-tree preset |
| `communication-visual` | Academic communication and optional visual-reference intake |
| `hardware` | Physical experiment workflow and hardware safety |
| `hygiene` | Archive-first repository/data lifecycle |
| `platform-dev` | Maintaining Skills, hooks, manifests, and the plugin system itself |
| `full` | All supported capabilities |

`rops bundles` and `--bundle` remain compatibility aliases.

## User-facing Skills and internal task codes

Users describe the goal in ordinary language or invoke a stable top-level Skill. Internal codes such as `discover`, `design`, `implement`, `debug`, `validate`, and `communicate` are machine-facing work-unit descriptors used by routing, evaluation, and Benchmark Packs. Users do not need to memorize them.

| Skill | Primary owner |
|---|---|
| `research-program-orchestrator` | lifecycle, gates, next owner, project progress |
| `research-discovery` | traceable survey, closest work, Related Work synthesis |
| `research-route-evaluator` | fatal-flaw checks and a bounded set of falsifiable routes |
| `experimental-research` | experiment contract, execution, analysis, evidence |
| `research-engineering` | research-led code whose behavior can affect claims or measurements |
| `software-development` | development-led investigation, implementation, debugging, review, release |
| `adaptive-agent-orchestration` | bounded delegation, model routing, independent acceptance |
| `research-validation` | reproduction, artifact audit, manuscript red-team review |
| `research-writing` | evidence-gated drafting and LaTeX revision |
| `research-communication` | publication figures, result plots, research presentations |
| `hardware-experiment-loop` | physical topology, calibration, leases, restoration |
| `project-hygiene` | archive, restore, quarantine, approved purge, worktrees |
| `skill-system-engineering` | Skill/Pack boundaries, triggers, hooks, provenance, release |

## Research-led and Development-led R&D

Both orientations share the same engineering skeleton:

```text
Frame → Investigate → Decide → Implement → Verify → Learn
```

Research-led work optimizes for valid knowledge and claim-to-evidence linkage; novel, expensive, or negative-result routes can remain useful. Development-led work optimizes for a reliable, maintainable, deployable deliverable and rejects complexity whose system-level value does not justify its cost. The shared `engineering-assurance` component provides task contracts, RED/baseline evidence, diff analysis, and risk-scaled verification; each Skill adds its own acceptance rules.

## Visual reference intake is optional

A user may send a reference image to any capable external vision model and ask it to produce the schema in `components/visual-contracts/visual-reference.schema.json` using `templates/visual-reference-analysis.md`. ResearchOps consumes the resulting design brief; it does not require the main Harness to have vision capability and does not copy brand-specific assets.

## Model and provider identity

An execution arm records model family/revision, endpoint, quantization or reasoning configuration, adapter/tool schema, Harness/prompt revision, mitigation bundle, and a local deployment epoch. When a closed provider exposes no immutable revision, ResearchOps cannot prove that hidden weights changed. It can detect sustained changes in observable behavior, format/tool compliance, latency, token use, anchor outcomes, and returned identity metadata, then isolate future evidence in a new deployment epoch.

## Memory boundary

ROPS owns authoritative state. Built-in Memory v2.1 adds episodic, semantic, procedural, and preference layers; candidate/active/superseded/retired lifecycle; source-aware deduplication; temporal validity; relations; project synchronization; and bounded provenance-bearing context bundles. Harness memory, vector stores, or temporal graph systems remain optional Recall Adapters. Retrieved memory cannot directly change a routing profile, approve a mitigation, replace current prices, or authorize a high-risk operation.

## Product evaluation and baselines

ResearchOps now evaluates the tool as well as the models it routes:

```bash
python3 -m rops evaluate \
  --baseline-root /path/to/older/researchops \
  --out /tmp/researchops-product-benchmark
```

The bundled deterministic suite measures non-destructive adoption, actual HTTP Dashboard startup, SQLite authority, and Memory lifecycle behavior. External products can be ingested through the standardized report contract, but a feature matrix is not treated as proof of superior performance. Paired Skill/Workflow studies and longitudinal project outcomes remain necessary for broader claims.

## Packaging and releases

Generate a filtered native artifact from the monorepo:

```bash
python3 -m rops package \
  --out /tmp/researchops-release \
  --preset routing-core \
  --target codex

python3 -m rops package \
  --out /tmp/researchops-release \
  --preset full \
  --target portable
```

Each archive contains only the selected Skills, components, and Behavior Packs; its own default Preset, catalog, native manifest, validation report, and SHA-256 manifest are regenerated inside the package.

## Documentation

| Document | Purpose |
|---|---|
| [Documentation index](docs/README.md) | Recommended reading paths |
| [Getting started](docs/getting-started.md) | Inspect/adopt, install, quick-start Dashboard, upgrade |
| [Architecture and state](docs/architecture.md) | Horizontal layers, vertical capability slices, authority |
| [Model Intelligence](docs/model-intelligence.md) | events, aggregation, projections, routing, drift, warmup, Judge |
| [Research agenda](docs/research-agenda.md) | research questions, baselines, metrics, ablations, and empirical boundaries |
| [Research and Development](docs/research-and-development.md) | research-led vs development-led objective functions |
| [Presets and distribution](docs/presets-and-distribution.md) | monorepo composition and filtered native artifacts |
| [Product landscape](docs/product-landscape.md) | Adjacent observability, research-agent, coding-agent, and memory systems |
| [Evaluation and baselines](docs/evaluation-and-baselines.md) | Tool regression, external adapters, paired Skill tests, routing and user studies |
| [State and memory](docs/state-and-memory.md) | `.researchops/`, SQLite authority, lifecycle-aware Memory and optional adapters |
| [Skills and progressive loading](docs/skills-and-bundles.md) | top-level ownership, internal modes, triggers |
| [Agents and model routing](docs/agents-and-model-routing.md) | provider setup, execution arms, dispatch and evaluation |
| [Safety and hygiene](docs/safety-and-hygiene.md) | lifecycle hooks, approvals, archive-first operations |
| [Migration to v2](docs/migration-v2.md) | legacy state and JSONL migration |
| [Development and release](docs/development.md) | tests, provenance, packaging, contribution |

Agents modifying this repository should read [`AGENTS.md`](AGENTS.md).

## Validation

```bash
python3 -m rops validate
python3 tests/smoke.py
python3 tests/intelligence_smoke.py
python3 tests/behavior_smoke.py
python3 tests/model_control_plane_smoke.py
python3 tests/model_effort_routing_smoke.py
python3 tests/adoption_memory_smoke.py
python3 -m rops evaluate --out /tmp/researchops-product-benchmark
python3 -m rops package --out /tmp/researchops-release --preset full --target portable
```

The tests validate deterministic structure and behavior. They do not prove that every future model/provider/Harness will route perfectly, that a closed provider did or did not change hidden weights, or that a research project will reach a particular venue.

## Provenance and license

ResearchOps Toolkit is released under the [MIT License](LICENSE). External projects and platform documentation informed design analysis, but no third-party Skill, prompt, script, template, handbook, or visual asset is vendored by default. See [`PROVENANCE.json`](PROVENANCE.json) for the machine-readable declaration.
