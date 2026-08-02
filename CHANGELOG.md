# Changelog

All notable user-visible changes are documented here. The project follows semantic versioning and uses this file for release-level changes rather than commit history.

## [Unreleased]

No unreleased changes.

## [1.5.0] - 2026-08-02

### Added

- Added a cross-cutting Behavior Runtime with a compact universal kernel, seven task-specific behavior packs, lifecycle-hook adapters, metadata-only audit events, and four operating modes.
- Added project-scoped hook installation for Codex, Claude Code, and Gemini CLI, plus plugin/extension manifests for distribution.
- Added exact-command, short-lived, concurrency-locked, one-use approvals for deterministic destructive, hardware-write, worktree-removal, and sensitive external-transfer checks.
- Added behavior classification, evaluation, status, mode, approval, and installation commands under `python3 -m rops behavior`.
- Added parent-session task-pack inheritance for Sub-Agents without persisting raw parent prompts.
- Added Claude marketplace metadata and a native Gemini extension Hook manifest.

### Changed

- Renamed the public project to **ResearchOps Toolkit**.
- Separated progressively loaded workflow Skills from cross-cutting task behavior and Harness adapters.
- Project bootstrap can install the default behavior layer without turning it into another user-routable Skill.

### Security

- `guide` remains the default; `enforce` blocks only deterministic configured risks and never replaces platform sandbox or permission controls.
- Runtime logs contain task classes, effects, hashes, and lengths rather than raw prompts or raw tool input.
- Normal approval creation is operator-only from an interactive terminal; Agent self-approval attempts are classified as non-approvable `policy-bypass`.

## [1.4.0] - 2026-08-02

### Changed

- Renamed the project from **Research Agent OS** to **ResearchOps Toolkit** to describe its function directly.
- Replaced sixteen scattered root scripts and duplicated Bash/PowerShell installers with one cross-platform `python3 -m rops` command surface and four focused internal modules.
- Consolidated framework, bundle, trigger, proposal, artifact, and vendor-lock metadata under `config/`.
- Moved generated Skill catalogs to `catalog/`, release evidence to `release/`, and trigger fixtures/smoke validation to `tests/`.
- Flattened non-Skill component layouts and replaced three near-duplicate project policy templates with one rendered template.
- Removed the duplicated demo dashboard, empty Skill directories, placeholder third-party directory, and version-specific migration utility.

### Preserved

- Twelve progressively loaded top-level Skills, evidence ledger, dashboard, capability proposals, adaptive model routing, hardware safeguards, independent validation, and archive-first hygiene.

### Security

- Consequential hardware, deletion, external-provider, and publication actions retain specialist approval gates after proposal approval.
- Worker self-scores do not determine acceptance; high-risk tasks can require independent verification.
