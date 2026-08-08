#!/usr/bin/env python3
"""Emit one idempotent next action and proposal-only safeguards from project state."""
from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path

OWNER = {
    "charter": "research-program-orchestrator",
    "survey": "research-discovery",
    "related-work": "research-discovery",
    "route-triage": "research-route-evaluator",
    "feasibility": "experimental-research",
    "main-experiment": "experimental-research",
    "analysis": "experimental-research",
    "independent-validation": "research-validation",
    "writing": "research-writing",
    "revision": "research-writing",
    "red-team-review": "research-validation",
    "submission": "research-validation",
    "archive": "project-hygiene",
    "closeout": "project-hygiene",
}


def advisor_module():
    suite = Path(__file__).resolve().parents[3]
    if not (suite / "rops/proposals.py").exists():
        return None
    sys.path.insert(0, str(suite))
    from rops import proposals
    return proposals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out")
    parser.add_argument("--no-record-proposals", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    state = json.loads((root / ".researchops/state/dashboard/project.json").read_text(encoding="utf-8"))
    status = state.get("status", {})
    phase = status.get("phase", "charter")
    open_actions = sorted(
        [item for item in state.get("human_actions", []) if item.get("status", "open") == "open"],
        key=lambda item: ({"high": 0, "medium": 1, "low": 2}.get(item.get("priority", "medium"), 1), item.get("id", "")),
    )
    if open_actions and open_actions[0].get("priority") == "high":
        item = open_actions[0]
        action = {
            "kind": "human-gate",
            "id": item.get("id"),
            "public_label": item.get("public_label") or item.get("title"),
            "owner": "human",
            "phase": phase,
            "reason": "highest-priority open human action",
        }
    else:
        action = {
            "kind": "skill-action",
            "skill": OWNER.get(phase, "research-program-orchestrator"),
            "phase": phase,
            "next_gate": status.get("next_gate"),
            "objective": status.get("focus") or status.get("objective"),
            "reason": "stage owner for current on-disk phase",
        }

    action_text = " ".join(
        str(value)
        for value in (
            action.get("public_label"),
            action.get("objective"),
            status.get("blocking_uncertainty"),
            action.get("next_gate"),
        )
        if value
    )
    advisor = advisor_module()
    proposals = advisor.suggest(root, phase, action_text, [status.get("focus", ""), status.get("objective", "")]) if advisor else []
    if advisor and proposals and not args.no_record_proposals:
        advisor.record(root, proposals)

    output = {
        "schema_version": 3,
        "root": str(root),
        "state_updated_at": state.get("meta", {}).get("updated_at"),
        "next": action,
        "safeguard_proposals": proposals,
        "recorded_proposals": bool(proposals and not args.no_record_proposals),
        "executed_proposals": False,
    }
    text = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
