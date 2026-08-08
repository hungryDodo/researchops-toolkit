# Getting started

## Requirements

- Python 3.10 or newer;
- a local checkout or a native ResearchOps plugin artifact;
- Codex, Claude Code, Gemini CLI, or the portable Skill paths;
- project filesystem access appropriate to the requested operations.

No database server is required. SQLite is included in Python.

## Inspect before writing

ResearchOps does not assume the host repository is empty. Preview the intake first:

```bash
python3 -m rops inspect /path/to/project
```

The scanner reports observable repository/Git facts, a conservative adoption mode, an inferred phase, confidence, and remaining uncertainty. It does not modify the project.

## Bootstrap, adopt, migrate, or resume

```bash
python3 -m rops bootstrap /path/to/project \
  --title "My Project" \
  --mode auto \
  --upgrade
```

`--mode auto` selects `new`, `adopt`, `migrate`, or `resume`. A non-empty project is adopted non-destructively: existing files are preserved, only one `.researchops/` root is created, and the Dashboard starts from the inferred current phase rather than an empty charter. The research-program orchestrator then confirms/corrects the semantic state and chooses a light, standard, or deep adoption depth.

Use `--mode new` only for a truly new project. ResearchOps refuses to apply new-project initialization over a detected non-empty repository.

## Choose a Preset

```bash
python3 -m rops presets
python3 -m rops presets research-routed --format json
```

A typical Research project uses `research-routed`; a standalone model-evaluation/routing installation uses `routing-core`; a product/repository project can use `development-core`.

## Install into a Harness

```bash
python3 -m rops install \
  --target codex \
  --scope project \
  --project /path/to/project \
  --mode link \
  --preset research-routed \
  --with-agents \
  --with-behavior \
  --behavior-mode guide
```

Targets: `codex`, `claude`, `gemini`, `portable`, or `all`.

Modes:

- `link` keeps project Skill entries linked to the source checkout;
- `copy` creates an independent project copy and is suitable for packaged artifacts or systems where symlinks are undesirable.

Behavior modes:

- `off`: no guidance or audit;
- `observe`: metadata-only classification/audit;
- `guide`: compact applicable guidance and proposals; default;
- `enforce`: guide plus blocking for exposed high/critical operations without a matching one-use approval.

The platform sandbox and OS permissions remain the final authority.

## Inspect installation

```bash
python3 -m rops doctor --target codex --project /path/to/project
python3 -m rops intelligence --root /path/to/project status
python3 -m rops behavior --root /path/to/project status
```

## One-command status and Dashboard

```bash
python3 -m rops status --root /path/to/project
python3 -m rops up --root /path/to/project --open
```

`rops up` adopts/initializes the project when needed, builds the current projections, starts the live Dashboard, and optionally opens it. For direct control:

```bash
python3 -m rops dashboard start \
  --root /path/to/project \
  --host 127.0.0.1 \
  --port 8765 \
  --open
```

The server refreshes the read-only view on page requests and the browser refreshes periodically. It joins project progress, intake confidence, model assignments/routing, endpoint/cost summaries, warmup, failure/mitigation signals, and Memory status without exposing every internal score factor.

## Install only selected Skills

For advanced use:

```bash
python3 -m rops install \
  --target codex \
  --scope project \
  --project /path/to/project \
  --skills software-development,adaptive-agent-orchestration
```

Direct Skill selection bypasses Preset feature/Behavior composition and is therefore less convenient for ordinary users.

## Provider/model setup

Secrets are entered locally and must not be sent in chat or stored in project state:

```bash
python3 -m rops models --root /path/to/project secret-template
python3 -m rops models --root /path/to/project sync
python3 -m rops models --root /path/to/project doctor
```

A connectivity probe tests service/format behavior only. It does not update competence.

## Evaluate ResearchOps as a product

```bash
python3 -m rops evaluate \
  --baseline-root /path/to/older/researchops \
  --out /tmp/researchops-product-benchmark
```

This local deterministic benchmark measures non-destructive adoption, actual Dashboard quick start, SQLite authority, and Memory lifecycle behavior. External tools can be compared only through an equivalent adapter report; see [Evaluation and baselines](evaluation-and-baselines.md).

## Upgrade

1. update the source checkout or install a newer native artifact;
2. run `bootstrap --upgrade` to migrate state/layout;
3. rerun `rops install` with the intended Preset;
4. run `rops validate`, `doctor`, and the relevant smoke checks;
5. inspect `.researchops/suite.lock.json` and Dashboard migration results.

## Multi-host use

The authoritative SQLite database is local to a project root. Do not place one SQLite file on an unsafe network filesystem or let multiple hosts mutate independent copies. For a coordinated team deployment, use one owner process or implement the `StateStore` boundary with a transactional server database in a later deployment profile. Large artifacts can use shared object storage while retaining hashes and provenance locally.
