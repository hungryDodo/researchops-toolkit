---
name: software-development
description: >
  Use for development-led R&D where the primary outcome is a correct, maintainable, deployable software change and technical investigation supports delivery. Do not use when code is mainly an experimental instrument whose validity, metrics, baselines, or research claims are the primary concern; use research-engineering instead.
---

# Software Development

## Trigger contract

Use this Skill when the primary acceptance boundary is a software deliverable: repository understanding, technical investigation, implementation, debugging, refactoring, review, integration, or release. It may perform research, but it prunes options that cannot justify their maintenance, deployment, reliability, or operational cost.

Do not use it merely because a research task contains code. Use `research-engineering` when a change can alter experimental meaning, data lineage, baselines, metrics, or claims. Use ordinary editing for trivial, local, semantics-preserving changes that do not justify a workflow.

## Operating orientation

This is **development-led R&D**. It shares the Frame → Investigate → Decide → Implement → Verify → Learn skeleton with research-led work, but optimizes for delivery quality rather than novelty or isolated experimental value.

## Modes

- `technical-investigation`: compare feasible technologies and trade-offs under a delivery constraint;
- `implementation`: produce the smallest sufficient change against a frozen acceptance contract;
- `debug`: reproduce, localize, fix, and retain a regression check;
- `refactor`: improve structure without silently changing behavior;
- `review`: lead with concrete correctness, regression, security, and maintainability findings;
- `release`: verify packaging, migration, rollback, documentation, and operational readiness.

The modes are internal routing codes. Users should describe the goal naturally and should not need to remember these labels.

## Procedure

1. Frame the delivery objective, non-goals, affected users, mutability, risk, budget, and acceptance checks.
2. Investigate only enough to resolve material uncertainty. Prefer proven, maintainable choices unless a more complex route has demonstrated value.
3. Freeze a compact task contract before consequential edits.
4. Use the minimality ladder from `references/DEVELOPMENT_PROTOCOL.md`.
5. Establish a relevant failing observation for bugs or an explicit behavior baseline for refactors.
6. Implement the minimum sufficient change. Do not silently reduce scope or defer requested artifacts.
7. Run risk-calibrated checks and capture fresh evidence.
8. Report completed acceptance items, unresolved items, trade-offs, rollback, and residual risk.

## Output contract

Return a task contract, investigation decision when needed, implementation diff, dependency impact, fresh checks, acceptance coverage, operational notes, and residual risks. A large diff or long answer is not progress unless it changes verified project state.

## Progressive loading

Read `references/DEVELOPMENT_PROTOCOL.md` for the development-led objective function and trade-off rules. Use `scripts/assurance.py` only when a machine-checkable contract/evidence bundle is useful. The shared `coding-minimal-change` and `coding-evidence` behavior packs remain cross-cutting and are not duplicated here.
