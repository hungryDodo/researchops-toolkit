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

## Routing strategy

The provided registry uses constrained ranking, not an opaque learned router:

1. reject candidates violating hard constraints;
2. combine declared prior affinity with beta-smoothed observed success/quality;
3. subtract normalized cost, latency, correction, and verifier-disagreement penalties;
4. add a bounded exploration bonus for eligible low-risk tasks;
5. select a primary and, when required, a verifier/escalation model.

This is intentionally interpretable during cold start. Once hundreds of well-labeled tasks exist, the history can train a separate router, but it must be evaluated offline against static, random, strongest-only, cheapest-only, and rules-based baselines before deployment.

## Avoid self-reinforcing bias

- randomize a small safe fraction of low-risk tasks across eligible models;
- keep failed and escalated tasks in history;
- separate task difficulty from model quality;
- use independent acceptance tests and human ratings;
- pin model versions and prompt/agent revisions;
- compare costs at equal verified quality, not self-rated quality;
- do not train on outputs that the same model graded without calibration.
