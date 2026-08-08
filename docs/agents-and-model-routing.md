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

## Work-unit contract

Delegation is appropriate when a task can be bounded with:

- objective and frozen acceptance contract;
- allowed read/write/tool scope;
- budget and stop conditions;
- required artifacts and verifier;
- orientation, primary operation, artifact, risk and privacy;
- an independent acceptance path where risk warrants it.

One long request should be split when discovery, design, implementation and validation require different evidence or model capabilities.

## Route selection

1. hard-filter ineligible arms;
2. query the most specific sufficiently supported profile;
3. quote current endpoint health and current price;
4. apply project utility/risk policy;
5. preserve uncertainty and bounded exploration;
6. record route decision and selection probability;
7. evaluate the completed work unit from artifacts/state, not prose impression alone.

The Router returns a selected arm plus applicable mitigation and verifier policy. It does not expose every internal score factor in the main UI.

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
