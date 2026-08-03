# Safety, archive, and project hygiene

## Safety hierarchy

- Capability proposals are advisory and never authorize the underlying operation.
- Hardware actions begin with read-only discovery and preflight.
- External-provider routing applies privacy, trust-zone, candidate-Agent, risk, and provider hard filters before cost/quality scoring.
- Permanent deletion uses content-bound plans, quarantine or archive, and a second approval.
- Main, dirty, active, locked, unknown, or unmerged worktrees are not automatically removed.
- Public artifacts use semantic names; internal B/E/A identifiers may remain as stable keys but not as the only visible label.

## Archive-first cleanup

The default path for obsolete scripts, tests, documents, and moderate-size artifacts is reversible archive:

```text
inventory → explicit plan → content-bound approval token
→ .research/archive/<batch> + manifest → restore or later purge
```

Example:

```bash
python3 skills/project-hygiene/scripts/archive_manager.py --root . plan \
  --path old_scripts \
  --reason "superseded after validation" \
  --out .research/hygiene/archive-plan.json
```

The archive manifest records original paths, checksums, sizes, reason, and batch identity. Restore refuses destination conflicts or changed archive contents.

Moving content to an archive on the same filesystem does not free disk capacity. Large raw datasets, traces, checkpoints, or profiles need a separate retention decision.

## Large-data retirement

Before deleting data that supported a result, retain the smallest sufficient reproducibility/evidence package:

- design/config and environment manifest;
- exact regeneration or acquisition command;
- aggregate tables and figure-source data;
- statistical results and analysis code;
- representative samples where appropriate;
- checksums, run IDs, failure summary, and evidence-ledger links;
- waiver and human approval when the source is inherently non-reproducible.

Then use quarantine, a grace period, and a separately generated permanent-purge token. Raw data must not be removed merely because an Agent says an insight was extracted.

## Tests and smoke scripts

Temporary tests and smoke implementations should be registered as `temporary`, `maintained`, `superseded`, or `retired`. Before archival, identify the behavior they protected, their replacement, the validation command, and any CI/document references.

## Worktrees

A child worktree is eligible for removal only when it is registered, not the main worktree, unlocked, inactive, clean, past its lease, associated with a closed task, and merged or explicitly approved as abandoned. Unknown worktrees are reported, not removed. The workflow does not use force removal by default.

## Hardware

Hardware workflows require a topology record, power-source boundaries, exclusive leases, calibration state, safe operating limits, preflight, human confirmation for physical state when needed, and a restoration procedure. Proposal approval only loads the hardware workflow; it does not authorize power output or flashing.

## External providers and API keys

Do not send private manuscripts, unpublished results, credentials, device identifiers, participant data, or proprietary datasets to a third-party provider without an explicit data boundary and approval. Record provider/model identity, trust zone, disclosure scope, and verifier requirement in the task contract.

API key values belong only in provider-standard environment variables, an operating-system/organization secret manager, or the user-level `~/.config/rops/secrets.env` file with restrictive permissions. They must not appear in chat, Git, Skills, `.research/`, prompt files, CLI arguments, model dossiers, logs, issue reports, or test fixtures.

`rops models dispatch` and `delegate` are classified as external-data-transfer events by the Behavior Runtime. A connectivity probe and smoke test prove API function only; they do not justify sending higher-classification data or updating a model capability profile.
