"""Proposal-only advisor for consequential ResearchOps Toolkit capabilities.

The broker may surface and persist proposals. It never invokes the target Skill,
runs tools on its behalf, or treats a proposal decision as the target Skill's
own operational approval.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from . import ROOT as SUITE_ROOT


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def registry(project_root: Path) -> dict[str, Any]:
    local = project_root / ".researchops/state/governance/capability-proposals.json"
    package = SUITE_ROOT / "config/capability-proposals.json"
    return load_json(local, load_json(package, {"capabilities": []}))


def state_path(project_root: Path) -> Path:
    return project_root / ".researchops/state/proposals/state.json"


def load_state(project_root: Path) -> dict[str, Any]:
    return load_json(state_path(project_root), {"schema_version": 2, "proposals": []})


def stable_id(capability_id: str, stage: str, fingerprint: str) -> str:
    raw = f"{capability_id}|{stage}|{fingerprint}".encode()
    return "PROP-" + hashlib.sha256(raw).hexdigest()[:12].upper()


def _fingerprint(stage: str, action_text: str, stage_entry: bool) -> str:
    source = f"stage-entry:{normalize(stage)}" if stage_entry else normalize(action_text)
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def suggest(project_root: Path, stage: str, action: str, signals: list[str] | None = None) -> list[dict[str, Any]]:
    """Return relevant proposals without executing or persisting them."""
    stage_norm = normalize(stage)
    text = " ".join([normalize(action)] + [normalize(x) for x in (signals or [])]).strip()
    current = load_state(project_root)
    existing = {item.get("id"): item for item in current.get("proposals", [])}
    proposals: list[dict[str, Any]] = []

    for capability in registry(project_root).get("capabilities", []):
        allowed_stages = {normalize(x) for x in capability.get("stages", [])}
        stage_allowed = not allowed_stages or stage_norm in allowed_stages
        pattern_hit = any(re.search(pattern, text, re.I) for pattern in capability.get("patterns", []))
        stage_entry = stage_norm in {normalize(x) for x in capability.get("auto_propose_stages", [])}
        explicit_hit = capability.get("activation") == "explicit_only" and pattern_hit

        if not ((pattern_hit and (stage_allowed or capability.get("allow_pattern_any_stage", False))) or stage_entry or explicit_hit):
            continue

        fingerprint = _fingerprint(stage_norm, text, stage_entry and not pattern_hit)
        proposal_id = stable_id(capability["id"], stage_norm, fingerprint)
        old = existing.get(proposal_id)
        if old and old.get("status") in {"dismissed", "snoozed", "completed"}:
            continue

        trigger = "stage-entry" if stage_entry and not pattern_hit else "planned-action"
        proposals.append(
            {
                "id": proposal_id,
                "capability_id": capability["id"],
                "skill": capability["skill"],
                "mode": capability.get("mode"),
                "stage": stage,
                "trigger": trigger,
                "action_fingerprint": fingerprint,
                "reason": capability.get("reason") or f"The current {trigger} matches capability '{capability['id']}'.",
                "benefit": capability.get("benefit"),
                "approval": capability.get("approval"),
                "activation": capability.get("activation"),
                "context_cost": capability.get("context_cost", "unknown"),
                "status": old.get("status", "recommended") if old else "recommended",
                "created_at": old.get("created_at", now()) if old else now(),
                "proposal_only": True,
                "execution_started": False,
            }
        )
    return proposals


def _sync_dashboard(project_root: Path, proposals: list[dict[str, Any]]) -> None:
    dashboard = project_root / ".researchops/state/dashboard/project.json"
    if not dashboard.exists():
        return
    data = load_json(dashboard, {})
    by_id = {item.get("id"): item for item in data.setdefault("capability_proposals", [])}
    for proposal in proposals:
        by_id[proposal["id"]] = proposal
    data["capability_proposals"] = sorted(by_id.values(), key=lambda x: (x.get("status") != "recommended", x.get("created_at", "")))
    data.setdefault("meta", {})["updated_at"] = now()
    atomic_write(dashboard, data)


def record(project_root: Path, proposals: list[dict[str, Any]]) -> dict[str, Any]:
    data = load_state(project_root)
    by_id = {item.get("id"): item for item in data.setdefault("proposals", [])}
    for proposal in proposals:
        by_id.setdefault(proposal["id"], proposal)
    data["schema_version"] = 2
    data["proposals"] = list(by_id.values())
    atomic_write(state_path(project_root), data)
    _sync_dashboard(project_root, data["proposals"])
    return data


def decide(project_root: Path, proposal_id: str, decision: str, note: str) -> dict[str, Any]:
    data = load_state(project_root)
    hit = next((item for item in data.get("proposals", []) if item.get("id") == proposal_id), None)
    if not hit:
        raise SystemExit("proposal not found")
    hit["status"] = decision
    hit["decision_at"] = now()
    hit["note"] = note
    # Approval authorizes loading/starting the specialist workflow only. The
    # specialist's own safety/operation gate remains mandatory.
    hit["specialist_execution_authorized"] = decision == "approved"
    hit["execution_started"] = False
    atomic_write(state_path(project_root), data)
    _sync_dashboard(project_root, data["proposals"])
    return hit


