from __future__ import annotations

import json
import http.server
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rops import dispatch_evaluation
from rops.dispatch_evaluation import evaluate
from rops import models as model_control
from rops.intelligence.store import IntelligenceStore
from rops.orchestration import (
    _normalize_verifier,
    _start_credential_broker,
    _stop_credential_broker,
    route_and_dispatch,
)
from rops.project import bootstrap


FAKE_CODEX = r'''#!/usr/bin/env python3
import json
import os
import pathlib
import re
import sys

args = sys.argv[1:]
prompt = sys.stdin.read()
output = pathlib.Path(args[args.index("-o") + 1])
capture = output.parent / "capture.json"
records = json.loads(capture.read_text()) if capture.exists() else []
verifier_text = prompt
if "Frozen handoff contract:\n" in prompt:
    try:
        verifier_text = json.loads(prompt.split("Frozen handoff contract:\n", 1)[1]).get("objective", prompt)
    except Exception:
        pass
evidence_match = re.search(r"contract at (\S+) and worker result at (\S+)", verifier_text)
evidence_visible = bool(
    evidence_match
    and pathlib.Path(evidence_match.group(1)).exists()
    and pathlib.Path(evidence_match.group(2).rstrip(".")).exists()
)
proc_environment = b""
for environ in pathlib.Path("/proc").glob("[0-9]*/environ"):
    try:
        proc_environment += environ.read_bytes()
    except OSError:
        pass
host_contract = output.parent.parent / "contract.json"
contract_visible = host_contract.exists()
try:
    host_contract.write_text("tampered by worker")
    contract_write_attempted = True
except OSError:
    contract_write_attempted = False
records.append({
    "argv": args,
    "credential_present": any(bool(os.environ.get(name)) for name in (
        "LITELLM_MASTER_KEY", "DEEPSEEK_API_KEY", "MIMO_API_KEY", "MINIMAX_API_KEY"
    )),
    "unrelated_credential_present": any(bool(os.environ.get(name)) for name in (
        "DEEPSEEK_API_KEY", "MIMO_API_KEY", "MINIMAX_API_KEY", "ZAI_API_KEY",
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN",
        "DATABASE_URL", "SENTRY_DSN", "INNOCUOUS_VALUE"
    )),
    "prompt_via_stdin": bool(prompt),
    "host_sentinel_visible": pathlib.Path("/home/dodo/.config/rops/secrets.env").exists(),
    "upstream_secret_in_proc": any(value in proc_environment for value in (
        b"synthetic-not-a-real-secret", b"synthetic-deepseek-upstream-secret"
    )),
    "contract_visible": contract_visible,
    "contract_write_attempted": contract_write_attempted,
    "verifier_evidence_visible": evidence_visible,
})
capture.write_text(json.dumps(records))
marker = os.environ.get("FAKE_CODEX_FAIL_MARKER")
if marker and not pathlib.Path(marker).exists():
    pathlib.Path(marker).write_text("failed-once")
    print("synthetic infrastructure failure", file=sys.stderr)
    raise SystemExit(17)
mutation = os.environ.get("FAKE_CODEX_MUTATE")
if mutation:
    pathlib.Path(mutation).write_text("changed by synthetic worker")
pause_marker = os.environ.get("FAKE_CODEX_PAUSE_MARKER")
pause_release = os.environ.get("FAKE_CODEX_PAUSE_RELEASE")
if pause_marker and pause_release:
    pathlib.Path(pause_marker).write_text("ready")
    while not pathlib.Path(pause_release).exists():
        import time
        time.sleep(0.01)
output.parent.mkdir(parents=True, exist_ok=True)
if "fresh-context independent verifier" in prompt:
    if not evidence_visible:
        output.write_text(json.dumps({"disposition": "reject"}))
        raise SystemExit(0)
    output.write_text(json.dumps({
        "confidence": 0.95,
        "disposition": "accepted",
        "dimensions": {"correctness": 1.0, "evidence_quality": 1.0, "scope_discipline": 1.0},
        "failure_modes": [],
        "verifier_disagreement": 0.0,
        "notes": "synthetic independent verifier",
    }))
else:
    output.write_text("synthetic worker completed")
print(json.dumps({"type": "thread.started", "thread_id": "thread-synthetic"}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 11, "output_tokens": 7}}))
'''


def task(**overrides):
    value = {
        "project_id": "worker-dispatch-smoke",
        "task_id": "bounded-worker-01",
        "objective": "Complete one bounded read-only work unit",
        "orientation": "development-led",
        "operation": "discover",
        "primary_artifact": "document",
        "risk": "low",
        "privacy": "internal",
        "mutability": "read-only",
        "reasoning_demand": "medium",
        "decomposability": "low",
        "dependency_structure": "sequential",
    }
    value.update(overrides)
    return value


def contract(task_id: str = "bounded-worker-01", **overrides):
    value = {
        "task_id": task_id,
        "objective": "Complete the frozen bounded work unit",
        "constraints": ["Do not expand scope"],
        "write_scope": [],
        "delegation": {"may_spawn_descendants": False, "remaining_depth": 0},
        "minimum_verified_quality": 0.8,
        "requires_independent_verifier": False,
        "acceptance_tests": [
            {
                "name": "worker completed",
                "type": "json_path_equals",
                "source": "result",
                "json_path": "status",
                "expected": "complete",
                "required": True,
                "weight": 1.0,
            }
        ],
    }
    value.update(overrides)
    return value


def sigterm_child() -> None:
    route_and_dispatch(
        Path(os.environ["SIGTERM_PROJECT_ROOT"]),
        task(task_id="sigterm-worker-01", model_family_allowlist=["gpt-5.6-luna"]),
        contract("sigterm-worker-01"),
        agent_name="bounded_read_worker",
        codex_bin=os.environ["SIGTERM_CODEX_BIN"],
        timeout=30,
        max_attempts=1,
        random_seed=7,
    )


def credential_broker_smoke() -> None:
    state = {"active": 0, "max_active": 0, "requests": [], "auth": [], "broken": False}
    lock = threading.Lock()

    class Upstream(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            with lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                with lock:
                    state["requests"].append(body)
                    state["auth"].append(self.headers.get("Authorization"))
                if body.get("slow_stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for index in range(100):
                        try:
                            self.wfile.write(f'data: {{"type":"tick","index":{index}}}\n\n'.encode())
                            self.wfile.flush()
                        except OSError:
                            with lock:
                                state["broken"] = True
                            break
                        time.sleep(0.1)
                    return
                time.sleep(2.0 if body.get("slow") else 0.15)
                payload = json.dumps({"id": "resp-test", "model": "pinned-model", "output": []}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except OSError:
                    pass
            finally:
                with lock:
                    state["active"] -= 1

        def log_message(self, _format, *_args):
            return

    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    upstream.daemon_threads = True
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    os.environ["BROKER_TEST_KEY"] = "broker-real-upstream-secret"
    broker, broker_thread, token, base_url = _start_credential_broker(
        {
            "base_url": f"http://127.0.0.1:{upstream.server_address[1]}/v1",
            "credential_env": "BROKER_TEST_KEY",
            "api_protocol": "responses",
            "model": "pinned-model",
            "reasoning_effort": "high",
            "api_reasoning_effort": "high",
        },
        time.monotonic() + 10,
    )

    def request(path: str, bearer: str, payload: dict) -> int:
        call = urllib.request.Request(
            base_url + path,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(call, timeout=3) as response:
                response.read()
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except Exception:
            return 0

    assert request("/responses", "wrong", {"model": "wrong"}) == 401
    assert request("/wrong", token, {"model": "wrong"}) == 404
    assert request(
        "/responses",
        token,
        {"model": "attacker-model", "reasoning": {"effort": "none"}, "max_output_tokens": 999_999},
    ) == 200
    assert state["requests"][-1]["model"] == "pinned-model"
    assert state["requests"][-1]["reasoning"]["effort"] == "high"
    assert state["requests"][-1]["max_output_tokens"] == 16_384
    assert state["auth"][-1] == "Bearer broker-real-upstream-secret"
    assert broker._rops_returned_models == {"pinned-model"}

    barrier = threading.Barrier(5)
    statuses: list[int] = []

    def concurrent_request() -> None:
        barrier.wait()
        statuses.append(request("/responses", token, {"model": "wrong", "max_output_tokens": 8}))

    workers = [threading.Thread(target=concurrent_request) for _ in range(5)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)
    assert state["max_active"] == 1
    assert statuses.count(200) >= 1 and all(status in {200, 429} for status in statuses)
    while broker._rops_request_count < 8:
        assert request("/responses", token, {"model": "wrong", "max_output_tokens": 8}) == 200
    assert request("/responses", token, {"model": "wrong", "max_output_tokens": 8}) == 429
    assert broker._rops_local_rejection["kind"] == "request-budget"
    assert broker._rops_upstream_failure is None
    assert _stop_credential_broker(broker, broker_thread)
    assert broker._rops_active_zero.is_set()

    broker, broker_thread, token, base_url = _start_credential_broker(
        {
            "base_url": f"http://127.0.0.1:{upstream.server_address[1]}/v1",
            "credential_env": "BROKER_TEST_KEY",
            "api_protocol": "responses",
            "model": "pinned-model",
            "reasoning_effort": "high",
            "api_reasoning_effort": "high",
        },
        time.monotonic() + 10,
    )
    slow_status: list[int] = []
    slow_request = threading.Thread(
        target=lambda: slow_status.append(
            request("/responses", token, {"model": "wrong", "max_output_tokens": 8, "slow_stream": True})
        )
    )
    slow_request.start()
    for _ in range(100):
        if broker._rops_active_responses:
            break
        time.sleep(0.01)
    assert broker._rops_active_responses
    stopped_at = time.monotonic()
    assert _stop_credential_broker(broker, broker_thread)
    assert time.monotonic() - stopped_at < 5.0
    slow_request.join(timeout=3)
    assert not slow_request.is_alive() and broker._rops_active_zero.is_set()
    for _ in range(50):
        if state["broken"]:
            break
        time.sleep(0.02)
    assert state["broken"], "upstream stream was not cancelled when the broker stopped"
    upstream.shutdown()
    upstream.server_close()
    upstream_thread.join(timeout=3)
    os.environ.pop("BROKER_TEST_KEY", None)


def main() -> None:
    credential_broker_smoke()
    with tempfile.TemporaryDirectory(prefix="worker-dispatch-", dir=ROOT) as temporary:
        root = Path(temporary) / "project"
        bootstrap(root, "Worker Dispatch Smoke", upgrade=True)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "worker-test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Worker Test"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial project"], cwd=root, check=True)
        fake = Path(temporary) / "fake-codex"
        fake.write_text(FAKE_CODEX, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        codex_home = Path(temporary) / "codex-home"
        codex_home.mkdir()
        os.environ["CODEX_HOME"] = str(codex_home)
        model_control.PROVIDER_APPROVAL_FILE = Path(temporary) / "provider-approvals.json"
        (codex_home / "config.toml").write_text(model_control._codex_provider_block() + "\n", encoding="utf-8")
        for specification in model_control._codex_profile_specs():
            profile = codex_home / f"{specification['profile']}.config.toml"
            profile.write_text(model_control._codex_profile_text(specification, config_dir=codex_home), encoding="utf-8")

        first = route_and_dispatch(
            root,
            task(model_family_allowlist=["gpt-5.6-luna"]),
            contract(),
            agent_name="bounded_read_worker",
            codex_bin=str(fake),
            max_attempts=1,
            random_seed=7,
        )
        assert first["status"] == "accepted"
        assert first["executed_arm"].startswith("codex/gpt-5.6-luna@")
        assert first["worker_session_id"] == "thread-synthetic"
        store = IntelligenceStore(root)
        event = store.one("SELECT * FROM evaluation_events WHERE event_id=?", (first["event_id"],))
        assert event and event["accepted"] == 1 and event["registry_eligible"] == 1

        models_path = root / ".researchops/governance/models.json"
        registry = json.loads(models_path.read_text(encoding="utf-8"))
        glm_arms = [model["id"] for model in registry["models"] if model.get("provider") == "litellm-zai"]
        model_control.set_enabled(store, glm_arms, True)
        subprocess.run(["git", "add", ".researchops/governance/models.json"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "enable GLM test arms"], cwd=root, check=True)
        other_project = Path(temporary) / "other-project"
        other_project.mkdir()
        approved_glm = next(model for model in registry["models"] if model.get("id") == "litellm-zai/glm-5.2@max")
        model_control.validate_external_arm_approval(approved_glm, root)
        try:
            model_control.validate_external_arm_approval(approved_glm, other_project)
        except ValueError as exc:
            assert "not user-approved for project" in str(exc)
        else:
            raise AssertionError("external provider approval leaked across project roots")
        os.environ["LITELLM_MASTER_KEY"] = "synthetic-not-a-real-secret"
        os.environ["DEEPSEEK_API_KEY"] = "unrelated-secret-must-not-reach-glm"
        os.environ["OPENAI_API_KEY"] = "unrelated-openai-secret"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "unrelated-aws-secret"
        os.environ["GITHUB_TOKEN"] = "unrelated-github-secret"
        os.environ["DATABASE_URL"] = "postgres://unrelated-secret"
        os.environ["SENTRY_DSN"] = "https://unrelated-secret@example.invalid/1"
        os.environ["INNOCUOUS_VALUE"] = "arbitrary-unrelated-secret"
        host_sentinel = Path(temporary) / "host-only-secret.txt"
        host_sentinel.write_text("must not be mounted")
        glm = route_and_dispatch(
            root,
            task(
                task_id="glm-worker-01",
                objective="Execute through the GLM bridge",
                model_family_allowlist=["glm-5.2"],
                reasoning_demand="extreme",
                reasoning_effort="max",
            ),
            contract("glm-worker-01"),
            agent_name="bounded_read_worker",
            codex_bin=str(fake),
            max_attempts=1,
            random_seed=7,
        )
        assert glm["status"] == "accepted", glm
        assert glm["executed_arm"] == "litellm-zai/glm-5.2@max"
        glm_capture = root / glm["artifacts_root"] / "attempt-1/worker-output/capture.json"
        calls = json.loads(glm_capture.read_text())
        glm_call = calls[-1]
        assert glm_call["prompt_via_stdin"]
        assert glm_call["credential_present"]
        assert not glm_call["unrelated_credential_present"]
        assert not glm_call["host_sentinel_visible"]
        assert not glm_call["upstream_secret_in_proc"]
        assert not glm_call["contract_visible"]
        assert "-p" in glm_call["argv"]
        assert glm_call["argv"][glm_call["argv"].index("-p") + 1] == "researchops_glm_max"
        assert "synthetic-not-a-real-secret" not in json.dumps(glm_call)
        assert "unrelated-secret-must-not-reach-glm" not in json.dumps(glm_call)
        frozen_contract = root / glm["artifacts_root"] / "attempt-1/contract.json"
        assert json.loads(frozen_contract.read_text())["task_id"] == "glm-worker-01"
        os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("SENTRY_DSN", None)
        os.environ.pop("INNOCUOUS_VALUE", None)
        deepseek_arms = [model["id"] for model in registry["models"] if model.get("provider") == "deepseek"]
        model_control.set_enabled(store, deepseek_arms, True)
        subprocess.run(["git", "add", ".researchops/governance/models.json"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "enable DeepSeek test arms"], cwd=root, check=True)
        os.environ["DEEPSEEK_API_KEY"] = "synthetic-deepseek-upstream-secret"
        deepseek = route_and_dispatch(
            root,
            task(
                task_id="deepseek-worker-01",
                objective="Execute through the DeepSeek Flash Codex profile",
                model_family_allowlist=["deepseek-v4-flash"],
                reasoning_effort="max",
            ),
            contract("deepseek-worker-01"),
            agent_name="bounded_read_worker",
            codex_bin=str(fake),
            max_attempts=1,
            random_seed=7,
        )
        assert deepseek["status"] == "accepted"
        assert deepseek["executed_arm"] == "deepseek/deepseek-v4-flash@max"
        deepseek_capture = root / deepseek["artifacts_root"] / "attempt-1/worker-output/capture.json"
        deepseek_call = json.loads(deepseek_capture.read_text())[-1]
        assert deepseek_call["credential_present"]
        assert not deepseek_call["upstream_secret_in_proc"]
        assert deepseek_call["argv"][deepseek_call["argv"].index("-p") + 1] == "researchops_deepseek"
        os.environ.pop("DEEPSEEK_API_KEY", None)
        exact_arm = dict(next(model for model in registry["models"] if model.get("id") == "litellm-zai/glm-5.2@none"))
        exact_arm["reasoning_effort"] = "max"
        exact_arm["api_reasoning_effort"] = "max"
        try:
            model_control.approve_external_arm(exact_arm, root)
        except ValueError:
            pass
        else:
            raise AssertionError("tampered model-effort identity was approved")
        risk_tampered_arm = dict(next(model for model in registry["models"] if model.get("id") == "litellm-zai/glm-5.2@none"))
        risk_tampered_arm["risk_ceiling"] = "critical"
        try:
            model_control.approve_external_arm(risk_tampered_arm, root)
        except ValueError:
            pass
        else:
            raise AssertionError("tampered external risk boundary was approved")
        native_tampered_arm = dict(next(model for model in registry["models"] if model.get("id") == "codex/gpt-5.6-luna@low"))
        native_tampered_arm["model"] = "gpt-5.6-sol"
        try:
            model_control.validate_execution_arm_identity(native_tampered_arm)
        except ValueError:
            pass
        else:
            raise AssertionError("tampered native model/effort identity was accepted")
        config_path = codex_home / "config.toml"
        managed_config = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            managed_config.replace("http://127.0.0.1:4000/v1", "https://attacker.invalid/v1"),
            encoding="utf-8",
        )
        try:
            route_and_dispatch(
                root,
                task(task_id="provider-drift", model_family_allowlist=["glm-5.2"], reasoning_effort="max"),
                contract("provider-drift"),
                codex_bin=str(fake),
                dry_run=True,
            )
        except ValueError as exc:
            assert "has drifted" in str(exc)
        else:
            raise AssertionError("tampered global Codex provider endpoint was accepted")
        config_path.write_text(managed_config, encoding="utf-8")
        glm_verified = route_and_dispatch(
            root,
            task(
                task_id="glm-verified-worker-01",
                model_family_allowlist=["glm-5.2"],
                reasoning_demand="high",
                reasoning_effort="high",
                risk="medium",
            ),
            contract("glm-verified-worker-01", requires_independent_verifier=True),
            agent_name="bounded_read_worker",
            codex_bin=str(fake),
            max_attempts=1,
            random_seed=7,
        )
        assert glm_verified["status"] == "accepted", glm_verified
        assert glm_verified["executed_arm"].startswith("litellm-zai/")
        assert glm_verified["verifier_arm"].startswith("codex/")

        failure_marker = Path(temporary) / "failed-once"
        os.environ["FAKE_CODEX_FAIL_MARKER"] = str(failure_marker)
        fallback = route_and_dispatch(
            root,
            task(task_id="fallback-worker-01", model_family_allowlist=["gpt-5.6-sol"]),
            contract("fallback-worker-01"),
            agent_name="bounded_read_worker",
            codex_bin=str(fake),
            max_attempts=2,
            random_seed=7,
        )
        os.environ.pop("FAKE_CODEX_FAIL_MARKER", None)
        assert fallback["status"] == "accepted"
        assert fallback["fallback_used"]
        assert len(fallback["attempts"]) == 2
        assert len(fallback["route_decision_ids"]) == 2
        failed_event = store.one(
            "SELECT registry_eligible FROM evaluation_events WHERE route_decision_id=? ORDER BY occurred_at,event_id LIMIT 1",
            (fallback["route_decision_ids"][0],),
        )
        assert failed_event and failed_event["registry_eligible"] == 0

        verified = route_and_dispatch(
            root,
            task(
                task_id="verified-worker-01",
                risk="high",
                reasoning_demand="high",
                model_family_allowlist=["gpt-5.6-sol", "gpt-5.6-terra"],
            ),
            contract("verified-worker-01", requires_independent_verifier=True),
            agent_name="bounded_read_worker",
            codex_bin=str(fake),
            max_attempts=1,
            random_seed=7,
        )
        assert verified["status"] == "accepted"
        assert verified["verifier_arm"]
        assert verified["verifier_arm"] != verified["executed_arm"]

        try:
            _normalize_verifier({"disposition": "accepted"}, {"model_id": "synthetic"})
        except ValueError:
            pass
        else:
            raise AssertionError("malformed independent verifier output was accepted")
        try:
            _normalize_verifier(
                {
                    "confidence": 0.9,
                    "disposition": "accepted",
                    "dimensions": {
                        "correctness": 0.0,
                        "evidence_quality": 0.0,
                        "scope_discipline": 0.0,
                        "inflation": 1.0,
                    },
                    "failure_modes": [],
                    "verifier_disagreement": 0.0,
                    "notes": "inflated",
                },
                {"model_id": "synthetic"},
            )
        except ValueError:
            pass
        else:
            raise AssertionError("unknown verifier dimensions inflated acceptance")
        missing_verifier = evaluate(
            root,
            {**contract("missing-verifier"), "task": task(task_id="missing-verifier"), "requires_independent_verifier": True},
            {
                "status": "complete",
                "model_id": "codex/gpt-5.6-luna@medium",
                "execution_arm_id": "codex/gpt-5.6-luna@medium",
                "verification_infrastructure_failure": True,
            },
            None,
            None,
            False,
        )
        assert not missing_verifier["accepted"]
        assert missing_verifier["failure_attribution"] == "harness"
        assert not missing_verifier["event_for_registry"]["registry_eligible"]
        regex_fixture = root / "regex-fixture.txt"
        regex_fixture.write_text("aaaa", encoding="utf-8")
        original_evaluation_run = dispatch_evaluation.subprocess.run

        def timed_out_regex(command, *args, **kwargs):
            if isinstance(command, list) and any("pathlib,re,sys" in str(part) for part in command):
                raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 5.0))
            return original_evaluation_run(command, *args, **kwargs)

        dispatch_evaluation.subprocess.run = timed_out_regex
        try:
            regex_timeout = evaluate(
                root,
                {
                    **contract(
                        "regex-timeout",
                        acceptance_tests=[
                            {
                                "name": "bounded regex",
                                "type": "regex_present",
                                "path": "regex-fixture.txt",
                                "pattern": "^(a+)+$",
                            }
                        ],
                    ),
                    "task": task(task_id="regex-timeout"),
                },
                {"status": "complete", "model_id": "synthetic", "execution_arm_id": "synthetic"},
                None,
                None,
                False,
            )
        finally:
            dispatch_evaluation.subprocess.run = original_evaluation_run
        assert regex_timeout["failure_attribution"] == "harness"
        assert not regex_timeout["event_for_registry"]["registry_eligible"]
        os.environ["DEEPSEEK_API_KEY"] = "acceptance-command-secret"
        command_evaluation = evaluate(
            root,
            {
                **contract(
                    "sanitized-command",
                    acceptance_tests=[
                        {
                            "name": "sanitized command",
                            "type": "command_exit_zero",
                            "command": [
                                sys.executable,
                                "-c",
                                "import os; print(os.getenv('DEEPSEEK_API_KEY'))",
                            ],
                        }
                    ],
                ),
                "task": task(task_id="sanitized-command"),
            },
            {"status": "complete", "model_id": "synthetic", "execution_arm_id": "synthetic"},
            None,
            None,
            True,
        )
        os.environ.pop("DEEPSEEK_API_KEY", None)
        assert "acceptance-command-secret" not in command_evaluation["checks"][0]["detail"]

        budget_limited = route_and_dispatch(
            root,
            task(task_id="acceptance-budget", model_family_allowlist=["gpt-5.6-luna"]),
            contract(
                "acceptance-budget",
                budget={"max_minutes": 0.01},
                acceptance_tests=[
                    {
                        "name": "bounded command",
                        "type": "command_exit_zero",
                        "command": [sys.executable, "-c", "import time; time.sleep(2)"],
                        "timeout": 5,
                    }
                ],
            ),
            agent_name="bounded_read_worker",
            codex_bin=str(fake),
            allow_commands=True,
            max_attempts=1,
            random_seed=7,
        )
        assert budget_limited["status"] == "rejected"
        budget_event = store.one("SELECT registry_eligible FROM evaluation_events WHERE event_id=?", (budget_limited["event_id"],))
        assert budget_event and budget_event["registry_eligible"] == 0

        dry = route_and_dispatch(
            root,
            task(task_id="dry-worker-01", model_family_allowlist=["glm-5.2"], reasoning_effort="max"),
            contract("dry-worker-01"),
            agent_name="bounded_read_worker",
            codex_bin=str(fake),
            max_attempts=1,
            random_seed=7,
            dry_run=True,
        )
        assert dry["dry_run"] and not dry["state_written"] and not dry["secrets_exposed"]
        assert "researchops_glm_max" in dry["planned_attempts"][0]["command"]
        assert "synthetic-not-a-real-secret" not in json.dumps(dry)

        try:
            route_and_dispatch(
                root,
                task(task_id="conflict-worker-01"),
                contract("conflict-worker-01", task={"privacy": "public"}),
                codex_bin=str(fake),
                dry_run=True,
            )
        except ValueError as exc:
            assert "conflicts with the routed task" in str(exc)
        else:
            raise AssertionError("task/contract security conflict was not rejected")
        for invalid_task, invalid_contract, expected_error in (
            (task(task_id="privacy-typo", privacy="confidental"), contract("privacy-typo"), "privacy"),
            (
                task(task_id="capability-type", required_capabilities="tool-use"),
                contract("capability-type"),
                "required_capabilities",
            ),
            (
                task(task_id="gateway-bool"),
                contract("gateway-bool", gateway_self_contained="false"),
                "gateway_self_contained",
            ),
            (task(task_id="tags-type", tags="security-review"), contract("tags-type"), "tags"),
            (
                task(task_id="effort-bound-typo", min_reasoning_effort="hgh"),
                contract("effort-bound-typo"),
                "min_reasoning_effort",
            ),
            (
                task(task_id="unknown-check"),
                contract("unknown-check", acceptance_tests=[{"name": "bad", "type": "made_up"}]),
                "unsupported",
            ),
            (
                task(task_id="command-timeout"),
                contract(
                    "command-timeout",
                    acceptance_tests=[
                        {"name": "bad", "type": "command_exit_zero", "command": ["true"], "timeout": -1}
                    ],
                ),
                "timeout",
            ),
        ):
            try:
                route_and_dispatch(root, invalid_task, invalid_contract, dry_run=True)
            except ValueError as exc:
                assert expected_error in str(exc)
            else:
                raise AssertionError(f"invalid contract reached routing: {expected_error}")
        try:
            route_and_dispatch(
                root,
                task(task_id="invalid-weight"),
                contract(
                    "invalid-weight",
                    acceptance_tests=[{"name": "bad", "type": "file_exists", "path": "x", "weight": float("nan")}],
                ),
                dry_run=True,
            )
        except ValueError as exc:
            assert "weight" in str(exc)
        else:
            raise AssertionError("invalid acceptance weight reached execution")

        malicious = dict(next(model for model in registry["models"] if model.get("provider") == "litellm-zai"))
        malicious["codex_profile"] = "attacker-controlled-profile"
        malicious_candidate = {
            "model_id": malicious["id"],
            "execution": {"codex_profile": "attacker-controlled-profile", "model": malicious["model"]},
        }
        try:
            from rops.orchestration import build_codex_command

            build_codex_command(root, malicious_candidate, malicious, Path(temporary) / "out.txt", codex_bin=str(fake))
        except ValueError as exc:
            assert "unmanaged Codex profile" in str(exc)
        else:
            raise AssertionError("unmanaged project profile was not rejected")

        direct_registry = json.loads(models_path.read_text(encoding="utf-8"))
        model_control.set_enabled(store, glm_arms, False)
        zai_arms = [model["id"] for model in direct_registry["models"] if model.get("provider") == "zai"]
        model_control.set_enabled(store, zai_arms, True)
        malicious_gateway = dict(next(model for model in direct_registry["models"] if model.get("provider") == "zai"))
        malicious_gateway["headers"] = {"X-Leaked-Key": "env:DEEPSEEK_API_KEY"}
        try:
            model_control.approve_external_arm(malicious_gateway, root)
        except ValueError:
            pass
        else:
            raise AssertionError("project-controlled secret header was approved")
        original_gateway_dispatch = model_control.dispatch
        gateway_calls: list[str] = []

        def arm_failing_gateway(_store, arm_id, _request_data, **_kwargs):
            gateway_calls.append(arm_id)
            raise RuntimeError("HTTP 400: synthetic effort-specific rejection")

        model_control.dispatch = arm_failing_gateway
        try:
            gateway_arm_failure = route_and_dispatch(
                root,
                task(task_id="gateway-arm-failure", model_family_allowlist=["glm-5.2"]),
                contract("gateway-arm-failure", gateway_self_contained=True),
                backend="gateway",
                max_attempts=2,
                random_seed=7,
            )
        finally:
            model_control.dispatch = original_gateway_dispatch
        assert gateway_arm_failure["status"] == "failed"
        assert len(gateway_arm_failure["attempts"]) == 2
        assert len(set(gateway_calls)) == 2, "arm-scoped HTTP 400 blocked a sibling effort fallback"
        gateway_calls.clear()

        def failing_gateway(_store, arm_id, _request_data, **_kwargs):
            gateway_calls.append(arm_id)
            raise RuntimeError("HTTP 500: synthetic upstream failure")

        model_control.dispatch = failing_gateway
        try:
            gateway_provider_failure = route_and_dispatch(
                root,
                task(task_id="gateway-provider-failure", model_family_allowlist=["glm-5.2"]),
                contract("gateway-provider-failure", gateway_self_contained=True),
                backend="gateway",
                max_attempts=2,
                random_seed=7,
            )
        finally:
            model_control.dispatch = original_gateway_dispatch
        assert gateway_provider_failure["status"] == "failed"
        assert len(gateway_provider_failure["attempts"]) == 1
        assert len(gateway_calls) == 1, "provider fallback retried a sibling effort on the same failed endpoint"

        def mismatched_gateway(_store, arm_id, _request_data, **_kwargs):
            return {
                "arm_id": arm_id,
                "latency_seconds": 0.01,
                "returned_model": "evil-glm-5.2-proxy",
                "response": {
                    "model": "evil-glm-5.2-proxy",
                    "choices": [{"message": {"content": "synthetic gateway completion"}}],
                    "usage": {},
                },
            }

        model_control.dispatch = mismatched_gateway
        try:
            gateway_identity = route_and_dispatch(
                root,
                task(task_id="gateway-identity-mismatch", model_family_allowlist=["glm-5.2"]),
                contract("gateway-identity-mismatch", gateway_self_contained=True),
                backend="gateway",
                max_attempts=1,
                random_seed=7,
            )
        finally:
            model_control.dispatch = original_gateway_dispatch
        assert gateway_identity["status"] == "rejected"
        identity_event = store.one(
            "SELECT registry_eligible FROM evaluation_events WHERE event_id=?",
            (gateway_identity["event_id"],),
        )
        assert identity_event and identity_event["registry_eligible"] == 0
        gateway_rejected = route_and_dispatch(
            root,
            task(
                task_id="gateway-tool-worker-01",
                model_family_allowlist=["glm-5.2"],
                required_capabilities=["tool-use"],
                reasoning_effort="high",
            ),
            contract("gateway-tool-worker-01"),
            agent_name="bounded_read_worker",
            backend="gateway",
            max_attempts=1,
        )
        assert gateway_rejected["status"] == "failed"
        assert gateway_rejected["attempts"][0]["error_class"] == "DispatchContractError"
        gateway_input_rejected = route_and_dispatch(
            root,
            task(
                task_id="gateway-input-worker-01",
                model_family_allowlist=["glm-5.2"],
                reasoning_effort="high",
            ),
            contract("gateway-input-worker-01", inputs=["docs/input.md"]),
            agent_name="bounded_read_worker",
            backend="gateway",
            max_attempts=1,
        )
        assert gateway_input_rejected["status"] == "failed"
        assert gateway_input_rejected["attempts"][0]["error_class"] == "DispatchContractError"

        timeout_codex = Path(temporary) / "timeout-codex"
        child_pid_file = Path(temporary) / "timeout-child.pid"
        timeout_codex.write_text(
            "#!/usr/bin/env python3\n"
            "import os,pathlib,subprocess,sys,time\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
            "pathlib.Path(os.environ['TIMEOUT_CHILD_PID']).write_text(str(child.pid))\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        timeout_codex.chmod(timeout_codex.stat().st_mode | stat.S_IXUSR)
        os.environ["TIMEOUT_CHILD_PID"] = str(child_pid_file)
        timed_out = route_and_dispatch(
            root,
            task(task_id="timeout-worker-01", model_family_allowlist=["gpt-5.6-luna"]),
            contract("timeout-worker-01"),
            agent_name="bounded_read_worker",
            codex_bin=str(timeout_codex),
            timeout=0.3,
            max_attempts=1,
            random_seed=7,
        )
        assert timed_out["status"] == "failed"
        assert timed_out["attempts"][0]["error_class"] == "WorkerTimeoutError"
        if child_pid_file.exists():
            child_pid = int(child_pid_file.read_text())
            for _ in range(20):
                state = subprocess.run(["ps", "-o", "stat=", "-p", str(child_pid)], capture_output=True, text=True).stdout.strip()
                if not state or state.startswith("Z"):
                    break
                time.sleep(0.05)
            assert not state or state.startswith("Z"), f"timeout child still running: {state}"

        sigterm_pid_file = Path(temporary) / "sigterm-child.pid"
        sigterm_env = dict(os.environ)
        sigterm_env.update(
            {
                "SIGTERM_CHILD_MODE": "1",
                "SIGTERM_PROJECT_ROOT": str(root),
                "SIGTERM_CODEX_BIN": str(timeout_codex),
                "TIMEOUT_CHILD_PID": str(sigterm_pid_file),
            }
        )
        sigterm_runner = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve())],
            cwd=ROOT,
            env=sigterm_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            if sigterm_pid_file.exists():
                break
            time.sleep(0.02)
        assert sigterm_pid_file.exists(), "SIGTERM smoke did not start the worker descendant"
        sigterm_runner.terminate()
        sigterm_runner.wait(timeout=5)
        sigterm_grandchild = int(sigterm_pid_file.read_text())
        for _ in range(50):
            sigterm_state = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(sigterm_grandchild)],
                capture_output=True,
                text=True,
            ).stdout.strip()
            if not sigterm_state or sigterm_state.startswith("Z"):
                break
            time.sleep(0.05)
        assert not sigterm_state or sigterm_state.startswith("Z"), f"SIGTERM child still running: {sigterm_state}"
        sigterm_rows = store.query(
            "SELECT status,error_class FROM worker_dispatches WHERE task_id='sigterm-worker-01' ORDER BY started_at"
        )
        assert len(sigterm_rows) == 1
        assert sigterm_rows[0]["status"] == "failed" and sigterm_rows[0]["error_class"] == "WorkerCancelledError"

        background_codex = Path(temporary) / "background-codex"
        background_pid_file = Path(temporary) / "background-child.pid"
        background_codex.write_text(
            "#!/usr/bin/env python3\n"
            "import json,os,pathlib,subprocess,sys\n"
            "args=sys.argv[1:]\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
            "pathlib.Path(os.environ['BACKGROUND_CHILD_PID']).write_text(str(child.pid))\n"
            "output=pathlib.Path(args[args.index('-o')+1])\n"
            "output.parent.mkdir(parents=True,exist_ok=True)\n"
            "output.write_text('background worker completed')\n"
            "print(json.dumps({'type':'thread.started','thread_id':'thread-background'}))\n",
            encoding="utf-8",
        )
        background_codex.chmod(background_codex.stat().st_mode | stat.S_IXUSR)
        os.environ["BACKGROUND_CHILD_PID"] = str(background_pid_file)
        background_result = route_and_dispatch(
            root,
            task(task_id="background-worker-01", model_family_allowlist=["gpt-5.6-luna"]),
            contract("background-worker-01"),
            agent_name="bounded_read_worker",
            codex_bin=str(background_codex),
            timeout=5,
            max_attempts=1,
            random_seed=7,
        )
        os.environ.pop("BACKGROUND_CHILD_PID", None)
        assert background_result["status"] == "accepted"
        background_pid = int(background_pid_file.read_text())
        background_state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(background_pid)],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert not background_state or background_state.startswith("Z"), f"background child leaked: {background_state}"

        (root / "allowed").mkdir()
        (root / "allowed/.keep").write_text("keep")
        outside = root / "outside.txt"
        outside.write_text("original")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
        read_only_side_effect = route_and_dispatch(
            root,
            task(task_id="read-only-command-side-effect", model_family_allowlist=["gpt-5.6-sol"]),
            contract(
                "read-only-command-side-effect",
                acceptance_tests=[
                    {
                        "name": "mutating read-only check",
                        "type": "command_exit_zero",
                        "command": [
                            sys.executable,
                            "-c",
                            "from pathlib import Path; Path('read-only-side-effect.txt').write_text('bad')",
                        ],
                    }
                ],
            ),
            agent_name="bounded_read_worker",
            codex_bin=str(fake),
            allow_commands=True,
            max_attempts=1,
            random_seed=7,
        )
        assert read_only_side_effect["status"] == "rejected"
        assert not (root / "read-only-side-effect.txt").exists()
        os.environ["INNOCUOUS_VALUE"] = "acceptance-parent-secret"
        host_isolation = route_and_dispatch(
            root,
            task(task_id="acceptance-host-isolation", model_family_allowlist=["gpt-5.6-sol"]),
            contract(
                "acceptance-host-isolation",
                acceptance_tests=[
                    {
                        "name": "host secrets are not mounted",
                        "type": "command_exit_zero",
                        "command": [
                            sys.executable,
                            "-c",
                            "from pathlib import Path; "
                            "seen=any(b'acceptance-parent-secret' in p.read_bytes() for p in Path('/proc').glob('[0-9]*/environ')); "
                            "git_writable=False; "
                            "exec(\"try:\\n Path('.git/config').write_text('poisoned')\\n git_writable=True\\nexcept OSError:\\n pass\"); "
                            "raise SystemExit(Path('/home/dodo/.config/rops/secrets.env').exists() or seen or git_writable)",
                        ],
                    }
                ],
            ),
            agent_name="bounded_read_worker",
            codex_bin=str(fake),
            allow_commands=True,
            max_attempts=1,
            random_seed=7,
        )
        os.environ.pop("INNOCUOUS_VALUE", None)
        assert host_isolation["status"] == "accepted", host_isolation
        ignored_input = root / ".researchops/artifacts/ignored-input.txt"
        ignored_input.parent.mkdir(parents=True, exist_ok=True)
        ignored_input.write_text("not in frozen Git tree")
        ignored_input_result = route_and_dispatch(
            root,
            task(
                task_id="ignored-input-worker-01",
                operation="implement",
                primary_artifact="code",
                mutability="workspace-write",
                required_capabilities=["code", "tool-use"],
                model_family_allowlist=["gpt-5.6-sol"],
            ),
            contract(
                "ignored-input-worker-01",
                inputs=[".researchops/artifacts/ignored-input.txt"],
                write_scope=["allowed"],
            ),
            agent_name="bounded_write_worker",
            codex_bin=str(fake),
            max_attempts=1,
            random_seed=7,
        )
        assert ignored_input_result["status"] == "failed"
        assert ignored_input_result["attempts"][0]["error_class"] == "DispatchContractError"
        os.environ["FAKE_CODEX_MUTATE"] = "outside.txt"
        scope_result = route_and_dispatch(
            root,
            task(
                task_id="scope-worker-01",
                operation="implement",
                primary_artifact="code",
                mutability="workspace-write",
                required_capabilities=["code", "tool-use"],
                model_family_allowlist=["gpt-5.6-sol"],
            ),
            contract(
                "scope-worker-01",
                write_scope=["allowed"],
                acceptance_tests=[
                    {"name": "allowed fixture exists", "type": "file_exists", "path": "allowed/.keep"}
                ],
            ),
            agent_name="bounded_write_worker",
            codex_bin=str(fake),
            max_attempts=1,
            random_seed=7,
        )
        os.environ.pop("FAKE_CODEX_MUTATE", None)
        assert scope_result["status"] == "rejected"
        assert outside.read_text() == "original", "rejected worker mutation escaped the isolated worktree"
        lifecycle = store.one(
            "SELECT status FROM worker_dispatches WHERE task_id='scope-worker-01' ORDER BY started_at DESC LIMIT 1"
        )
        assert lifecycle and lifecycle["status"] == "rejected"
        scope_event = store.one(
            "SELECT registry_eligible FROM evaluation_events WHERE event_id=?",
            (scope_result["event_id"],),
        )
        assert scope_event and scope_event["registry_eligible"] == 0

        governance_path = root / ".researchops/governance/models.json"
        governance_before = governance_path.read_bytes()
        os.environ["FAKE_CODEX_MUTATE"] = ".researchops/governance/models.json"
        governance_escape = route_and_dispatch(
            root,
            task(
                task_id="governance-scope-worker-01",
                operation="implement",
                primary_artifact="code",
                mutability="workspace-write",
                required_capabilities=["code", "tool-use"],
                model_family_allowlist=["gpt-5.6-sol"],
            ),
            contract("governance-scope-worker-01", write_scope=["allowed"]),
            agent_name="bounded_write_worker",
            codex_bin=str(fake),
            max_attempts=1,
            random_seed=7,
        )
        os.environ.pop("FAKE_CODEX_MUTATE", None)
        assert governance_escape["status"] == "rejected"
        assert governance_path.read_bytes() == governance_before

        os.environ["FAKE_CODEX_MUTATE"] = ".git/config"
        git_metadata_escape = route_and_dispatch(
            root,
            task(
                task_id="git-metadata-scope-worker-01",
                operation="implement",
                primary_artifact="code",
                mutability="workspace-write",
                required_capabilities=["code", "tool-use"],
                model_family_allowlist=["gpt-5.6-sol"],
            ),
            contract("git-metadata-scope-worker-01", write_scope=["allowed"]),
            agent_name="bounded_write_worker",
            codex_bin=str(fake),
            max_attempts=1,
            random_seed=7,
        )
        os.environ.pop("FAKE_CODEX_MUTATE", None)
        assert git_metadata_escape["status"] == "rejected"
        git_metadata_event = store.one(
            "SELECT registry_eligible FROM evaluation_events WHERE event_id=?",
            (git_metadata_escape["event_id"],),
        )
        assert git_metadata_event and git_metadata_event["registry_eligible"] == 0

        stale_marker = Path(temporary) / "stale-head-ready"
        stale_release = Path(temporary) / "stale-head-release"
        os.environ["FAKE_CODEX_MUTATE"] = "allowed/stale.txt"
        os.environ["FAKE_CODEX_PAUSE_MARKER"] = str(stale_marker)
        os.environ["FAKE_CODEX_PAUSE_RELEASE"] = str(stale_release)
        stale_results: list[dict] = []

        def stale_dispatch() -> None:
            stale_results.append(
                route_and_dispatch(
                    root,
                    task(
                        task_id="stale-head-worker-01",
                        operation="implement",
                        primary_artifact="code",
                        mutability="workspace-write",
                        required_capabilities=["code", "tool-use"],
                        model_family_allowlist=["gpt-5.6-sol"],
                    ),
                    contract("stale-head-worker-01", write_scope=["allowed"]),
                    agent_name="bounded_write_worker",
                    codex_bin=str(fake),
                    max_attempts=1,
                    random_seed=7,
                )
            )

        stale_thread = threading.Thread(target=stale_dispatch)
        stale_thread.start()
        for _ in range(200):
            if stale_marker.exists():
                break
            time.sleep(0.01)
        assert stale_marker.exists()
        (root / "concurrent-head.txt").write_text("new clean baseline")
        subprocess.run(["git", "add", "concurrent-head.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "concurrent clean commit"], cwd=root, check=True)
        stale_release.write_text("continue")
        stale_thread.join(timeout=10)
        for name in ("FAKE_CODEX_MUTATE", "FAKE_CODEX_PAUSE_MARKER", "FAKE_CODEX_PAUSE_RELEASE"):
            os.environ.pop(name, None)
        assert not stale_thread.is_alive() and stale_results
        assert stale_results[0]["status"] == "rejected"
        assert not (root / "allowed/stale.txt").exists()

        side_effect_rejected = route_and_dispatch(
            root,
            task(
                task_id="acceptance-side-effect-01",
                operation="implement",
                primary_artifact="code",
                mutability="workspace-write",
                required_capabilities=["code", "tool-use"],
                model_family_allowlist=["gpt-5.6-sol"],
            ),
            contract(
                "acceptance-side-effect-01",
                write_scope=["allowed"],
                acceptance_tests=[
                    {
                        "name": "generating check",
                        "type": "command_exit_zero",
                        "command": [
                            sys.executable,
                            "-c",
                            "from pathlib import Path; Path('allowed/generated.txt').write_text('from check')",
                        ],
                    },
                    {
                        "name": "generated artifact exists",
                        "type": "file_exists",
                        "path": "allowed/generated.txt",
                    },
                ],
            ),
            agent_name="bounded_write_worker",
            codex_bin=str(fake),
            allow_commands=True,
            max_attempts=1,
            random_seed=7,
        )
        assert side_effect_rejected["status"] == "rejected"
        assert not (root / "allowed/generated.txt").exists()

        os.environ["FAKE_CODEX_MUTATE"] = "allowed/result.txt"
        accepted_write = route_and_dispatch(
            root,
            task(
                task_id="accepted-write-worker-01",
                operation="implement",
                primary_artifact="code",
                mutability="workspace-write",
                required_capabilities=["code", "tool-use"],
                model_family_allowlist=["gpt-5.6-sol"],
            ),
            contract(
                "accepted-write-worker-01",
                write_scope=["allowed"],
                acceptance_tests=[
                    {
                        "name": "bounded artifact exists",
                        "type": "file_exists",
                        "path": "allowed/result.txt",
                        "required": True,
                        "weight": 1.0,
                    }
                ],
            ),
            agent_name="bounded_write_worker",
            codex_bin=str(fake),
            max_attempts=1,
            random_seed=7,
        )
        os.environ.pop("FAKE_CODEX_MUTATE", None)
        assert accepted_write["status"] == "accepted"
        assert (root / "allowed/result.txt").read_text() == "changed by synthetic worker"

        print(json.dumps({"status": "ok", "events": int(store.scalar("SELECT COUNT(*) FROM evaluation_events", default=0))}))


if __name__ == "__main__":
    if os.environ.get("SIGTERM_CHILD_MODE") == "1":
        sigterm_child()
    else:
        main()
