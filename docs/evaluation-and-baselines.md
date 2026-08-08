# Product evaluation, baselines, and benchmark methodology

ResearchOps evaluates both the models it routes and the tool that performs the routing.
These are separate evaluation problems.

## Evaluation layers

### A. Deterministic product regression

The built-in Product Benchmark runs without model API keys. It measures whether the
software itself behaves correctly on a non-empty research/software repository:

- inspect-before-write adoption;
- preservation of existing files;
- host-root pollution and single-hidden-root behavior;
- status inference and review flagging;
- Dashboard initialization, actual HTTP quick start, and visible intake/Memory/routing;
- SQLite authority;
- Memory deduplication, supersession, temporal validity, scope isolation, provenance,
  four-layer coverage, bounded context assembly, and idempotent synchronization.

Run:

```bash
python3 -m rops evaluate \
  --baseline-root /path/to/older/researchops \
  --out /tmp/researchops-product-benchmark
```

The report contains raw measurements, boolean acceptance checks, version/configuration,
and an explicit interpretation boundary.

### B. External product adapters

A third-party adapter should execute an equivalent fixture and emit the report contract
in `config/product-benchmark-report.schema.json`. Import the result with:

```bash
python3 -m rops evaluate \
  --baseline-report /path/to/external-report.json \
  --out /tmp/comparison
```

An adapter may mark unsupported dimensions as uncovered; it must not fabricate `false`
or `true` results. Comparisons should report both score and coverage.

### C. Skill and workflow contribution

Use paired runs on pinned project snapshots:

```text
Harness/model without ResearchOps intervention
vs.
the same Harness/model with one selected Preset/Skill
```

Keep model, endpoint, reasoning effort, tools, task, seed policy, and budget as stable as
possible. Measure verified progress, acceptance, regressions, human correction, token
and dollar cost, wall time, and catastrophic failures. Skills can add overhead or even
harm mismatched tasks, so selection and compatibility are part of the hypothesis rather
than assumed benefits.

SWE-Skills-Bench is a directly relevant research direction because it evaluates the
marginal effect of procedural Skill packages with paired execution-based acceptance:
<https://arxiv.org/abs/2603.15401>.

### D. Model-intelligence/routing evaluation

Compare:

- fixed strongest model;
- fixed cheapest model;
- random/round-robin;
- static global ranking;
- manual policy;
- current online router;
- oracle hindsight bound.

Use chronological and leave-one-project-out splits. Report cumulative verified utility,
cost per accepted milestone, regret, adaptation delay, failure severity, exploration
cost, and calibration. Endpoint outages and prices must be separated from competence.

### E. Longitudinal product utility

A tool can pass unit tests and still be unpleasant or ineffective in real work. Run a
multi-project user study or diary study measuring:

- time to first useful state;
- time to locate the next action/blocker;
- repeated context the user must restate;
- manual correction and approval burden;
- project-state accuracy as judged by the owner;
- recovery after interruption;
- cost per accepted work unit;
- trust and explanation usefulness;
- retention after one or more weeks.


### F. Longitudinal Memory evaluation

Memory quality is not equivalent to retrieval recall. Use multi-session fixtures with
explicit fact creation, consolidation, correction, expiration, deletion, and conflicting
updates. Report current-state answer accuracy, obsolete-memory reuse, provenance coverage,
context tokens, latency, and downstream task success. Memora's forgetting-aware framing and
MemoryArena's interdependent multi-session tasks are useful reference points:

- Memora: <https://arxiv.org/abs/2604.20006>
- MemoryArena: <https://digitaleconomy.stanford.edu/publication/memoryarena-benchmarking-agent-memory-in-interdependent-multi-session-agentic-tasks/>

ResearchOps should compare exact SQL state, flat retrieval, Memory v2.1, and optional external
adapters on the same evolving project history. A result that retrieves more text but reuses an
invalidated decision is a regression, not an improvement.

### G. Black-box deployment-drift evaluation

Use frozen identity canaries and task anchors, then inject controlled changes such as response
truncation, tool-schema regression, quantized/local substitution, mixed routing, or a new
deployment epoch. Measure detection delay, false alarms, missed changes, and routing regret.
Output-feature distribution tests and online adaptive detection provide starting points:

- Detecting Modification of Black-Box LLMs: <https://arxiv.org/abs/2504.12335>
- Online Detection for Black-Box LLMs: <https://openreview.net/forum?id=fwHVclv0ij>

The benchmark can establish that observable behavior changed; it cannot prove the provider's
internal cause.

## Current bundled baseline

The v2.1 release report compares the supplied v2.0 source package with v2.1 on the local
deterministic suite. The expected interpretation is narrow:

- it demonstrates regression improvement for project adoption, quick-start Dashboard,
  and Memory lifecycle behavior;
- it does not demonstrate that ResearchOps produces better scientific discoveries than
  every other agent tool;
- local process latency should not be compared across machines;
- external products require adapters and equivalent deployments.

The generated report is included under `release/product-benchmark.{json,md}`.

## Benchmark-pack relationship

Product Benchmark and Model Benchmark Packs are different:

- Product Benchmark tests ResearchOps software/product behavior.
- Model Benchmark Packs define task fixtures, evaluators, and metrics for execution arms.
- Live Evaluation Events measure actual project work.

All three can share deterministic verifiers and artifact contracts, but their evidence
must remain labeled by source.

## Required reporting discipline

Every published comparison should include:

- exact ResearchOps, Harness, model, endpoint/deployment epoch, prompt, mitigation,
  evaluator, and adapter revisions;
- task and project sampling procedure;
- coverage and unsupported dimensions;
- raw event/artifact references when releasable;
- uncertainty, repeated trials, and failure distributions;
- costs including Judge and retry overhead;
- negative results and cases where the plugin does not help.
