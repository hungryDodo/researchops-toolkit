from __future__ import annotations

import datetime as dt
import json
import math
import uuid
from dataclasses import dataclass
from typing import Any

from ..common import now
from .store import IntelligenceStore

ORIENTATIONS = {"research-led", "development-led", "mixed", "unknown"}
OPERATIONS = {"discover", "design", "implement", "debug", "validate", "communicate", "operate", "unknown"}
ARTIFACTS = {"code", "experiment", "analysis", "document", "visual", "system", "unknown"}
SOURCES = {"live", "shadow", "anchor"}
RISK = {"low", "medium", "high", "critical"}
PRIVACY = {"public", "internal", "confidential", "restricted"}
MUTABILITY = {"read-only", "workspace-write", "external-write", "hardware-write", "destructive"}

OPERATION_MAP = {
    "search": "discover",
    "extraction": "discover",
    "classification": "discover",
    "synthesis": "communicate",
    "writing": "communicate",
    "formatting": "communicate",
    "implementation": "implement",
    "coding": "implement",
    "review": "validate",
    "validation": "validate",
    "experiment": "design",
    "analysis": "validate",
}


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return max(0.0, min(1.0, number))


def _nonnegative(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return max(0.0, number)


def _integer(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _choice(value: Any, allowed: set[str], default: str) -> str:
    normalized = str(value or default).strip().lower()
    return normalized if normalized in allowed else default


def _timestamp(value: Any) -> str:
    if not value:
        return now().replace("+00:00", "Z")
    text = str(value)
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        raise ValueError(f"invalid ISO timestamp: {text}") from None


def normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    raw_type = str(task.get("operation") or task.get("type") or "unknown").lower()
    operation = OPERATION_MAP.get(raw_type, raw_type)
    if operation not in OPERATIONS:
        operation = "unknown"
    orientation = _choice(task.get("orientation"), ORIENTATIONS, "unknown")
    primary_artifact = _choice(task.get("primary_artifact") or task.get("artifact"), ARTIFACTS, "unknown")
    if primary_artifact == "unknown":
        primary_artifact = {
            "discover": "analysis",
            "design": "analysis",
            "implement": "code",
            "debug": "code",
            "validate": "analysis",
            "communicate": "document",
            "operate": "system",
        }.get(operation, "unknown")
    return {
        **task,
        "objective": str(task.get("objective") or task.get("description") or "").strip(),
        "orientation": orientation,
        "operation": operation,
        "primary_artifact": primary_artifact,
        "risk": _choice(task.get("risk"), RISK, "low"),
        "privacy": _choice(task.get("privacy"), PRIVACY, "internal"),
        "mutability": _choice(task.get("mutability"), MUTABILITY, "read-only"),
        "required_capabilities": sorted({str(x) for x in task.get("required_capabilities", []) if str(x).strip()}),
        "uncertain_fields": sorted({str(x) for x in task.get("uncertain_fields", []) if str(x).strip()}),
    }


@dataclass(frozen=True)
class EvaluationEvent:
    data: dict[str, Any]

    @classmethod
    def normalize(cls, raw: dict[str, Any], *, project_id: str | None = None) -> "EvaluationEvent":
        if not isinstance(raw, dict):
            raise ValueError("evaluation event must be an object")
        task = normalize_task(raw.get("task") if isinstance(raw.get("task"), dict) else {})
        outcome_raw = raw.get("outcome") if isinstance(raw.get("outcome"), dict) else {}
        usage_raw = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        verification = raw.get("verification") if isinstance(raw.get("verification"), dict) else {}
        versions = raw.get("versions") if isinstance(raw.get("versions"), dict) else {}

        accepted = bool(outcome_raw.get("accepted", raw.get("accepted", False)))
        source_candidate = str(raw.get("source", "live")).lower()
        probe_like = source_candidate in {"smoke", "probe", "connectivity"} or bool(raw.get("probe", False))
        source = source_candidate if source_candidate in SOURCES else "live"
        eligible = bool(raw.get("registry_eligible", not probe_like)) and not probe_like

        arm_id = str(raw.get("execution_arm_id") or raw.get("model_id") or "").strip()
        if not arm_id:
            raise ValueError("execution_arm_id/model_id is required")
        event_id = str(raw.get("event_id") or f"evt-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}")
        progress_default = 1.0 if accepted else 0.0
        quality_default = 1.0 if accepted else 0.0
        cost = usage_raw.get("cost_amount", raw.get("cost", raw.get("cost_amount", 0.0)))
        latency = usage_raw.get("latency_seconds", raw.get("latency_seconds", 0.0))

        data = {
            "schema_version": 2,
            "event_id": event_id,
            "occurred_at": _timestamp(raw.get("occurred_at") or raw.get("evaluated_at") or raw.get("recorded_at")),
            "recorded_at": _timestamp(raw.get("recorded_at")),
            "project_id": str(raw.get("project_id") or project_id or "default"),
            "task_id": raw.get("task_id") or task.get("task_id"),
            "work_unit_id": raw.get("work_unit_id"),
            "route_decision_id": raw.get("route_decision_id"),
            "source": source,
            "execution_arm_id": arm_id,
            "task": task,
            "outcome": {
                **outcome_raw,
                "accepted": accepted,
                "verified_progress": _clamp(outcome_raw.get("verified_progress", raw.get("verified_progress", progress_default)), progress_default),
                "quality": _clamp(outcome_raw.get("quality", raw.get("quality", quality_default)), quality_default),
                "human_correction": _clamp(outcome_raw.get("human_correction", raw.get("human_correction", 0.0))),
                "verifier_disagreement": _clamp(outcome_raw.get("verifier_disagreement", raw.get("verifier_disagreement", 0.0))),
                "disposition": outcome_raw.get("disposition", raw.get("disposition")),
            },
            "usage": {
                **usage_raw,
                "input_tokens": _integer(usage_raw.get("input_tokens", raw.get("input_tokens", 0))),
                "output_tokens": _integer(usage_raw.get("output_tokens", raw.get("output_tokens", 0))),
                "latency_seconds": _nonnegative(latency),
                "cost_amount": _nonnegative(cost),
                "currency": str(usage_raw.get("currency", raw.get("currency", "USD"))).upper(),
                "price_quote_id": usage_raw.get("price_quote_id", raw.get("price_quote_id")),
            },
            "verification": verification,
            "failure_observations": raw.get("failure_observations") or [
                {
                    "code": str(code),
                    "severity": "medium",
                    "attribution": raw.get("failure_attribution", "worker-model"),
                    "description": str(code),
                }
                for code in (raw.get("failure_modes") or [])
            ],
            "versions": versions,
            "registry_eligible": eligible,
            "selection_probability": None if raw.get("selection_probability") is None else _clamp(raw.get("selection_probability")),
            "supersedes_event_id": raw.get("supersedes_event_id"),
        }
        return cls(data)

    def insert(self, store: IntelligenceStore) -> dict[str, Any]:
        d = self.data
        task, outcome, usage = d["task"], d["outcome"], d["usage"]
        with store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO evaluation_events(
                    event_id, occurred_at, recorded_at, project_id, task_id, work_unit_id,
                    route_decision_id, source, execution_arm_id, orientation, operation,
                    primary_artifact, risk, privacy, mutability, accepted, verified_progress,
                    quality, human_correction, verifier_disagreement, cost_amount, currency,
                    latency_seconds, input_tokens, output_tokens, selection_probability,
                    registry_eligible, task_json, outcome_json, usage_json, verification_json,
                    versions_json, raw_json, supersedes_event_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    d["event_id"], d["occurred_at"], d["recorded_at"], d["project_id"], d.get("task_id"),
                    d.get("work_unit_id"), d.get("route_decision_id"), d["source"], d["execution_arm_id"],
                    task["orientation"], task["operation"], task["primary_artifact"], task["risk"],
                    task["privacy"], task["mutability"], int(outcome["accepted"]), outcome["verified_progress"],
                    outcome["quality"], outcome["human_correction"], outcome["verifier_disagreement"],
                    usage["cost_amount"], usage["currency"], usage["latency_seconds"], usage["input_tokens"],
                    usage["output_tokens"], d.get("selection_probability"), int(d["registry_eligible"]),
                    json.dumps(task, ensure_ascii=False, sort_keys=True),
                    json.dumps(outcome, ensure_ascii=False, sort_keys=True),
                    json.dumps(usage, ensure_ascii=False, sort_keys=True),
                    json.dumps(d["verification"], ensure_ascii=False, sort_keys=True),
                    json.dumps(d["versions"], ensure_ascii=False, sort_keys=True),
                    json.dumps(d, ensure_ascii=False, sort_keys=True), d.get("supersedes_event_id"),
                ),
            )
            seen_codes: set[str] = set()
            for index, observation in enumerate(d.get("failure_observations", [])):
                if not isinstance(observation, dict):
                    continue
                code = str(observation.get("code") or "unknown_failure").strip().lower().replace(" ", "_")
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                connection.execute(
                    """
                    INSERT INTO failure_observations(
                        observation_id,event_id,arm_id,code,attribution,severity,description,evidence_ref,observed_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        f"fo-{d['event_id']}-{index}", d["event_id"], d["execution_arm_id"], code,
                        str(observation.get("attribution") or "unknown"),
                        str(observation.get("severity") or "medium"),
                        str(observation.get("description") or code),
                        observation.get("evidence_ref"), d["occurred_at"],
                    ),
                )
        return d


def record_event(store: IntelligenceStore, raw: dict[str, Any], *, project_id: str | None = None) -> dict[str, Any]:
    return EvaluationEvent.normalize(raw, project_id=project_id).insert(store)
