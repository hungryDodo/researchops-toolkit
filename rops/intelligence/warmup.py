from __future__ import annotations

import json
from typing import Any

from ..common import now
from .store import IntelligenceStore


def _task(row: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(row["task_json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return {}


def initialize_transfer(
    store: IntelligenceStore,
    *,
    project_id: str,
    arm_id: str,
    operation: str,
    primary_artifact: str = "unknown",
    acceptance_profile: str | None = None,
    mode: str = "conservative",
    persist: bool = True,
) -> dict[str, Any]:
    """Create an explainable, capped project prior.

    Unknown project details are valid.  Transfer is based only on fields known
    for the current work unit, never on an invented project-wide similarity.
    """

    if mode not in {"zero", "conservative", "normal"}:
        raise ValueError("mode must be zero, conservative, or normal")
    candidates = store.query(
        """
        SELECT project_id,accepted,operation,primary_artifact,task_json
        FROM evaluation_events
        WHERE registry_eligible=1 AND execution_arm_id=? AND project_id<>? AND operation=?
        ORDER BY occurred_at DESC LIMIT 100
        """,
        (arm_id, project_id, operation),
    )
    rationale: list[dict[str, Any]] = []
    inherited_n = 0.0
    accepted_weight = 0.0
    if mode != "zero" and candidates:
        for row in candidates:
            weight = 0.25  # same operation only; deliberately weak
            reasons = ["same-operation"]
            if primary_artifact != "unknown" and row["primary_artifact"] == primary_artifact:
                weight += 0.25
                reasons.append("same-primary-artifact")
            task = _task(row)
            if acceptance_profile and task.get("acceptance_profile") == acceptance_profile:
                weight += 0.50
                reasons.append("same-acceptance-profile")
            if mode == "normal":
                weight *= 1.25
            cap = 2.0 if mode == "conservative" else 4.0
            contribution = min(weight, max(0.0, cap - inherited_n))
            if contribution <= 0:
                break
            inherited_n += contribution
            accepted_weight += contribution * int(row["accepted"])
            if len(rationale) < 5:
                rationale.append({"source_project": row["project_id"], "weight": round(contribution, 3), "reasons": reasons})
            if inherited_n >= cap:
                break
    success_mean = accepted_weight / inherited_n if inherited_n else None
    state = {
        "project_id": project_id,
        "arm_id": arm_id,
        "operation": operation,
        "initialization": "zero" if inherited_n == 0 else "soft-transfer",
        "inherited_equivalent_observations": round(inherited_n, 3),
        "inherited_success_mean": None if success_mean is None else round(success_mean, 6),
        "transfer_status": "not-used" if inherited_n == 0 else "active",
        "rationale": rationale,
        "unknown_fields_do_not_block": True,
        "updated_at": now(),
    }
    if persist:
        with store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO warmup_states(project_id,arm_id,operation,initialization,
                    inherited_equivalent_observations,inherited_success_mean,transfer_status,
                    rationale_json,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(project_id,arm_id,operation) DO UPDATE SET
                    initialization=excluded.initialization,
                    inherited_equivalent_observations=excluded.inherited_equivalent_observations,
                    inherited_success_mean=excluded.inherited_success_mean,
                    transfer_status=excluded.transfer_status,
                    rationale_json=excluded.rationale_json,
                    updated_at=excluded.updated_at
                """,
                (
                    project_id, arm_id, operation, state["initialization"], inherited_n,
                    success_mean, state["transfer_status"], json.dumps(rationale, ensure_ascii=False), state["updated_at"],
                ),
            )
    return state


def warmup_state(store: IntelligenceStore, project_id: str, arm_id: str, operation: str, *, persist: bool = True) -> dict[str, Any]:
    prior = store.one(
        "SELECT * FROM warmup_states WHERE project_id=? AND arm_id=? AND operation=?",
        (project_id, arm_id, operation),
    )
    rows = store.query(
        """
        SELECT accepted,quality,verified_progress FROM evaluation_events
        WHERE registry_eligible=1 AND project_id=? AND execution_arm_id=? AND operation=?
        ORDER BY occurred_at
        """,
        (project_id, arm_id, operation),
    )
    local_n = len(rows)
    local_accepted = sum(int(row["accepted"]) for row in rows)
    inherited_n = float((prior or {}).get("inherited_equivalent_observations", 0.0))
    inherited_mean = (prior or {}).get("inherited_success_mean")
    transfer_status = str((prior or {}).get("transfer_status", "not-initialized"))
    negative_transfer = False
    if local_n >= 3 and inherited_n and inherited_mean is not None:
        local_mean = (local_accepted + 1.0) / (local_n + 2.0)
        if abs(float(inherited_mean) - local_mean) >= 0.35:
            inherited_n = 0.0
            transfer_status = "rejected-negative-transfer"
            negative_transfer = True
            if persist:
                with store.transaction() as connection:
                    connection.execute(
                        "UPDATE warmup_states SET inherited_equivalent_observations=0,transfer_status=?,updated_at=? WHERE project_id=? AND arm_id=? AND operation=?",
                        (transfer_status, now(), project_id, arm_id, operation),
                    )
    target_local = 5
    rootedness = local_n / (local_n + inherited_n) if (local_n + inherited_n) else 0.0
    calibration = min(1.0, (local_n + min(inherited_n, 2.0)) / target_local)
    status = "cold" if local_n == 0 and inherited_n == 0 else "warming" if calibration < 0.6 else "project-calibrated" if local_n < target_local else "stable"
    return {
        "project_id": project_id,
        "execution_arm_id": arm_id,
        "operation": operation,
        "status": status,
        "local_observations": local_n,
        "local_accepted": local_accepted,
        "inherited_equivalent_observations": round(inherited_n, 3),
        "rootedness": round(rootedness, 3),
        "calibration_progress": round(calibration, 3),
        "estimated_remaining_local_episodes": max(0, target_local - local_n),
        "initialization": (prior or {}).get("initialization", "zero"),
        "transfer_status": transfer_status,
        "negative_transfer_guard_triggered": negative_transfer,
        "rationale": json.loads((prior or {}).get("rationale_json", "[]")),
    }


def all_warmup_states(store: IntelligenceStore) -> list[dict[str, Any]]:
    combinations = store.query(
        "SELECT DISTINCT project_id,execution_arm_id arm_id,operation FROM evaluation_events ORDER BY project_id,arm_id,operation"
    )
    persisted = store.query("SELECT project_id,arm_id,operation FROM warmup_states")
    keys = {(row["project_id"], row["arm_id"], row["operation"]) for row in combinations + persisted}
    return [warmup_state(store, *key) for key in sorted(keys)]
