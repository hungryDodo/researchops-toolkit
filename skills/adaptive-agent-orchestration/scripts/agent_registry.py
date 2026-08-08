#!/usr/bin/env python3
"""Compatibility CLI backed by the canonical SQLite model-intelligence engine.

This file intentionally contains no aggregation or scoring implementation. The
single source of truth is ``rops.intelligence``; this wrapper preserves the
historic Skill command surface for existing projects and Harness prompts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Support direct execution from an installed Skill checkout.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rops.intelligence.events import record_event
from rops.intelligence.patterns import rebuild_patterns
from rops.intelligence.projections import rebuild_projections
from rops.intelligence.routing import recommend as core_recommend
from rops.intelligence.store import IntelligenceStore
from rops.models import sync_registry
from rops.project import _copy_governance_defaults


def read_json_arg(raw: str | None, path: str | None) -> dict[str, Any]:
    if bool(raw) == bool(path):
        raise SystemExit("provide exactly one JSON string or file")
    value = json.loads(raw) if raw else json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("expected a JSON object")
    return value


def init_project(root: Path, assets: Path | None = None, force: bool = False) -> dict[str, Any]:
    store = IntelligenceStore(root)
    _copy_governance_defaults(store.layout.governance)
    if force and assets:
        mapping = {"models.example.json": "models.json", "agents.example.json": "agents.json", "routing-policy.example.json": "routing-policy.json"}
        for source, destination in mapping.items():
            candidate = assets / source
            if candidate.exists():
                (store.layout.governance / destination).write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
    registry = sync_registry(store)
    projections = rebuild_projections(store)
    return {"directory": str(store.layout.governance), "database": str(store.path), "registry": registry, "projections": projections}


def recommend(root: Path, task: dict[str, Any], agent_name: str | None = None, write: bool = True) -> dict[str, Any]:
    store = IntelligenceStore(root)
    _copy_governance_defaults(store.layout.governance)
    sync_registry(store)
    task = {"project_id": root.name, **task}
    return core_recommend(store, task, agent_name=agent_name, write=write)


def record(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    store = IntelligenceStore(root)
    normalized = record_event(store, event, project_id=str(event.get("project_id") or root.name))
    patterns = rebuild_patterns(store)
    projections = rebuild_projections(store)
    return {"recorded": normalized, "patterns": patterns, "projections": projections}


def rebuild(root: Path) -> dict[str, Any]:
    store = IntelligenceStore(root)
    return {"patterns": rebuild_patterns(store), "projections": rebuild_projections(store)}


def summary(root: Path) -> dict[str, Any]:
    store = IntelligenceStore(root)
    rebuilt = rebuild(root)
    return {
        "schema_version": 2,
        "authority": "sqlite",
        "database": str(store.path),
        "model_count": int(store.scalar("SELECT COUNT(*) n FROM execution_arms", default=0)),
        "event_count": int(store.scalar("SELECT COUNT(*) n FROM evaluation_events", default=0)),
        "profile_count": int(store.scalar("SELECT COUNT(*) n FROM profile_slices", default=0)),
        **rebuilt,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init"); init.add_argument("--force", action="store_true"); init.add_argument("--assets", type=Path)
    route = sub.add_parser("recommend"); route.add_argument("--task-json"); route.add_argument("--task-file"); route.add_argument("--agent"); route.add_argument("--no-write", action="store_true")
    rec = sub.add_parser("record"); rec.add_argument("--event-json"); rec.add_argument("--event-file")
    sub.add_parser("rebuild")
    sub.add_parser("summary")
    args = parser.parse_args(); root = args.root.resolve()
    if args.cmd == "init": result = init_project(root, args.assets, args.force)
    elif args.cmd == "recommend": result = recommend(root, read_json_arg(args.task_json, args.task_file), args.agent, not args.no_write)
    elif args.cmd == "record": result = record(root, read_json_arg(args.event_json, args.event_file))
    elif args.cmd == "rebuild": result = rebuild(root)
    else: result = summary(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
