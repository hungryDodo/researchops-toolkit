# Repository hygiene protocol

## Review sequence

1. Establish the authoritative implementation and current research phase.
2. Inventory candidate files, tests, smoke implementations, IDs, worktrees, and references.
3. Trace imports, shell scripts, configs, CI, documentation, experiment manifests, and the evidence ledger.
4. Mark each item `keep`, `rename`, `merge`, `replace`, `archive`, `purge-candidate`, or `needs-human`.
5. Prefer a minimum sufficient change and dependency budget.
6. Validate replacements and run relevant tests.
7. Apply a content-bound archive plan; retain manifest and decision record.
8. Purge only at project close or after a separate lifecycle decision.

## Internal IDs

Internal IDs remain immutable keys in manifests and ledgers, but public surfaces must include semantic labels. A bare ID is an ID token with no semantic label in the same sentence, table row, heading, or structured object. Lint findings require a registry mapping; do not blind-regex ambiguous text.

## Temporary test retirement

A test/smoke may be archived when its protected behavior no longer exists or a maintained replacement covers it; the replacement and validation command are recorded; required coverage is not reduced; it is not the sole reproduction of a bug; the owning experiment is closed; and the cleanup plan explains the decision.

## Minimality

Before adding another script, abstraction, dependency, fixture, or configuration, check for an existing implementation, standard-library/platform capability, installed dependency, consolidation, or deletion. Minimality never overrides safety, accessibility, data integrity, measurement validity, or hardware calibration.
