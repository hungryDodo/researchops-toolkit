# Security policy

Report suspected vulnerabilities privately to the repository maintainer rather than opening a public issue with exploit details, secrets, unpublished data, or device credentials.

## Trust boundary

ResearchOps Toolkit contains Skills, lifecycle Hooks, policy code, and scripts that execute with privileges granted by the host Harness. Review the repository, installed `.researchops/` copy, generated Hook definitions, and platform trust prompts before enabling them.

The ROPS Behavior Runtime is a defense-in-depth guardrail, not a complete security boundary:

- it sees only lifecycle/tool events exposed by the active Harness;
- commands launched outside the Harness and uncovered built-in/tool paths are outside its control;
- shell parsing intentionally does not execute alias, variable, or arbitrary command expansion;
- semantic review is probabilistic and cannot prove safety;
- OS/container permissions, repository protection, hardware interlocks, and human confirmation remain authoritative.

In `enforce` mode, an internal failure during an exposed pre-tool event fails closed. In `guide` and `observe`, failures are surfaced without claiming that the action was checked. Configure host-level deny/approval policies for operations that must remain impossible even when a Hook is absent or compromised.

## Risk policy and approvals

The deterministic policy uses parsed/normalized commands plus declarative categories. Regular expressions are a narrow fallback, not the primary parser. Approvals are operator-created, short-lived, one-use, and bound to raw/canonical command hashes and rule IDs. Policy-bypass and resource-exhaustion categories are non-approvable.

Never grant write access to `.research/runtime/approvals.json`, `.research/runtime/config.json`, or the installed `.researchops/behavior/` directory to an untrusted worker when these files are expected to enforce policy.

## Semantic reviewer privacy

Semantic review is disabled by default. Enabling it sends raw exposed tool input to the configured reviewer command. Prefer an approved local endpoint for private projects, keep credentials in environment variables, and review provider retention/data-use terms. A semantic reviewer can add or escalate findings but cannot clear deterministic findings.

## Data handling

Default audit events store metadata, lengths, hashes, rule IDs, and decisions rather than raw prompts or tool arguments. Do not attach real secrets, private papers, unpublished datasets, raw participant data, or unsafe hardware envelopes to issue reports.

## Supply chain

Treat every third-party Skill, Hook, reviewer model, model gateway, plugin, and generated configuration as executable supply-chain content. Pin revisions, preserve licenses, inspect network/filesystem behavior, use least privilege, and update `PROVENANCE.json` before vendoring anything.
