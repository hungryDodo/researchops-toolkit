# Documentation index

This directory contains stable operational documentation. Design-decision diaries, reference-project dissections, and commit-style notes do not belong here; external influences are acknowledged in the root README and declared in `PROVENANCE.json`.

## Shortest reading paths

### First-time user

1. [`getting-started.md`](getting-started.md)
2. [`skills-and-bundles.md`](skills-and-bundles.md)
3. [`workflows.md`](workflows.md)

### Research lead or operator

1. [`architecture.md`](architecture.md)
2. [`workflows.md`](workflows.md)
3. [`agents-and-model-routing.md`](agents-and-model-routing.md)
4. [`safety-and-hygiene.md`](safety-and-hygiene.md)

### Maintainer or framework integrator

1. [`architecture.md`](architecture.md)
2. [`skills-and-bundles.md`](skills-and-bundles.md)
3. [`development.md`](development.md)

## Agent fast path

An Agent entering this repository should not read every file.

1. Read the root `AGENTS.md` and README.
2. Read this index.
3. Use `catalog/README.md` to choose the narrowest owner.
4. Read only that Skill's `SKILL.md` and the references required by its current mode.
5. If operating on a bootstrapped research project, inspect `.research/PROJECT.md`, `.research/suite.lock.json`, the dashboard state, open human actions, and the authoritative design/run/evidence files.
6. Treat capability proposals as advisory records, not action approval.
7. Use the unified `python3 -m rops` CLI for installation, project setup, validation, and release tasks.

## Document map

| File | Contents |
|---|---|
| [`getting-started.md`](getting-started.md) | Installation, bootstrap, dashboard, bundles, upgrades, multi-host use |
| [`architecture.md`](architecture.md) | Repository layout, control/execution planes, authoritative state |
| [`workflows.md`](workflows.md) | Research stages, gates, evidence states, handoffs, proposals |
| [`skills-and-bundles.md`](skills-and-bundles.md) | Skill ownership, progressive loading, triggers, bundle selection |
| [`agents-and-model-routing.md`](agents-and-model-routing.md) | Sub-Agent contracts, model selection, independent evaluation |
| [`safety-and-hygiene.md`](safety-and-hygiene.md) | Hardware, external providers, archive, purge, worktree safety |
| [`development.md`](development.md) | Skill authoring, adapters, provenance, tests, release process |
