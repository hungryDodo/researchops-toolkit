from __future__ import annotations

import datetime as dt
import json
import math
import statistics
from collections import defaultdict
from typing import Any, Iterable

from ..common import now
from .store import IntelligenceStore

AGGREGATOR_VERSION = "profile-engine-v2"
Z80 = 1.2815515655446004


def _iso_now() -> str:
    return now().replace("+00:00", "Z")


def _median(values: list[float]) -> float:
    return round(float(statistics.median(values)), 6) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(float(ordered[0]), 6)
    position = (len(ordered) - 1) * percentile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return round(float(ordered[lower]), 6)
    value = ordered[lower] * (upper - position) + ordered[upper] * (position - lower)
    return round(float(value), 6)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _optional_median(values: list[float]) -> float | None:
    return _median(values) if values else None


def _beta_summary(accepted: int, observations: int) -> dict[str, Any]:
    alpha, beta = accepted + 1.0, observations - accepted + 1.0
    mean = alpha / (alpha + beta)
    variance = alpha * beta / (((alpha + beta) ** 2) * (alpha + beta + 1.0))
    radius = Z80 * math.sqrt(variance)
    return {
        "alpha": round(alpha, 6),
        "beta": round(beta, 6),
        "posterior_mean": round(mean, 6),
        "credible_interval_80": [round(max(0.0, mean - radius), 6), round(min(1.0, mean + radius), 6)],
    }


def scope_key(arm_id: str, project_id: str | None = None, orientation: str | None = None, operation: str | None = None) -> str:
    return "|".join((arm_id, project_id or "*", orientation or "*", operation or "*"))


def _scopes(event: dict[str, Any]) -> Iterable[tuple[str, str | None, str | None, str | None]]:
    arm = event["execution_arm_id"]
    project = event["project_id"]
    orientation = event["orientation"]
    operation = event["operation"]
    # Intentionally finite.  Rich event metadata is not an invitation to build
    # a sparse Cartesian product of profiles.
    yield arm, None, None, None
    yield arm, None, None, operation
    yield arm, project, None, operation
    yield arm, None, orientation, operation


def _parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _snapshot(rows: list[dict[str, Any]], *, arm_id: str, project_id: str | None, orientation: str | None, operation: str | None, generated_at: str) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: row["occurred_at"])
    accepted = sum(int(row["accepted"]) for row in ordered)
    recent_cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
    recent = [row for row in ordered[-20:] if _parse_time(row["occurred_at"]) >= recent_cutoff]
    if not recent:
        recent = ordered[-min(5, len(ordered)):]
    source_mix: dict[str, int] = defaultdict(int)
    for row in ordered:
        source_mix[row["source"]] += 1
    usage_rows = [json.loads(row["usage_json"]) for row in ordered]
    cache_counts = {"hit": 0, "miss": 0, "unknown": 0}
    for usage in usage_rows:
        cache_hit = usage.get("cache_hit")
        cache_counts["hit" if cache_hit is True else "miss" if cache_hit is False else "unknown"] += 1
    lifetime_success = accepted / len(ordered)
    recent_success = sum(int(row["accepted"]) for row in recent) / len(recent) if recent else lifetime_success
    delta = recent_success - lifetime_success
    drift = "stable"
    if len(ordered) >= 8 and len(recent) >= 3:
        if delta <= -0.20:
            drift = "degrading"
        elif delta >= 0.20:
            drift = "improving"
    return {
        "scope": {
            "scope_key": scope_key(arm_id, project_id, orientation, operation),
            "execution_arm_id": arm_id,
            "project_id": project_id,
            "orientation": orientation,
            "operation": operation,
        },
        "observations": len(ordered),
        "accepted": accepted,
        "success": _beta_summary(accepted, len(ordered)),
        "verified_progress": {
            "mean": _mean([float(row["verified_progress"]) for row in ordered]),
            "median": _median([float(row["verified_progress"]) for row in ordered]),
        },
        "quality": {"mean": _mean([float(row["quality"]) for row in ordered])},
        "cost": {
            "median": _median([float(row["cost_amount"]) for row in ordered]),
            "p90": _percentile([float(row["cost_amount"]) for row in ordered], 0.90),
            "currency": next((row["currency"] for row in reversed(ordered) if row["currency"]), "USD"),
        },
        "latency_seconds": {
            "median": _median([float(row["latency_seconds"]) for row in ordered]),
            "p95": _percentile([float(row["latency_seconds"]) for row in ordered], 0.95),
        },
        "human_correction_mean": _mean([float(row["human_correction"]) for row in ordered]),
        "verifier_disagreement_mean": _mean([float(row["verifier_disagreement"]) for row in ordered]),
        "tokens": {
            "input_median": _median([float(row["input_tokens"]) for row in ordered]),
            "output_median": _median([float(row["output_tokens"]) for row in ordered]),
            "input_cached_median": _optional_median(
                [float(row["input_tokens_cached"]) for row in usage_rows if row.get("input_tokens_cached") is not None]
            ),
            "reasoning_median": _optional_median(
                [float(row["reasoning_tokens"]) for row in usage_rows if row.get("reasoning_tokens") is not None]
            ),
        },
        "cache": cache_counts,
        "ttft_seconds": {
            "median": _optional_median(
                [float(row["ttft_seconds"]) for row in usage_rows if row.get("ttft_seconds") is not None]
            )
        },
        "recent_window": {
            "observations": len(recent),
            "success_mean": round(recent_success, 6),
            "quality_mean": _mean([float(row["quality"]) for row in recent]),
            "progress_mean": _mean([float(row["verified_progress"]) for row in recent]),
            "delta_from_lifetime": round(delta, 6),
        },
        "source_mix": dict(sorted(source_mix.items())),
        "first_seen": ordered[0]["occurred_at"],
        "last_seen": ordered[-1]["occurred_at"],
        "drift_status": drift,
        "generated_at": generated_at,
        "aggregator_version": AGGREGATOR_VERSION,
    }


def rebuild_profiles(store: IntelligenceStore) -> dict[str, Any]:
    rows = store.query(
        """
        SELECT e.* FROM evaluation_events e
        WHERE e.registry_eligible=1
          AND NOT EXISTS (
            SELECT 1 FROM evaluation_events replacement
            WHERE replacement.supersedes_event_id=e.event_id
          )
        ORDER BY e.occurred_at, e.event_id
        """
    )
    buckets: dict[tuple[str, str | None, str | None, str | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for scope in _scopes(row):
            buckets[scope].append(row)
    generated_at = _iso_now()
    snapshots: dict[str, dict[str, Any]] = {}
    with store.transaction() as connection:
        connection.execute("DELETE FROM profile_slices")
        for (arm, project, orientation, operation), events in sorted(buckets.items(), key=lambda item: scope_key(*item[0])):
            snapshot = _snapshot(events, arm_id=arm, project_id=project, orientation=orientation, operation=operation, generated_at=generated_at)
            key = snapshot["scope"]["scope_key"]
            snapshots[key] = snapshot
            connection.execute(
                """
                INSERT INTO profile_slices(
                    scope_key,arm_id,project_id,orientation,operation,generated_at,
                    aggregator_version,event_count,snapshot_json
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    key, arm, project, orientation, operation, generated_at,
                    AGGREGATOR_VERSION, len(events), json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                ),
            )
    return {
        "schema_version": 2,
        "generated": True,
        "do_not_edit": True,
        "aggregator_version": AGGREGATOR_VERSION,
        "generated_at": generated_at,
        "input_event_count": len(rows),
        "profiles": snapshots,
    }


def load_profiles(store: IntelligenceStore) -> dict[str, Any]:
    rows = store.query("SELECT scope_key,snapshot_json FROM profile_slices ORDER BY scope_key")
    return {row["scope_key"]: json.loads(row["snapshot_json"]) for row in rows}


def best_profile(profiles: dict[str, Any], arm_id: str, task: dict[str, Any], project_id: str) -> tuple[dict[str, Any] | None, str]:
    operation = str(task.get("operation", "unknown"))
    orientation = str(task.get("orientation", "unknown"))
    candidates = [
        (scope_key(arm_id, project_id, None, operation), "project-operation"),
        (scope_key(arm_id, None, orientation, operation), "orientation-operation"),
        (scope_key(arm_id, None, None, operation), "operation"),
        (scope_key(arm_id), "global"),
    ]
    for key, reason in candidates:
        if key in profiles:
            return profiles[key], reason
    return None, "prior-only"
