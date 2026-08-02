# Trigger design

Semantic description matching is primary. Keywords are examples for evaluation, never the sole router.

A strong description states:
- the owned job;
- concrete situations in which it should activate;
- adjacent situations in which it must not activate;
- important safety or lifecycle boundary.

Evaluate at least:
- obvious positive requests;
- paraphrased positives without the preferred keyword;
- obvious negatives;
- adjacent-skill conflicts;
- broad requests that should route to an orchestrator;
- explicit invocation.

For high-cost or high-risk Skills, prefer explicit invocation or orchestrator-owned activation. For common low-risk Skills, semantic implicit activation is acceptable when overlap tests pass.
