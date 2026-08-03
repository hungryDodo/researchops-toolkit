# Release validation — v1.7.0

- Completed: 2026-08-03T02:52:06+00:00
- Python: 3.13.5
- Platform: Linux-6.12.13-x86_64-with-glibc2.41
- Top-level Skills: 12
- Internal components: 3 (evidence ledger, dashboard, model control plane)
- Behavior Runtime: 1 universal kernel, 7 task packs, 3 Harness adapters, parsed risk policy, optional semantic reviewer
- Model Control Plane: 3 direct protocol adapters, provider recipes, secret-safe onboarding, routing dispatch, smoke tests, and evidence-backed dossiers
- Startup catalog estimate: 3956 / 8000 characters
- Trigger fixtures: 26 structural positive/negative cases
- Behavior fixtures: 9 task, pack, lifecycle, and decision cases
- Risk corpus: 134 adversarial and benign-neighbor command cases (100 positive, 34 negative)

## Successful automated checks

- Unified cross-platform CLI installation, bootstrap, bundle selection, and diagnostics.
- Skill structure, progressive-loading references, positive/negative trigger boundaries, eval files, metadata, and licenses.
- Trigger registry coverage, startup context budget, provenance, local Markdown links, and internal file hashes.
- Native Codex, Claude Code, and Gemini CLI agent rendering.
- Project Hook installation, plugin/extension manifests, task-pack selection, structured tool inspection, parsed/canonical risk policy, optional semantic escalation, and platform output adapters.
- Parent-session policy propagation into Sub-Agents without raw-prompt persistence.
- Interactive-operator, raw/canonical/rule-bound, short-lived, concurrency-safe one-use approvals and metadata-only behavior event logging.
- Proposal-only safeguard discovery, persistence, snooze state, and no target execution.
- Provider/model onboarding, secret-safe doctor/probe/enrollment, remote model discovery, direct dispatch, deterministic smoke tests, and model-specific prompt-overlay approval.
- Sub-Agent routing, bounded exploration, deterministic checks, independent verification, routing-profile recording, and model-dossier refresh.
- Archive-first cleanup, restore, separate purge, large-data quarantine, semantic ID normalization, and worktree safety.
- Research engineering gauntlet, LaTeX discovery, dashboard validation, Python compilation, and ZIP integrity.

## Smoke summary

```json
{
  "workflow": {
    "project": {
      "router_primary": "codex/gpt-5.6-luna",
      "verified_quality": 0.976667,
      "skills_per_framework": 12,
      "semantic_ids_normalized": true,
      "quarantine_and_purge": true,
      "archive_restore_and_purge": true,
      "repository_archive": true,
      "bundle_install": true,
      "gauntlet_and_latex_audit": true,
      "idempotent_next_step": true,
      "proposal_only_broker": true,
      "symlink_boundary": true
    },
    "worktree": {
      "eligible_child_removed": true,
      "main_blocked": true
    }
  },
  "behavior": {
    "behavior_packs": 7,
    "framework_hook_configs": 3,
    "rm_bypass_variants": 8,
    "high_risk_categories_smoked": 11,
    "benign_neighbors": 6,
    "rops_external_dispatch_guarded": true,
    "parsed_command_policy": true,
    "content_bound_one_use_approval": true,
    "semantic_escalation": true,
    "semantic_cannot_downgrade_static": true,
    "required_semantic_fail_closed": true,
    "structured_tool_policy": true,
    "metadata_only_logging": true,
    "feedback_without_auto_weakening": true,
    "hook_fail_closed_in_enforce": true,
    "subagent_context_inheritance": true,
    "operator_only_approval": true
  },
  "model_control_plane": {
    "protocol_adapters": 3,
    "providers_enrolled": [
      "mock-openai/mock-model",
      "mock-anthropic/mock-claude",
      "mock-google/mock-gemini"
    ],
    "secret_values_logged": false,
    "remote_model_listing": true,
    "smoke_does_not_train_profile": true,
    "verified_history_updates_dossier": true,
    "prompt_overlay_requires_approval": true,
    "unsafe_secret_file_rejected": true,
    "prompt_overlay_not_duplicated": true,
    "agent_prompt_and_overlay_injected": true,
    "bounded_route_and_dispatch": true
  }
}
```

## Validation boundary

Trigger and Behavior fixtures verify structural and regression coverage, not exhaustive shell-language safety or empirical reviewer accuracy for every model/Harness release. Hook enforcement only covers exposed lifecycle/tool paths and does not replace platform permissions, sandboxing, repository protection, hardware interlocks, or human confirmation.
