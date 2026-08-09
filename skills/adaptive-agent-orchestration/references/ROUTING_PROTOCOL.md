# Adaptive routing protocol

## Task feature taxonomy

Record at least:

- stage: survey, route-triage, design, implementation, execution, analysis, writing, review, hygiene;
- type: search, extraction, coding, debugging, experiment-run, statistics, synthesis, critique, formatting, hardware;
- ambiguity: low/medium/high;
- risk: low/medium/high/critical;
- mutability: read-only/workspace-write/external-write/hardware-write/destructive;
- context volume: small/medium/large;
- required capabilities and tools;
- privacy: public/internal/confidential/restricted;
- deterministic acceptance tests available: yes/no;
- estimated duration/cost.
- reasoning demand: low/medium/high/extreme;
- decomposability: low/medium/high;
- dependency structure: independent/mixed/sequential;
- tool intensity and shared mutable state;
- exact/minimum/maximum reasoning effort when the contract requires a bound.

## Routing strategy

The provided registry uses constrained ranking, not an opaque learned router:

1. treat each model × reasoning-effort pair as a separate execution arm and reject candidates violating hard constraints;
2. combine declared prior affinity with beta-smoothed observed success/quality;
3. score task-demand/effort fit without assuming that more effort is always better;
4. subtract normalized cost, latency, correction, and verifier-disagreement penalties;
5. add a bounded exploration bonus for eligible low-risk tasks;
6. select a primary and, when required, a verifier/escalation arm from a different model family when possible.
7. persist the complete eligible candidate ranking, exact arm identity, score components, and selection flag under the route decision.

This is intentionally interpretable during cold start. Once hundreds of well-labeled tasks exist, the history can train a separate router, but it must be evaluated offline against static, random, strongest-only, cheapest-only, and rules-based baselines before deployment.

## Coordination topology

Agent templates are capability, context, mutability, and acceptance envelopes. They are not long-lived company departments and should not make a general model pretend to be permanently specialized.

- Use one agent for sequential dependencies, shared mutable state, small tasks, or coordination-heavy tool use.
- Use a centralized Lead with fan-out/fan-in for independent bounded work units. The Lead owns the session objective, task graph, budgets, routing, and synthesis.
- Use fresh-context workers for independent evidence lanes or implementation units, then pass artifact references rather than repeatedly summarizing full outputs.
- Use a separate verifier because context isolation and non-self-approval are evaluation controls, not because the verifier is a permanent occupational persona.
- A Harness may technically support agent trees, but the current ResearchOps executor uses centralized Lead fan-out and caps worker delegation depth at zero. Workers return decomposition requests so the Lead can route and record each child independently.

Current evidence supports task-conditioned topology rather than a universal multi-agent company chart: centralized coordination improves parallelizable work, while multi-agent variants can degrade sequential reasoning. See [Google Research's controlled agent-system study](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/) and [the paper](https://arxiv.org/abs/2512.08296). OpenAI's [Multi-agent guide](https://developers.openai.com/api/docs/guides/responses-multi-agent) likewise recommends bounded independent workstreams and documents descendant agent trees.

## Model and effort priors

Priors bootstrap exploration; they are not permanent rankings. Current official OpenAI guidance positions GPT-5.6 Sol for frontier professional work, Terra for the intelligence/cost balance, and Luna for cost-sensitive high-volume work. Start routine work near medium effort, use low for latency-sensitive work, move to high/xhigh only when evaluation shows a gain, and reserve max for the hardest quality-first workloads. Re-test the same effort and one level lower on representative tasks. See [official GPT-5.6 guidance](https://developers.openai.com/api/docs/guides/latest-model).

Codex `ultra` includes automatic task delegation in the local model catalog. Treat it as an orchestration mode with its own evaluation, not as one more linear worker-effort level.

## Avoid self-reinforcing bias

- randomize a small safe fraction of low-risk tasks across eligible models;
- keep failed and escalated tasks in history;
- separate task difficulty from model quality;
- use independent acceptance tests and human ratings;
- pin model versions and prompt/agent revisions;
- pin and record reasoning effort; never pool evidence across effort variants under one arm;
- compare costs at equal verified quality, not self-rated quality;
- do not train on outputs that the same model graded without calibration.
