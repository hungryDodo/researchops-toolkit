# ROPS Behavior Runtime

This directory contains the cross-cutting behavior layer used beside progressively loaded Skills.

- `runtime.py` — task/policy orchestration, approvals, metadata logging, feedback, and hook output.
- `shell_analyzer.py` — non-executing shell parsing, wrapper normalization, and static risk rules and canonical command fingerprints.
- `semantic_reviewer.py` — strict opt-in command adapter for semantic review.
- `policies/risk-policy.json` — declarative categories, severities, approval eligibility, and privacy defaults.
- `packs/` — compact task behavior packs.
- `reviewers/` — optional reviewer adapters and contract documentation.
- `evals/cases.json` — task/pack lifecycle fixtures.
- `evals/risk-cases.json` — adversarial command variants and benign-neighbor regression cases.

The runtime supports `off`, `observe`, `guide`, and `enforce`. In `enforce`, static high/critical findings and completed configured semantic findings are denied unless an approvable category has a matching operator-created one-use token. Deterministic findings cannot be downgraded by a model reviewer.

The guardrail covers only exposed Harness lifecycle/tool paths. Platform permissions, sandboxing, OS/container policy, repository protection, human approval, and physical interlocks remain the security boundary.
