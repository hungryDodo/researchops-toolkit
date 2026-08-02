# Sub-Agents and model routing

## When parallelism helps

Delegate work that can be independently specified and verified, such as:

- separate literature query families or paper clusters;
- independent closest-work or counterexample searches;
- isolated code modules or worktrees;
- experiment cells that do not compete for the same hardware;
- result, statistics, figure, and citation checks;
- clean-context reproduction or reviewer roles;
- repository/data/test inventories.

Avoid parallel workers that concurrently write the same files, mutate shared state without a transaction boundary, compete for an exclusive device, or perform irreversible operations without independent approval.

## Task contract

Each dispatch should record:

- objective and task type;
- frozen inputs and authoritative files;
- allowed tools, writes, network/provider, and hardware scope;
- risk, privacy, and mutability level;
- acceptance tests and minimum verified quality;
- whether an independent verifier is required;
- budget, timeout, and escalation path;
- expected compact handoff artifact.

Workers should return a path to the authoritative artifact and a short summary, not dump an entire corpus into the parent context.

## Model selection

Routing first applies hard constraints:

1. privacy and provider approval;
2. required tools and context length;
3. write/hardware permissions;
4. risk and independent-verifier requirements;
5. cost, latency, and availability.

Only eligible models are scored using task-specific history: verified success rate, quality, human correction, verifier disagreement, latency, and cost. Low-risk tasks with deterministic acceptance may explore cheaper models. Core claims, destructive actions, and hardware writes require stronger verification or explicit human review.

## Third-party and local models

The package can register native harness models, local OpenAI-compatible endpoints, or a controlled gateway. Provider keys belong in environment variables or a secrets manager, never in repository configuration.

Optional gateways such as LiteLLM may provide provider normalization, retries, cooldowns, load balancing, and usage accounting. ResearchOps Toolkit remains responsible for semantic routing and acceptance policy.

## Independent acceptance

A worker's self-score never determines acceptance. Record deterministic checks, independent verifier output, human corrections, disagreement, cost, latency, and final disposition:

```text
accepted
accepted-with-corrections
retry-same
retry-stronger
route-different
reject
```

If a task contract requires an independent verifier, missing verification blocks profile updates and evidence promotion.

## Learning model strengths

Profiles are keyed by model version, Agent revision, task type, and risk band. They summarize observed performance rather than assigning a permanent global ranking. A model may be strong at corpus extraction, weak at statistics, cheap for formatting, or appropriate only for candidate generation.

Do not train an opaque learned router until enough independently evaluated tasks exist. Compare any learned policy against strongest-only, cheapest-only, random, static-rule, and current constrained-scoring baselines.
