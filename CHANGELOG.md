# Changelog

All notable user-visible changes are documented here. The project follows semantic versioning and uses this file for release-level changes rather than commit history.

## [Unreleased]

### Changed

- Added provider recipes and protocol-aware gateway/Codex configuration for DeepSeek V4 Flash, Xiaomi MiMo, MiniMax, and gateway-only GLM 5.2, with secrets kept in environment variables.
- Persisted every eligible model × reasoning-mode candidate score for each routing decision, rather than storing only the selected arm.
- Added non-destructive project upgrades for newly introduced model arms and routing allowlists, plus direct-operation restrictions for plan-specific endpoints.
- Added separately layered managed Codex profiles for external providers; they default to disabling the provider-native web-search declaration after a live MiMo Token Plan probe demonstrated that unsupported tools can reject a request before execution.
- Model selection now routes over explicit model × reasoning-effort execution arms, with effort-specific evidence, cost, latency, failure patterns, mitigations, and executable Codex parameters.
- Added reasoning-demand/effort fit, exact/min/max effort constraints, `orchestrate` Lead routing, task-conditioned coordination topology, and model-family-diverse verifier preference.
- Replaced occupational worker personas with session Lead, bounded read/write work-unit, and fresh-context verifier templates.
- Added GPT-5.6 Sol/Terra/Luna cold-start arms and a deterministic model-effort/topology/Codex-rendering smoke test.
- Made `--no-write` routing use a genuinely read-only SQLite connection so Codex read-only sandboxes can route without WAL writes.

## [2.1.0] - 2026-08-06

### Added

- Inspect-before-write intake with explicit `new`, `adopt`, `migrate`, and `resume` modes for non-empty repositories.
- Light, standard, and deep existing-project adoption protocol owned by the Research Program Orchestrator.
- `rops inspect`, compact `rops status`, and one-command `rops up --open` Dashboard startup.
- Memory v2.1 with episodic, semantic, procedural, and preference layers; lifecycle, validity windows, source-aware deduplication/supersession, relations, project synchronization, and provenance-bearing context bundles.
- Executable Product Benchmark for non-destructive adoption, actual Dashboard HTTP readiness, SQLite authority, and Memory lifecycle behavior.
- Standardized external product-benchmark report schema and adapter skeleton.
- Product-landscape and evaluation/baseline documentation covering observability/eval systems, scientific agents, software agents/benchmarks, and memory platforms.
- Dedicated adoption/Memory/database-migration smoke test.

### Changed

- Existing repositories are no longer initialized as empty charter projects; Dashboard state is seeded from the repository assessment and remains reviewable.
- Bootstrap no longer modifies the host root `.gitignore` or writes root Agent policy files unless explicitly requested.
- Product Benchmark now starts the actual HTTP Dashboard on an ephemeral port and verifies that `view.json` can be loaded.
- Dashboard benchmark and adoption smoke processes now terminate the full process group, preventing orphan HTTP servers after validation.
- Memory is now a managed local lifecycle layer rather than only an FTS recall index, while authoritative governance/evaluation state remains separate.

### Evidence boundary

- The bundled v2.0-versus-v2.1 report demonstrates deterministic product-regression improvements only. It is not a claim of universal scientific superiority over unrelated third-party tools.

## [2.0.0] - 2026-08-05

### Added

- A project-scoped Model Intelligence module that is independently installable from the Research workflow.
- SQLite as the authoritative store from the first evaluation event, with JSONL retained only for import, export, audit, and reproducible research exchange.
- One canonical Evaluation Event schema, one deterministic profile engine, and separate read-only routing, dossier, dashboard, benchmark, and audit projections.
- Finite task-conditioned profile slices, posterior uncertainty, current endpoint health, effective-dated pricing, and explainable routing decisions.
- Warmup/soft-transfer state with visible project adaptation, zero-start comparison, bounded inherited evidence, and an automatic negative-transfer guard.
- Aggregated failure patterns, scoped mitigation revisions, human approval, canary/active lifecycle, and prompt compilation that remains separate from high-risk operation approval.
- Black-box behavior-drift monitoring, identity canaries, and deployment epochs without asserting unobservable provider-side causes.
- Task-family-conditioned Judge calibration, position-order consistency, abstention, selective escalation, and reliability-weighted pairwise Bradley–Terry projections.
- An optional SQLite FTS recall layer; authoritative state remains independent of Harness or external memory services.
- A development-led `software-development` Skill and shared Engineering Assurance component alongside the existing research-led engineering workflow.
- Preset-based filtered release artifacts for Routing, Development, Research, Visual Communication, Hardware, Hygiene, Platform Development, and the full suite.
- Native Codex, Claude Code, and Gemini extension manifests plus lifecycle hook adapters.

### Changed

- Unified all project-owned state, governance, runtime, artifacts, cache, and model intelligence under one hidden `.researchops/` directory.
- Replaced the duplicate routing-profile and model-dossier aggregation paths with one canonical aggregation pipeline.
- Reframed Bundles as installation and packaging **Presets**; `--bundle` remains a compatibility alias.
- Split model gateway concerns—provider calls, secrets, endpoint health, and pricing—from semantic model intelligence and routing.
- Added routing and model-adaptation summaries to the research project dashboard while keeping low-level score factors in audit views.
- Kept internal operation codes and benchmark-pack IDs machine-facing; users invoke stable Skills or describe their goal in ordinary language.

### Migration

- Legacy `.research/` project state is migrated to `.researchops/state/`.
- Legacy replaceable `.researchops/` runtime content is migrated under `.researchops/runtime/`.
- Existing JSONL task history can be imported into the canonical SQLite store with `rops intelligence import-jsonl`.

### Compatibility

- Existing `research-core`, `minimal-control`, stage-oriented presets, `rops bundles`, and legacy agent-registry commands remain available as compatibility surfaces.

## [1.7.0] - 2026-08-03

### Added

- Model Control Plane for provider/model onboarding, dispatch, connectivity probes, and model dossiers.

## [1.6.0] - 2026-08-03

### Added

- Parsed shell inspection and an optional semantic reviewer for Behavior Runtime risk escalation.

## [1.5.0] - 2026-08-02

### Added

- Cross-cutting Behavior Runtime, Behavior Packs, lifecycle hooks, and content-bound approvals.

## [1.4.0] - 2026-08-02

### Changed

- Renamed the project from **Research Agent OS** to **ResearchOps Toolkit**.
- Consolidated framework, bundle, trigger, proposal, artifact, and vendor-lock metadata under `config/`.
- Moved generated Skill catalogs to `catalog/`, release evidence to `release/`, and trigger fixtures/smoke validation to `tests/`.
- Preserved progressively loaded Skills, evidence ledger, dashboard, capability proposals, adaptive model routing, hardware safeguards, independent validation, and archive-first hygiene.
