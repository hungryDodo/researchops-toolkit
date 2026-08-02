# Documentation

Use the shortest path that matches the task. Do not read every Skill or every reference file.

## First-time user

1. [Getting started](getting-started.md)
2. [Architecture and state](architecture.md)
3. [Behavior Runtime](behavior-runtime.md)
4. The workflow- or safety-specific document needed next

## Agent entering the repository

1. Read [`../AGENTS.md`](../AGENTS.md).
2. Read [`../catalog/README.md`](../catalog/README.md) to find the narrowest Skill owner.
3. Read that Skill's `SKILL.md` and only the references explicitly needed.
4. Read [Development and release](development.md) before changing shared infrastructure.

## Documents

| Document | Purpose |
|---|---|
| [Getting started](getting-started.md) | Install Skills, Behavior Runtime, agents, and dashboard |
| [Architecture and state](architecture.md) | Two control planes, four layers, repository layout, and authority |
| [Behavior Runtime](behavior-runtime.md) | Kernel, packs, hooks, modes, approvals, privacy, and portability |
| [Research workflows](workflows.md) | Stages, gates, evidence states, proposals, and handoffs |
| [Skills and bundles](skills-and-bundles.md) | Skill ownership, progressive loading, bundles, and granularity |
| [Agents and model routing](agents-and-model-routing.md) | Subtasks, model/provider selection, verification, and profiles |
| [Safety and hygiene](safety-and-hygiene.md) | Hardware, archive-first cleanup, purge, worktrees, and privacy |
| [Development and release](development.md) | Authoring Skills/Packs, adapters, tests, provenance, and publishing |
