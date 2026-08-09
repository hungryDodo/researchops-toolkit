# Agents, providers, evaluation, and routing

## Separation of responsibilities

### Model Gateway

- provider/endpoint adapters;
- secret indirection;
- request/response normalization;
- connectivity probes;
- current endpoint health;
- effective-dated pricing;
- returned identity metadata;
- dispatch and error classification.

### Model Intelligence

- canonical Evaluation Events;
- profile aggregation and uncertainty;
- warmup/soft transfer;
- failure patterns and mitigations;
- Judge calibration;
- behavior drift/deployment epochs;
- semantic routing and projections.

`rops models` is a compatibility facade over gateway/projection operations. `rops intelligence` exposes the new control plane directly.

## Secrets

Provider keys must not appear in chat, Git, command-line arguments, project state, prompts, or generated dossiers. Local secret templates belong under the user's configuration directory, such as `~/.config/rops/`.

## Execution arms

The registry should identify behaviorally meaningful configurations, not only marketing model names:

```json
{
  "arm_id": "provider/model/revision/endpoint/epoch/config",
  "provider": "provider",
  "model_family": "model",
  "model_revision": "declared-or-local-hash",
  "endpoint_id": "region-or-deployment",
  "deployment_epoch": "epoch-1",
  "reasoning_effort": "high",
  "quantization": "none",
  "tool_schema_revision": 4,
  "adapter_revision": 2,
  "base_prompt_hash": "sha256:...",
  "mitigation_bundle_hash": "sha256:..."
}
```

Unknown provider-side revisions are handled through observed deployment epochs rather than false certainty.

`reasoning_effort` is a routed dimension. `gpt-5.6-sol@medium`, `gpt-5.6-sol@high`, and `gpt-5.6-sol@xhigh` are separate arms with separate observations, costs, latencies, failure patterns, and mitigations. `model_family` preserves their relationship for comparison without pooling their evidence.

Provider labels are normalized by observed behavior, not by marketing UI. When a provider maps several effort labels to one behavior, ResearchOps keeps only the distinct arms (for example MiMo/MiniMax `none` versus `high`). Region, plan, and endpoint remain distinct where they affect policy or telemetry. See [`provider-configuration.md`](provider-configuration.md) for the current DeepSeek, GLM, MiMo, and MiniMax recipes.

The default registry includes declared cold-start priors for GPT-5.6 Sol, Terra, and Luna across a bounded set of efforts. These priors follow current [official OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model), but remain hypotheses until representative project tasks validate them. Effective-dated price records remain separate from capability priors.

## Session Lead and task-space partitioning

The Lead is a control-plane responsibility, not a permanent company executive persona. It owns the session objective, task graph, budgets, routing calls, dependency tracking, and synthesis. Route it as an ordinary `orchestrate` work unit so its model and effort can also change as evidence accumulates.

Worker templates describe context, tools, mutability, and acceptance boundaries:

- `bounded_read_worker`: one evidence lane, repository slice, hypothesis, or comparison arm;
- `bounded_write_worker`: one isolated implementation unit with deterministic checks;
- `independent_verifier`: a fresh-context acceptance path that does not inherit the worker's hidden reasoning.

The decomposition axis is the task space. A general model may execute different work units over time. Context-isolated review/Judge work remains separate because independence and non-self-approval are experimental controls. This is not a claim that role prompting is never useful; it is a refusal to treat a human company chart as the default decomposition. The [ICML 2025 position paper on LLM-agent scaling](https://openreview.net/forum?id=LEYmr1TsBW) similarly argues that intuitive human-role decomposition can be far from efficient and that the algorithmic structure of the task should drive the split.

Current controlled evidence does not support a universal “more agents” rule. Multi-agent coordination helps parallelizable tasks, while sequential tasks can regress because coordination consumes the same reasoning/tool budget. Therefore the router emits a topology recommendation:

```text
sequential or shared mutable state       → single-agent
partially decomposable                   → lead-worker
independent bounded workstreams          → centralized-fanout
independent acceptance / disputed result → fresh-context verifier
```

Sources: [Towards a Science of Scaling Agent Systems](https://arxiv.org/abs/2512.08296), [Google Research summary](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/), and [OpenAI Multi-agent](https://developers.openai.com/api/docs/guides/responses-multi-agent).

OpenAI's Multi-agent API can support descendant trees rather than only one flat fan-out. The current ResearchOps executor deliberately sets delegation depth to zero: it supports centralized Lead fan-out only, and workers must return decomposition requests instead of launching children. This keeps every provider/model/effort choice and acceptance event attached to the authoritative project store.

## Work-unit contract

Delegation is appropriate when a task can be bounded with:

- objective and frozen acceptance contract;
- allowed read/write/tool scope;
- time budget and stop conditions (the runner enforces `max_minutes` across worker attempts, verification, and acceptance; mandatory cleanup and bounded patch integration still run to completion; monetary caps remain Lead/provider governance);
- required artifacts and verifier;
- orientation, primary operation, artifact, risk and privacy;
- an independent acceptance path where risk warrants it.

One long request should be split when discovery, design, implementation and validation require different evidence or model capabilities.

## Route selection

1. hard-filter ineligible arms;
2. filter exact/minimum/maximum effort constraints and score reasoning-demand/effort fit;
3. query the most specific sufficiently supported profile for that exact arm;
4. quote current endpoint health and current price;
5. apply project utility/risk policy without assuming maximum effort is optimal;
6. preserve uncertainty and bounded exploration;
7. record model, effort, topology, route decision, and selection probability;
8. evaluate the completed work unit from artifacts/state, not prose impression alone.

The Router returns a selected arm plus executable `model`/`reasoning_effort` fields, applicable mitigation, topology, and verifier policy. It does not expose every internal score factor in the main UI.

For a project-local Codex installation, agents can inspect a route without mutating the decision log or creating SQLite WAL/SHM files:

```bash
python3 .agents/skills/adaptive-agent-orchestration/scripts/agent_registry.py \
  --root . recommend --no-write --compact --task-file task.json
```

`--compact` returns only the executable primary/verifier arms, orchestration contract, and visible rationale. `--no-write` opens the last checkpointed SQLite snapshot in immutable read-only mode, which is safe inside a read-only Harness sandbox.

## Route-driven worker execution

The Lead should remain on its normal provider. It must not ask the user to restart the top-level session with `codex -p ...`. After freezing `task.json` and a structured `contract.json`, consume the route and execute it in one bounded operation:

```bash
python3 .agents/skills/adaptive-agent-orchestration/scripts/dispatch_worker.py \
  --root . \
  --task-file task.json \
  --contract-file contract.json \
  --agent bounded_read_worker \
  --max-attempts 2
```

The contract must contain a task ID, objective, mutability, bounded write scope when applicable, delegation policy, and at least one machine-checkable acceptance test. Automatic `workspace-write` is limited to a clean Git snapshot with tracked inputs and non-ignored outputs; ignored ResearchOps state stays Lead-owned. The runner:

1. freezes one canonical task before routing and rejects safety-field conflicts;
2. launches the selected exact provider/model/effort arm in an isolated `codex exec` session when a native or ResearchOps-managed profile exists; profiled third-party sessions additionally require Linux bubblewrap and see only a private tracked project clone, a dedicated writable output directory, minimal system files, and a sanitized temporary Codex home;
3. permits a direct gateway only for explicitly input-free, self-contained, read-only text work whose contract sets `gateway_self_contained=true`; artifact/file readers and verifiers always use a tool-capable Codex session;
4. runs `workspace-write` workers in a detached private Git clone, enforces a 256-path, 16 MiB-per-file, 64 MiB binary-patch ceiling, evaluates that bounded patch, and applies it to a still-clean project only after acceptance;
5. records private raw artifacts under `.researchops/artifacts/dispatches/` and a durable lifecycle row in `worker_dispatches`;
6. on local or arm-scoped request failure, excludes the failed arm; on endpoint-wide provider failure, excludes every sibling arm on that endpoint; then creates a linked new route decision before retrying;
7. starts a separately routed fresh-context verifier when required;
8. records Evaluation Events and updates competence profiles only from registry-eligible evidence.

Use `--dry-run` to inspect the selected backend and argument vector without launching a worker or writing route state. Real third-party credentials remain in a parent-owned local broker and never appear in the worker command, prompt, summary, database, or process environment; the worker gets a one-dispatch token for the exact approved endpoint/model/effort. Third-party workers receive a positive environment allowlist rather than the Lead's ambient environment. Worker-to-worker descendants and native unaccounted multi-agent spawning are disabled: a worker returns a decomposition request and the authoritative Lead creates every child session.

## Probe, Anchor, Shadow, Live

| Source | Purpose | Competence update |
|---|---|---|
| Probe/smoke | connectivity, schema, endpoint identity/health | no |
| Anchor | small reproducible project/task calibration | yes, labeled anchor |
| Shadow | challenger processes a real task without controlling production | yes, after evaluation |
| Live | selected arm performs a real accepted work unit | primary evidence |

## Independent evaluation

Deterministic tests and state/artifact verification have priority. LLM Judges receive the task contract, before/after state, artifacts, tests and rubric—not only the final answer. Worker identity should be hidden for pairwise evaluation. High-risk or disputed outcomes escalate to a stronger/different Judge or human.

See [`model-intelligence.md`](model-intelligence.md) for profile and Judge details.
