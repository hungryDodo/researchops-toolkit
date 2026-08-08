# Research agenda: project-scoped model intelligence

## Problem statement

ROPS treats model selection as a project-scoped, task-conditional and non-stationary decision problem. The unit of evidence is a verified work unit, not a single answer or a global benchmark score. A route decision chooses an execution arm together with applicable mitigation and verification policy, while endpoint health and current price remain separate runtime facts.

The research goal is to test whether this design produces more verified project progress per unit cost and human effort than static model choice, without allowing noisy Judge scores or stale project history to become permanent stereotypes.

## Research questions

### RQ1 — Does verified-progress routing outperform static choice?

Compare:

- always use the nominally strongest model;
- always use the cheapest eligible model;
- round robin / random;
- a static global leaderboard;
- the current transparent UCB baseline;
- project-scoped routing with bounded warmup;
- an offline oracle computed after all outcomes are known.

Primary outcome: accepted verified progress under a fixed budget. Secondary outcomes: completion, quality, cost, latency, human correction, catastrophic failure and route regret.

### RQ2 — What conditioning scope is useful without overfitting?

Ablate the finite v2 scopes:

1. arm global;
2. arm × operation;
3. arm × project × operation;
4. arm × orientation × operation.

Candidate metadata such as language, stack or device enters routing only if a chronological holdout shows lower prediction loss or higher routing utility with adequate sample support.

### RQ3 — Does bounded soft transfer improve cold start?

Compare zero start, conservative transfer and normal transfer. Measure:

- episodes until local calibration target;
- early-project verified progress;
- Brier/log loss for the first 5 and 10 work units;
- negative-transfer frequency;
- time until local evidence dominates;
- user-visible warmup/rootedness trajectory.

Transfer caps should be calibrated by leave-one-project-out evaluation rather than chosen only by intuition.

### RQ4 — Can black-box degradation be detected early enough to reroute?

Inject or observe:

- endpoint outage and rate limiting;
- latency/TTFT changes;
- price-window changes;
- output truncation or schema regressions;
- tool-call format changes;
- controlled worker-quality degradation;
- a declared model revision or simulated silent deployment swap.

Measure detection delay, false alarms, missed changes, regret before rerouting and recovery after a new deployment epoch. The system reports observable behavior drift and never claims to prove an unobservable hidden-weight replacement.

### RQ5 — Do failure-pattern mitigations improve use of a model?

For repeated failure patterns, compare:

- no intervention;
- prompt overlay;
- checklist/structured output;
- deterministic verifier;
- second-pass or shadow review;
- model escalation or route exclusion.

Measure task-specific uplift, cost/latency overhead, new side effects and whether a mitigation transfers safely across projects. Approval, canary and active phases must remain distinguishable.

### RQ6 — How should heterogeneous LLM Judges be aggregated?

Compare:

- one Judge;
- equal-weight panel;
- human-calibrated Judge weights;
- reliability-weighted Bradley–Terry;
- a future judge-aware BT model that jointly estimates item strength and Judge reliability.

Test worker-identity blinding, A/B order swaps, ties, abstention, verbosity/format perturbations and non-transitivity. High-risk or low-margin cases escalate to deterministic checks, a different Judge family or a human.

### RQ7 — Does optional recall help without corrupting authority?

Compare exact state only, SQLite FTS recall and optional vector/external-memory adapters. Evaluate similar-task retrieval, cold-start decisions, long-task recovery and failure-pattern discovery. Recall must not directly modify profiles, activate mitigations or override current price/health facts.

### RQ8 — Does modular distribution preserve behavior?

Validate `routing-core`, `development-core`, `research-base`, `research-routed` and `full` independently. Measure installation surface, startup catalog size, package size, missing-dependency failures and behavior equivalence for shared components.

## Evaluation corpus

Use three layers:

1. **Anchor packs** — small reproducible tasks for onboarding and longitudinal calibration.
2. **Replayable project work units** — repository snapshots, task contracts, verifiers and expected artifact/state transitions.
3. **Live work** — real project episodes with selection probability, evidence, cost and human feedback.

Chronological and leave-one-project-out splits are required. Highly similar tasks from one repository must not be randomly split across train and test.

## Minimal metric set

Keep the main paper focused:

- verified progress;
- accepted completion;
- quality;
- monetary cost;
- wall time;
- human correction time;
- reliability / repeated success;
- severe-failure rate;
- adaptation delay;
- drift detection delay;
- Judge–human agreement and calibration.

Raw observations remain available for analysis, but the product dashboard displays only the operator-relevant subset.

## Current implementation boundary

v2.1 provides the deterministic data plane and transparent baselines needed to run these studies. Its smoke tests establish structural correctness, migration, isolation and reproducibility; they do not prove that one routing policy is empirically optimal across providers or projects.

Not included in the initial empirical claim:

- a learned semantic project-similarity model;
- a mandatory vector or graph database;
- autonomous activation of mitigations;
- proof that a provider changed hidden weights;
- a universal model IQ score;
- a global ranking that ignores task family.

## Closely related research directions

Representative starting points include contextual/cost-aware LLM routing (FrugalGPT and RouteLLM), longitudinal model-behavior evaluation, non-stationary bandits, fine-grained Agent progress evaluation, task-state verification, LLM-as-a-Judge bias and non-transitivity, and judge-aware Bradley–Terry aggregation. Black-box model-modification detection (<https://arxiv.org/abs/2504.12335>) supports frozen canaries and distributional monitoring, while Memora (<https://arxiv.org/abs/2604.20006>) and MemoryArena motivate evaluation of memory mutation and downstream multi-session utility. SWE-Skills-Bench (<https://arxiv.org/abs/2603.15401>) reinforces that procedural Skills need paired, deterministic marginal-utility tests and may hurt when mismatched.

## RQ9 — Does inspect-before-write adoption improve time-to-useful-state?

Compare empty-project initialization, blind workflow reset, and ResearchOps adoption on repositories sampled at different lifecycle stages. Measure preservation, phase/active-workstream agreement with the owner, time to identify the next valid work unit, redundant work, and correction burden. Ablate deterministic scan, agent semantic review, and adoption depth.

## RQ10 — Does lifecycle-aware Memory improve longitudinal work?

Compare no recall, raw conversation/history retrieval, flat FTS/vector recall, ResearchOps Memory v2.1, and optional graph/external adapters. Evaluate retrieval precision/recall, stale/conflicting recall, context tokens, repeated user explanations, recovery after interruption, task success, and latency. Memory is useful only if downstream work improves; retrieval metrics alone are insufficient.

## RQ11 — Does the ResearchOps plugin itself provide measurable marginal utility?

Run paired, pinned-repository tasks with and without selected Presets/Skills using the same Harness/model/budget. Measure acceptance, verified progress, regressions, token and dollar overhead, wall time, human correction, and severe failures. Include negative results and compatibility failures. This follows the same first-principles concern as recent Skill-effect benchmarks: procedural packages must demonstrate marginal value rather than assume it.

## Tool-level baselines

The bundled Product Benchmark covers deterministic adoption, Dashboard, state, and Memory behavior. Broader comparisons should include observability/evaluation platforms, scientific literature agents, software-development agents, and memory systems only on shared dimensions. See `product-landscape.md` and `evaluation-and-baselines.md`.
