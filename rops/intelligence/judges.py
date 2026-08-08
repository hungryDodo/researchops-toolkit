from __future__ import annotations

import json
import math
import uuid
from typing import Any

from ..common import now
from .store import IntelligenceStore


def record(store: IntelligenceStore, *, judge_arm_id: str, task_family: str, agrees_with_reference: bool | None, position_consistent: bool | None, abstained: bool, confidence: float | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    observation_id = f"judge-{uuid.uuid4().hex[:16]}"
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO judge_observations(observation_id,judge_arm_id,task_family,observed_at,agrees_with_reference,position_consistent,abstained,confidence,metadata_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                observation_id, judge_arm_id, task_family, now(),
                None if agrees_with_reference is None else int(agrees_with_reference),
                None if position_consistent is None else int(position_consistent), int(abstained),
                None if confidence is None else max(0.0, min(1.0, float(confidence))),
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
    return {"observation_id": observation_id, "judge_arm_id": judge_arm_id, "task_family": task_family}


def profile(store: IntelligenceStore, judge_arm_id: str, task_family: str) -> dict[str, Any]:
    rows = store.query(
        "SELECT * FROM judge_observations WHERE judge_arm_id=? AND task_family=? ORDER BY observed_at",
        (judge_arm_id, task_family),
    )
    references = [row for row in rows if row["agrees_with_reference"] is not None]
    agreements = sum(int(row["agrees_with_reference"]) for row in references)
    reliability = (agreements + 1.0) / (len(references) + 2.0)
    positioned = [row for row in rows if row["position_consistent"] is not None]
    position_consistency = (sum(int(row["position_consistent"]) for row in positioned) + 1.0) / (len(positioned) + 2.0)
    abstention = sum(int(row["abstained"]) for row in rows) / len(rows) if rows else 0.0
    freshness = 1.0 if rows else 0.0
    weight = max(0.0, 2.0 * reliability - 1.0) * position_consistency * freshness
    return {
        "judge_arm_id": judge_arm_id,
        "task_family": task_family,
        "observations": len(rows),
        "reference_observations": len(references),
        "reliability_posterior_mean": round(reliability, 6),
        "position_consistency": round(position_consistency, 6),
        "abstention_rate": round(abstention, 6),
        "weight": round(weight, 6),
        "calibration_status": "uncalibrated" if len(references) < 5 else "calibrating" if len(references) < 12 else "calibrated",
    }


def cascade(store: IntelligenceStore, judge_arm_ids: list[str], task_family: str, *, high_risk: bool = False) -> dict[str, Any]:
    profiles = [profile(store, judge, task_family) for judge in judge_arm_ids]
    eligible = [item for item in profiles if item["calibration_status"] != "uncalibrated" and item["weight"] > 0]
    eligible.sort(key=lambda item: -item["weight"])
    if not eligible:
        return {"action": "human-or-deterministic-only", "judges": profiles, "reason": "no calibrated judge"}
    selected = eligible[:2 if high_risk else 1]
    return {
        "action": "judge-cascade",
        "primary": selected[0],
        "secondary": selected[1] if len(selected) > 1 else None,
        "escalate_when": ["low-margin", "position-inconsistent", "abstain", "unfamiliar-task", "high-risk-disagreement"],
        "judges": profiles,
    }


PAIRWISE_RESULTS = {"a", "b", "tie", "abstain"}


def record_pairwise(
    store: IntelligenceStore,
    *,
    judge_arm_id: str,
    task_family: str,
    item_a: str,
    item_b: str,
    first_result: str,
    swapped_result: str | None = None,
    evidence_package_hash: str | None = None,
    rubric_revision: str | None = None,
    prompt_revision: str | None = None,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a blind pairwise judgment in canonical A/B identity space.

    `swapped_result` is still expressed as the canonical winner (`a` or `b`),
    even though the display order was reversed.  This makes position
    consistency deterministic and avoids storing ambiguous left/right labels.
    """
    if not item_a or not item_b or item_a == item_b:
        raise ValueError("pairwise items must be distinct non-empty identifiers")
    if first_result not in PAIRWISE_RESULTS:
        raise ValueError(f"invalid pairwise result: {first_result}")
    if swapped_result is not None and swapped_result not in PAIRWISE_RESULTS:
        raise ValueError(f"invalid swapped pairwise result: {swapped_result}")
    consistent = None if swapped_result is None else first_result == swapped_result
    pairwise_id = f"pair-{uuid.uuid4().hex[:16]}"
    observed_at = now()
    payload = metadata or {}
    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO judge_pairwise_observations(
                pairwise_id,judge_arm_id,task_family,observed_at,item_a,item_b,
                first_result,swapped_result,position_consistent,evidence_package_hash,
                rubric_revision,prompt_revision,metadata_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                pairwise_id,
                judge_arm_id,
                task_family,
                observed_at,
                item_a,
                item_b,
                first_result,
                swapped_result,
                None if consistent is None else int(consistent),
                evidence_package_hash,
                rubric_revision,
                prompt_revision,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
    calibration = record(
        store,
        judge_arm_id=judge_arm_id,
        task_family=task_family,
        agrees_with_reference=None,
        position_consistent=consistent,
        abstained=first_result == "abstain" or swapped_result == "abstain",
        confidence=confidence,
        metadata={"pairwise_id": pairwise_id, **payload},
    )
    return {
        "pairwise_id": pairwise_id,
        "judge_observation_id": calibration["observation_id"],
        "judge_arm_id": judge_arm_id,
        "task_family": task_family,
        "item_a": item_a,
        "item_b": item_b,
        "first_result": first_result,
        "swapped_result": swapped_result,
        "position_consistent": consistent,
    }


def rank_pairwise(store: IntelligenceStore, task_family: str) -> dict[str, Any]:
    """Produce a reliability-weighted Bradley--Terry projection.

    Raw pairwise observations remain authoritative.  This deterministic
    ranking is a read-only projection and is intentionally conditioned on one
    task family rather than treated as a global model leaderboard.
    """
    rows = store.query(
        "SELECT * FROM judge_pairwise_observations WHERE task_family=? ORDER BY observed_at,pairwise_id",
        (task_family,),
    )
    judge_ids = sorted({str(row["judge_arm_id"]) for row in rows})
    judge_profiles = {judge: profile(store, judge, task_family) for judge in judge_ids}
    comparisons: list[tuple[str, str, float, float, str]] = []
    skipped = 0
    for row in rows:
        judge = str(row["judge_arm_id"])
        weight = float(judge_profiles[judge]["weight"])
        if weight <= 0:
            skipped += 1
            continue
        results = [str(row["first_result"])]
        if row["swapped_result"] is not None:
            results.append(str(row["swapped_result"]))
        usable = [result for result in results if result != "abstain"]
        if not usable:
            skipped += 1
            continue
        per_result_weight = weight / len(usable)
        for result in usable:
            outcome = 1.0 if result == "a" else 0.0 if result == "b" else 0.5
            comparisons.append((str(row["item_a"]), str(row["item_b"]), outcome, per_result_weight, judge))

    items = sorted({item for comparison in comparisons for item in comparison[:2]})
    if not comparisons:
        return {
            "task_family": task_family,
            "status": "insufficient-calibrated-evidence",
            "observations": len(rows),
            "usable_comparisons": 0,
            "skipped_observations": skipped,
            "ranking": [],
            "judges": list(judge_profiles.values()),
        }

    scores = {item: 0.0 for item in items}
    for iteration in range(200):
        gradients = {item: -0.01 * scores[item] for item in items}
        for item_a, item_b, outcome, weight, _judge in comparisons:
            delta = max(-30.0, min(30.0, scores[item_a] - scores[item_b]))
            probability_a = 1.0 / (1.0 + math.exp(-delta))
            gradient = weight * (outcome - probability_a)
            gradients[item_a] += gradient
            gradients[item_b] -= gradient
        learning_rate = 0.16 / (1.0 + iteration / 50.0)
        for item in items:
            scores[item] += learning_rate * gradients[item]
        center = sum(scores.values()) / len(scores)
        for item in items:
            scores[item] -= center

    exp_scores = {item: math.exp(max(-30.0, min(30.0, value))) for item, value in scores.items()}
    normalizer = sum(exp_scores.values()) or 1.0
    counts = {item: {"wins": 0.0, "losses": 0.0, "ties": 0.0, "weighted_comparisons": 0.0} for item in items}
    for item_a, item_b, outcome, weight, _judge in comparisons:
        counts[item_a]["weighted_comparisons"] += weight
        counts[item_b]["weighted_comparisons"] += weight
        if outcome == 1.0:
            counts[item_a]["wins"] += weight
            counts[item_b]["losses"] += weight
        elif outcome == 0.0:
            counts[item_b]["wins"] += weight
            counts[item_a]["losses"] += weight
        else:
            counts[item_a]["ties"] += weight
            counts[item_b]["ties"] += weight
    ranking = [
        {
            "item_id": item,
            "score": round(scores[item], 6),
            "normalized_strength": round(exp_scores[item] / normalizer, 6),
            **{key: round(value, 6) for key, value in counts[item].items()},
        }
        for item in sorted(items, key=lambda name: (-scores[name], name))
    ]
    return {
        "task_family": task_family,
        "status": "ranked",
        "observations": len(rows),
        "usable_comparisons": len(comparisons),
        "skipped_observations": skipped,
        "ranking": ranking,
        "judges": list(judge_profiles.values()),
        "method": "reliability-weighted-bradley-terry-v1",
        "note": "Task-family-conditioned projection; not a global model score.",
    }
