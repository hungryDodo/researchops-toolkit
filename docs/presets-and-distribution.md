# Presets and distribution

## What a Preset is

A Preset is a tested installation and packaging recipe containing:

- top-level Skills;
- deterministic feature/components;
- applicable Behavior Packs.

It lowers user choice complexity and startup catalog size while preserving independent capability combinations.

```bash
python3 -m rops presets
python3 -m rops presets research-routed --format json
```

`Bundle` remains a CLI compatibility term. It is unrelated to Git bundle files.

## What a Preset is not

- It is not a code ownership boundary.
- It is not a separate source repository.
- It is not a Git submodule.
- It does not duplicate Routing code into Research or Development.

Code is organized by horizontal responsibility; a Preset assembles a vertical product slice.

## Why a modular monorepo

Research workflows, model-intelligence schemas, task contracts, Behavior Runtime, Dashboard, and release manifests still evolve together. A monorepo provides atomic changes and a single combination-test matrix. Git submodules would introduce detached commits, multi-repository version coordination, and fragile clone/install behavior before the interfaces are stable.

Separate source repositories become reasonable only after an API is stable across multiple releases, independent consumers and maintainers exist, and release cadence is no longer coupled.

## Current Presets

| Preset | Skills/features |
|---|---|
| `routing-core` | adaptive orchestration + model gateway/intelligence + dashboard |
| `development-core` | software development + engineering assurance |
| `research-base` | research workflow without required dynamic routing |
| `research-routed` | research-base + routing-core |
| `communication-visual` | research communication + visual contracts |
| `hardware` | hardware experiment loop + evidence/safety |
| `hygiene` | project hygiene + archive-first policy |
| `platform-dev` | Skill/plugin maintenance |
| `full` | all supported slices |

Compatibility aliases include `research-core`, `minimal-control`, `all`, and the earlier stage-oriented names.

## Filtered release artifacts

```bash
python3 -m rops package --out DIST --preset routing-core --target codex
python3 -m rops package --out DIST --preset development-core --target claude
python3 -m rops package --out DIST --preset research-routed --target gemini
python3 -m rops package --out DIST --preset full --target portable
```

The builder:

1. validates the source repository and smoke suites;
2. resolves the Preset recursively;
3. copies only selected Skills, components, and Behavior Packs;
4. ships the deterministic ROPS runtime;
5. filters trigger/provenance metadata;
6. generates a package-local default Preset and catalog;
7. writes target-native manifests and hooks;
8. validates the filtered staging tree;
9. creates a ZIP and SHA-256 checksum.

Independent artifacts can therefore be released from one source monorepo without Git submodules or manual forks.

## Distribution forms

- **Source checkout:** maintainers and advanced users run `python3 -m rops install`.
- **Native plugin/extension ZIP:** primary end-user form for Codex, Claude Code, or Gemini CLI.
- **Portable ZIP:** carries all supported native manifests.
- **Headless Python runtime:** a future optional package for CI/server use; it is not required for normal plugin users.
