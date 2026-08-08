from __future__ import annotations

import json
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rops.intelligence.drift import record_endpoint_observation, record_identity_observation
from rops.intelligence.events import record_event
from rops.intelligence.projections import rebuild_projections
from rops.intelligence.store import IntelligenceStore
from rops.models import dossier, secret_status, sync_registry
from rops.project import bootstrap


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="researchops-model-plane-") as temp:
        root = Path(temp) / "project"
        bootstrap(root, "Model Control Plane Smoke", upgrade=True)
        store = IntelligenceStore(root)
        registry = sync_registry(store)
        assert registry["execution_arms"] >= 1
        before = int(store.scalar("SELECT COUNT(*) FROM evaluation_events", default=0))
        endpoint = record_endpoint_observation(
            store,
            endpoint_id="mock-endpoint",
            arm_id="codex/gpt-5.6-sol@medium",
            success=True,
            latency_seconds=0.25,
            metadata={"kind": "probe"},
        )
        identity = record_identity_observation(
            store,
            arm_id="codex/gpt-5.6-sol@medium",
            endpoint_id="mock-endpoint",
            declared_identity={"requested_model": "gpt-5.6", "returned_model": "gpt-5.6"},
            fingerprint={"response_shape": ["choices", "usage"]},
        )
        after_probe = int(store.scalar("SELECT COUNT(*) FROM evaluation_events", default=0))
        assert before == after_probe == 0, "probe/identity telemetry must not update competence"

        event = record_event(
            store,
            {
                "schema_version": 2,
                "project_id": "model-plane-smoke",
                "task_id": "task-1",
                "work_unit_id": "wu-1",
                "source": "live",
                "execution_arm_id": "codex/gpt-5.6-sol@medium",
                "task": {
                    "objective": "Validate the compatibility facade",
                    "orientation": "development-led",
                    "operation": "validate",
                    "primary_artifact": "system",
                    "risk": "low",
                    "privacy": "internal",
                    "mutability": "read-only",
                    "acceptance_profile": "model-control-plane-smoke-v1",
                },
                "outcome": {
                    "accepted": True,
                    "verified_progress": 1.0,
                    "quality": 0.95,
                    "human_correction": 0.0,
                    "verifier_disagreement": 0.0,
                },
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 40,
                    "latency_seconds": 0.5,
                    "cost_amount": 0.01,
                    "currency": "USD",
                },
                "verification": {
                    "deterministic_checks_count": 2,
                    "deterministic_checks_passed": 2,
                    "evidence_refs": ["test://model-control-plane-smoke"],
                },
                "versions": {
                    "routing_policy": "smoke",
                    "evaluator_bundle": "model-control-plane-smoke-v1",
                    "harness": "test",
                },
                "registry_eligible": True,
            },
        )
        projection = rebuild_projections(store)
        model_dossier = dossier(root, "codex/gpt-5.6-sol@medium")
        secrets = secret_status(root)
        assert event["event_id"]
        assert projection["event_count"] == 1
        assert model_dossier["generated"] is True and model_dossier["do_not_edit"] is True
        assert secrets["values_exposed"] is False
        assert (Path(__file__).parents[1] / "components/model-control-plane/profile-schema.json").exists()

        print(
            json.dumps(
                {
                    "gateway_registry_sync": True,
                    "probe_competence_separation": True,
                    "identity_observation": bool(identity.get("observation_id")),
                    "endpoint_observation": bool(endpoint.get("observation_id")),
                    "shared_dossier_projection": True,
                    "secret_values_exposed": False,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
