# ResearchOps Toolkit documentation

## Fastest reading path

1. [`getting-started.md`](getting-started.md) — inspect/adopt a project, install a Preset, and start the Dashboard.
2. [`architecture.md`](architecture.md) — understand intake, layers, capability slices, and authoritative state.
3. [`research-and-development.md`](research-and-development.md) — choose Research-led or Development-led R&D.
4. [`model-intelligence.md`](model-intelligence.md) — evaluation, aggregation, routing, warmup, drift, and Judge calibration.
5. [`state-and-memory.md`](state-and-memory.md) — lifecycle-aware local Memory and optional adapters.
6. [`evaluation-and-baselines.md`](evaluation-and-baselines.md) — evaluate the product, Skills, routing, and longitudinal utility.
7. [`product-landscape.md`](product-landscape.md) — understand adjacent products and fair comparison boundaries.

## By concern

| Document | Use it when… |
|---|---|
| [`getting-started.md`](getting-started.md) | installing, adopting, resuming, or upgrading a project |
| [`architecture.md`](architecture.md) | deciding where a requirement belongs |
| [`workflows.md`](workflows.md) | following research gates, evidence states, and handoffs |
| [`research-and-development.md`](research-and-development.md) | distinguishing research-led code from product engineering |
| [`skills-and-bundles.md`](skills-and-bundles.md) | changing Skill ownership, triggers, modes, or progressive loading |
| [`model-intelligence.md`](model-intelligence.md) | working on model evaluation, routing, failure patterns, drift, or Judge logic |
| [`state-and-memory.md`](state-and-memory.md) | storing project state or integrating Harness/vector/graph memory |
| [`evaluation-and-baselines.md`](evaluation-and-baselines.md) | designing regression, external adapter, paired Skill, routing, or user-study evaluation |
| [`product-landscape.md`](product-landscape.md) | comparing or integrating observability, research-agent, coding-agent, or memory products |
| [`research-agenda.md`](research-agenda.md) | designing research questions, baselines, metrics, ablations, or longitudinal study |
| [`agents-and-model-routing.md`](agents-and-model-routing.md) | onboarding providers or dispatching workers |
| [`provider-configuration.md`](provider-configuration.md) | configuring DeepSeek, GLM, MiMo, MiniMax, credentials, endpoints, and Codex compatibility |
| [`presets-and-distribution.md`](presets-and-distribution.md) | generating Routing-only, Development-only, Research, or full artifacts |
| [`safety-and-hygiene.md`](safety-and-hygiene.md) | high-risk operations, approvals, hardware, cleanup, and privacy |
| [`migration-v2.md`](migration-v2.md) | moving from `.research/`, old JSONL profiles, or v1 Bundles |
| [`development.md`](development.md) | tests, provenance, release packaging, and contributions |

## Stable terminology

- **Skill:** user-facing workflow owner selected progressively by a Harness.
- **Mode / operation code:** internal classification inside a Skill; users need not memorize it.
- **Behavior Pack:** cross-cutting execution constraints selected by hooks/runtime.
- **Component / feature:** deterministic shared service that is not semantically routed as a top-level Skill.
- **Preset:** installation and packaging recipe. `Bundle` is retained only as a compatibility term.
- **Execution Arm:** a behaviorally meaningful model/provider/endpoint/configuration revision.
- **Evaluation Event:** one canonical observation about a completed work unit.
- **Projection:** generated, read-only view derived from canonical state.
- **Recall Memory:** non-authoritative context retrieval with scope, lifecycle, validity, and provenance.
