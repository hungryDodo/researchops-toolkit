from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from typing import Any

from ..common import now
from .store import IntelligenceStore

SEVERITY = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def rebuild_patterns(store: IntelligenceStore) -> dict[str, Any]:
    rows = store.query(
        """
        SELECT f.*,e.orientation,e.operation,e.occurred_at
        FROM failure_observations f
        JOIN evaluation_events e ON e.event_id=f.event_id
        WHERE e.registry_eligible=1
        ORDER BY e.occurred_at
        """
    )
    buckets: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["arm_id"], row["orientation"], row["operation"], row["code"], row["attribution"])
        buckets[key].append(row)
    generated: list[dict[str, Any]] = []
    with store.transaction() as connection:
        for (arm, orientation, operation, code, attribution), observations in buckets.items():
            count = len({row["event_id"] for row in observations})
            recent = len({row["event_id"] for row in observations[-10:]})
            severity = max((row["severity"] for row in observations), key=lambda value: SEVERITY.get(value, 0))
            pattern_id = "fp-" + hashlib.sha256("|".join((arm, orientation, operation, code, attribution)).encode()).hexdigest()[:16]
            human_confirmed = bool(store.one(
                "SELECT 1 FROM approvals WHERE approval_kind='failure-pattern-confirmation' AND subject_id=? LIMIT 1",
                (pattern_id,),
            ))
            status = "active" if count >= 2 or severity == "critical" or human_confirmed else "candidate"
            confidence = min(0.95, 0.35 + 0.15 * count + (0.15 if human_confirmed else 0.0))
            representatives = [
                {"event_id": row["event_id"], "description": row["description"], "evidence_ref": row["evidence_ref"]}
                for row in observations[-3:]
            ]
            item = {
                "pattern_id": pattern_id,
                "arm_id": arm,
                "orientation": orientation,
                "operation": operation,
                "code": code,
                "attribution": attribution,
                "status": status,
                "occurrence_count": count,
                "recent_occurrence_count": recent,
                "severity": severity,
                "confidence": round(confidence, 3),
                "first_seen": observations[0]["observed_at"],
                "last_seen": observations[-1]["observed_at"],
                "representative": representatives,
            }
            generated.append(item)
            connection.execute(
                """
                INSERT INTO failure_patterns(pattern_id,arm_id,orientation,operation,code,attribution,status,
                    occurrence_count,recent_occurrence_count,severity,confidence,first_seen,last_seen,representative_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(arm_id,orientation,operation,code,attribution) DO UPDATE SET
                    status=excluded.status,occurrence_count=excluded.occurrence_count,
                    recent_occurrence_count=excluded.recent_occurrence_count,severity=excluded.severity,
                    confidence=excluded.confidence,first_seen=excluded.first_seen,last_seen=excluded.last_seen,
                    representative_json=excluded.representative_json
                """,
                (
                    pattern_id, arm, orientation, operation, code, attribution, status, count, recent,
                    severity, confidence, observations[0]["observed_at"], observations[-1]["observed_at"],
                    json.dumps(representatives, ensure_ascii=False, sort_keys=True),
                ),
            )
    return {"schema_version": 1, "generated_at": now(), "observations": len(rows), "patterns": generated}


def approve_pattern(store: IntelligenceStore, pattern_id: str, approved_by: str) -> dict[str, Any]:
    """Human-confirm a candidate pattern without changing raw failure attribution."""
    row = store.one("SELECT * FROM failure_patterns WHERE pattern_id=?", (pattern_id,))
    if not row:
        raise ValueError(f"unknown failure pattern: {pattern_id}")
    approved_at = now()
    digest = hashlib.sha256(
        "|".join(
            str(row[key])
            for key in ("pattern_id", "arm_id", "orientation", "operation", "code", "attribution")
        ).encode()
    ).hexdigest()
    approval_id = f"approval-fp-{uuid.uuid4().hex[:12]}"
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO approvals(approval_id,approval_kind,subject_id,scope_json,approved_by,approved_at,one_use,content_hash,metadata_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                approval_id,
                "failure-pattern-confirmation",
                pattern_id,
                json.dumps(
                    {
                        "execution_arm_id": row["arm_id"],
                        "orientation": row["orientation"],
                        "operation": row["operation"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                approved_by,
                approved_at,
                0,
                digest,
                json.dumps({"code": row["code"], "attribution": row["attribution"]}, sort_keys=True),
            ),
        )
        connection.execute(
            "UPDATE failure_patterns SET status='active', confidence=MIN(0.95, confidence + 0.15) WHERE pattern_id=?",
            (pattern_id,),
        )
    return {
        "pattern_id": pattern_id,
        "status": "active",
        "human_confirmed": True,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "approval_id": approval_id,
    }
