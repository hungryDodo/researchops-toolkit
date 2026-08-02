# Agent performance evaluation protocol

## Avoid circular grading

Use this preference order:

1. deterministic acceptance tests;
2. external ground truth or primary-source verification;
3. a separately configured verifier model/agent;
4. calibrated human review;
5. worker self-assessment only as metadata.

`evaluate_dispatch.py` never uses worker self-scores to accept a result. It computes deterministic coverage, optionally blends an independent verifier score, applies recorded human-correction penalties, and emits a registry event. A contract can require an independent verifier with `requires_independent_verifier: true`.

## Contract fields

```json
{
  "task_id": "survey-batch-01",
  "task": {
    "stage": "survey",
    "type": "extraction",
    "risk": "medium",
    "privacy": "internal",
    "mutability": "read-only"
  },
  "minimum_verified_quality": 0.85,
  "requires_independent_verifier": true,
  "acceptance_tests": [
    {
      "name": "structured result",
      "type": "json_path_equals",
      "source": "result",
      "json_path": "status",
      "expected": "complete",
      "required": true,
      "weight": 1.0
    }
  ]
}
```

## Independent verifier file

```json
{
  "verifier_id": "independent-reviewer-v3",
  "model_id": "provider/model-version",
  "independent": true,
  "confidence": 0.82,
  "disposition": "accepted",
  "dimensions": {
    "correctness": 0.9,
    "evidence_quality": 0.85,
    "scope_discipline": 1.0
  },
  "failure_modes": [],
  "verifier_disagreement": 0.05,
  "notes": "All source claims were checked against the assigned primary papers."
}
```

The verifier must not share the worker's hidden scratchpad or be instructed to preserve the worker's conclusion. For high-risk claims, use a stronger model, deterministic reproduction, or human review rather than a cheap model grading another cheap model.

## Human feedback file

```json
{
  "reviewer": "human-owner",
  "correction_fraction": 0.1,
  "notes": "One table label and two citations were corrected."
}
```

`override_disposition` is allowed only for an explicit human decision and remains visible in the event.

## Minimum event record

Each event should include task features, selected candidates and scores, chosen model/provider/version, agent revision, start/end times, usage, cost, retries, acceptance-test outcomes, quality dimensions, human correction, verifier disagreement, final disposition, failure attribution, and artifact hashes/paths.

## Cold start

Before five observations for a task-model pair, rely mostly on declared capabilities and conservative priors. Use exploration only on bounded low/medium-risk tasks with deterministic checks. Report uncertainty in every recommendation.
