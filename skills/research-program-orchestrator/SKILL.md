---
name: research-program-orchestrator
description: >
  Use when a request spans research stages, the current owner is unclear, or a lifecycle transition, gate, evidence freeze, dashboard update, or safeguard proposal is needed. Do not use for one narrow survey, experiment, code change, or writing task with a clear owner.
---
# Research Program Orchestrator

## Trigger contract

Own multi-stage coordination, lifecycle transitions, human gates, the shared claim–evidence protocol, dashboard state, and **proposal-only** surfacing of consequential capabilities. Never perform specialist work merely because it is aware of that work.

## Progressive loading

Start here and read only the branch required by the current state:

- project intake/adoption/resume: `references/INTAKE_PROTOCOL.md`;
- program state and transitions: `references/PROGRAM_PROTOCOL.md`;
- continue/revise/pause/kill decisions: `references/GATE_PROTOCOL.md`;
- claim and evidence status: `references/EVIDENCE_PROTOCOL.md`;
- dashboard semantics: `references/DASHBOARD_PROTOCOL.md`;
- safeguard proposals: `references/PROPOSAL_PROTOCOL.md`.

Use `scripts/next_step.py` to emit one idempotent next action. It also asks the package-level capability advisor for relevant safeguards and returns proposals without executing them.

## Operating model

1. Run or read the inspect-before-write intake. If this is an adopted, migrated, or resumed project, follow `INTAKE_PROTOCOL.md` before applying the normal lifecycle.
2. Read `.researchops/state/PROJECT.md`, suite lock, dashboard state, decisions, open human actions, and evidence coverage.
3. Confirm or correct the inferred phase; never restart an existing project merely because the plugin was installed late.
4. Name the narrowest specialist owner and the smallest verifiable next work unit.
5. At a stage boundary, freeze the inputs and criteria that the next stage may consume.
6. Run the lightweight capability proposal scan. A proposal explains why a dormant/high-risk capability may be useful, its expected cost, and the approval required.
7. Execute only safe orchestration updates. A proposal is not approval and never implies destructive, hardware, publication, or external-provider action.
8. Update the dashboard with semantic labels, next gate, blocker, adoption confidence, and proposal status.

## Proposal trade-off

High-risk capabilities are neither silently auto-run nor hidden behind memorized names. They use three states:

- `recommended`: shown to the user/dashboard with reason and scope;
- `approved`: the user accepted invocation, but execution still belongs to the named specialist Skill;
- `dismissed` or `snoozed`: retained so the system does not nag repeatedly.

The proposal broker belongs here at runtime. `skill-system-engineering` owns the design, tests, and maintenance of the proposal policy.

## Output contract

Return current phase, one next owner/action, open gate, evidence blocker, relevant safeguard proposals, and files updated. Do not dump the entire project history.
