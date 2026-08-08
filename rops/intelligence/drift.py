from __future__ import annotations

import json
import uuid
from typing import Any

from ..common import now
from .profiles import load_profiles, rebuild_profiles, scope_key
from .routing import endpoint_health
from .store import IntelligenceStore


def record_endpoint(store: IntelligenceStore, *, endpoint_id: str, success: bool, latency_seconds: float, arm_id: str | None = None, ttft_seconds: float | None = None, error_class: str | None = None, rate_limited: bool = False, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    observation_id = f"endpoint-{uuid.uuid4().hex[:16]}"
    item = {
        "observation_id": observation_id,
        "observed_at": now(),
        "endpoint_id": endpoint_id,
        "arm_id": arm_id,
        "success": bool(success),
        "latency_seconds": max(0.0, float(latency_seconds)),
        "ttft_seconds": None if ttft_seconds is None else max(0.0, float(ttft_seconds)),
        "error_class": error_class,
        "rate_limited": bool(rate_limited),
        "metadata": metadata or {},
    }
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO endpoint_observations(observation_id,observed_at,endpoint_id,arm_id,success,latency_seconds,ttft_seconds,error_class,rate_limited,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (observation_id, item["observed_at"], endpoint_id, arm_id, int(success), item["latency_seconds"], item["ttft_seconds"], error_class, int(rate_limited), json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)),
        )
    return item


def record_identity(store: IntelligenceStore, *, arm_id: str, endpoint_id: str | None, declared_identity: dict[str, Any], fingerprint: dict[str, Any]) -> dict[str, Any]:
    observation_id = f"identity-{uuid.uuid4().hex[:16]}"
    # Compare against the active deployment-epoch baseline when available.
    # Falling back to the first observed fingerprint makes a persistent silent
    # replacement remain visible on every canary run; comparing only with the
    # immediately previous response would detect it once and then incorrectly
    # treat the new behavior as stable.
    baseline_row = store.one(
        "SELECT fingerprint_json FROM deployment_epochs WHERE arm_base_id=? AND status='active' ORDER BY started_at DESC LIMIT 1",
        (arm_id,),
    ) or store.one(
        "SELECT fingerprint_json FROM identity_observations WHERE arm_id=? ORDER BY observed_at ASC,rowid ASC LIMIT 1",
        (arm_id,),
    )
    signals = 0
    if baseline_row:
        old = json.loads(baseline_row["fingerprint_json"])
        for key in sorted(set(old) | set(fingerprint)):
            if old.get(key) != fingerprint.get(key):
                signals += 1
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO identity_observations(observation_id,arm_id,endpoint_id,observed_at,declared_identity_json,fingerprint_json,signal_count) VALUES (?,?,?,?,?,?,?)",
            (observation_id, arm_id, endpoint_id, now(), json.dumps(declared_identity, ensure_ascii=False, sort_keys=True), json.dumps(fingerprint, ensure_ascii=False, sort_keys=True), signals),
        )
    return {"observation_id": observation_id, "arm_id": arm_id, "changed_signals": signals}


def detect(store: IntelligenceStore, *, arm_id: str, endpoint_id: str | None = None, operation: str | None = None) -> dict[str, Any]:
    if not store.query("SELECT 1 FROM profile_slices LIMIT 1"):
        rebuild_profiles(store)
    profiles = load_profiles(store)
    profile = profiles.get(scope_key(arm_id, None, None, operation)) if operation else profiles.get(scope_key(arm_id))
    health = endpoint_health(store, endpoint_id)
    identity_rows = store.query("SELECT signal_count,observed_at FROM identity_observations WHERE arm_id=? ORDER BY observed_at DESC,rowid DESC LIMIT 3", (arm_id,))
    identity_signal = len(identity_rows) >= 3 and all(int(row["signal_count"]) > 0 for row in identity_rows)
    outcome_signal = bool(profile and profile.get("drift_status") == "degrading")
    endpoint_signal = health.get("state") in {"degraded", "open-circuit"}
    signals = {
        "outcome_degradation": outcome_signal,
        "identity_fingerprint_change": identity_signal,
        "endpoint_degradation": endpoint_signal,
        "profile_recent_delta": ((profile or {}).get("recent_window") or {}).get("delta_from_lifetime"),
    }
    active_count = sum(bool(value) for key, value in signals.items() if key != "profile_recent_delta")
    if endpoint_signal and not outcome_signal and not identity_signal:
        drift_type, status = "endpoint-health", "confirmed"
    elif outcome_signal and (identity_signal or not endpoint_signal):
        drift_type, status = "black-box-behavior", "confirmed" if active_count >= 2 else "suspected"
    elif identity_signal:
        drift_type, status = "identity", "suspected"
    else:
        drift_type, status = "none", "stable"
    response = {
        "route_action": "avoid-temporarily" if status == "confirmed" and drift_type != "none" else "monitor",
        "run_anchor": status == "suspected",
        "create_new_epoch": status == "confirmed" and drift_type in {"black-box-behavior", "identity"},
        "claim": "observed behavior drift; underlying provider cause is unknown" if drift_type in {"black-box-behavior", "identity"} else None,
    }
    result = {"arm_id": arm_id, "endpoint_id": endpoint_id, "drift_type": drift_type, "status": status, "signals": signals, "response": response}
    if status != "stable":
        drift_id = "drift-" + uuid.uuid4().hex[:16]
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO drift_events(drift_id,arm_id,endpoint_id,detected_at,drift_type,status,signals_json,response_json) VALUES (?,?,?,?,?,?,?,?)",
                (drift_id, arm_id, endpoint_id, now(), drift_type, status, json.dumps(signals, ensure_ascii=False, sort_keys=True), json.dumps(response, ensure_ascii=False, sort_keys=True)),
            )
        result["drift_id"] = drift_id
    return result


def create_epoch(store: IntelligenceStore, *, arm_base_id: str, endpoint_id: str | None, declared_identity: dict[str, Any], fingerprint: dict[str, Any], status: str = "active") -> dict[str, Any]:
    count = int(store.scalar("SELECT COUNT(*) n FROM deployment_epochs WHERE arm_base_id=?", (arm_base_id,), 0))
    epoch_id = f"{arm_base_id}@epoch-{count + 1}"
    with store.transaction() as connection:
        connection.execute("UPDATE deployment_epochs SET status='closed',ended_at=? WHERE arm_base_id=? AND status='active'", (now(), arm_base_id))
        connection.execute(
            "INSERT INTO deployment_epochs(epoch_id,arm_base_id,endpoint_id,status,started_at,declared_identity_json,fingerprint_json) VALUES (?,?,?,?,?,?,?)",
            (epoch_id, arm_base_id, endpoint_id, status, now(), json.dumps(declared_identity, ensure_ascii=False, sort_keys=True), json.dumps(fingerprint, ensure_ascii=False, sort_keys=True)),
        )
    return {"epoch_id": epoch_id, "arm_base_id": arm_base_id, "status": status, "prior_transfer": "weak-only-after-anchor"}

# Compatibility names used by the public CLI and model gateway.  Keep these
# aliases until all downstream plugins have migrated to the shorter verbs.
record_endpoint_observation = record_endpoint
record_identity_observation = record_identity
