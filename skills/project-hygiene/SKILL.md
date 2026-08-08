---
name: project-hygiene
description: >
  Use when repositories, large data, logs, checkpoints, worktrees, temporary tests, internal IDs, or obsolete files need inventory, archive, restoration, quarantine, or approved purge. Do not use on active, referenced, dirty, unregistered, or ambiguously owned assets.
---
# Project Hygiene

## Trigger contract

Own code/data/worktree lifecycle and semantic cleanup. Repository and asset hygiene are one Skill because users think in terms of “what is stale and safe to retire,” while the mode selects the correct safety protocol.

## Progressive loading

- large artifacts, archive, restore, quarantine, purge, worktrees: `references/ASSET_LIFECYCLE.md`;
- stale code/tests/docs/internal IDs: `references/REPOSITORY_HYGIENE.md`.

Use only the needed script:

- `scripts/archive_manager.py` for reversible archive/restore/purge batches;
- `scripts/asset_lifecycle.py` for large data and worktrees;
- `scripts/repo_hygiene.py` for code, tests, docs, and public naming.

## Modes

- `scan`: read-only inventory and ownership/evidence checks;
- `archive`: default reversible retirement into `.researchops/state/archive/` with manifest;
- `restore`: content-checked reversal;
- `quarantine`: staged removal when actual storage must be reclaimed;
- `purge`: second-token permanent deletion after grace period;
- `worktree`: lease/status/dirty/merge-aware cleanup;
- `repository`: stale tests, smoke code, duplicates, dead configs, internal labels.

## Rules

1. Archive-first is the default, but same-filesystem archive does not free capacity.
2. Permanent purge requires evidence-reference checks, regeneration/retention assessment, content-bound plan, approval, and grace period.
3. Main, dirty, locked, active, or unknown worktrees are blocked.
4. Internal IDs may remain stable keys, but public surfaces require semantic labels.
5. Temporary tests are removed only after replacement and validation are recorded.
6. Never follow external Skill symlinks during scans.

## Output contract

Return inventory, ownership/evidence blockers, proposed actions, space impact, archive/restore path, approval token, validation result, and dashboard update. Scans never imply deletion approval.
