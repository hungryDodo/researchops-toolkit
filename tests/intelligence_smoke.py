#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rops.behavior import approve as approve_operation
from rops.behavior import check as check_operation
from rops.intelligence import drift, judges, memory, mitigations, patterns, warmup
from rops.intelligence.events import EvaluationEvent, record_event
from rops.intelligence.profiles import load_profiles, rebuild_profiles, scope_key
from rops.intelligence.projections import rebuild_projections
from rops.intelligence.routing import recommend
from rops.intelligence.store import IntelligenceStore
from rops.layout import migrate_legacy_layout
from rops.presets import resolve as resolve_preset


def event(
    *,
    event_id: str,
    arm: str = "provider/model@epoch-1/config-a",
    project: str = "project-a",
    operation: str = "debug",
    accepted: bool = True,
    quality: float = 0.9,
    progress: float = 0.9,
    source: str = "live",
    probe: bool = False,
    failure: str | None = None,
) -> dict:
    failures = []
    if failure:
        failures.append(
            {
                "code": failure,
                "severity": "high",
                "attribution": "worker-model",
                "description": "repeated verified omission",
                "evidence_ref": f"artifact://{event_id}",
            }
        )
    return {
        "event_id": event_id,
        "project_id": project,
        "task_id": f"task-{event_id}",
        "work_unit_id": f"wu-{event_id}",
        "source": source,
        "probe": probe,
        "execution_arm_id": arm,
        "task": {
            "orientation": "development-led",
            "operation": operation,
            "primary_artifact": "code",
            "risk": "medium",
            "privacy": "internal",
            "mutability": "workspace-write",
            "acceptance_profile": "software-debug-v1",
            # Rich metadata is recorded, but deliberately not used as an
            # automatic group-by dimension by ProfileEngine v2.
            "language": "python",
            "stack": ["sqlite"],
        },
        "outcome": {
            "accepted": accepted,
            "verified_progress": progress,
            "quality": quality,
            "human_correction": 0.0 if accepted else 0.4,
            "verifier_disagreement": 0.0,
        },
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 200,
            "latency_seconds": 10.0,
            "cost_amount": 0.1,
            "currency": "USD",
        },
        "verification": {
            "deterministic_checks_count": 2,
            "deterministic_checks_passed": 2 if accepted else 1,
            "evidence_refs": [f"artifact://{event_id}"],
        },
        "failure_observations": failures,
        "versions": {
            "harness": "test",
            "evaluator_bundle": "software-debug-v1",
        },
        "registry_eligible": not probe,
        "selection_probability": 0.5,
    }


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rops-intelligence-smoke-") as temp:
        root = Path(temp) / "project"
        root.mkdir()
        store = IntelligenceStore(root)

        # One user-visible hidden root; SQLite is canonical from first use.
        assert store.path == root / ".researchops/intelligence/state.sqlite"
        assert store.path.exists()
        assert not (root / ".research").exists()
        assert not list(root.rglob("task-history.jsonl"))

        # Probe/smoke observations remain operational telemetry, never
        # competence evidence.
        probe_event = EvaluationEvent.normalize(event(event_id="probe-1", source="probe", probe=True))
        assert probe_event.data["registry_eligible"] is False
        probe_event.insert(store)

        for index in range(6):
            record_event(store, event(event_id=f"a-{index}"))
        for index in range(2):
            record_event(
                store,
                event(
                    event_id=f"a-fail-{index}",
                    accepted=False,
                    quality=0.25,
                    progress=0.2,
                    failure="edge_case_omission",
                ),
            )

        aggregate = rebuild_profiles(store)
        profiles = load_profiles(store)
        assert aggregate["input_event_count"] == 8
        assert len(profiles) == 4
        assert profiles[scope_key("provider/model@epoch-1/config-a")]["observations"] == 8
        assert profiles[scope_key("provider/model@epoch-1/config-a", "project-a", None, "debug")]["observations"] == 8
        # Extra metadata did not create sparse profile dimensions.
        assert all("python" not in key and "sqlite" not in key for key in profiles)

        pattern_result = patterns.rebuild_patterns(store)
        assert pattern_result["patterns"][0]["status"] == "active"
        assert pattern_result["patterns"][0]["occurrence_count"] == 2
        pattern_id = pattern_result["patterns"][0]["pattern_id"]
        record_event(
            store,
            event(
                event_id="human-pattern-1",
                arm="provider/candidate@epoch-1/config-a",
                project="project-candidate",
                accepted=False,
                quality=0.2,
                progress=0.1,
                failure="scope_narrowing",
            ),
        )
        candidate_result = patterns.rebuild_patterns(store)
        candidate = next(item for item in candidate_result["patterns"] if item["code"] == "scope_narrowing")
        assert candidate["status"] == "candidate"
        confirmed = patterns.approve_pattern(store, candidate["pattern_id"], "human-reviewer")
        assert confirmed["human_confirmed"] is True
        confirmed_result = patterns.rebuild_patterns(store)
        assert next(item for item in confirmed_result["patterns"] if item["pattern_id"] == candidate["pattern_id"])["status"] == "active"

        proposal = mitigations.propose(
            store,
            "prompt_overlay",
            {
                "execution_arm_id": "provider/model@epoch-1/config-a",
                "project_id": "project-a",
                "operation": "debug",
            },
            {
                "instruction": "Enumerate boundary cases and verify every frozen acceptance item before finalizing."
            },
            pattern_ids=[pattern_id],
        )
        before = mitigations.compile_prompt(
            store,
            arm_id="provider/model@epoch-1/config-a",
            project_id="project-a",
            operation="debug",
            task_contract="Fix the bug without silently reducing scope.",
        )
        assert not before["applied_mitigations"]
        try:
            mitigations.set_status(store, proposal["mitigation_id"], "active")
            raise AssertionError("an unapproved mitigation became active")
        except ValueError as exc:
            assert "transition" in str(exc) or "approval" in str(exc)
        approval = mitigations.approve(store, proposal["mitigation_id"], "human-reviewer")
        assert approval["high_risk_operation_approval_granted"] is False
        approved_only = mitigations.compile_prompt(
            store,
            arm_id="provider/model@epoch-1/config-a",
            project_id="project-a",
            operation="debug",
            task_contract="Fix the bug without silently reducing scope.",
        )
        assert not approved_only["applied_mitigations"]
        mitigations.set_status(store, proposal["mitigation_id"], "active")
        after = mitigations.compile_prompt(
            store,
            arm_id="provider/model@epoch-1/config-a",
            project_id="project-a",
            operation="debug",
            task_contract="Fix the bug without silently reducing scope.",
        )
        assert after["applied_mitigations"]
        assert "boundary cases" in after["compiled_prompt"]

        # Prompt mitigation approval never authorizes a consequential command.
        dangerous = "git reset --hard HEAD~1"
        operation_check = check_operation(store, dangerous)
        assert operation_check["approved"] is False
        operation_approval = approve_operation(store, dangerous, "history-rewrite", "human-reviewer")
        assert operation_approval["prompt_mitigation_approval_granted"] is False
        assert check_operation(store, dangerous, consume=True)["approved"] is True
        assert check_operation(store, dangerous)["approved"] is False

        # Cold start and soft transfer are both visible.  Transfer is bounded,
        # and local contradictory evidence can reject it quickly.
        transfer_arm = "provider/transfer-model@epoch-1/config-a"
        for index in range(6):
            record_event(store, event(event_id=f"transfer-source-{index}", arm=transfer_arm, project="project-transfer-source"))
        zero = warmup.initialize_transfer(
            store,
            project_id="project-zero",
            arm_id=transfer_arm,
            operation="debug",
            primary_artifact="code",
            mode="zero",
        )
        assert zero["inherited_equivalent_observations"] == 0
        transferred = warmup.initialize_transfer(
            store,
            project_id="project-b",
            arm_id=transfer_arm,
            operation="debug",
            primary_artifact="code",
            acceptance_profile="software-debug-v1",
            mode="conservative",
        )
        assert 0 < transferred["inherited_equivalent_observations"] <= 2
        for index in range(3):
            record_event(
                store,
                event(
                    event_id=f"b-fail-{index}",
                    arm=transfer_arm,
                    project="project-b",
                    accepted=False,
                    quality=0.1,
                    progress=0.0,
                ),
            )
        warm = warmup.warmup_state(store, "project-b", transfer_arm, "debug")
        assert warm["negative_transfer_guard_triggered"] is True
        assert warm["inherited_equivalent_observations"] == 0
        assert warm["estimated_remaining_local_episodes"] <= 2

        # Soft transfer is not only a dashboard annotation: the router consumes
        # the bounded equivalent observations instead of the complete
        # cross-project history.  It also returns applicable mitigation and
        # verification policy alongside the selected arm.
        governance = store.layout.governance
        governance.mkdir(parents=True, exist_ok=True)
        (governance / "models.json").write_text(
            json.dumps(
                {
                    "models": [
                        {
                            "id": "provider/model@epoch-1/config-a",
                            "arm_id": "provider/model@epoch-1/config-a",
                            "provider": "provider",
                            "model": "model",
                            "model_family": "model",
                            "enabled": True,
                            "risk_ceiling": "high",
                            "capabilities": ["code"],
                            "task_affinity": {"debug": 0.5},
                            "cost_hint": 0.2,
                            "latency_hint": 0.2,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (governance / "agents.json").write_text('{"agents": []}\n', encoding="utf-8")
        (governance / "routing-policy.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "privacy_provider_allowlist": {"internal": ["provider"]},
                    "minimum_observations_for_empirical_routing": 5,
                    "warmup_mode": "conservative",
                    "exploration": {"enabled": False},
                }
            ),
            encoding="utf-8",
        )
        routed_new = recommend(
            store,
            {
                "project_id": "project-c",
                "task_id": "route-soft-transfer",
                "orientation": "development-led",
                "operation": "debug",
                "primary_artifact": "code",
                "risk": "medium",
                "privacy": "internal",
                "mutability": "workspace-write",
                "required_capabilities": ["code"],
                "acceptance_profile": "software-debug-v1",
            },
            write=True,
            random_seed=0,
        )
        assert routed_new["primary"]["profile_source"].startswith("soft-transfer:")
        assert 0 < routed_new["primary"]["inherited_equivalent_observations"] <= 2
        assert routed_new["primary"]["observations"] <= 2
        routed_existing = recommend(
            store,
            {
                "project_id": "project-a",
                "task_id": "route-with-mitigation",
                "orientation": "development-led",
                "operation": "debug",
                "primary_artifact": "code",
                "risk": "medium",
                "privacy": "internal",
                "mutability": "workspace-write",
                "required_capabilities": ["code"],
                "acceptance_profile": "software-debug-v1",
            },
            write=True,
            random_seed=0,
        )
        assert routed_existing["applicable_mitigations"][0]["mitigation_id"] == proposal["mitigation_id"]
        assert routed_existing["verification_policy"]["acceptance_profile"] == "software-debug-v1"

        # Endpoint degradation is separated from behavior/identity drift.
        for _ in range(3):
            drift.record_endpoint_observation(
                store,
                endpoint_id="endpoint-a",
                arm_id="provider/model@epoch-1/config-a",
                success=False,
                latency_seconds=30.0,
                error_class="timeout",
            )
        endpoint_drift = drift.detect(
            store,
            arm_id="provider/model@epoch-1/config-a",
            endpoint_id="endpoint-a",
            operation="debug",
        )
        assert endpoint_drift["drift_type"] in {"endpoint-health", "black-box-behavior"}
        drift.record_identity_observation(
            store,
            arm_id="provider/model@epoch-1/config-a",
            endpoint_id="endpoint-a",
            declared_identity={"model": "same-id"},
            fingerprint={"schema": "a", "tool_style": "v1"},
        )
        for fingerprint in (
            {"schema": "b", "tool_style": "v2"},
            {"schema": "c", "tool_style": "v3"},
            {"schema": "d", "tool_style": "v4"},
        ):
            drift.record_identity_observation(
                store,
                arm_id="provider/model@epoch-1/config-a",
                endpoint_id="endpoint-a",
                declared_identity={"model": "same-id"},
                fingerprint=fingerprint,
            )
        identity_drift = drift.detect(
            store,
            arm_id="provider/model@epoch-1/config-a",
            endpoint_id="endpoint-a",
            operation="debug",
        )
        assert identity_drift["status"] in {"suspected", "confirmed"}
        assert identity_drift["response"]["claim"] == "observed behavior drift; underlying provider cause is unknown"

        # Judges are not assumed equal: calibration is task-conditional.
        for index in range(12):
            judges.record(
                store,
                judge_arm_id="judge-a",
                task_family="development.debug",
                agrees_with_reference=index != 0,
                position_consistent=True,
                abstained=False,
            )
        for index in range(12):
            judges.record(
                store,
                judge_arm_id="judge-b",
                task_family="development.debug",
                agrees_with_reference=index < 7,
                position_consistent=index % 3 != 0,
                abstained=index == 11,
            )
        judge_a = judges.profile(store, "judge-a", "development.debug")
        judge_b = judges.profile(store, "judge-b", "development.debug")
        assert judge_a["calibration_status"] == "calibrated"
        assert judge_a["weight"] > judge_b["weight"]
        cascade = judges.cascade(store, ["judge-b", "judge-a"], "development.debug", high_risk=True)
        assert cascade["primary"]["judge_arm_id"] == "judge-a"
        for _ in range(3):
            pair = judges.record_pairwise(
                store,
                judge_arm_id="judge-a",
                task_family="development.debug",
                item_a="worker-model-a",
                item_b="worker-model-b",
                first_result="a",
                swapped_result="a",
                evidence_package_hash="sha256:evidence-a",
                rubric_revision="debug-rubric-v1",
                prompt_revision="judge-prompt-v1",
            )
            assert pair["position_consistent"] is True
        judges.record_pairwise(
            store,
            judge_arm_id="judge-b",
            task_family="development.debug",
            item_a="worker-model-a",
            item_b="worker-model-b",
            first_result="b",
            swapped_result="a",
        )
        pairwise_ranking = judges.rank_pairwise(store, "development.debug")
        assert pairwise_ranking["status"] == "ranked"
        assert pairwise_ranking["ranking"][0]["item_id"] == "worker-model-a"

        # Recall memory is optional and explicitly non-authoritative.
        first = memory.add(
            store,
            scope="project-a",
            kind="decision",
            title="Boundary verification decision",
            body="Use property tests for repeated keys and empty input.",
            provenance={"event_id": "a-fail-0"},
        )
        second = memory.add(
            store,
            scope="project-a",
            kind="mitigation-rationale",
            title="Scope preservation",
            body="Do not silently defer acceptance criteria.",
            provenance={"mitigation_id": proposal["mitigation_id"]},
        )
        memory.relate(store, second["memory_id"], first["memory_id"], "supports")
        hits = memory.search(store, "property tests", scope="project-a")
        assert hits and hits[0]["authoritative"] is False
        assert hits[0]["provenance"]["event_id"] == "a-fail-0"

        projection_paths = rebuild_projections(store)
        routing = read_json(Path(projection_paths["routing"]))
        dossier_index = read_json(Path(projection_paths["dossiers"]))
        dashboard = read_json(Path(projection_paths["dashboard"]))
        benchmark = read_json(Path(projection_paths["benchmark"]))
        audit = read_json(Path(projection_paths["audit"]))
        eligible_events = int(store.scalar("SELECT COUNT(*) n FROM evaluation_events WHERE registry_eligible=1", default=0))
        assert routing["input_event_count"] == eligible_events
        assert dashboard["input_event_count"] == eligible_events
        assert benchmark["input_event_count"] == eligible_events
        assert audit["input_event_count"] == eligible_events
        assert dossier_index["input_event_count"] == eligible_events
        assert routing["do_not_edit"] is True
        assert dashboard["routing"]["warmup"]
        assert dashboard["routing"]["active_failure_patterns"]
        assert dashboard["routing"]["active_mitigations"]
        assert benchmark["source_summary"]["live"]["observations"] >= 1
        assert any(pack["id"] == "development-benchmark-v1" for pack in benchmark["packs"])
        assert benchmark["pairwise_rankings"][0]["ranking"][0]["item_id"] == "worker-model-a"

        # Presets are installation recipes, not code ownership boundaries.
        full = resolve_preset("full")
        assert "research-program-orchestrator" in full.skills
        assert "software-development" in full.skills
        assert "model-intelligence" in full.features
        assert "research-integrity" in full.behavior_packs

        # Legacy sibling directories migrate under one root without clobbering.
        legacy_root = Path(temp) / "legacy"
        (legacy_root / ".research/evidence").mkdir(parents=True)
        (legacy_root / ".research/evidence/sample.txt").write_text("evidence", encoding="utf-8")
        (legacy_root / ".researchops/hooks").mkdir(parents=True)
        (legacy_root / ".researchops/hooks/hook.json").write_text("{}", encoding="utf-8")
        migration = migrate_legacy_layout(legacy_root)
        assert (legacy_root / ".researchops/state/evidence/sample.txt").exists()
        assert (legacy_root / ".researchops/runtime/hooks/hook.json").exists()
        assert not (legacy_root / ".research").exists()
        assert migration["events"]

        result = {
            "sqlite_authority": True,
            "single_hidden_root": True,
            "eligible_events": eligible_events,
            "profile_slices": len(routing["profiles"]),
            "projection_consistency": True,
            "benchmark_projection": True,
            "failure_pattern_active": True,
            "human_pattern_confirmation": True,
            "mitigation_approval_separate": True,
            "warmup_and_negative_transfer": True,
            "warmup_drives_routing": True,
            "routing_returns_mitigation_policy": True,
            "black_box_drift": identity_drift["status"],
            "judge_calibration": True,
            "weighted_pairwise_ranking": True,
            "recall_memory_optional": True,
            "preset_composition": True,
            "legacy_migration": True,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
