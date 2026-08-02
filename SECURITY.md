# Security policy

Report security issues privately to the repository maintainer rather than opening a public issue.

## Trust boundary

ResearchOps Toolkit contains Skills, lifecycle Hooks, and scripts that execute with the privileges granted by the host Harness. Review the repository and the generated Hook configuration before trusting it. Platform permission prompts, sandboxes, OS/container controls, repository protection, and hardware interlocks remain the final authority.

The Behavior Runtime is a guardrail, not a complete security boundary:

- it can inspect only lifecycle events exposed by the active Harness;
- an uncovered tool path or a command run outside the Harness is outside its control;
- the portable Hook intentionally fails open on internal errors so a broken adapter does not brick the host;
- `enforce` mode must be combined with platform permissions for security-sensitive use.

## Data handling

The default runtime audit log stores metadata, input length, and a SHA-256 digest. It does not store raw prompts or raw tool arguments. Never include real secrets, private paper data, device credentials, unpublished datasets, or unsafe hardware envelopes in bug reports.

## Supply chain

Treat every third-party Skill, Hook, model gateway, and plugin as executable supply-chain content. Pin revisions, preserve licenses, inspect network and file-system behavior, and update `PROVENANCE.json` before vendoring anything.
