from __future__ import annotations

import json
import os
import tempfile
import tomllib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rops.intelligence.drift import record_endpoint_observation, record_identity_observation
from rops.intelligence.events import record_event
from rops.intelligence.projections import rebuild_projections
from rops.intelligence.store import IntelligenceStore
from rops import models as model_gateway
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

        responses_payload = model_gateway._prepare_payload(
            {
                "model": "deepseek-v4-flash",
                "api_protocol": "responses",
                "reasoning_effort": "max",
            },
            {"messages": [{"role": "user", "content": "hello"}], "max_tokens": 32},
        )
        assert responses_payload["reasoning"] == {"effort": "max"}
        assert "reasoning_effort" not in responses_payload and "messages" not in responses_payload
        assert responses_payload["max_output_tokens"] == 32
        assert model_gateway._request_path({"api_protocol": "responses"}) == "/responses"

        chat_payload = model_gateway._prepare_payload(
            {
                "model": "glm-5.2",
                "api_protocol": "chat_completions",
                "reasoning_effort": "high",
                "thinking_type": "enabled",
            },
            {"input": "hello", "max_tokens": 32},
        )
        assert chat_payload["reasoning_effort"] == "high"
        assert chat_payload["thinking"] == {"type": "enabled"}
        assert chat_payload["messages"][0]["content"] == "hello"

        codex_path = root / "codex-config.toml"
        codex_path.write_text('model = "gpt-5.6-sol"\n', encoding="utf-8")
        first_codex = model_gateway.codex_config(install=True, path=codex_path)
        second_codex = model_gateway.codex_config(install=True, path=codex_path)
        codex_text = codex_path.read_text(encoding="utf-8")
        codex_toml = tomllib.loads(codex_text)
        assert first_codex["installed"] and second_codex["installed"]
        assert first_codex["default_model_changed"] is False
        assert codex_text.count(model_gateway.CODEX_CONFIG_BEGIN) == 1
        assert codex_toml["model"] == "gpt-5.6-sol"
        assert codex_toml["model_providers"]["deepseek"]["env_key"] == "DEEPSEEK_API_KEY"
        assert codex_toml["model_providers"]["mimo_paygo"]["wire_api"] == "responses"
        assert "profiles" not in codex_toml
        deepseek_profile = tomllib.loads((root / "researchops_deepseek.config.toml").read_text(encoding="utf-8"))
        mimo_profile = tomllib.loads((root / "researchops_mimo_token_plan.config.toml").read_text(encoding="utf-8"))
        assert deepseek_profile["model_provider"] == "deepseek"
        assert mimo_profile["web_search"] == "disabled"
        assert first_codex["providers"][2]["codex_overrides"] == {"web_search": "disabled"}
        assert "experimental_bearer_token" not in codex_text and "sk-" not in codex_text

        original_secret_file = model_gateway.SECRET_FILE
        try:
            model_gateway.SECRET_FILE = root / "secrets.env"
            model_gateway.SECRET_FILE.write_text(
                "# keep comments and operator variables\nDEEPSEEK_API_KEY=keep-me\nCUSTOM_VALUE=keep-too\n",
                encoding="utf-8",
            )
            secret_template = model_gateway.secret_template(root)
            secret_template_again = model_gateway.secret_template(root)
            secret_text = model_gateway.SECRET_FILE.read_text(encoding="utf-8")
            assert set(secret_template["variables"]) >= {"DEEPSEEK_API_KEY", "MIMO_API_KEY", "MINIMAX_API_KEY", "ZAI_API_KEY"}
            assert set(secret_template["added"]) >= {"MIMO_API_KEY", "MINIMAX_API_KEY", "ZAI_API_KEY"}
            assert secret_template_again["added"] == []
            assert "DEEPSEEK_API_KEY=keep-me" in secret_text and "CUSTOM_VALUE=keep-too" in secret_text
            assert os.stat(model_gateway.SECRET_FILE).st_mode & 0o777 == 0o600
        finally:
            model_gateway.SECRET_FILE = original_secret_file

        print(
            json.dumps(
                {
                    "gateway_registry_sync": True,
                    "probe_competence_separation": True,
                    "identity_observation": bool(identity.get("observation_id")),
                    "endpoint_observation": bool(endpoint.get("observation_id")),
                    "shared_dossier_projection": True,
                    "secret_values_exposed": False,
                    "chat_and_responses_protocols": True,
                    "codex_provider_config_secret_safe": True,
                    "secret_template_idempotent": True,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
