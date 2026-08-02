# Changelog

All notable user-visible changes are documented here. The project follows semantic versioning and uses this file for release-level changes rather than commit history.

## [Unreleased]

### Changed

- No unreleased changes.

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
