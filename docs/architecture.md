# Architecture and authoritative state

## First principles

The minimum research loop is:

1. define the question, scope, resources, and kill criteria;
2. retrieve and verify external evidence;
3. select falsifiable routes;
4. freeze an experiment contract before execution;
5. challenge results from an independent context;
6. write only claims supported by registered evidence;
7. retain enough state to reproduce, audit, archive, and safely clean the project.

A top-level Skill represents a stable user intent, not every internal step. Capabilities that are almost always used internally should not compete in semantic routing.

## Planes

- **Control plane:** `research-program-orchestrator`, project Gates, proposals, dashboard, and `.research/` state.
- **Research execution plane:** discovery, route evaluation, experiments, engineering, validation, writing, and communication.
- **Resource execution plane:** hardware, adaptive agents, and project hygiene.
- **System meta-layer:** Skill design, trigger evaluation, provenance, and harness adapters.

The orchestrator selects an owner, freezes inputs, records transitions, and surfaces safeguards. It does not perform specialist work merely because it knows that work exists.

## Repository layout

```text
skills/                 top-level capabilities eligible for Skill discovery
components/             internal evidence-ledger and dashboard components
rops/                   unified cross-platform CLI and internal command modules
config/                 framework paths, bundles, triggers, proposals, contracts
catalog/                generated Skill catalog for human/agent routing
tests/                  trigger fixtures and end-to-end smoke validation
templates/              one rendered project-agent policy template
release/                validation report and internal file manifest
docs/                   stable user and maintainer documentation
```

## Bootstrapped project state

```text
.research/
├── PROJECT.md           research question, scope, venue hypothesis, budgets
├── suite.lock.json      suite version and installation source
├── decisions.md         durable human/agent decisions
├── human_actions.md     open approvals and physical actions
├── governance/          project snapshot copied from package config
├── designs/             frozen experiment and method contracts
├── survey/              corpus, queries, source states, syntheses
├── runs/                manifests, logs, structured outputs, failures
├── evidence/            claim/evidence ledger and validated artifacts
├── agents/              model registry, dispatches, acceptance, profiles
├── proposals/           capability recommendations and decisions
├── hygiene/             inventory, archive/purge plans, registries
├── archive/             reversible retired content
├── trash/               quarantine before approved permanent purge
└── dashboard/           schema-versioned semantic project state
```

Root-level `task_plan.md`, `findings.md`, and `progress.md` are lightweight working views. Validated findings must be promoted into authoritative designs, evidence, or decisions rather than remaining only in transient notes.

## Authority rules

- Experiment design files are authoritative for hypotheses, variables, baselines, metrics, and stopping rules.
- Run manifests and immutable run IDs are authoritative for execution.
- The evidence ledger links claims to artifacts; a registered artifact is not automatically a scientifically valid interpretation.
- LaTeX source is editable authority for a manuscript; the rendered PDF is visual authority.
- Dashboard cards summarize state but do not replace underlying evidence.
- Chat history and terminal output are not authoritative unless captured into a registered artifact.

## Internal components

`evidence-ledger` and `dashboard` are components rather than top-level Skills because they are controlled by the orchestrator, used across many stages, and rarely represent a standalone user intent. This reduces trigger competition and startup catalog context.
