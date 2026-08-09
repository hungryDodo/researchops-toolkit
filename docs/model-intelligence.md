# Model Intelligence

Model Intelligence is a framework-independent module for project-scoped, task-conditioned, time-varying evaluation and routing. It can be installed with `routing-core` without the complete Research workflow.

## Why the first version uses SQLite directly

The system does not use JSONL as an interim primary store. Model-evaluation data requires uniqueness, transactions, corrections, joins, indexes, time-window queries, and coordinated failure/mitigation/Judge state. SQLite provides these properties without requiring a server.

```text
.researchops/intelligence/state.sqlite     authoritative
JSONL                                      import/export/audit only
Markdown / JSON projections                generated human/machine views
```

JSONL remains useful for portability and research replay:

```bash
python3 -m rops intelligence --root PROJECT export-jsonl --out events.jsonl
python3 -m rops intelligence --root PROJECT import-jsonl events.jsonl
```

## Evaluation Event

The routing/evaluation unit is a bounded work unit, not every token or every model call. A canonical event records:

- project/task/work-unit/route IDs;
- `live`, `shadow`, or `anchor` source;
- complete execution-arm identity;
- orientation, primary operation, primary artifact, risk and permissions;
- accepted state, verified progress, quality and human correction;
- cost, token use and latency;
- verifier evidence and versions;
- failure observations;
- selection probability for future off-policy analysis.

Smoke/probe data is not an Evaluation Event and is never competence evidence.

## One aggregation engine

The engine validates eligible events, ignores superseded observations, creates a small set of scopes, and computes:

- Beta-smoothed success posterior and interval;
- verified-progress mean/median;
- quality;
- cost and latency distributions;
- input/output token distributions;
- human correction and verifier disagreement;
- lifetime and recent windows;
- source mix and evidence freshness;
- simple improvement/degradation status.

The first implementation intentionally uses recent/lifetime windows instead of a complex state-space model. The raw events are retained, so a future aggregation policy can rebuild history without data loss.

## Read-only projections

| Projection | Consumer | Content |
|---|---|---|
| Routing | Router | eligibility, expected utility, uncertainty, cost, health |
| Dossier | human/operator | identity, profiles, patterns, mitigations, epochs |
| Dashboard | project UI | current preference, assignments, warmup, health, drift |
| Benchmark | research analysis | anchor/shadow/live comparisons and policy results |
| Audit | maintainer | event-to-profile-to-decision provenance |

Run:

```bash
python3 -m rops intelligence --root PROJECT rebuild
```

All projections can be deleted and regenerated from canonical state.

## Routing

Routing first hard-filters candidates by required capabilities, risk ceiling, privacy, tool support, endpoint health, and operator policy. It then evaluates the best available profile using this backoff order:

```text
same project + operation
→ same orientation + operation
→ operation
→ global arm prior
```

Current price and endpoint health are queried at decision time; they are not folded permanently into model competence. The current UCB-style policy remains a transparent baseline while the data layer stabilizes. The decision stores its policy version and selection probability.

Each recorded decision also writes one normalized row per eligible arm to `route_candidate_scores`. These rows retain rank, selected state, exact arm/effort, task score, profile source, uncertainty, score components, endpoint health, price, and execution fields. `route_decisions.summary_json` remains the self-contained audit snapshot, while the normalized table supports direct SQL analysis across tasks and arms.

Read-only recommendations use an immutable, checkpointed SQLite snapshot and skip profile rebuilds, registry sync, warmup persistence, and route-decision writes. This makes `recommend --no-write --compact` suitable for an installed Codex skill running under a read-only sandbox; normal recorded routes continue to use transactional WAL mode.

`worker_dispatches` records running/completed/failed/timed-out/rejected execution lifecycle separately from competence. A provider, harness, verifier, integration, or environment failure remains visible there, while its Evaluation Event is marked `registry_eligible=false`; only confirmed remote attempts update endpoint health. Raw Codex JSONL, final worker messages, and isolated patches are private local artifacts, not database payloads or routing-profile input.

## Execution-arm identity

A model name is not sufficient. An execution arm can include:

- provider and requested/returned model ID;
- declared revision or local checkpoint hash;
- endpoint/region;
- deployment epoch;
- quantization, reasoning effort, temperature;
- adapter and tool-schema revision;
- Harness and base-prompt hash;
- mitigation-bundle hash.

A materially changed configuration becomes a new arm or epoch rather than silently sharing all evidence.

Reasoning effort is always material for routing. Arms use stable effort-bearing IDs such as `provider/model@high`; the Router may compare them through `model_family`, but the Profile Engine never collapses their observations. Task contracts can request `reasoning_demand` or hard exact/min/max effort bounds. The default effort-fit prior penalizes under-provision more strongly than over-provision while still charging the measured cost and latency of excess effort.

## Black-box degradation and model replacement

For a closed API, no client can prove a hidden weight swap when the provider preserves all public identifiers. ROPS therefore reports only observable drift.

Identity canaries and normal work can monitor:

- returned model/fingerprint/header changes;
- schema and tool-call compliance;
- refusal/format behavior;
- context and output-length distribution;
- latency, TTFT, rate limits and token use;
- repeated anchor outcomes;
- recent verified success/quality relative to the same scope.

The state machine is:

```text
stable → suspected_drift → confirmed_new_epoch or cleared
```

Endpoint degradation is kept separate from competence degradation. A confirmed epoch isolates new evidence and inherits only a weak prior.

## Warmup and soft transfer

A project can start in `zero`, `conservative`, or `normal` mode. Transfer is delayed until a concrete work unit reveals at least its operation and artifact; a vague project motivation does not receive a fabricated semantic-similarity score.

The visible warmup state includes:

- initialization mode;
- inherited equivalent observations;
- local verified observations;
- adaptation/calibration progress;
- transfer status and rationale;
- remaining local evidence target.

Transfer is bounded. Local evidence quickly dominates, and three contradictory local observations can reject negative transfer. A zero-start state remains available as a comparison. Later experiments can calibrate transfer caps with leave-one-project-out prediction.

## Failure patterns and mitigations

Each failed episode can contain normalized failure observations. The system aggregates repeated observations by arm, orientation, operation, code, and attribution. Attribution can be:

```text
worker-model · task-contract · tool · provider · harness · judge · environment · unknown
```

A pattern becomes active after repeated independent episodes, a human confirmation, or a reviewed critical event. The raw episodes remain linked but the dossier shows one aggregate pattern with count, severity, confidence, first/last seen, recency, and representative evidence.

Mitigations are separate versioned governance objects. Supported controls include prompt overlays, checklists, structured output, deterministic verification, second-pass review, shadow review, model escalation, tool restriction, and route exclusion.

```text
proposed → approved → canary → active → paused / retired
```

`approved` means a human accepted the governance object; it is not injected until it enters `canary` or `active`. Invalid lifecycle jumps are rejected. Mitigation approval and high-risk operation approval are distinct. A prompt can never authorize deletion, disclosure, force push, hardware writing, or power control.

## Judge calibration

An LLM Judge is itself a versioned evaluator arm:

```text
judge model + provider/epoch + task family + rubric + prompt + evidence-package version
```

Reliability is conditioned by task family. Pairwise evaluation should blind worker identity, randomize A/B order, repeat in swapped order where justified, allow tie/abstain, and record position consistency. Human labels are sampled for high-risk, high-disagreement, new-Judge, and random calibration cases.

Judge weights derive from observed agreement, position consistency, freshness and diversity—not from a manually asserted global IQ score or the Judge's raw self-confidence. Low-confidence results escalate through a calibrated cascade. Blind A/B observations are retained as facts and projected into a task-family-conditioned, reliability-weighted Bradley–Terry ranking; this is not a global model score.

## Dashboard visibility

The project dashboard displays current preference, concise reason, verified sample count, success/drift trend, cost/health, and warmup. Detailed score factors and posterior internals remain in audit projections. This keeps the operator informed without turning the dashboard into an opaque leaderboard dump.
