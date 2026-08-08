#!/usr/bin/env python3
"""Independently evaluate a delegated task result against a bounded contract."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def load(path: Path | None) -> Any:
    if path is None:
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def digest(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_path(obj: Any, path: str) -> Any:
    cur = obj
    for token in path.strip(".").split("."):
        if not token:
            continue
        if isinstance(cur, list):
            cur = cur[int(token)]
        elif isinstance(cur, dict):
            cur = cur[token]
        else:
            raise KeyError(path)
    return cur


def clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def safe_project_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root)
    return path


def run_checks(root: Path, contract: dict[str, Any], result: dict[str, Any], allow_commands: bool) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for spec in contract.get("acceptance_tests", []):
        typ = spec.get("type")
        passed = False
        detail = ""
        required = bool(spec.get("required", True))
        weight = clamp(float(spec.get("weight", 1.0)))
        try:
            if typ == "file_exists":
                path = safe_project_path(root, spec["path"])
                passed = path.exists()
                detail = str(path)
            elif typ == "file_sha256":
                path = safe_project_path(root, spec["path"])
                actual = digest(path)
                passed = actual == spec.get("sha256")
                detail = str(actual)
            elif typ in {"regex_present", "regex_absent"}:
                path = safe_project_path(root, spec["path"])
                text = path.read_text(encoding="utf-8", errors="replace")
                found = re.search(spec["pattern"], text, re.MULTILINE) is not None
                passed = found if typ == "regex_present" else not found
                detail = spec["pattern"]
            elif typ == "json_path_equals":
                source = result if spec.get("source", "result") == "result" else load(safe_project_path(root, spec["path"]))
                actual = json_path(source, spec["json_path"])
                passed = actual == spec.get("expected")
                detail = repr(actual)
            elif typ == "command_exit_zero":
                if not allow_commands:
                    detail = "command checks disabled; rerun with --allow-commands after review"
                else:
                    command = spec["command"]
                    completed = subprocess.run(
                        command,
                        cwd=root,
                        shell=isinstance(command, str),
                        capture_output=True,
                        text=True,
                        timeout=float(spec.get("timeout", 120)),
                        env=None,
                    )
                    passed = completed.returncode == 0
                    detail = (completed.stdout + "\n" + completed.stderr)[-2000:]
            else:
                detail = f"unsupported check type: {typ}"
        except Exception as exc:  # The exception is evidence; do not hide it.
            detail = f"{type(exc).__name__}: {exc}"
        checks.append(
            {
                "name": spec.get("name", typ),
                "type": typ,
                "required": required,
                "weight": weight,
                "passed": passed,
                "detail": detail,
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
) -> dict[str, Any]:
    checks = run_checks(root, contract, result, allow_commands)
    required_failures = [check for check in checks if check["required"] and not check["passed"]]
    total_weight = sum(check["weight"] for check in checks)
    passed_weight = sum(check["weight"] for check in checks if check["passed"])
    deterministic_quality = round(passed_weight / total_weight, 6) if total_weight else 0.0

    verifier_data = verifier_summary(verifier)
    human_data = human_summary(human_feedback)
    verifier_quality = verifier_data["quality"]
    if verifier_quality is None:
        quality_before_correction = deterministic_quality
    else:
        quality_before_correction = 0.65 * deterministic_quality + 0.35 * float(verifier_quality)
    quality = clamp(quality_before_correction * (1.0 - 0.5 * human_data["correction_fraction"]))

    threshold = clamp(float(contract.get("minimum_verified_quality", 0.8)))
    requires_independent = bool(contract.get("requires_independent_verifier", False))
    verifier_blocked = requires_independent and not verifier_data["independent"]
    negative_verdicts = {"reject", "retry-same", "retry-stronger", "route-different"}
    verifier_rejects = verifier_data["disposition"] in negative_verdicts

    accepted = bool(checks) and not required_failures and not verifier_blocked and not verifier_rejects and quality >= threshold
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

    failure_attribution = "none"
    if contract.get("contract_invalid"):
        failure_attribution = "orchestration-contract"
    elif result.get("infrastructure_failure"):
        failure_attribution = "infrastructure"
    elif not accepted:
        failure_attribution = "worker-or-capability"

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
            "attribution": "worker-model" if failure_attribution == "worker-or-capability" else failure_attribution,
            "description": f"{check['name']}: {check['detail']}",
        }
        for check in required_failures
    )
    event = {
        "schema_version": 2,
        "source": "live",
        "project_id": contract.get("project_id") or root.name,
        "task_id": contract.get("task_id"),
        "work_unit_id": contract.get("work_unit_id") or contract.get("task_id"),
        "route_decision_id": result.get("route_decision_id"),
        "task": raw_task,
        "execution_arm_id": result.get("execution_arm_id") or result.get("model_id"),
        "outcome": {
            "accepted": accepted,
            "disposition": disposition,
            "verified_progress": deterministic_quality,
            "quality": round(quality, 6),
            "human_correction": human_data["correction_fraction"],
            "verifier_disagreement": verifier_data["verifier_disagreement"],
        },
        "usage": {
            "latency_seconds": float(result.get("latency_seconds", 0.0)),
            "cost_amount": float(result.get("cost", 0.0)),
            "currency": result.get("currency", "USD"),
            "input_tokens": int((result.get("usage") or {}).get("prompt_tokens", result.get("input_tokens", 0)) or 0),
            "output_tokens": int((result.get("usage") or {}).get("completion_tokens", result.get("output_tokens", 0)) or 0),
            "price_quote_id": result.get("price_quote_id"),
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
        "registry_eligible": True,
    }
    return {
        "schema_version": 2,
        "evaluated_at": iso(),
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, help="Independent verifier JSON; required when the contract says so.")
    parser.add_argument("--human-feedback", type=Path, help="Optional calibrated human correction/override JSON.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-commands", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    data = evaluate(root, load(args.contract), load(args.result), load(args.verifier), load(args.human_feedback), args.allow_commands)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
