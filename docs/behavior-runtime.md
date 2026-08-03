# Behavior Runtime and risk guardrails

## Purpose and boundary

The ROPS Behavior Runtime is a cross-cutting control plane closer to the Agent execution loop than a progressively loaded Skill. It classifies the task, activates compact behavior packs, injects context at supported lifecycle events, analyzes exposed tool calls, records metadata, and can block configured high-risk operations.

It is **not a complete security boundary**. It cannot intercept a command that bypasses the configured Harness event, a process launched outside the Harness, an unknown privileged tool path, or a compromised host. Platform permissions, sandboxing, OS/container policy, repository protection, hardware interlocks, and human confirmation remain authoritative.

## Four-layer risk evaluation

Before an exposed tool call, the runtime evaluates risk in this order:

1. **Structured tool inspection** — distinguish an actual shell command from a patch, file body, or structured tool request. Direct writes to approval/runtime state and sensitive device/system paths are handled without interpreting documentation text as shell code.
2. **Shell parsing and normalization** — tokenize without executing aliases, substitutions, or expansions; unwrap paths and common wrappers such as `sudo`, `env`, `busybox`, `command`, `timeout`, and nested `sh -c`; inspect `xargs` and `find -exec`; preserve uncertainty instead of guessing.
3. **Declarative category policy** — `behavior/policies/risk-policy.json` maps rule IDs to severity, approval eligibility, and the specialist workflow. Regular expressions remain only for narrow syntax that the parser cannot model reliably.
4. **Optional semantic review** — an explicitly configured local or approved model reviewer examines dynamic or all exposed tool inputs. It can add or escalate a finding, but it can never remove or downgrade a deterministic finding.

No shell expansion is executed during analysis. A syntactically safe substitution such as `$(which rm)` is resolved only to its literal executable name; arbitrary substitutions are marked uncertain and escalated.

## Covered risk categories

The current policy includes:

- recursive/forced deletion and destructive Git cleanup;
- direct overwrite, truncation, shredding, and device writes;
- filesystem/partition administration and mount changes;
- recursive ownership/permission changes;
- Git history rewrite and force push;
- worktree removal;
- privileged containers, host-root/control-socket mounts, and destructive container pruning;
- destructive cluster, infrastructure-as-code, and cloud operations;
- cron, systemd, launchd, shell-startup, and scheduler persistence;
- sensitive or general outbound data transfer, listeners, tunnels, and process-connected sockets;
- remote download/decode followed by execution;
- fork bombs, broad process termination, and host power control;
- firmware/device programming and protected device changes;
- dynamic shell constructions that static analysis cannot resolve;
- attempts to disable, rewrite, or self-authorize the installed policy runtime.

The adversarial regression corpus is `behavior/evals/risk-cases.json`. It contains positive bypass variants and nearby benign commands. This corpus is a maintained test set, not a proof that every shell language or tool is covered.

## Modes

```bash
python3 -m rops behavior --root . mode observe
python3 -m rops behavior --root . mode guide
python3 -m rops behavior --root . mode enforce
```

- `off`: no context, decision, or telemetry.
- `observe`: classify and record metadata without changing behavior.
- `guide`: inject behavior and produce proposals, but do not block ordinary work.
- `enforce`: deny high/critical findings unless the category is approvable and a matching operator approval exists.

Use `observe` or `guide` while measuring false positives on a new project/Harness. Enable `enforce` only after reviewing hook trust, platform permissions, and the project policy.

## Command analysis

Inspect a command without executing it:

```bash
python3 -m rops behavior --root . analyze \
  --command 'sudo /bin/rm --recursive --force /data'
```

The output includes:

- normalized invocation chain and wrappers;
- raw and canonical SHA-256 values;
- parse warnings and dynamic constructs;
- rule ID, category, severity, confidence, evidence, approval eligibility, and specialist owner.

## Content-bound approvals

Approvals are:

- created by a human-operated interactive terminal outside the Agent Harness;
- short-lived and consumed once;
- protected by a small cross-platform lock;
- bound to the risk category, raw command hash, canonical command hash, and exact rule-ID set;
- rejected when the command does not currently produce the requested category;
- unavailable for non-approvable categories such as policy bypass and resource exhaustion.

```bash
python3 -m rops behavior --root . approve \
  --kind destructive-delete \
  --command '/bin/rm -rf raw_traces' \
  --reason 'archive, evidence package, and recovery path verified' \
  --ttl 10
```

Changing `/bin/rm` to `rm`, adding a wrapper, changing a target, or changing the policy rule set produces a different fingerprint. Approval of a proposal only permits entering the specialist workflow; it does not replace the workflow's topology, archive, privacy, recovery, or physical-safety checks.

## Optional semantic/adaptive review

The deterministic engine is portable and remains primary. A semantic reviewer is useful for code hidden behind general-purpose interpreters, dynamic shell construction, complex structured tools, or new commands not represented in the policy.

Any reviewer command must read one JSON object from stdin and write one strict JSON object to stdout. Configure it explicitly:

```bash
python3 -m rops behavior --root . semantic \
  --mode advisory \
  --scope uncertain \
  --command 'python3 /path/to/reviewer.py'
```

Modes:

- `off`: no semantic review;
- `advisory`: completed high/critical semantic findings are enforced, but reviewer failure does not itself block;
- `required`: a selected review that times out, fails, or returns invalid JSON produces a non-approvable failure finding.

Scopes:

- `uncertain`: review only inputs with parse uncertainty/dynamic construction;
- `all`: review every exposed tool input; higher latency, cost, and privacy impact.

The included `behavior/reviewers/openai_compatible.py` can call an explicitly approved local or OpenAI-compatible endpoint. API keys remain in environment variables. Raw tool input is sent to a reviewer only after the operator enables this feature. For private research, prefer a local endpoint.

A semantic reviewer may **escalate only**. A model response of `risk: none` cannot clear a deterministic `git-force-push`, device-write, deletion, or other finding.

## Human feedback and adaptation

Record the disposition of a runtime event:

```bash
python3 -m rops behavior --root . feedback \
  --event-id evt-... \
  --label false-positive \
  --note 'read-only mount inspection in isolated namespace'

python3 -m rops behavior --root . report
```

Feedback supports `true-positive`, `false-positive`, `missed-risk`, `acceptable-risk`, and `needs-policy-update`. It is used for offline policy/eval review. The runtime **never weakens a rule automatically** from model or operator feedback; changes require a reviewed policy update and new positive/negative regression cases.

## Privacy and logging

`.research/runtime/events.jsonl` stores event ID, time, framework, mode, decision, task classes, active pack IDs, rule/category/severity metadata, semantic status, input length, and SHA-256. It does not store raw prompts or raw tool input by default.

Semantic review is an explicit exception: the configured reviewer receives raw exposed tool input. Review the provider, endpoint, retention, and data policy before enabling it.

## Failure behavior

- In `observe` and `guide`, an internal hook error is surfaced but does not claim the input was checked.
- In configured `enforce` mode, an internal error during an exposed pre-tool event fails closed and emits a deny decision.
- A command run outside the Harness or a tool path without a matching hook remains outside ROPS control.
- Hook definitions and hashes must be trusted according to the host Harness.

## Adding or changing policy

A policy change requires:

1. a stable category and rule ID;
2. severity, approval eligibility, and specialist owner;
3. positive adversarial variants;
4. nearby negative cases to control false positives;
5. approval and semantic-layer interaction tests;
6. adapter smoke coverage when output/decision behavior changes;
7. an explicit security note in the changelog.
