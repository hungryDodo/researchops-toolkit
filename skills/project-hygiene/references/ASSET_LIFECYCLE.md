# Asset lifecycle policy

## Default disposition: archive first

For stale material whose deletion confidence is not yet high, move it to `.researchops/state/archive/<batch>/` through `archive_manager.py`. Each batch has a content-bound plan, manifest, hashes, reason, and restore path. Archive on the same filesystem improves repository clarity but does not reclaim storage.

## Evidence-preserving purge contract

A raw/intermediate asset may enter quarantine/purge only when it has:

1. a stable run or acquisition ID;
2. producer command and code revision;
3. schema, units, sampling rate, device/model identity, and environment metadata;
4. accepted derived artifacts such as compact tables, statistical summaries, figure source data, or representative traces;
5. a deterministic analysis/regeneration script or a documented irreproducibility waiver;
6. a content hash or collection manifest;
7. evidence-ledger reference checks;
8. an explicit retention decision with owner/date;
9. a first approval for quarantine and a second approval for permanent deletion.

A screenshot or prose insight alone is not sufficient evidence. Preserve enough structured information to recompute published statistics and investigate likely measurement errors.

## Suggested retention

- canonical evidence and design contracts: versioned indefinitely;
- irreplaceable hardware data: external archive, no automatic deletion;
- reproducible raw data: retain through independent validation/paper freeze, then externalize or purge by policy;
- intermediate tensors/checkpoints: archive 7–30 days after accepted analysis, then review;
- failed-run logs: preserve compact failure summary; archive/purge redundant raw logs after debugging closes;
- profiler traces: preserve representative traces and derived summaries;
- worktrees: remove only after registration, clean status, task closure, merge/approved abandonment, and lease expiry.

## Storage backends

DVC, MLflow, Git LFS, object storage, NAS, or cold storage may be used as backends, but do not replace lifecycle policy. Git should mainly retain metadata, small canonical results, manifests, and regeneration logic.
