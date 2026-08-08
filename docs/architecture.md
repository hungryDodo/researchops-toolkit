# Architecture and authoritative state

## First principles

1. A stable user intent owns a top-level Skill; every internal step does not become a Skill.
2. A canonical fact is written once and can feed many generated views.
3. Research-led and Development-led R&D share an engineering skeleton but optimize different outcomes.
4. Model routing is a cross-cutting service, not a third domain workflow equivalent to Research and Development.
5. Project state must remain usable without a closed Harness memory service.
6. Store rich evidence, but aggregate only dimensions that change eligibility, verification, risk, or predictive value.
7. Human-readable summaries are projections, not editable sources of truth.

## Horizontal responsibility layers

```text
Distribution
  native Codex / Claude Code / Gemini plugin artifacts
        ↓
Project Intake / Adoption
  inspect-before-write facts plus agent/human semantic confirmation
        ↓
Workflow Skills
  stable user intents and acceptance contracts
        ↓
Behavior Runtime
  task classification, compact guidance, risk and approval checks
        ↓
Deterministic Runtime Components
  model gateway, model intelligence, engineering assurance, evidence, dashboard
        ↓
Canonical Project State
  SQLite plus registered project artifacts
        ↓
Read-only Projections
  routing, dossier, dashboard, benchmark, audit
        ↓
Optional Recall
  FTS, vector or external Harness memory adapters
```

Dependencies point downward. A domain Skill can register task/evaluator metadata with Model Intelligence, but Model Intelligence does not import Research- or Development-specific workflow code.

## Vertical capability slices

A user-visible product variant is assembled across the horizontal layers:

| Capability slice | Workflow owner | Cross-cutting support |
|---|---|---|
| Research-led R&D | research Skills | evidence, engineering assurance, optional routing |
| Development-led R&D | `software-development` | engineering assurance, optional routing |
| Communication / Visual | `research-communication` | visual contracts, optional visual model routing |
| Hardware | `hardware-experiment-loop` | evidence, leases, safety approval |
| Hygiene | `project-hygiene` | archive-first policy and audit |
| Platform development | `skill-system-engineering` | trigger, manifest, provenance, release validation |
| Model evaluation/routing | `adaptive-agent-orchestration` | model gateway + model intelligence; reusable by all slices |

A Preset is a tested selection across these layers. Code ownership remains horizontal and is not duplicated per Preset.

## Existing-project adoption

Plugin installation is not equivalent to project creation. Before writing state, `rops inspect` inventories the repository and selects a conservative mode: `new`, `adopt`, `migrate`, or `resume`. The deterministic scanner reports facts and uncertainty; `research-program-orchestrator` samples representative artifacts, confirms/corrects the phase, chooses an adoption depth, registers useful existing work, and names the smallest next work unit. It never recreates artifacts merely to force the project into the default pipeline.

Adoption is non-destructive by default: one `.researchops/` directory is added, root project files and `.gitignore` are not modified, and inferred completion is never treated as verified evidence.

## Source repository layout

```text
researchops-toolkit/
├── skills/                 progressively loaded user-facing workflow owners
├── behavior/               cross-cutting packs and portable lifecycle runtime
├── hooks/                  Harness lifecycle adapters
├── components/             deterministic shared services and schemas
├── rops/                   thin deterministic CLI/runtime layer
├── config/                 Presets, framework paths, triggers, contracts
├── catalog/                generated Skill catalog
├── templates/              project and optional visual-reference templates
├── tests/                  structural, behavior, intelligence, end-to-end tests
├── release/                validation evidence and integrity manifest
└── docs/                   stable user and maintainer documentation
```

`rops/` contains deterministic Python because schemas, migrations, aggregation, policy decisions, package resolution, atomic writes, and release validation must be reproducible. Open-ended research reasoning, novelty judgment, writing, and visual creativity stay in Skills or external models.

## One hidden project root

```text
.researchops/
├── suite.lock.json
├── state/
│   ├── PROJECT.md
│   ├── decisions.md
│   ├── human_actions.md
│   ├── designs/
│   ├── survey/
│   ├── runs/
│   ├── evidence/
│   ├── agents/
│   ├── proposals/
│   ├── hygiene/
│   ├── archive/
│   ├── trash/
│   └── dashboard/
├── governance/
├── intelligence/
│   ├── state.sqlite
│   └── exports/
├── runtime/
├── artifacts/
├── cache/
└── logs/
```

The project root receives no sibling `.research/` directory in v2. `state/` contains project-owned human/audit artifacts; `intelligence/state.sqlite` is authoritative for model-intelligence facts; `runtime/` is replaceable.

## Canonical facts and projections

There is not one universal table for everything. Each semantic fact has one authority:

| Fact domain | Authority |
|---|---|
| Work-unit evaluation | `evaluation_events` in SQLite |
| Endpoint observations | `endpoint_observations` |
| Effective-dated prices | `pricing_rules` |
| Identity/drift observations | identity and deployment-epoch tables |
| Failure observations/patterns | failure tables |
| Mitigations and approvals | governance tables |
| Experiment designs and evidence artifacts | `.researchops/state/` artifacts and ledger |

The profile engine is a deterministic pure aggregation path:

```text
validated event
  → append to SQLite
  → finite profile aggregation
  → canonical profile snapshot
  → routing / dossier / dashboard / benchmark / audit projections
```

Projections include `generated`, `do_not_edit`, aggregator version, event count, and input digest. UI actions write new facts or governance events; they never patch a generated profile.

## Deliberately finite task conditioning

Evaluation Events can retain rich metadata, but v2 aggregates only:

1. arm global;
2. arm × primary operation;
3. arm × project × primary operation;
4. arm × orientation × primary operation.

A new dimension enters routing only after it demonstrates predictive or eligibility value and avoids sparse-bucket explosion. `unknown` is a valid value when a project has not yet discovered its stack or method.

## Authority rules

- Chat history and terminal scrollback are not authoritative unless captured.
- A model dossier summarizes facts; it is not edited directly.
- Prompt-mitigation approval never authorizes a destructive or high-risk operation.
- Provider probes update service/identity telemetry, not competence.
- External memory can suggest relevant history but cannot alter profiles or approvals.
- Dashboard cards summarize state and never replace evidence or audit records.
