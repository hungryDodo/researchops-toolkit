from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import models
from .usage_metrics import normalize_provider_usage

MAX_ACCEPTANCE_FILE_BYTES = 64 * 1024 * 1024


def load(path: Path | None) -> Any:
    if path is None:
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def digest(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def json_path(obj: Any, path: str) -> Any:
    current = obj
    for token in path.strip(".").split("."):
        if not token:
            continue
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(path)
    return current


def clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def safe_project_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root)
    return path


def _bounded_acceptance_file(path: Path) -> Path:
    if path.stat().st_size > MAX_ACCEPTANCE_FILE_BYTES:
        raise ValueError(f"acceptance input exceeds {MAX_ACCEPTANCE_FILE_BYTES} bytes: {path}")
    return path


def _sanitized_check_environment() -> dict[str, str]:
    allowed = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM", "COLORTERM", "NO_COLOR"}
    return {key: value for key, value in os.environ.items() if key in allowed}


def _redact_check_output(value: str) -> str:
    redacted = str(value)
    for name in models.governed_credential_names():
        secret = models._secret(name)
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"\bsk-[A-Za-z0-9_.-]{12,}\b", "[REDACTED]", redacted)
    return redacted[-2000:]


def _acceptance_sandbox_command(root: Path, command: list[str]) -> list[str]:
    sandbox = [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-net",
        "--unshare-pid",
        "--tmpfs",
        "/",
    ]
    created: set[str] = set()

    def ensure_parents(path: Path) -> None:
        for parent in reversed(path.parents):
            value = str(parent)
            if value == "/" or value in created:
                continue
            sandbox.extend(["--dir", value])
            created.add(value)

    ensure_parents(Path("/usr"))
    sandbox.extend(["--ro-bind", "/usr", "/usr"])
    for source in (
        Path("/etc/ssl"),
        Path("/etc/ca-certificates"),
        Path("/etc/pki"),
        Path("/etc/passwd"),
        Path("/etc/group"),
    ):
        if source.exists():
            ensure_parents(source)
            sandbox.extend(["--ro-bind", str(source), str(source)])
    for destination, target in (("usr/bin", "/bin"), ("usr/lib", "/lib"), ("usr/lib64", "/lib64")):
        sandbox.extend(["--symlink", destination, target])
    ensure_parents(root)
    sandbox.extend(
        [
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--dir",
            "/tmp",
            "--dir",
            "/tmp/home",
            "--bind",
            str(root),
            str(root),
            "--ro-bind",
            str(root / ".git"),
            str(root / ".git"),
            "--setenv",
            "HOME",
            "/tmp/home",
            "--chdir",
            str(root),
            "--",
            *command,
        ]
    )
    return sandbox


def run_checks(
    root: Path,
    contract: dict[str, Any],
    result: dict[str, Any],
    allow_commands: bool,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for spec in contract.get("acceptance_tests", []):
        typ = spec.get("type")
        passed = False
        detail = ""
        harness_failure = False
        required = bool(spec.get("required", True))
        weight = clamp(float(spec.get("weight", 1.0)))
        try:
            if deadline is not None and time.monotonic() >= deadline:
                harness_failure = True
                detail = "contract max_minutes budget exhausted during acceptance"
            elif typ == "file_exists":
                path = safe_project_path(root, spec["path"])
                passed = path.exists()
                detail = str(path)
            elif typ == "file_sha256":
                path = _bounded_acceptance_file(safe_project_path(root, spec["path"]))
                actual = digest(path)
                passed = actual == spec.get("sha256")
                detail = str(actual)
            elif typ in {"regex_present", "regex_absent"}:
                path = _bounded_acceptance_file(safe_project_path(root, spec["path"]))
                regex_timeout = 5.0
                if deadline is not None:
                    regex_timeout = min(regex_timeout, max(0.001, deadline - time.monotonic()))
                regex_probe = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import pathlib,re,sys; text=pathlib.Path(sys.argv[2]).read_text(encoding='utf-8',errors='replace'); "
                        "raise SystemExit(0 if re.search(sys.argv[1],text,re.MULTILINE) else 1)",
                        spec["pattern"],
                        str(path),
                    ],
                    capture_output=True,
                    timeout=regex_timeout,
                    env=_sanitized_check_environment(),
                )
                found = regex_probe.returncode == 0
                passed = found if typ == "regex_present" else not found
                detail = spec["pattern"]
            elif typ == "json_path_equals":
                source = result if spec.get("source", "result") == "result" else load(
                    _bounded_acceptance_file(safe_project_path(root, spec["path"]))
                )
                actual = json_path(source, spec["json_path"])
                passed = actual == spec.get("expected")
                detail = repr(actual)
            elif typ == "command_exit_zero":
                if not allow_commands:
                    detail = "command checks disabled; rerun with --allow-commands after review"
                elif not result.get("acceptance_command_sandboxed"):
                    detail = "command checks require a dispatcher-owned disposable Git snapshot"
                elif shutil.which("bwrap") is None:
                    detail = "command checks require bubblewrap isolation on this host"
                else:
                    command = spec["command"]
                    if not isinstance(command, list) or not command or not all(isinstance(value, str) for value in command):
                        raise ValueError("command_exit_zero requires a non-empty argv array; shell strings are not allowed")
                    command_timeout = float(spec.get("timeout", 120))
                    if deadline is not None:
                        command_timeout = min(command_timeout, max(0.001, deadline - time.monotonic()))
                    completed = subprocess.run(
                        _acceptance_sandbox_command(root, command),
                        cwd=root,
                        shell=False,
                        capture_output=True,
                        text=True,
                        timeout=command_timeout,
                        env=_sanitized_check_environment(),
                    )
                    passed = completed.returncode == 0
                    detail = _redact_check_output(completed.stdout + "\n" + completed.stderr)
            else:
                detail = f"unsupported check type: {typ}"
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, subprocess.TimeoutExpired) and typ in {"regex_present", "regex_absent"}:
                harness_failure = True
                detail = "acceptance regex exceeded the isolated evaluation timeout"
            elif deadline is not None and time.monotonic() >= deadline:
                harness_failure = True
                detail = "contract max_minutes budget exhausted during acceptance"
        checks.append(
            {
                "name": spec.get("name", typ),
                "type": typ,
                "required": required,
                "weight": weight,
                "passed": passed,
                "detail": detail,
                "harness_failure": harness_failure,
            }
        )
    return checks


def verifier_summary(verifier: dict[str, Any] | None) -> dict[str, Any]:
    if not verifier:
        return {
            "provided": False,
            "independent": False,
            "quality": None,
            "disposition": None,
            "failure_modes": [],
            "verifier_disagreement": 0.0,
        }
    dimensions = verifier.get("dimensions", {})
    numeric = [clamp(float(value)) for value in dimensions.values() if isinstance(value, (int, float))]
    return {
        "provided": True,
        "independent": bool(verifier.get("independent", False)),
        "verifier_id": verifier.get("verifier_id"),
        "model_id": verifier.get("model_id"),
        "quality": round(sum(numeric) / len(numeric), 6) if numeric else None,
        "dimensions": dimensions,
        "confidence": clamp(float(verifier.get("confidence", 0.0))),
        "disposition": verifier.get("disposition"),
        "failure_modes": verifier.get("failure_modes", []),
        "verifier_disagreement": clamp(float(verifier.get("verifier_disagreement", 0.0))),
        "notes": verifier.get("notes", ""),
    }


def human_summary(feedback: dict[str, Any] | None) -> dict[str, Any]:
    feedback = feedback or {}
    return {
        "provided": bool(feedback),
        "reviewer": feedback.get("reviewer"),
        "correction_fraction": clamp(float(feedback.get("correction_fraction", 0.0))),
        "override_disposition": feedback.get("override_disposition"),
        "notes": feedback.get("notes", ""),
    }


def evaluate(
    root: Path,
    contract: dict[str, Any],
    result: dict[str, Any],
    verifier: dict[str, Any] | None,
    human_feedback: dict[str, Any] | None,
    allow_commands: bool,
    deadline: float | None = None,
) -> dict[str, Any]:
    checks = run_checks(root, contract, result, allow_commands, deadline)
    required_failures = [check for check in checks if check["required"] and not check["passed"]]
    total_weight = sum(check["weight"] for check in checks)
    passed_weight = sum(check["weight"] for check in checks if check["passed"])
    deterministic_quality = round(passed_weight / total_weight, 6) if total_weight else 0.0

    verifier_data = verifier_summary(verifier)
    human_data = human_summary(human_feedback)
    verifier_quality = verifier_data["quality"]
    quality_before_correction = (
        deterministic_quality
        if verifier_quality is None
        else 0.65 * deterministic_quality + 0.35 * float(verifier_quality)
    )
    quality = clamp(quality_before_correction * (1.0 - 0.5 * human_data["correction_fraction"]))

    threshold = clamp(float(contract.get("minimum_verified_quality", 0.8)))
    requires_independent = bool(contract.get("requires_independent_verifier", False))
    verification_infrastructure_failure = bool(result.get("verification_infrastructure_failure"))
    integration_infrastructure_failure = bool(result.get("integration_infrastructure_failure"))
    acceptance_harness_failure = bool(
        result.get("acceptance_harness_failure") or any(check.get("harness_failure") for check in checks)
    )
    identity_mismatch = bool(result.get("identity_mismatch"))
    harness_infrastructure_failure = (
        verification_infrastructure_failure or integration_infrastructure_failure or acceptance_harness_failure
    )
    verifier_blocked = requires_independent and not verifier_data["independent"]
    negative_verdicts = {"reject", "retry-same", "retry-stronger", "route-different"}
    verifier_rejects = verifier_data["disposition"] in negative_verdicts
    worker_contract_failure = bool(result.get("scope_violation") or result.get("status") != "complete")

    accepted = bool(
        checks
        and not required_failures
        and not verifier_blocked
        and not verifier_rejects
        and not worker_contract_failure
        and not identity_mismatch
        and quality >= threshold
    )
    disposition = "accepted" if accepted else "reject"
    if accepted and human_data["correction_fraction"] > 0:
        disposition = "accepted-with-corrections"
    elif verifier_data["disposition"] in negative_verdicts:
        disposition = str(verifier_data["disposition"])
    elif required_failures:
        disposition = "retry-same"
    elif verifier_blocked:
        disposition = "retry-stronger"
    elif quality < threshold:
        disposition = "route-different"
    if human_data["override_disposition"]:
        disposition = str(human_data["override_disposition"])
        accepted = disposition in {"accepted", "accepted-with-corrections"}
    if worker_contract_failure:
        accepted = False
        disposition = "reject"
    if identity_mismatch:
        accepted = False
        disposition = "route-different"
    if verification_infrastructure_failure:
        accepted = False
        disposition = "retry-stronger"
    elif integration_infrastructure_failure:
        accepted = False
        disposition = "retry-same"
    elif acceptance_harness_failure:
        accepted = False
        disposition = "retry-same"

    failure_attribution = "none"
    if contract.get("contract_invalid"):
        failure_attribution = "task-contract"
    elif harness_infrastructure_failure:
        failure_attribution = "harness"
    elif result.get("infrastructure_failure"):
        error_class = str(result.get("error_class") or "")
        if error_class in {"WorkerRateLimitError", "ProviderResponseError"}:
            failure_attribution = "provider"
        elif error_class == "BrokerBudgetError":
            failure_attribution = "harness"
        else:
            failure_attribution = "environment"
    elif not accepted:
        failure_attribution = "provider" if identity_mismatch else "worker-model"

    raw_task = dict(contract.get("task", {}))
    failure_observations = [
        {
            "code": str(mode).strip().lower().replace(" ", "_"),
            "severity": "medium",
            "attribution": failure_attribution,
            "description": str(mode),
        }
        for mode in verifier_data["failure_modes"]
    ]
    failure_observations.extend(
        {
            "code": "acceptance_check_failed",
            "severity": "high" if check["required"] else "medium",
            "attribution": failure_attribution,
            "description": f"{check['name']}: {check['detail']}",
        }
        for check in required_failures
    )
    if verification_infrastructure_failure:
        failure_observations.append(
            {
                "code": "verification_harness_unavailable",
                "severity": "high",
                "attribution": "harness",
                "description": "required independent verification did not produce a valid, attributable verdict",
            }
        )
    if integration_infrastructure_failure:
        failure_observations.append(
            {
                "code": "accepted_patch_not_integrated",
                "severity": "high",
                "attribution": "harness",
                "description": str(result.get("integration_error") or "accepted patch could not be safely applied"),
            }
        )
    if acceptance_harness_failure:
        failure_observations.append(
            {
                "code": "acceptance_harness_not_isolated",
                "severity": "high",
                "attribution": "harness",
                "description": str(
                    result.get("acceptance_harness_error")
                    or "acceptance command could not be executed without mutating the evaluated state"
                ),
            }
        )
    if result.get("scope_violation"):
        failure_observations.append(
            {
                "code": "worker_write_scope_violation",
                "severity": "high",
                "attribution": "worker-model",
                "description": str(result.get("error") or "worker changed files outside the frozen write_scope"),
            }
        )
    if identity_mismatch:
        failure_observations.append(
            {
                "code": "provider_model_identity_mismatch",
                "severity": "high",
                "attribution": "provider",
                "description": (
                    f"requested model {result.get('requested_model')!r} but provider returned "
                    f"{result.get('returned_model')!r}"
                ),
            }
        )
    usage = normalize_provider_usage(result)
    worker_complete = result.get("status") == "complete"
    output_present = bool(result.get("output_text") or result.get("artifacts"))
    event = {
        "schema_version": 2,
        "source": "live",
        "project_id": contract.get("project_id") or root.name,
        "task_id": contract.get("task_id"),
        "work_unit_id": contract.get("work_unit_id") or contract.get("task_id"),
        "route_decision_id": result.get("route_decision_id"),
        "task": raw_task,
        "execution_arm_id": result.get("execution_arm_id") or result.get("model_id"),
        "execution_identity": {
            "provider": result.get("provider"),
            "model": result.get("model"),
            "reasoning_effort": result.get("reasoning_effort"),
            "requested_model": result.get("requested_model"),
            "returned_model": result.get("returned_model"),
            "endpoint_id": result.get("endpoint_id"),
        },
        "outcome": {
            "accepted": accepted,
            "disposition": disposition,
            "worker_status": result.get("status"),
            "output_present": output_present,
            "contract_complete": worker_complete and not required_failures,
            "required_artifacts_complete": not any(
                check["required"] and not check["passed"] for check in checks
            ),
            "verified_progress": deterministic_quality,
            "quality": round(quality, 6),
            "human_correction": human_data["correction_fraction"],
            "verifier_disagreement": verifier_data["verifier_disagreement"],
        },
        "usage": {
            **usage,
            "latency_seconds": float(result.get("latency_seconds", 0.0)),
            "cost_amount": float(result.get("cost", 0.0)),
            "currency": result.get("currency", "USD"),
            "price_quote_id": result.get("price_quote_id"),
            "cost_provenance": "provider_usage" if result.get("cost") is not None else "unknown",
        },
        "verification": {
            "deterministic_checks_count": len(checks),
            "deterministic_checks_passed": sum(int(check["passed"]) for check in checks),
            "requires_independent_verifier": requires_independent,
            "independent_verifier_provided": verifier_data["independent"],
            "evidence_refs": result.get("artifacts", []),
        },
        "failure_observations": failure_observations,
        "versions": {
            "agent_revision": result.get("agent_revision"),
            "evaluator": "evaluate-dispatch-v2",
            "verifier_id": verifier_data.get("verifier_id"),
        },
        "selection_probability": result.get("selection_probability"),
        # Infrastructure failures update endpoint health, not model competence.
        "registry_eligible": not bool(
            result.get("infrastructure_failure")
            or harness_infrastructure_failure
            or worker_contract_failure
            or identity_mismatch
        ),
    }
    return {
        "schema_version": 2,
        "task_id": contract.get("task_id"),
        "model_id": result.get("model_id"),
        "accepted": accepted,
        "disposition": disposition,
        "minimum_verified_quality": threshold,
        "quality": round(quality, 6),
        "deterministic_quality": deterministic_quality,
        "checks": checks,
        "required_failures": [check["name"] for check in required_failures],
        "verifier": verifier_data,
        "human_feedback": human_data,
        "failure_attribution": failure_attribution,
        "worker_self_assessment_ignored_for_acceptance": True,
        "event_for_registry": event,
    }
