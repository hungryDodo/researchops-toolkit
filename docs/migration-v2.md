# Migration to v2

## Single project root

v1 used `.research/` for project state and `.researchops/` for installed runtime. v2 uses one root:

```text
.researchops/state/      former `.research/` content
.researchops/runtime/    replaceable installed runtime
```

Run:

```bash
python3 -m rops bootstrap /path/to/project --title "Project" --upgrade
```

The migration is deterministic and covered by tests. Back up consequential projects before any tool-assisted migration.

## Model history

SQLite is authoritative in v2. Import an existing task-history JSONL:

```bash
python3 -m rops intelligence --root /path/to/project import-jsonl \
  /path/to/task-history.jsonl \
  --project-id PROJECT_ID
```

Duplicate event IDs are skipped; invalid lines are reported instead of silently discarded. Rebuild projections afterward if required:

```bash
python3 -m rops intelligence --root /path/to/project rebuild
```

## Bundles to Presets

The following remain compatible:

```text
rops bundles
--bundle research-core
research-core
minimal-control
all
```

New documentation uses:

```text
rops presets
--preset research-routed
```

## Model Control Plane

Provider calls, secrets, endpoint health and pricing now belong to Model Gateway. Evaluation, profiles, routing, failure patterns, mitigations, warmup, drift and Judge calibration belong to Model Intelligence. `rops models` remains a compatibility facade.
