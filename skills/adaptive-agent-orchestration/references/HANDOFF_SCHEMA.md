# Handoff schema

A dispatch contract should contain:

```json
{
  "task_id": "survey-kv-routing-01",
  "stage": "survey",
  "task_type": "primary-source-extraction",
  "objective": "Extract mechanism, assumptions, experiments, and limitations from assigned papers.",
  "inputs": ["docs/survey/papers/batch-01.json"],
  "constraints": ["Do not infer missing results", "Use primary sources only"],
  "write_scope": ["reports/survey/agents/batch-01/"],
  "required_capabilities": ["long-context", "citation-extraction"],
  "reasoning_demand": "medium",
  "selected_execution_arm": {
    "arm_id": "provider/model@medium",
    "model": "model",
    "reasoning_effort": "medium"
  },
  "delegation": {"may_spawn_descendants": false, "remaining_depth": 0},
  "risk": "medium",
  "privacy": "internal",
  "expected_output": "evidence-table-v1",
  "acceptance_tests": ["all assigned papers accounted for", "no invented citation"],
  "budget": {"max_minutes": 30},
  "stop_conditions": ["source unavailable", "contradictory versions"],
  "escalate_to": "research-program-orchestrator"
}
```

Partition by task or evidence lane, not by permanent occupational identity. The current executor uses centralized fan-out: worker-to-worker descendants are rejected, and the authoritative Lead creates each additional bounded work unit so parent scope and budget cannot be silently expanded.

For automatic execution, use structured acceptance-test objects rather than prose-only test names. See `../assets/dispatch-contract.example.json`. `workspace-write` contracts require a clean Git worktree, Git-tracked inputs, and a non-empty safe relative `write_scope` whose outputs are not ignored; ResearchOps executes them in a detached private Git clone and applies only an accepted, bounded patch back to the still-clean project. Ignored `.researchops/state`, virtual environments, package caches, and untracked datasets are not copied into that clone; use a read-only worker plus Lead-owned state registration, or first create a reproducible tracked input artifact. Direct gateways are eligible only when `gateway_self_contained=true`, `inputs` is empty, and all required text is inline; file/artifact verification requires a Codex worker. `external-write`, `hardware-write`, and `destructive` mutability never enter the automatic worker executor.
