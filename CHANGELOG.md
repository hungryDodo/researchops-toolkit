# Changelog

All notable user-visible changes are documented here. The project follows semantic versioning and uses this file for release-level changes rather than commit history.

## [Unreleased]

No unreleased changes.

## [1.6.0] - 2026-08-03

### Added

- Added a non-executing shell analyzer that unwraps common command wrappers and executable paths, normalizes split/compact/long options, follows nested `sh -c`, `xargs`, and `find -exec`, and preserves unresolved dynamic syntax as uncertainty.
- Added declarative risk categories for deletion, overwrite/device writes, recursive permissions, Git history/force operations, privileged containers, filesystem and cloud administration, persistence, external transfer, listeners/tunnels, remote execution, resource exhaustion, power control, hardware writes, and policy bypass.
- Added an opt-in strict-JSON semantic reviewer interface plus an OpenAI-compatible adapter. Semantic review can identify hidden side effects in general-purpose interpreters or unfamiliar tools, but can only add or escalate findings.
- Added operator feedback records and offline policy reports. Feedback never weakens rules automatically.
- Added 131 adversarial and benign-neighbor risk cases, including 98 high-risk variants and 33 nearby safe commands.

### Changed

- Standardized the Python package, CLI namespace, environment variables, installed metadata, and documentation on the current **`rops`/`ROPS`** abbreviation.
- Replaced regex-first command blocking with structured tool inspection, parsed/canonical command analysis, declarative policy, and optional semantic escalation. Narrow regexes remain only as conservative syntax fallbacks.
- Approvals now bind the category, raw command hash, canonical command hash, and exact matched rule-ID set; equivalent-looking rewrites cannot reuse an old approval.
- Release validation now runs the Behavior Runtime smoke suite and reports the adversarial risk corpus separately from task/pack fixtures.

### Security

- Deterministic findings cannot be downgraded by a semantic reviewer. In `required` semantic mode, reviewer timeout, failure, or invalid output becomes a non-approvable finding when enforcement is active.
- Exposed pre-tool internal failures fail closed in `enforce`; `observe` and `guide` surface the failure without claiming the input was checked.
- Self-authorization, direct approval-state/runtime modification, resource-exhaustion rules, and required-review failures are non-approvable.
- The runtime remains a guardrail rather than a complete sandbox; platform permissions, OS/container isolation, repository controls, hardware interlocks, and human confirmation remain authoritative.

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
