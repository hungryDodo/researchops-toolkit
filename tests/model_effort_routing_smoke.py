from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rops.intelligence.routing import recommend
from rops.intelligence.store import IntelligenceStore
from rops.models import sync_registry
from rops.project import bootstrap, doctor, install


def route(store: IntelligenceStore, *, demand: str, effort: str | None = None, write: bool = False) -> dict:
    task = {
        "project_id": "model-effort-smoke",
        "objective": f"Solve one {demand} reasoning work unit",
        "orientation": "development-led",
        "operation": "implement",
        "primary_artifact": "code",
        "risk": "medium",
        "privacy": "internal",
        "mutability": "read-only",
        "required_capabilities": ["reasoning", "code"],
        "model_family_allowlist": "gpt-5.6-sol",
        "reasoning_demand": demand,
        "decomposability": "low",
        "dependency_structure": "sequential",
    }
    if effort:
        task["reasoning_effort"] = effort
    return recommend(store, task, agent_name="bounded_read_worker", write=write, random_seed=7)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="model-effort-routing-", dir=ROOT) as temp:
        root = Path(temp) / "project"
        bootstrap(root, "Model Effort Routing Smoke", upgrade=True)
        store = IntelligenceStore(root)
        registry = sync_registry(store)
        models = json.loads((root / ".researchops/governance/models.json").read_text(encoding="utf-8"))["models"]

        sol_arms = [model for model in models if model.get("model_family") == "gpt-5.6-sol"]
        assert {model.get("reasoning_effort") for model in sol_arms} >= {"medium", "high", "xhigh", "max"}
        assert len({_arm["id"] for _arm in sol_arms}) == len(sol_arms)
        assert registry["execution_arms"] == len(models)

        medium = route(store, demand="medium")
        high = route(store, demand="high")
        extreme = route(store, demand="extreme")
        forced_max = route(store, demand="extreme", effort="max")
        recorded = route(store, demand="high", write=True)

        assert medium["primary"]["model_family"] == high["primary"]["model_family"] == "gpt-5.6-sol"
        assert medium["primary"]["reasoning_effort"] == "medium"
        assert high["primary"]["reasoning_effort"] == "high"
        assert extreme["primary"]["reasoning_effort"] == "xhigh"
        assert forced_max["primary"]["reasoning_effort"] == "max"
        assert forced_max["primary"]["execution"] == {
            "provider": "codex-native",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "max",
            "reasoning_mode": "standard",
        }
        score_rows = store.json_rows(
            "SELECT * FROM route_candidate_scores WHERE decision_id=? ORDER BY rank",
            (recorded["decision_id"],),
            json_columns=("components_json", "endpoint_health_json", "price_json", "execution_json"),
        )
        assert recorded["schema_version"] == 4
        assert len(score_rows) == len(recorded["ranked"])
        assert sum(int(row["selected"]) for row in score_rows) == 1
        assert score_rows[0]["arm_id"] == recorded["ranked"][0]["model_id"]
        assert all("reasoning_fit" in row["components_json"] for row in score_rows)
        assert {row["reasoning_effort"] for row in score_rows} >= {"medium", "high", "xhigh", "max"}

        parallel = recommend(
            store,
            {
                "project_id": "model-effort-smoke",
                "objective": "Inspect three independent repository areas",
                "operation": "discover",
                "risk": "low",
                "privacy": "internal",
                "mutability": "read-only",
                "decomposability": "high",
                "dependency_structure": "independent",
                "tool_intensity": "medium",
            },
            write=False,
            random_seed=7,
        )
        assert parallel["orchestration"]["topology"] == "centralized-fanout"
        assert medium["orchestration"]["topology"] == "single-agent"

        lead = recommend(
            store,
            {
                "project_id": "model-effort-smoke",
                "objective": "Build and govern a bounded task graph",
                "operation": "orchestrate",
                "risk": "high",
                "privacy": "internal",
                "mutability": "read-only",
                "reasoning_demand": "high",
            },
            agent_name="session_lead",
            write=False,
            random_seed=7,
        )
        assert lead["primary"]["reasoning_effort"] == "high"
        assert "coordination" in next(model for model in models if model["id"] == lead["primary"]["model_id"])["capabilities"]

        renderer = ROOT / "skills/adaptive-agent-orchestration/scripts/render_native_agents.py"
        subprocess.run([sys.executable, str(renderer), "--root", str(root), "--framework", "codex"], check=True, capture_output=True, text=True)
        lead_toml = (root / ".codex/agents/session_lead.toml").read_text(encoding="utf-8")
        assert 'model = "gpt-5.6-sol"' in lead_toml
        assert 'model_reasoning_effort = "high"' in lead_toml

        existing_hooks = root / ".codex/hooks.json"
        existing_hooks.write_text(
            json.dumps({
                "hooks": {
                    "PreToolUse": [{
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "echo existing-hook"}],
                    }]
                }
            }) + "\n",
            encoding="utf-8",
        )

        install(
            target="codex",
            scope="project",
            project=root,
            mode="copy",
            preset="routing-core",
            with_agents=True,
            with_behavior=True,
        )
        installation_health = doctor(target="codex", project=root)["targets"]["codex"]
        assert installation_health["healthy"]
        assert not installation_health["missing"]
        assert installation_health["preset"] == "routing-core"
        stale_skill = root / ".agents/skills/software-development"
        stale_skill.symlink_to(ROOT / "skills/software-development", target_is_directory=True)
        stale_health = doctor(target="codex", project=root)["targets"]["codex"]
        assert not stale_health["healthy"]
        assert stale_health["extra"] == ["software-development"]
        stale_skill.unlink()
        merged_hooks = json.loads(existing_hooks.read_text(encoding="utf-8"))["hooks"]
        pre_tool_commands = [
            item["command"]
            for group in merged_hooks["PreToolUse"]
            for item in group.get("hooks", [])
        ]
        assert "echo existing-hook" in pre_tool_commands
        assert sum("researchops_hook.py" in command for command in pre_tool_commands) == 1
        assert all(merged_hooks[event] for event in ("SessionStart", "UserPromptSubmit", "SubagentStart"))
        installed_registry = root / ".agents/skills/adaptive-agent-orchestration/scripts/agent_registry.py"
        installed_dispatcher = root / ".agents/skills/adaptive-agent-orchestration/scripts/dispatch_worker.py"
        installed_evaluator = root / ".agents/skills/adaptive-agent-orchestration/scripts/evaluate_dispatch.py"
        installed_runtime = root / ".researchops/runtime/rops/orchestration.py"
        assert installed_dispatcher.is_file() and installed_evaluator.is_file() and installed_runtime.is_file()
        assert os.access(installed_dispatcher, os.X_OK) and os.access(installed_evaluator, os.X_OK)
        assert (root / ".researchops/runtime/config/provider-recipes.json").is_file()
        assert (root / ".researchops/runtime/config/execution-arms.json").is_file()
        clean_env = dict(os.environ)
        clean_env.pop("PYTHONPATH", None)
        installed = subprocess.run(
            [
                sys.executable,
                str(installed_registry),
                "--root",
                str(root),
                "recommend",
                "--no-write",
                "--compact",
                "--task-json",
                json.dumps(
                    {
                        "objective": "Review three independent evidence files",
                        "operation": "discover",
                        "reasoning_demand": "medium",
                        "reasoning_effort": "medium",
                        "decomposability": "high",
                        "dependency_structure": "independent",
                    }
                ),
            ],
            cwd=root,
            env=clean_env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert installed.returncode == 0, installed.stderr
        installed_route = json.loads(installed.stdout)
        assert installed_route["primary"]["reasoning_effort"] == "medium"
        assert installed_route["orchestration"]["topology"] == "centralized-fanout"

        database = root / ".researchops/intelligence/state.sqlite"
        digest_before = hashlib.sha256(database.read_bytes()).hexdigest()
        read_only_store = IntelligenceStore(root, read_only=True)
        read_only_route = route(read_only_store, demand="high")
        assert read_only_route["primary"]["reasoning_effort"] == "high"
        assert hashlib.sha256(database.read_bytes()).hexdigest() == digest_before
        try:
            with read_only_store.transaction():
                pass
        except RuntimeError as exc:
            assert "read-only" in str(exc)
        else:
            raise AssertionError("read-only store unexpectedly allowed a transaction")

        models_path = root / ".researchops/governance/models.json"
        external_registry = json.loads(models_path.read_text(encoding="utf-8"))
        for model in external_registry["models"]:
            if model.get("model_family") == "deepseek-v4-flash":
                model["enabled"] = True
        models_path.write_text(json.dumps(external_registry) + "\n", encoding="utf-8")
        sync_registry(store)
        external_none = recommend(
            store,
            {
                "project_id": "model-effort-smoke",
                "objective": "Run a bounded direct extraction without thinking",
                "operation": "discover",
                "risk": "low",
                "privacy": "internal",
                "mutability": "read-only",
                "model_family_allowlist": ["deepseek-v4-flash"],
                "reasoning_effort": "none",
            },
            agent_name="bounded_read_worker",
            write=False,
            random_seed=7,
        )
        external_max = recommend(
            store,
            {
                "project_id": "model-effort-smoke",
                "objective": "Solve a bounded difficult debugging analysis",
                "operation": "debug",
                "risk": "medium",
                "privacy": "internal",
                "mutability": "read-only",
                "model_family_allowlist": ["deepseek-v4-flash"],
                "reasoning_effort": "max",
            },
            agent_name="bounded_read_worker",
            write=False,
            random_seed=7,
        )
        assert external_none["primary"]["model_id"] == "deepseek/deepseek-v4-flash@none"
        assert external_max["primary"]["model_id"] == "deepseek/deepseek-v4-flash@max"
        assert external_max["primary"]["execution"]["provider"] == "deepseek"
        assert external_max["primary"]["execution"]["codex_profile"] == "researchops_deepseek"

        bridge_registry = json.loads(models_path.read_text(encoding="utf-8"))
        for model in bridge_registry["models"]:
            if model.get("provider") == "litellm-zai":
                model["enabled"] = True
        models_path.write_text(json.dumps(bridge_registry) + "\n", encoding="utf-8")
        sync_registry(store)
        bridge_none = recommend(
            store,
            {
                "project_id": "model-effort-smoke",
                "objective": "Extract one bounded fact through the local GLM bridge",
                "operation": "discover",
                "risk": "low",
                "privacy": "internal",
                "mutability": "read-only",
                "model_family_allowlist": ["glm-5.2"],
                "reasoning_effort": "none",
            },
            agent_name="bounded_read_worker",
            write=False,
            random_seed=7,
        )
        bridge_max = recommend(
            store,
            {
                "project_id": "model-effort-smoke",
                "objective": "Analyze a difficult failure through the local GLM bridge",
                "operation": "debug",
                "risk": "medium",
                "privacy": "internal",
                "mutability": "read-only",
                "model_family_allowlist": ["glm-5.2"],
                "reasoning_effort": "max",
            },
            agent_name="bounded_read_worker",
            write=False,
            random_seed=7,
        )
        assert bridge_none["primary"]["model_id"] == "litellm-zai/glm-5.2@none"
        assert bridge_max["primary"]["model_id"] == "litellm-zai/glm-5.2@max"
        assert bridge_max["primary"]["execution"] == {
            "provider": "litellm-zai",
            "model": "glm-5.2-max",
            "reasoning_effort": "max",
            "reasoning_mode": "thinking",
            "codex_profile": "researchops_glm_max",
            "codex_overrides": {"web_search": "disabled"},
        }

        legacy_glm = dict(next(model for model in bridge_registry["models"] if model["id"] == "litellm-zai/glm-5.2@high"))
        legacy_glm.pop("returned_model_aliases", None)
        legacy_glm["task_affinity"] = {"discover": 0.123}
        models_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "models": [
                        {
                            "id": "operator/custom-arm",
                            "provider": "operator-provider",
                            "model": "custom-model",
                            "enabled": False,
                        },
                        legacy_glm,
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        agents_path = root / ".researchops/governance/agents.json"
        legacy_agents = json.loads(agents_path.read_text(encoding="utf-8"))
        for agent in legacy_agents["agents"]:
            agent["candidate_arms"] = [arm for arm in agent.get("candidate_arms", []) if not arm.startswith("deepseek/")]
        agents_path.write_text(json.dumps(legacy_agents) + "\n", encoding="utf-8")
        policy_path = root / ".researchops/governance/routing-policy.json"
        legacy_policy = json.loads(policy_path.read_text(encoding="utf-8"))
        legacy_policy["privacy_provider_allowlist"]["internal"] = [
            provider for provider in legacy_policy["privacy_provider_allowlist"]["internal"] if provider != "deepseek"
        ]
        policy_path.write_text(json.dumps(legacy_policy) + "\n", encoding="utf-8")
        bootstrap(root, "Model Effort Routing Smoke", mode="resume", upgrade=True)
        upgraded_models = json.loads(models_path.read_text(encoding="utf-8"))
        assert upgraded_models["schema_version"] >= 3
        assert any(model["id"] == "operator/custom-arm" for model in upgraded_models["models"])
        assert any(model["id"] == "codex/gpt-5.6-sol@high" for model in upgraded_models["models"])
        assert any(model["id"] == "deepseek/deepseek-v4-flash@high" for model in upgraded_models["models"])
        assert any(model["id"] == "litellm-zai/glm-5.2@high" for model in upgraded_models["models"])
        upgraded_glm = next(model for model in upgraded_models["models"] if model["id"] == "litellm-zai/glm-5.2@high")
        assert upgraded_glm["returned_model_aliases"] == ["glm-5.2"]
        assert upgraded_glm["task_affinity"] == {"discover": 0.123}
        upgraded_agents = json.loads(agents_path.read_text(encoding="utf-8"))
        upgraded_lead = next(agent for agent in upgraded_agents["agents"] if agent["name"] == "session_lead")
        assert "deepseek/deepseek-v4-flash@high" in upgraded_lead["candidate_arms"]
        assert "litellm-zai/glm-5.2@high" in upgraded_lead["candidate_arms"]
        upgraded_policy = json.loads(policy_path.read_text(encoding="utf-8"))
        assert "deepseek" in upgraded_policy["privacy_provider_allowlist"]["internal"]
        assert "litellm-zai" in upgraded_policy["privacy_provider_allowlist"]["internal"]

        print(
            json.dumps(
                {
                    "execution_arms": len(models),
                    "same_model_efforts": {
                        "medium_task": medium["primary"]["model_id"],
                        "high_task": high["primary"]["model_id"],
                        "extreme_task": extreme["primary"]["model_id"],
                        "forced_max": forced_max["primary"]["model_id"],
                    },
                    "lead_arm": lead["primary"]["model_id"],
                    "parallel_topology": parallel["orchestration"]["topology"],
                    "sequential_topology": medium["orchestration"]["topology"],
                    "codex_native_effort_rendered": True,
                    "normalized_candidate_scores": len(score_rows),
                    "installed_skill_compact_route": True,
                    "preset_aware_doctor": True,
                    "codex_project_hooks_merged": True,
                    "read_only_route_is_write_free": True,
                    "non_destructive_v2_upgrade": True,
                    "external_provider_upgrade_merged": True,
                    "external_model_modes_routable": [external_none["primary"]["model_id"], external_max["primary"]["model_id"]],
                    "glm_litellm_modes_routable": [bridge_none["primary"]["model_id"], bridge_max["primary"]["model_id"]],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
