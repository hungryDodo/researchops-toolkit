from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..common import atomic_json, now
from .profiles import AGGREGATOR_VERSION, load_profiles, rebuild_profiles
from . import judges as judge_tools
from . import memory as memory_tools
from .benchmarks import load_packs, validate_pack
from .store import IntelligenceStore
from .warmup import all_warmup_states

PROJECTION_VERSION = "projection-v3"


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _header(store: IntelligenceStore, event_count: int) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "generated": True,
        "do_not_edit": True,
        "projection_version": PROJECTION_VERSION,
        "aggregator_version": AGGREGATOR_VERSION,
        "generated_at": now(),
        "input_event_count": event_count,
    }


def rebuild_projections(store: IntelligenceStore) -> dict[str, Any]:
    aggregate = rebuild_profiles(store)
    profiles = aggregate["profiles"]
    event_count = int(aggregate["input_event_count"])
    header = _header(store, event_count)
    header["input_digest"] = _digest(profiles)
    export = store.layout.exports
    export.mkdir(parents=True, exist_ok=True)

    routing = {**header, "profiles": profiles}
    atomic_json(export / "routing-profiles.json", routing)

    patterns = store.json_rows(
        "SELECT * FROM failure_patterns ORDER BY arm_id,status,last_seen DESC",
        json_columns=("representative_json",),
    )
    mitigations = store.json_rows(
        "SELECT * FROM mitigations ORDER BY proposed_at DESC",
        json_columns=("scope_json", "content_json", "metadata_json"),
    )
    epochs = store.json_rows(
        "SELECT * FROM deployment_epochs ORDER BY started_at DESC",
        json_columns=("declared_identity_json", "fingerprint_json"),
    )
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in profiles.values():
        by_arm[snapshot["scope"]["execution_arm_id"]].append(snapshot)
    dossier_dir = export / "model-dossiers"
    dossier_dir.mkdir(parents=True, exist_ok=True)
    dossier_index: list[dict[str, Any]] = []
    for arm, slices in sorted(by_arm.items()):
        arm_patterns = [p for p in patterns if p["arm_id"] == arm]
        arm_mitigations = [m for m in mitigations if (m["scope_json"].get("execution_arm_id") in {None, arm})]
        arm_epochs = [e for e in epochs if e["arm_base_id"] == arm or e["epoch_id"] in arm]
        dossier = {
            **header,
            "execution_arm_id": arm,
            "profile_slices": sorted(slices, key=lambda x: x["scope"]["scope_key"]),
            "failure_patterns": arm_patterns,
            "mitigations": arm_mitigations,
            "deployment_epochs": arm_epochs,
        }
        name = hashlib.sha256(arm.encode("utf-8")).hexdigest()[:16] + ".json"
        atomic_json(dossier_dir / name, dossier)
        global_slice = next((s for s in slices if s["scope"]["project_id"] is None and s["scope"]["operation"] is None), None)
        dossier_index.append({
            "execution_arm_id": arm,
            "path": f"model-dossiers/{name}",
            "observations": (global_slice or {}).get("observations", 0),
            "success": ((global_slice or {}).get("success") or {}).get("posterior_mean"),
            "verified_progress": ((global_slice or {}).get("verified_progress") or {}).get("mean"),
            "quality": ((global_slice or {}).get("quality") or {}).get("mean"),
            "cost_median": ((global_slice or {}).get("cost") or {}).get("median"),
            "currency": ((global_slice or {}).get("cost") or {}).get("currency", "USD"),
            "last_seen": (global_slice or {}).get("last_seen"),
            "drift_status": (global_slice or {}).get("drift_status", "unknown"),
        })
    atomic_json(export / "model-dossiers.json", {**header, "models": dossier_index})

    recent_routes = store.json_rows(
        "SELECT * FROM route_decisions ORDER BY created_at DESC LIMIT 25",
        json_columns=("task_json", "summary_json"),
    )
    endpoint_rows = store.query(
        """
        SELECT endpoint_id, COUNT(*) observations, AVG(success) success_rate,
               AVG(latency_seconds) latency_mean, MAX(observed_at) last_seen,
               SUM(rate_limited) rate_limited_count
        FROM endpoint_observations
        WHERE observed_at >= datetime('now','-24 hours')
        GROUP BY endpoint_id ORDER BY endpoint_id
        """
    )
    recent_outcomes = store.json_rows(
        """
        SELECT occurred_at,project_id,task_id,work_unit_id,execution_arm_id,accepted,
               verified_progress,quality,cost_amount,currency,task_json
        FROM evaluation_events
        WHERE registry_eligible=1
        ORDER BY occurred_at DESC,event_id DESC LIMIT 10
        """,
        json_columns=("task_json",),
    )
    warmup = all_warmup_states(store)
    latest_snapshot = store.one(
        "SELECT snapshot_id,project_id,captured_at,adoption_mode,root_digest,assessment_json FROM project_snapshots ORDER BY captured_at DESC LIMIT 1"
    )
    if latest_snapshot:
        latest_snapshot["assessment"] = json.loads(latest_snapshot.pop("assessment_json") or "{}")
    dashboard = {
        **header,
        "routing": {
            "recent_decisions": recent_routes,
            "recent_outcomes": recent_outcomes,
            "model_summary": dossier_index,
            "warmup": warmup,
            "endpoint_health": endpoint_rows,
            "active_failure_patterns": [p for p in patterns if p["status"] == "active"],
            "active_mitigations": [m for m in mitigations if m["status"] in {"canary", "active"}],
            "memory": memory_tools.status(store),
            "project_snapshot": latest_snapshot,
        },
    }
    atomic_json(export / "dashboard-routing.json", dashboard)

    # Benchmark projection: a compact, reproducible analytical view over the
    # same canonical events.  Packs describe applicability and evaluator
    # vocabulary; they never become a second source of performance facts.
    benchmark_rows = store.query(
        """
        SELECT source,execution_arm_id,project_id,orientation,operation,
               primary_artifact,accepted,verified_progress,quality,cost_amount,
               currency,latency_seconds,occurred_at
        FROM evaluation_events
        WHERE registry_eligible=1
          AND NOT EXISTS (
            SELECT 1 FROM evaluation_events replacement
            WHERE replacement.supersedes_event_id=evaluation_events.event_id
          )
        ORDER BY occurred_at,event_id
        """
    )

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(rows)
        if not count:
            return {
                "observations": 0,
                "accepted_rate": None,
                "verified_progress_mean": None,
                "quality_mean": None,
                "cost_mean": None,
                "latency_mean": None,
            }
        return {
            "observations": count,
            "accepted_rate": round(sum(int(row["accepted"]) for row in rows) / count, 6),
            "verified_progress_mean": round(sum(float(row["verified_progress"]) for row in rows) / count, 6),
            "quality_mean": round(sum(float(row["quality"]) for row in rows) / count, 6),
            "cost_mean": round(sum(float(row["cost_amount"]) for row in rows) / count, 6),
            "latency_mean": round(sum(float(row["latency_seconds"]) for row in rows) / count, 6),
            "currencies": sorted({str(row["currency"]) for row in rows}),
            "first_seen": rows[0]["occurred_at"],
            "last_seen": rows[-1]["occurred_at"],
        }

    source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    arm_operation_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in benchmark_rows:
        source_groups[str(row["source"])].append(row)
        arm_operation_groups[(str(row["execution_arm_id"]), str(row["operation"]), str(row["source"]))].append(row)

    pack_summaries: list[dict[str, Any]] = []
    for pack in load_packs():
        errors = validate_pack(pack)
        operations = set(str(item) for item in pack.get("operations", []))
        orientation = pack.get("orientation")
        artifact = pack.get("primary_artifact")
        matching = [
            row
            for row in benchmark_rows
            if row["operation"] in operations
            and (orientation is None or row["orientation"] == orientation)
            and (artifact is None or row["primary_artifact"] == artifact)
        ]
        pack_summaries.append(
            {
                "id": pack.get("id"),
                "name": pack.get("name"),
                "valid": not errors,
                "errors": errors,
                "orientation": orientation,
                "operations": sorted(operations),
                "primary_artifact": artifact,
                "evaluators": pack.get("evaluators", []),
                "metrics": pack.get("metrics", []),
                "summary": summarize(matching),
            }
        )

    pairwise_families = [
        str(row["task_family"])
        for row in store.query("SELECT DISTINCT task_family FROM judge_pairwise_observations ORDER BY task_family")
    ]
    benchmark = {
        **header,
        "source_summary": {name: summarize(rows) for name, rows in sorted(source_groups.items())},
        "arm_operation_source": [
            {
                "execution_arm_id": arm,
                "operation": operation,
                "source": source,
                **summarize(rows),
            }
            for (arm, operation, source), rows in sorted(arm_operation_groups.items())
        ],
        "packs": pack_summaries,
        "pairwise_rankings": [judge_tools.rank_pairwise(store, family) for family in pairwise_families],
        "note": "Derived from canonical eligible Evaluation Events and calibrated pairwise observations; pack membership and rankings are read-only analytical projections.",
    }
    atomic_json(export / "benchmark.json", benchmark)

    audit = {
        **header,
        "events": store.query(
            "SELECT event_id,occurred_at,project_id,task_id,work_unit_id,execution_arm_id,source,registry_eligible FROM evaluation_events ORDER BY occurred_at,event_id"
        ),
        "profile_scope_keys": sorted(profiles),
        "route_decision_ids": [row["decision_id"] for row in recent_routes],
    }
    atomic_json(export / "audit.json", audit)
    return {
        "routing": str(export / "routing-profiles.json"),
        "dossiers": str(export / "model-dossiers.json"),
        "dashboard": str(export / "dashboard-routing.json"),
        "benchmark": str(export / "benchmark.json"),
        "audit": str(export / "audit.json"),
        "event_count": event_count,
        "profile_count": len(profiles),
    }

