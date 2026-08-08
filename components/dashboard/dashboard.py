#!/usr/bin/env python3
"""Initialize, patch, validate, and serve the ResearchOps dashboard.

The editable project state and the model-intelligence database stay separate.
This component emits a read-only ``view.json`` that joins the editable project
projection with the generated routing projection.
"""
from __future__ import annotations

import argparse
import datetime as dt
import http.server
import json
import os
import shutil
import socketserver
import sqlite3
import tempfile
import webbrowser
from pathlib import Path
from typing import Any

VERSION = "2.1.0"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def home(root: str | Path) -> Path:
    return Path(root).resolve() / ".researchops"


def dash(root: str | Path) -> Path:
    return home(root) / "state" / "dashboard"


def state_path(root: str | Path) -> Path:
    return dash(root) / "project.json"


def view_path(root: str | Path) -> Path:
    return dash(root) / "view.json"


def intelligence_path(root: str | Path) -> Path:
    return home(root) / "intelligence" / "exports" / "dashboard-routing.json"


def intake_path(root: str | Path) -> Path:
    return home(root) / "state" / "onboarding" / "current.json"


def database_path(root: str | Path) -> Path:
    return home(root) / "intelligence" / "state.sqlite"


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def _memory_summary(root: str | Path) -> dict[str, Any]:
    path = database_path(root)
    if not path.exists():
        return {"available": False, "total": 0, "active": 0, "layers": [], "last_sync": None}
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
        connection.row_factory = sqlite3.Row
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "memory_items" not in tables:
            return {"available": False, "total": 0, "active": 0, "layers": [], "last_sync": None}
        total = int(connection.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0])
        active = int(connection.execute("SELECT COUNT(*) FROM memory_items WHERE status='active'").fetchone()[0])
        layers = [dict(row) for row in connection.execute(
            "SELECT layer,COUNT(*) count FROM memory_items WHERE status='active' GROUP BY layer ORDER BY layer"
        )]
        last_sync = None
        if "memory_sync_runs" in tables:
            row = connection.execute(
                "SELECT completed_at,summary_json FROM memory_sync_runs ORDER BY completed_at DESC LIMIT 1"
            ).fetchone()
            if row:
                last_sync = {"completed_at": row[0], "summary": json.loads(row[1] or "{}") }
        return {"available": True, "total": total, "active": active, "layers": layers, "last_sync": last_sync}
    except (sqlite3.Error, json.JSONDecodeError) as error:
        return {"available": False, "total": 0, "active": 0, "layers": [], "last_sync": None, "warning": str(error)}
    finally:
        try:
            connection.close()
        except (UnboundLocalError, sqlite3.Error):
            pass


def initial(title: str, intake: dict[str, Any] | None = None) -> dict[str, Any]:
    intake = intake or {}
    inference = intake.get("inference", {})
    mode = intake.get("adoption_mode", "new")
    phase = inference.get("phase", "charter")
    progress = int(inference.get("progress_estimate", 5))
    focus = inference.get("focus") or ("Project initialization" if mode == "new" else "Existing-project intake")
    blocking = inference.get("blocking_uncertainty") or "Project charter not approved"
    action_label = (
        "Approve project charter and resource envelope"
        if mode == "new"
        else "Confirm the existing-project intake, inferred phase, and next work unit"
    )
    return {
        "schema_version": 4,
        "meta": {"title": title, "suite_version": VERSION, "updated_at": now()},
        "onboarding": intake,
        "status": {
            "phase": phase,
            "health": "yellow" if blocking else "green",
            "objective": inference.get("focus") or "Define the project objective and evidence plan.",
            "focus": focus,
            "owner": "human+agent",
            "next_gate": inference.get("next_gate", "Gate 0"),
            "blocking_uncertainty": blocking,
            "progress": max(0, min(100, progress)),
        },
        "routes": [],
        "experiments": [],
        "agents": {"active_dispatches": 0, "completed": 0, "failed": 0, "pending_evaluation": 0, "profiles": []},
        "evidence": [],
        "storage": {"total_bytes": 0, "cleanup_candidate_bytes": 0, "large_files": 0, "last_scan": None, "worktrees": []},
        "hygiene": {"open_items": 0, "bare_public_ids": 0, "temporary_tests": 0, "last_scan": None, "items": []},
        "literature": {"screened": 0, "included": 0, "queries": 0, "items": []},
        "capability_proposals": [],
        "human_actions": [{"id": "HA-001", "public_label": action_label, "priority": "high", "owner": "human", "status": "open"}],
        "decisions": [],
        "risks": [],
        "logs": [{"at": now(), "actor": "dashboard", "event": "Project dashboard initialized"}],
    }


def upgrade_data(data: dict[str, Any]) -> dict[str, Any]:
    data["schema_version"] = 4
    data.setdefault("meta", {})["suite_version"] = VERSION
    data.setdefault("agents", {"active_dispatches": 0, "completed": 0, "failed": 0, "pending_evaluation": 0, "profiles": []})
    data.setdefault("storage", {"total_bytes": 0, "cleanup_candidate_bytes": 0, "large_files": 0, "last_scan": None, "worktrees": []})
    data.setdefault("hygiene", {"open_items": 0, "bare_public_ids": 0, "temporary_tests": 0, "last_scan": None, "items": []})
    data.setdefault("capability_proposals", [])
    data.setdefault("onboarding", {})
    for collection in ("routes", "experiments", "evidence", "human_actions", "decisions", "risks"):
        for item in data.setdefault(collection, []):
            if "public_label" not in item:
                item["public_label"] = item.get("name") or item.get("purpose") or item.get("claim") or item.get("title") or item.get("text") or item.get("id", "Unnamed")
    return data


def load(root: str | Path) -> dict[str, Any]:
    return json.loads(state_path(root).read_text(encoding="utf-8"))


def _atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def save(root: str | Path, data: dict[str, Any]) -> Path:
    path = state_path(root)
    data.setdefault("meta", {})["updated_at"] = now()
    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
    _atomic(path, data)
    build_view(root)
    return path


def build_view(root: str | Path) -> dict[str, Any]:
    data = upgrade_data(load(root))
    intake = _load_json(intake_path(root), data.get("onboarding", {}))
    if intake:
        data["onboarding"] = intake
        inference = intake.get("inference", {})
        # Preserve explicit user/agent transitions. Intake only seeds fields
        # that are still empty or marked as initial/inferred.
        if not data.get("status", {}).get("phase"):
            data.setdefault("status", {})["phase"] = inference.get("phase", "unknown")
    intelligence: dict[str, Any] = {
        "available": False,
        "recent_decisions": [],
        "recent_outcomes": [],
        "model_summary": [],
        "warmup": [],
        "endpoint_health": [],
        "active_failure_patterns": [],
        "active_mitigations": [],
    }
    path = intelligence_path(root)
    if path.exists():
        try:
            projection = json.loads(path.read_text(encoding="utf-8"))
            intelligence = {"available": True, "generated_at": projection.get("generated_at"), **projection.get("routing", {})}
        except (OSError, json.JSONDecodeError):
            intelligence["warning"] = "routing projection could not be loaded"
    data["model_intelligence"] = intelligence
    data["memory"] = _memory_summary(root)
    data["view"] = {
        "generated": True,
        "do_not_edit": True,
        "generated_at": now(),
        "sources": [str(state_path(root)), str(path), str(intake_path(root)), str(database_path(root))],
    }
    _atomic(view_path(root), data)
    return data


def parts(path: str) -> list[str | int]:
    return [int(item) if item.isdigit() else item for item in path.split(".") if item]


def get_parent(data: dict[str, Any], path: str, create: bool = False) -> tuple[Any, str | int]:
    keys = parts(path)
    current: Any = data
    for key in keys[:-1]:
        if isinstance(key, int):
            current = current[key]
        else:
            if create and key not in current:
                current[key] = {}
            current = current[key]
    return current, keys[-1]


def parse(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = ("schema_version", "meta", "status", "routes", "experiments", "agents", "evidence", "storage", "hygiene", "literature", "capability_proposals", "human_actions", "decisions", "risks", "logs")
    for key in required:
        if key not in data:
            errors.append(f"missing {key}")
    for collection in ("routes", "experiments", "evidence", "human_actions", "decisions", "risks"):
        seen: set[str] = set()
        for item in data.get(collection, []):
            if not isinstance(item, dict):
                errors.append(f"{collection}: non-object")
                continue
            identifier = item.get("id")
            if not identifier:
                errors.append(f"{collection}: missing internal id")
            elif identifier in seen:
                errors.append(f"{collection}: duplicate id {identifier}")
            seen.add(identifier)
            if not any(item.get(field) for field in ("public_label", "name", "title", "purpose", "claim", "text")):
                errors.append(f"{collection}:{identifier}: missing semantic/public label")
    return errors


def copy_assets(root: str | Path) -> None:
    script_dir = Path(__file__).resolve().parent
    source_root = script_dir / "web" if (script_dir / "web").exists() else script_dir
    output = dash(root)
    output.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "styles.css", "app.js"):
        source, target = source_root / name, output / name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
    script_target = output / "dashboard.py"
    if Path(__file__).resolve() != script_target.resolve():
        shutil.copy2(Path(__file__).resolve(), script_target)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init"); init.add_argument("--root", default="."); init.add_argument("--title", required=True); init.add_argument("--intake-file"); init.add_argument("--force", action="store_true")
    upgrade = sub.add_parser("upgrade"); upgrade.add_argument("--root", default=".")
    for command in ("set", "append"):
        entry = sub.add_parser(command); entry.add_argument("--root", default="."); entry.add_argument("--path", required=True); entry.add_argument("--value", required=True)
    upsert = sub.add_parser("upsert"); upsert.add_argument("--root", default="."); upsert.add_argument("--path", required=True); upsert.add_argument("--id", required=True); upsert.add_argument("--value", required=True)
    transition = sub.add_parser("transition"); transition.add_argument("--root", default="."); transition.add_argument("--phase", required=True); transition.add_argument("--gate", required=True); transition.add_argument("--actor", default="agent")
    validate_parser = sub.add_parser("validate"); validate_parser.add_argument("--root", default=".")
    sync = sub.add_parser("sync"); sync.add_argument("--root", default=".")
    for command in ("serve", "start"):
        serve = sub.add_parser(command); serve.add_argument("--root", default="."); serve.add_argument("--host", default="127.0.0.1"); serve.add_argument("--port", type=int, default=8765); serve.add_argument("--open", action="store_true")
    args = parser.parse_args()
    path = state_path(args.root)
    if args.cmd == "init":
        if path.exists() and not args.force:
            raise SystemExit(f"exists: {path}")
        copy_assets(args.root)
        intake = _load_json(Path(args.intake_file), {}) if args.intake_file else _load_json(intake_path(args.root), {})
        _atomic(path, initial(args.title, intake))
        build_view(args.root)
        print(path)
        return
    if not path.exists():
        raise SystemExit("dashboard not initialized")
    if args.cmd == "upgrade":
        copy_assets(args.root); save(args.root, upgrade_data(load(args.root))); print(path); return
    if args.cmd == "validate":
        errors = validate(load(args.root)); print("\n".join(errors) if errors else "dashboard valid"); raise SystemExit(1 if errors else 0)
    if args.cmd == "sync":
        build_view(args.root); print(view_path(args.root)); return
    if args.cmd in {"serve", "start"}:
        copy_assets(args.root); build_view(args.root)
        root_value = str(Path(args.root).resolve())
        directory = str(dash(args.root))

        class LiveDashboardHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *handler_args: Any, **handler_kwargs: Any):
                super().__init__(*handler_args, directory=directory, **handler_kwargs)

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                if self.path.split("?", 1)[0] in {"/", "/index.html", "/view.json"}:
                    try:
                        build_view(root_value)
                    except Exception as error:  # dashboard must remain inspectable
                        print(f"dashboard refresh warning: {error}")
                super().do_GET()

            def log_message(self, format: str, *values: Any) -> None:
                print("dashboard:", format % values)

        class DashboardServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        with DashboardServer((args.host, args.port), LiveDashboardHandler) as server:
            actual_port = int(server.server_address[1])
            url = f"http://{args.host}:{actual_port}"
            print(url, flush=True)
            if args.open:
                webbrowser.open(url)
            server.serve_forever()
    data = upgrade_data(load(args.root))
    if args.cmd == "set":
        parent, key = get_parent(data, args.path, True); parent[key] = parse(args.value)
    elif args.cmd == "append":
        parent, key = get_parent(data, args.path, True); parent.setdefault(key, []).append(parse(args.value))
    elif args.cmd == "upsert":
        parent, key = get_parent(data, args.path, True); collection = parent.setdefault(key, []); item = parse(args.value)
        if not isinstance(item, dict):
            raise SystemExit("--value must be JSON object")
        item["id"] = args.id
        hit = next((index for index, current in enumerate(collection) if current.get("id") == args.id), None)
        if hit is None: collection.append(item)
        else: collection[hit] = {**collection[hit], **item}
    elif args.cmd == "transition":
        previous = data["status"].get("phase"); data["status"]["phase"] = args.phase; data["status"]["next_gate"] = args.gate
        data["logs"].insert(0, {"at": now(), "actor": args.actor, "event": f"Phase {previous} → {args.phase}", "detail": args.gate})
    errors = validate(data)
    if errors:
        raise SystemExit("invalid patch: " + "; ".join(errors))
    print(save(args.root, data))


if __name__ == "__main__":
    main()
