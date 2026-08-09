# Model profile protocol

- Write accepted work-unit outcomes as canonical Evaluation Events in SQLite.
- Give every model × reasoning-effort configuration its own stable execution-arm ID. Keep `model_family` for family-level comparison, but do not merge effort-specific evidence.
- Keep region/endpoint and subscription-plan variants separate when they can change latency, availability, price, policy, or returned behavior.
- Persist every eligible arm's task-specific route score and score components in `route_candidate_scores`; use Evaluation Events as outcome evidence and never confuse the two.
- Do not maintain a Skill-local aggregation implementation.
- Probe/smoke is endpoint/identity telemetry only.
- Use finite profile scopes and preserve uncertainty/sample count.
- Keep endpoint health, current price and competence separate.
- A model dossier is a generated projection composed from profiles, failure patterns, mitigations and deployment epochs.
- Repeated failure observations may become an aggregated pattern; do not turn one episode into a permanent stereotype.
- New project transfer is bounded and must yield quickly to local evidence.
