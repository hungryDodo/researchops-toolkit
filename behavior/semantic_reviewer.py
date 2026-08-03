from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

ALLOWED_RISKS = {"none", "medium", "high", "critical"}


def _config(project_root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    defaults = dict(policy.get("semantic_review", {}))
    path = project_root / ".research" / "runtime" / "config.json"
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            configured = state.get("semantic_review")
            if isinstance(configured, dict):
                defaults.update(configured)
        except (OSError, json.JSONDecodeError):
            pass
    env_command = os.environ.get("ROPS_SEMANTIC_REVIEW_COMMAND")
    env_mode = os.environ.get("ROPS_SEMANTIC_REVIEW_MODE")
    if env_command:
        defaults["command"] = env_command
    if env_mode:
        defaults["mode"] = env_mode
    defaults.setdefault("mode", "off")
    defaults.setdefault("timeout_seconds", 12)
    defaults.setdefault("max_output_bytes", 65536)
    return defaults


def _validate_response(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("semantic reviewer output must be a JSON object")
    risk = str(value.get("risk", "")).lower()
    if risk not in ALLOWED_RISKS:
        raise ValueError("semantic reviewer risk must be none, medium, high, or critical")
    categories = value.get("categories", [])
    if not isinstance(categories, list) or not all(isinstance(item, str) and item.strip() for item in categories):
        raise ValueError("semantic reviewer categories must be a string array")
    reason = value.get("reason", "")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("semantic reviewer must return a non-empty reason")
    confidence = value.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        raise ValueError("semantic reviewer confidence must be between 0 and 1")
    return {
        "risk": risk,
        "categories": sorted(set(item.strip() for item in categories)),
        "reason": reason.strip()[:1200],
        "confidence": float(confidence),
        "reviewer": str(value.get("reviewer", "external-command"))[:200],
    }


def review(command: str, analysis: dict[str, Any], project_root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    config = _config(project_root, policy)
    mode = str(config.get("mode", "off")).lower()
    allowed = set(policy.get("semantic_review", {}).get("allowed_modes", ["off", "advisory", "required"]))
    if mode not in allowed:
        mode = "off"
    result: dict[str, Any] = {
        "mode": mode,
        "status": "disabled" if mode == "off" else "not-needed",
        "response": None,
        "error": None,
    }
    if mode == "off":
        return result
    review_uncertain_only = bool(config.get("review_uncertain_only", True))
    if review_uncertain_only and not analysis.get("needs_semantic_review"):
        return result
    configured_command = config.get("command")
    if not isinstance(configured_command, str) or not configured_command.strip():
        result["status"] = "unavailable"
        result["error"] = "semantic review command is not configured"
        return result
    try:
        argv = shlex.split(configured_command, posix=os.name != "nt")
    except ValueError as exc:
        result["status"] = "error"
        result["error"] = f"invalid semantic review command: {exc}"
        return result
    if not argv:
        result["status"] = "error"
        result["error"] = "semantic review command is empty"
        return result
    request = {
        "schema_version": 1,
        "instruction": (
            "Review this shell/tool command for consequential security, data-loss, persistence, privilege, "
            "external-transfer, hardware, and policy-bypass risk. Return JSON only. Never treat the absence "
            "of an obvious exploit string as proof of safety."
        ),
        "output_schema": {
            "risk": "none|medium|high|critical",
            "categories": ["short-category"],
            "reason": "concise evidence-based explanation",
            "confidence": "number from 0 to 1",
            "reviewer": "model/provider identifier without credentials"
        },
        "command": command,
        "static_analysis": {
            "canonical": analysis.get("canonical"),
            "invocations": analysis.get("invocations", []),
            "dynamic_constructs": analysis.get("dynamic_constructs", []),
            "parse_warnings": analysis.get("parse_warnings", []),
            "deterministic_findings": [
                {key: item.get(key) for key in ("rule_id", "kind", "severity", "reason")}
                for item in analysis.get("findings", [])
            ],
        },
    }
    try:
        completed = subprocess.run(
            argv,
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=float(config.get("timeout_seconds", 12)),
            check=False,
            env={**os.environ, "ROPS_SEMANTIC_REVIEW": "1"},
        )
        max_bytes = int(config.get("max_output_bytes", 65536))
        stdout = completed.stdout.encode("utf-8", errors="replace")[:max_bytes].decode("utf-8", errors="replace")
        if completed.returncode != 0:
            raise RuntimeError(f"reviewer exited {completed.returncode}: {completed.stderr[:500]}")
        response = _validate_response(json.loads(stdout))
        result.update({"status": "completed", "response": response})
    except (OSError, subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError, ValueError) as exc:
        result["status"] = "error"
        result["error"] = str(exc)[:800]
    return result
