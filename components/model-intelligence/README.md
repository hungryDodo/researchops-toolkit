# Model Intelligence

A framework-independent module that can be installed without the Research workflow. It stores canonical observations in SQLite, derives a finite set of profile slices, and exposes read-only routing, dossier, dashboard, benchmark, and audit projections.

Recorded routes retain the self-contained decision JSON and normalized per-candidate score rows. This keeps model, endpoint/plan, and reasoning mode jointly queryable without collapsing their outcome histories.

Benchmark packs register task fixtures, evaluators, and metric vocabulary. They do not create user-facing Skills and users do not need to remember their IDs.


Version 2.1 also exposes inspect-before-write project snapshots, lifecycle-aware four-layer local Memory, and the deterministic Product Benchmark. These additions remain framework-independent and do not make Recall Memory authoritative.
