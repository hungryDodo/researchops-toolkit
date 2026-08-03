#!/usr/bin/env python3
"""Offline end-to-end smoke test for provider onboarding and model dossiers."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get("PYTHON", sys.executable)
REQUESTS: list[dict[str, Any]] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        return

    def _json(self, value: dict[str, Any]) -> None:
        raw = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        REQUESTS.append({"method": "GET", "path": self.path, "header_names": sorted(self.headers.keys())})
        if self.path.endswith("/models"):
            if "/google/" in self.path:
                self._json({"models": [{"name": "models/mock-gemini"}]})
            else:
                self._json({"data": [{"id": "mock-model"}]})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        REQUESTS.append({"method": "POST", "path": self.path, "header_names": sorted(self.headers.keys()), "body": body})
        text = request_text(body)
        output = response_text(text)
        if self.path.endswith("/v1/messages"):
            self._json({"id": "anthropic-response", "content": [{"type": "text", "text": output}], "usage": {"input_tokens": 1, "output_tokens": 1}})
        elif ":generateContent" in self.path:
            self._json({"responseId": "google-response", "candidates": [{"content": {"parts": [{"text": output}]}}], "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}})
        elif self.path.endswith("/chat/completions"):
            self._json({"id": "openai-response", "choices": [{"message": {"content": output}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
        else:
            self.send_error(404)


def request_text(body: dict[str, Any]) -> str:
    if "messages" in body:
        return "\n".join(str(item.get("content", "")) for item in body.get("messages", []))
    if "contents" in body:
        return "\n".join(str(part.get("text", "")) for item in body.get("contents", []) for part in item.get("parts", []))
    return ""


def response_text(text: str) -> str:
    if "ROPS_OK" in text:
        return "ROPS_OK"
    if "key status" in text or "valid compact JSON" in text:
        return '{"status":"ready"}'
    return "mock-result"


def run(*args: str, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    result = subprocess.run(list(args), cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"command failed: {' '.join(args)}\nstdout={result.stdout}\nstderr={result.stderr}")
    positions = [index for index, char in enumerate(result.stdout) if char == "{"]
    for position in reversed(positions):
        try:
            return json.loads(result.stdout[position:])
        except json.JSONDecodeError:
            continue
    return {"stdout": result.stdout.strip()}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with tempfile.TemporaryDirectory(prefix="rops-model-control-") as temp:
            project = Path(temp) / "project"
            project.mkdir()
            secret_file = Path(temp) / "secrets.env"
            secret_file.write_text("MOCK_API_KEY=test-secret-not-logged\n", encoding="utf-8")
            secret_file.chmod(0o600)
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT)
            env["ROPS_SECRETS_FILE"] = str(secret_file)
            env["MOCK_API_KEY"] = "test-secret-not-logged"
            run(PYTHON, "-m", "rops", "bootstrap", str(project), "--title", "Model Control Test", "--upgrade", cwd=ROOT, env=env)

            # A user secret file with group/other permissions must not be treated as ready.
            secret_file.chmod(0o644)
            env_file_only = dict(env)
            env_file_only.pop("MOCK_API_KEY", None)
            unsafe_plan = run(
                PYTHON, "-m", "rops", "models", "--root", str(project), "onboard",
                "--provider", "unsafe-mock", "--model", "mock-model", "--protocol", "openai-chat",
                "--base-url", f"http://127.0.0.1:{port}/unsafe/v1", "--credential-env", "MOCK_API_KEY",
                cwd=ROOT, env=env_file_only,
            )
            unsafe_status = run(PYTHON, "-m", "rops", "models", "--root", str(project), "doctor", "--provider", "unsafe-mock", cwd=ROOT, env=env_file_only)
            assert not unsafe_status["ready"] and not unsafe_status["secret_file_permissions_safe"]
            unsafe_probe = run(PYTHON, "-m", "rops", "models", "--root", str(project), "probe", "--plan", unsafe_plan["path"], cwd=ROOT, env=env_file_only)
            assert not unsafe_probe["probe"]["connectivity_ok"] and "permissions are too broad" in unsafe_probe["probe"]["error"]
            secret_file.chmod(0o600)

            protocol_specs = [
                ("mock-openai", "openai-chat", f"http://127.0.0.1:{port}/openai/v1", "mock-model", "routine_formatter"),
                ("mock-anthropic", "anthropic-messages", f"http://127.0.0.1:{port}/anthropic", "mock-claude", None),
                ("mock-google", "google-generate-content", f"http://127.0.0.1:{port}/google/v1beta", "mock-gemini", None),
            ]
            enrolled_ids: list[str] = []
            for provider, protocol, base_url, model, agent in protocol_specs:
                args = [
                    PYTHON, "-m", "rops", "models", "--root", str(project), "onboard",
                    "--provider", provider, "--model", model, "--protocol", protocol,
                    "--base-url", base_url, "--credential-env", "MOCK_API_KEY",
                    "--capability", "formatting", "--risk-ceiling", "low",
                ]
                if agent:
                    args += ["--agent", agent]
                planned = run(*args, cwd=ROOT, env=env)
                plan_path = planned["path"]
                probed = run(PYTHON, "-m", "rops", "models", "--root", str(project), "probe", "--plan", plan_path, "--enroll", cwd=ROOT, env=env)
                assert probed["probe"]["success"] and probed["enrolled"]
                enrolled_ids.append(probed["enrollment"]["model"]["id"])

            models = json.loads((project / ".research/agents/models.json").read_text())
            agents = json.loads((project / ".research/agents/agents.json").read_text())
            formatter = next(item for item in agents["agents"] if item["name"] == "routine_formatter")
            assert "mock-openai/mock-model" in formatter["candidate_models"]
            for item in models["models"]:
                if item["id"].startswith("codex/") or item["id"].startswith("gateway/"):
                    item["enabled"] = False
                if item["id"] == "mock-openai/mock-model":
                    item["task_affinity"] = {"formatting": 1.0}
            write_json(project / ".research/agents/models.json", models)

            # Model listing and smoke stay separate from the learned profile.
            provider_data = json.loads((project / ".research/agents/providers.json").read_text())
            for item in provider_data["providers"]:
                item["model_list_path"] = "/models"
            write_json(project / ".research/agents/providers.json", provider_data)
            remote = run(PYTHON, "-m", "rops", "models", "--root", str(project), "remote-list", "--provider", "mock-openai", cwd=ROOT, env=env)
            assert remote["models"] == ["mock-model"]
            smoke = run(PYTHON, "-m", "rops", "models", "--root", str(project), "smoke", "--model-id", "mock-openai/mock-model", cwd=ROOT, env=env)
            if not smoke["report"]["passed"]:
                raise AssertionError(json.dumps(smoke, ensure_ascii=False, indent=2))
            assert not smoke["report"]["profile_updated"]

            # Two independently evaluated events produce a proposed, not active, overlay.
            registry = ROOT / "skills/adaptive-agent-orchestration/scripts/agent_registry.py"
            for index in range(2):
                event = {
                    "task": {"stage": "execution", "type": "formatting", "risk": "low"},
                    "model_id": "mock-openai/mock-model", "accepted": False,
                    "quality": 0.45, "human_correction": 0.4, "verifier_disagreement": 0.1,
                    "failure_modes": ["missed-edge-case"], "disposition": "retry-stronger",
                    "registry_eligible": True, "deterministic_checks_count": 2,
                    "independent_verifier_provided": True, "evaluation_schema_version": 2,
                }
                event_path = Path(temp) / f"event-{index}.json"
                write_json(event_path, event)
                recorded = run(PYTHON, str(registry), "--root", str(project), "record", "--event-file", str(event_path), cwd=ROOT, env=env)
                assert recorded["model_dossier_updated"]
            dossier = run(PYTHON, "-m", "rops", "models", "--root", str(project), "profile", "--model-id", "mock-openai/mock-model", cwd=ROOT, env=env)
            assert dossier["prompt_overlay"]["proposed"] and not dossier["prompt_overlay"]["active"]
            run(PYTHON, "-m", "rops", "models", "--root", str(project), "profile-note", "--model-id", "mock-openai/mock-model", "--kind", "prompt", "--text", "Always preserve requested field order.", cwd=ROOT, env=env)
            approved = run(PYTHON, "-m", "rops", "models", "--root", str(project), "profile", "--model-id", "mock-openai/mock-model", "--approve-prompt", cwd=ROOT, env=env)
            assert approved["prompt_overlay"]["active_revision"] == 1
            assert approved["prompt_overlay"]["active"].count("Always preserve requested field order.") == 0

            prompt = Path(temp) / "prompt.txt"
            prompt.write_text("Format the result.", encoding="utf-8")
            output = Path(temp) / "dispatch.json"
            dispatched = run(PYTHON, "-m", "rops", "models", "--root", str(project), "dispatch", "--model-id", "mock-openai/mock-model", "--agent", "routine_formatter", "--prompt-file", str(prompt), "--output", str(output), cwd=ROOT, env=env)
            assert dispatched["result"]["profile_overlay_applied"]
            assert dispatched["result"]["agent_instructions_applied"]
            assert dispatched["result"]["output_text"] == "mock-result"
            last_openai = next(item for item in reversed(REQUESTS) if item["path"].endswith("/chat/completions"))
            system_text = "\n".join(str(item.get("content", "")) for item in last_openai["body"].get("messages", []) if item.get("role") == "system")
            assert "Only transform the assigned files" in system_text
            assert "missed-edge-case" in system_text
            assert system_text.count("Always preserve requested field order.") == 1

            task = Path(temp) / "task.json"
            write_json(task, {"stage": "execution", "type": "formatting", "risk": "low", "privacy": "public", "mutability": "workspace-write", "required_capabilities": ["formatting"], "deterministic_tests": True})
            delegated = run(PYTHON, "-m", "rops", "models", "--root", str(project), "delegate", "--task-file", str(task), "--prompt-file", str(prompt), "--output-dir", str(Path(temp) / "delegated"), "--agent", "routine_formatter", "--dry-run", cwd=ROOT, env=env)
            assert delegated["routing"]["primary"]["model_id"] == "mock-openai/mock-model"
            assert delegated["handoff"]["requires_evaluation"] and not delegated["handoff"]["profile_updated"]

            all_text = "\n".join(json.dumps(item, ensure_ascii=False) for item in REQUESTS)
            assert "test-secret-not-logged" not in all_text
            assert json.loads((project / ".research/agents/model-profiles/mock-openai-mock-model.json").read_text())["failure_patterns"]

            print(json.dumps({
                "protocol_adapters": 3,
                "providers_enrolled": enrolled_ids,
                "secret_values_logged": False,
                "remote_model_listing": True,
                "smoke_does_not_train_profile": True,
                "verified_history_updates_dossier": True,
                "prompt_overlay_requires_approval": True,
                "unsafe_secret_file_rejected": True,
                "prompt_overlay_not_duplicated": True,
                "agent_prompt_and_overlay_injected": True,
                "bounded_route_and_dispatch": True,
            }, ensure_ascii=False, indent=2))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
