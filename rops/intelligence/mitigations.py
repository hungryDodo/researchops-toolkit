from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from ..common import now
from .store import IntelligenceStore

TYPES = {
    "prompt_overlay", "mandatory_checklist", "structured_output", "deterministic_verifier",
    "second_pass_review", "shadow_reviewer", "model_escalation", "tool_restriction", "route_exclusion",
}
STATUSES = {"proposed", "approved", "canary", "active", "paused", "retired"}
TRANSITIONS = {
    "proposed": {"approved", "retired"},
    "approved": {"canary", "active", "paused", "retired"},
    "canary": {"active", "paused", "retired"},
    "active": {"paused", "retired"},
    "paused": {"approved", "canary", "active", "retired"},
    "retired": set(),
}


def propose(store: IntelligenceStore, mitigation_type: str, scope: dict[str, Any], content: dict[str, Any], *, pattern_ids: list[str] | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if mitigation_type not in TYPES:
        raise ValueError(f"unsupported mitigation type: {mitigation_type}")
    mitigation_id = f"mit-{uuid.uuid4().hex[:16]}"
    item = {
        "mitigation_id": mitigation_id,
        "mitigation_type": mitigation_type,
        "status": "proposed",
        "scope": scope,
        "content": content,
        "revision": 1,
        "proposed_at": now(),
        "metadata": metadata or {},
    }
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO mitigations(mitigation_id,mitigation_type,status,scope_json,content_json,revision,proposed_at,metadata_json) VALUES (?,?,?,?,?,?,?,?)",
            (
                mitigation_id, mitigation_type, "proposed", json.dumps(scope, ensure_ascii=False, sort_keys=True),
                json.dumps(content, ensure_ascii=False, sort_keys=True), 1, item["proposed_at"],
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        for pattern_id in pattern_ids or []:
            connection.execute("INSERT OR IGNORE INTO mitigation_pattern_links(mitigation_id,pattern_id) VALUES (?,?)", (mitigation_id, pattern_id))
    return item


def approve(store: IntelligenceStore, mitigation_id: str, approved_by: str, *, content_hash: str | None = None) -> dict[str, Any]:
    row = store.one("SELECT * FROM mitigations WHERE mitigation_id=?", (mitigation_id,))
    if not row:
        raise ValueError(f"unknown mitigation: {mitigation_id}")
    if row["status"] not in {"proposed", "paused"}:
        raise ValueError(f"mitigation cannot be approved from {row['status']}")
    digest = content_hash or hashlib.sha256((row["scope_json"] + row["content_json"] + str(row["revision"])).encode()).hexdigest()
    approval_id = f"approval-mit-{uuid.uuid4().hex[:12]}"
    approved_at = now()
    with store.transaction() as connection:
        connection.execute("UPDATE mitigations SET status='approved',approved_at=?,approved_by=? WHERE mitigation_id=?", (approved_at, approved_by, mitigation_id))
        connection.execute(
            "INSERT INTO approvals(approval_id,approval_kind,subject_id,scope_json,approved_by,approved_at,one_use,content_hash,metadata_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (approval_id, "prompt-mitigation", mitigation_id, row["scope_json"], approved_by, approved_at, 0, digest, "{}"),
        )
    return {"mitigation_id": mitigation_id, "status": "approved", "approved_by": approved_by, "approved_at": approved_at, "approval_id": approval_id, "high_risk_operation_approval_granted": False}


def set_status(store: IntelligenceStore, mitigation_id: str, status: str) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"invalid mitigation status: {status}")
    row = store.one("SELECT * FROM mitigations WHERE mitigation_id=?", (mitigation_id,))
    if not row:
        raise ValueError(f"unknown mitigation: {mitigation_id}")
    current = str(row["status"])
    if status == current:
        return {"mitigation_id": mitigation_id, "status": status, "changed": False}
    if status not in TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid mitigation transition: {current} -> {status}")
    if status in {"canary", "active"} and not row["approved_at"]:
        raise ValueError("mitigation must receive explicit human approval before canary or active use")
    with store.transaction() as connection:
        connection.execute("UPDATE mitigations SET status=? WHERE mitigation_id=?", (status, mitigation_id))
    return {"mitigation_id": mitigation_id, "previous_status": current, "status": status, "changed": True}


def applicable(store: IntelligenceStore, *, arm_id: str, project_id: str, operation: str, task_id: str | None = None) -> list[dict[str, Any]]:
    rows = store.json_rows(
        "SELECT * FROM mitigations WHERE status IN ('canary','active') ORDER BY revision,proposed_at",
        json_columns=("scope_json", "content_json", "metadata_json"),
    )
    selected = []
    for row in rows:
        scope = row["scope_json"]
        checks = {
            "execution_arm_id": arm_id,
            "project_id": project_id,
            "operation": operation,
            "task_id": task_id,
        }
        if all(scope.get(key) in {None, value} for key, value in checks.items()):
            selected.append(row)
    return selected


def compile_prompt(store: IntelligenceStore, *, arm_id: str, project_id: str, operation: str, task_contract: str, role: str = "", task_id: str | None = None, token_budget_chars: int = 6000) -> dict[str, Any]:
    mitigations = applicable(store, arm_id=arm_id, project_id=project_id, operation=operation, task_id=task_id)
    prompt_parts = []
    applied = []
    for row in mitigations:
        if row["mitigation_type"] != "prompt_overlay":
            continue
        instruction = str(row["content_json"].get("instruction", "")).strip()
        if not instruction:
            continue
        candidate = "\n\n".join(prompt_parts + [instruction])
        if len(candidate) > token_budget_chars:
            continue
        prompt_parts.append(instruction)
        applied.append({"mitigation_id": row["mitigation_id"], "revision": row["revision"]})
    compiled = "\n\n".join(part for part in [role.strip(), *prompt_parts, "Frozen task contract:\n" + task_contract.strip()] if part)
    return {
        "compiled_prompt": compiled,
        "compiled_prompt_hash": hashlib.sha256(compiled.encode()).hexdigest(),
        "applied_mitigations": applied,
        "priority": ["platform-safety", "project-governance", "behavior-packs", "agent-role", "approved-mitigations", "frozen-task-contract", "user-content"],
        "high_risk_operation_approval": "separate-required",
    }
