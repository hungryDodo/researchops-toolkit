# Semantic reviewer adapters

The deterministic parser and policy engine are the primary portable guardrail.
An optional semantic reviewer can inspect commands that are dynamic, ambiguous,
or outside the static rule set. It can only add or escalate findings; it cannot
remove deterministic findings.

Configure any executable that reads one JSON object from stdin and writes one
JSON object to stdout:

```json
{
  "risk": "none|medium|high|critical",
  "categories": ["category"],
  "reason": "evidence-based explanation",
  "confidence": 0.0,
  "reviewer": "provider:model"
}
```

Example using the included OpenAI-compatible adapter:

```bash
export ROPS_REVIEW_BASE_URL=http://127.0.0.1:8000/v1
export ROPS_REVIEW_MODEL=your-local-or-approved-model
# export ROPS_REVIEW_API_KEY=...  # only when the endpoint requires it

python3 -m rops behavior --root /path/to/project semantic \
  --mode advisory \
  --scope uncertain \
  --command "python3 /path/to/researchops-toolkit/behavior/reviewers/openai_compatible.py"
```

`--scope all` reviews every exposed tool input and can add substantial latency
and cost. Raw tool input is sent to the configured reviewer only after this
explicit opt-in. Use an approved local endpoint for sensitive projects.
