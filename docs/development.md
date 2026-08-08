# Development and release

## Choose the correct owner

Use `skill-system-engineering` when changing Skill boundaries, descriptions, progressive loading, permissions, Presets, hooks, native manifests, behavior packs, provenance, or release packaging.

Use `software-development` for ordinary development-led repository changes. Use `research-engineering` when code can alter research measurements, baselines, data transformations, or claims.

## Top-level Skill structure

```text
SKILL.md                 concise trigger and execution contract
references/              conditional long-form guidance
scripts/                 deterministic operations
assets/                  reusable non-code inputs
agents/openai.yaml       Harness metadata
evals/evals.json         positive/negative behavioral fixtures
LICENSE                  standalone license
```

Do not create empty directories. Keep the frontmatter name aligned with the directory and define both positive and negative trigger boundaries.

## Deterministic runtime boundaries

`rops/` is the thin deterministic runtime. Add code there for schema validation, migrations, atomic state changes, aggregation, routing-policy calculations, prompt compilation, risk/approval checks, Preset resolution, packaging, and validation.

Do not move open-ended research ideation, novelty judgment, manuscript writing, or visual creativity into deterministic Python merely to create a file for every concept.

A new module is justified when it has a distinct state owner or policy responsibility. Avoid both a single thousand-line control file and one-file-per-noun overdesign.

## Model Intelligence changes

Preserve these invariants:

1. SQLite is authoritative; JSONL is an exchange format.
2. One Evaluation Event is written once.
3. One profile engine owns all aggregation.
4. Projections are generated and read-only.
5. Probe/smoke does not update competence.
6. Endpoint health, current pricing and competence are distinct.
7. Failure observations remain linked to episodes while repeated patterns are aggregated.
8. Mitigation approval never grants high-risk operation approval.
9. External recall memory cannot mutate authoritative state.
10. New task facets do not automatically become group-by dimensions.

## Harness compatibility

Framework paths live in `config/frameworks.json`. Native manifests live in `.codex-plugin/`, `.claude-plugin/`, and `gemini-extension.json`; lifecycle adapters live in `hooks/`. Shared behavior/runtime logic must not be copied into three divergent implementations.

## Preset and packaging changes

`config/skill-bundles.json` is the Preset manifest despite its compatibility filename. A Preset assembles Skills, features/components and Behavior Packs. Add combination tests when changing it.

The release builder validates source, resolves a Preset, stages a filtered tree, filters trigger/provenance metadata, regenerates its catalog and integrity manifest, then creates a native or portable ZIP.

## Generated files

Do not hand-edit:

- `catalog/README.md` and `catalog/skills.json`;
- `release/MANIFEST.sha256`;
- `release/VALIDATION.md`;
- project-local Model Intelligence projections under `.researchops/intelligence/exports/`.

## Required checks

```bash
python3 -m compileall -q rops skills components behavior hooks tests
python3 -m rops validate
python3 tests/smoke.py
python3 tests/intelligence_smoke.py
python3 tests/behavior_smoke.py
python3 tests/model_control_plane_smoke.py
python3 tests/package_smoke.py
python3 -m rops package --out /tmp/researchops-release --preset full --target portable
```

The checks prove deterministic contracts and regression coverage, not empirical superiority of a router or Judge across all future models.

## Third-party content

No third-party Skill is vendored by default. To add one, pin the exact commit, preserve its license, audit executable/network behavior, install only the needed subtree, and update `PROVENANCE.json`, documentation, security notes and tests.

## Changelog policy

Record user-visible changes, deprecations, compatibility, migration and security changes. Do not use `CHANGELOG.md` as a commit log.
