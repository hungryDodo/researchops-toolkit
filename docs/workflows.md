# Research workflows

## Default lifecycle

```text
charter
→ survey / related work
→ route triage
→ feasibility experiments
→ main experiments
→ analysis
→ independent validation
→ writing / revision
→ red-team and submission review
→ archive / closeout
```

A project may loop backward when evidence invalidates a route. Backtracking is recorded as a decision; it is not hidden by overwriting earlier results.

## Gates

A Gate answers one narrow decision such as continue, revise, pause, or kill. High-stakes Gates should use a fresh context or independent Agent that reads authoritative artifacts rather than optimistic summaries.

A Gate cannot manufacture missing evidence. It may downgrade, supersede, or reject a claim.

## Evidence states

Claims progress through:

```text
proposed → exploratory → supported → independently_verified
→ approved_for_writing → superseded / rejected
```

Evidence artifacts progress through:

```text
registered → validated → invalidated
```

Validation means that the artifact exists, its checksum and provenance are complete, and its analysis protocol is known. It does not by itself prove the interpretation or generality of a claim.

## Handoffs

A cross-role handoff should include:

- source and destination role;
- one-sentence objective;
- frozen and open assumptions;
- authoritative files and immutable run IDs;
- acceptance and kill criteria;
- compute, hardware, time, and cost budget;
- allowed writes and forbidden actions;
- expected dashboard updates;
- human approval requirements.

A worker should reject a handoff that cannot be evaluated without guessing.

## Capability proposals

Some useful capabilities are too risky or expensive for implicit execution but too easy to forget if they require memorized names. The proposal mechanism separates discovery from invocation:

1. the orchestrator scans a small policy only at a lifecycle hinge or consequential planned action;
2. it records a recommendation with benefit, cost, scope, prerequisites, and required approval;
3. the user approves, dismisses, or snoozes it;
4. approval permits loading the named specialist workflow;
5. the specialist still enforces its own hardware, deletion, privacy, or publication Gate.

Proposal states are `recommended`, `approved`, `dismissed`, `snoozed`, and `completed`. A capability/stage/action fingerprint prevents repeated nagging.

Example:

```bash
python3 -m rops proposal --root /path/to/project propose \
  --stage analysis \
  --action "freeze headline results and retire raw traces" \
  --write
```

Proposal approval is not equivalent to approving power output, firmware flashing, third-party disclosure, manuscript submission, or permanent deletion.

## One next action

For long-running projects, use the on-disk state to produce one idempotent next action instead of replaying the entire history:

```bash
python3 skills/research-program-orchestrator/scripts/next_step.py \
  --root /path/to/project
```

The output identifies the current phase, one owner/action, the next Gate, and proposal-only safeguards without executing them.
