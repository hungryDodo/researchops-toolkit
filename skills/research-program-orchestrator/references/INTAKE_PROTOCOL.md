# Existing-project intake protocol

ResearchOps must never assume that installing the plugin means the host project is new.
The default entry path is **inspect before write**.

## Two-layer intake

### 1. Deterministic repository assessment

`rops inspect` records observable facts without interpreting scientific meaning:

- existing ResearchOps or legacy state;
- file and directory inventory;
- source, tests, experiments, results, manuscript, data, and configuration signals;
- Git branch, commit, dirty state, and latest commit when available;
- a conservative inferred phase, confidence, and blocking uncertainty;
- a digest that makes later changes auditable.

The scanner may infer a likely phase. It may not declare that a claim is valid, that an
experiment is complete, or that the project should restart.

### 2. Agent/human adoption review

The orchestrator reads `.researchops/state/onboarding/current.json`, samples the
representative artifacts named there, and confirms or corrects:

- the actual objective and current phase;
- completed, active, abandoned, and uncertain workstreams;
- artifacts that should be registered rather than recreated;
- current decisions, claims, evidence, tests, and blockers;
- the smallest next work unit and its specialist owner.

Record corrections as project decisions or a new onboarding snapshot. Do not edit the
scanner output to manufacture certainty.

## Adoption depth

Choose the least expensive depth that protects the requested work.

### Light adoption

Use when the project is mature, the request is narrow, and existing state can be treated
as read-only context. Register only the active branch, the next work unit, its acceptance
criteria, and the artifacts needed to verify it.

### Standard adoption — default

Map active workstreams, current phase, near-term milestones, key decisions, relevant
tests/experiments, claim–evidence status, and open human actions. This is appropriate for
most repositories that begin using ResearchOps mid-project.

### Deep adoption

Use only when publication, reproducibility, safety, external release, or a high-risk
change requires historical reconstruction. Trace data lineage, protocol revisions,
negative results, superseded decisions, and unresolved evidence gaps.

The agent recommends a depth from risk, requested scope, and evidence requirements.
A deep adoption that consumes substantial time or accesses sensitive artifacts requires
explicit user agreement.

## Mode-specific behavior

- `new`: create a new charter and empty project state. Refuse this mode over a non-empty
  project unless the user explicitly moves to a new root.
- `adopt`: preserve all host files, create only `.researchops/`, and seed status from the
  assessment rather than `charter`.
- `migrate`: move legacy ResearchOps state into the current layout, preserve backups and
  provenance, then run the adoption review.
- `resume`: read the current ResearchOps state and assess changes since the last snapshot.

## Non-destructive rules

1. Do not overwrite project files during intake.
2. Do not add root policy files or modify the root `.gitignore` unless explicitly asked.
3. Do not import every historical file into Memory; register representative, useful,
   provenance-bearing summaries.
4. Do not mark inferred completion as verified completion.
5. Do not discard existing plans merely because they do not match the default workflow.
6. Make the Dashboard useful immediately, but show that inferred status still needs
   confirmation.

## Output contract

Return:

- detected mode and assessment confidence;
- current phase, with observed evidence and uncertainty separated;
- selected adoption depth and why;
- artifacts registered or intentionally left untouched;
- one next work unit and specialist owner;
- any human confirmation required.
