# Behavior Runtime

## Purpose

The Behavior Runtime is a cross-cutting control plane closer to the Agent execution loop than a progressively loaded Skill. It is intentionally small: it classifies the current task, selects compact policies, injects context at supported lifecycle events, records metadata, and applies deterministic checks before configured consequential tools.

It does not own research artifacts and does not replace a Skill. A full workflow remains in the narrowest relevant Skill.

## Universal kernel

The kernel is always applicable in `guide` or `enforce` mode:

1. Stay inside requested scope.
2. Distinguish observation, inference, proposal, and unverified claim.
3. Persist durable decisions and evidence in `.research/`.
4. Propose consequential capabilities before operational approval.
5. Use least privilege, narrow write scope, and minimum sufficient context.

## Task packs

Task classification may activate one or more packs:

- `coding-minimal-change`
- `coding-evidence`
- `research-integrity`
- `writing-claim-discipline`
- `hardware-safety`
- `hygiene-archive-first`
- `delegation-quality`

A pack is stored as compact JSON rather than another semantic Skill. `behavior/registry.json` maps task classes and active Skills to packs. `behavior/evals/cases.json` provides deterministic regression cases for classification, pack selection, risk discovery, and decisions.

## Lifecycle placement

Adapters use the nearest platform-native hooks available:

- session or prompt start: inject the kernel and task-relevant packs;
- before a tool: identify dependency changes and deterministic configured risks;
- subagent start: propagate delegation policy plus the parent session's recent task packs without storing the raw parent prompt;
- later adapters may use after-tool or stop events for acceptance reminders and telemetry.

The plugin/extension manifests distribute these adapters; project installation writes explicit local hook settings and copies a versioned runtime into `.researchops/`.

## Modes

```bash
python3 -m rops behavior --root . mode observe
python3 -m rops behavior --root . mode guide
python3 -m rops behavior --root . mode enforce
```

- `off`: no runtime activity.
- `observe`: classify and write metadata only.
- `guide`: inject compact context and proposals; no ordinary hard block.
- `enforce`: additionally deny configured deterministic high-risk operations without a matching approval.

Use `guide` while evaluating a new project or Harness. Move to `enforce` only after reviewing generated Hook settings and platform trust prompts.

## High-risk approvals

Current hard-risk classes are:

- destructive deletion;
- destructive Git operations;
- worktree removal;
- hardware write/reset/program actions;
- sensitive external transfer.

An approval binds to the normalized exact command, has an expiry, and is consumed once. Approval state transitions use a small cross-platform lock so concurrent workers cannot normally consume the same approval twice. Create approvals from an interactive operator terminal outside the Agent Harness:

```bash
python3 -m rops behavior --root . approve \
  --kind destructive-delete \
  --command 'rm -rf raw_traces' \
  --reason 'archive and reproducibility package verified' \
  --ttl 10
```

The CLI rejects non-interactive approval creation by default. In `enforce` mode, a tool command that invokes `rops behavior ... approve`, calls the internal approval function, or writes the approval ledger is classified as a non-approvable `policy-bypass`. This is a guardrail rather than a cryptographic authority: OS permissions and the host sandbox still determine whether an Agent can alter files directly.

This runtime approval does not replace the specialist Skill's design, topology, archive, privacy, or recovery checks. It is the last narrow execution token after those checks.

## Privacy and audit

The default event log is `.research/runtime/events.jsonl`. It stores:

- timestamp, framework, event, mode, and decision;
- task classes and active pack IDs;
- configured risk kinds and consumed approval kinds;
- input length and SHA-256 hash.

It does not store raw prompts or raw tool input by default. Raw traces should not be enabled without an explicit retention and privacy policy.

## Fail-open and enforcement boundary

The portable Hook executable fails open on internal errors so that a broken adapter does not brick the Harness. Platform permissions, sandboxing, repository protection, hardware interlocks, and human confirmation remain authoritative.

Consequently:

- Hook coverage must be tested for every supported Harness release.
- Plugin/extension adapters and project-installed adapters are separate packaging paths and must both remain valid.
- A command executed outside the Harness is outside this runtime.
- A tool path not exposed to the configured event is not intercepted.
- Security-sensitive deployments should combine `enforce` with platform permissions and OS/container controls.

## Adding a pack

Create a new pack only when the behavior is cross-cutting across multiple workflows and can remain concise. Otherwise put the procedure in a Skill reference.

A new pack requires:

1. one JSON file under `behavior/packs/`;
2. a registry mapping;
3. positive and negative evaluation cases;
4. documentation of conflicts and priority;
5. adapter smoke coverage if it changes decisions or output schema.
