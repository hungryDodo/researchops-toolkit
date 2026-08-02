# Contributing

Keep each Skill narrow, independently installable, and explicit about its stage boundary. Add or update evals, run `python3 -m rops validate`, compile executable code, and audit new network or file-system behavior. Do not vendor third-party Skill text without compatible licensing and provenance.

Prefer extending the unified `rops` CLI or an existing Skill script over adding a new top-level utility. Pull requests that change Gate semantics, evidence schemas, implicit invocation, deletion, external-provider, or hardware permissions must include a compatibility and security note.
