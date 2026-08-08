# Handoff schema

A dispatch contract should contain:

```json
{
  "task_id": "survey-kv-routing-01",
  "stage": "survey",
  "task_type": "primary-source-extraction",
  "objective": "Extract mechanism, assumptions, experiments, and limitations from assigned papers.",
  "inputs": [".researchops/state/survey/papers/batch-01.json"],
  "constraints": ["Do not infer missing results", "Use primary sources only"],
  "write_scope": [".researchops/state/survey/agents/batch-01/"],
  "required_capabilities": ["long-context", "citation-extraction"],
  "risk": "medium",
  "privacy": "internal",
  "expected_output": "evidence-table-v1",
  "acceptance_tests": ["all assigned papers accounted for", "no invented citation"],
  "budget": {"max_minutes": 30, "max_cost_usd": 2.0},
  "stop_conditions": ["source unavailable", "contradictory versions"],
  "escalate_to": "research-program-orchestrator"
}
```
