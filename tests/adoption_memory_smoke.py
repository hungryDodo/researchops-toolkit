#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rops.intelligence import memory
from rops.intelligence.store import IntelligenceStore, SCHEMA_VERSION
from rops.project import bootstrap, inspect_project, project_status


def _process_group_alive(pgid: int) -> bool:
    if os.name != "posix":
        return False
    completed = subprocess.run(
        ["ps", "-eo", "pgid="],
        text=True,
        capture_output=True,
        timeout=2,
        check=False,
    )
    if completed.returncode == 0:
        return any(
            value.strip().isdigit() and int(value.strip()) == pgid
            for value in completed.stdout.splitlines()
        )
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def _wait_for_process_group_cleanup(pgid: int, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_group_alive(pgid):
            return True
        time.sleep(0.05)
    return not _process_group_alive(pgid)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_existing_project(root: Path) -> dict[str, str]:
    files = {
        "README.md": "# Existing project\n\nThis repository already has implementation and experimental results.\n",
        "pyproject.toml": '[project]\nname = "existing-project"\nversion = "0.6.0"\n',
        "src/runtime.py": "def execute(value: int) -> int:\n    return value + 1\n",
        "tests/test_runtime.py": "from src.runtime import execute\n\ndef test_execute():\n    assert execute(2) == 3\n",
        "experiments/profile.py": "print({'latency_ms': 10.0})\n",
        "results/profile.json": '{"latency_ms": 10.0}\n',
        "paper/main.tex": "\\documentclass{article}\\begin{document}Existing result.\\end{document}\n",
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return {relative: digest(root / relative) for relative in files}


def dashboard_round_trip(project: Path) -> dict[str, object]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT) + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "rops",
            "dashboard",
            "start",
            "--root",
            str(project),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    result: dict[str, object] = {}
    try:
        assert process.stdout is not None
        deadline = time.monotonic() + 10.0
        url = ""
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.2)
            if not ready:
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline().strip()
            if line.startswith("http://"):
                url = line
                break
        assert url, (process.stdout.read() if process.stdout else "", process.stderr.read() if process.stderr else "")
        with urllib.request.urlopen(url + "/view.json", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result.update({
            "served": True,
            "url_has_ephemeral_port": not url.endswith(":0"),
            "adoption_mode": payload.get("onboarding", {}).get("adoption_mode"),
            "phase": payload.get("status", {}).get("phase"),
            "memory_visible": bool(payload.get("memory", {}).get("available")),
            "routing_visible": "model_intelligence" in payload,
        })
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        result["process_group_cleaned"] = _wait_for_process_group_cleanup(process.pid)
    return result


def migration_round_trip(temp: Path) -> bool:
    project = temp / "legacy-memory-project"
    db = project / ".researchops" / "intelligence" / "state.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db)
    connection.executescript(
        """
        CREATE TABLE memory_items (
            memory_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            valid_from TEXT,
            valid_to TEXT,
            confidence REAL NOT NULL DEFAULT 1.0,
            provenance_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE VIRTUAL TABLE memory_fts USING fts5(memory_id UNINDEXED,title,body,tokenize='unicode61');
        INSERT INTO memory_items(memory_id,scope,kind,title,body,created_at,confidence,provenance_json)
        VALUES('legacy-1','project/legacy','decision','Legacy decision','Keep the compatible API','2026-01-01T00:00:00+00:00',0.9,'{}');
        INSERT INTO memory_fts(memory_id,title,body) VALUES('legacy-1','Legacy decision','Keep the compatible API');
        """
    )
    connection.commit()
    connection.close()
    store = IntelligenceStore(project)
    columns = {row["name"] for row in store.query("PRAGMA table_info(memory_items)")}
    row = store.one("SELECT layer,status,updated_at,content_hash FROM memory_items WHERE memory_id='legacy-1'")
    return bool(
        SCHEMA_VERSION >= 3
        and {"layer", "status", "updated_at", "salience", "content_hash", "metadata_json"}.issubset(columns)
        and row
        and row["layer"] == "semantic"
        and row["status"] == "active"
        and row["updated_at"]
        and row["content_hash"]
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="researchops-adoption-memory-smoke-") as temp_value:
        temp = Path(temp_value)
        project = temp / "existing-project"
        project.mkdir()
        original = create_existing_project(project)
        before_names = {path.name for path in project.iterdir()}

        preview = inspect_project(project)
        assert preview["adoption_mode"] == "adopt"
        assert not (project / ".researchops").exists()

        try:
            bootstrap(project, title="Existing Project", mode="new")
        except ValueError as exc:
            assert "refusing new-project initialization" in str(exc)
        else:
            raise AssertionError("new-project mode unexpectedly accepted a non-empty project")
        assert not (project / ".researchops").exists()

        bootstrap(project, title="Existing Project", mode="auto")
        after_names = {path.name for path in project.iterdir()}
        assert after_names - before_names == {".researchops"}
        assert all((project / relative).exists() and digest(project / relative) == expected for relative, expected in original.items())

        intake = json.loads((project / ".researchops/state/onboarding/current.json").read_text(encoding="utf-8"))
        assert intake["adoption_mode"] == "adopt"
        assert intake["requires_agent_review"] is True
        assert intake["inference"]["phase"] != "charter"

        store = IntelligenceStore(project)
        first = memory.add(
            store,
            scope="project/existing-project/task/debug",
            layer="semantic",
            kind="decision",
            title="Preserve API compatibility",
            body="Do not silently narrow or break the existing public API.",
            source_type="smoke",
            source_id="decision-1",
            confidence=0.8,
            salience=0.9,
            provenance={"path": "README.md", "observations": [{"case": "first"}]},
        )
        duplicate = memory.add(
            store,
            scope="project/existing-project/task/debug",
            layer="semantic",
            kind="decision",
            title="Preserve API compatibility",
            body="Do not silently narrow or break the existing public API.",
            source_type="smoke",
            source_id="decision-1",
            confidence=0.9,
            provenance={"observations": [{"case": "second"}]},
        )
        assert first["memory_id"] == duplicate["memory_id"] and duplicate["deduplicated"] is True

        replacement = memory.add(
            store,
            scope="project/existing-project/task/debug",
            layer="semantic",
            kind="decision",
            title="Preserve and version API compatibility",
            body="Preserve the public API and explicitly version unavoidable changes.",
            source_type="smoke",
            source_id="decision-2",
            provenance={"revision": 2},
        )
        memory.supersede(store, first["memory_id"], replacement["memory_id"], reason="updated decision")
        assert memory.get(store, first["memory_id"])["status"] == "superseded"

        memory.add(
            store,
            scope="project/other/task/debug",
            layer="semantic",
            kind="decision",
            title="Other project protocol",
            body="This unrelated project uses an incompatible private protocol.",
            provenance={"project": "other"},
        )
        hits = memory.search(store, "public API compatible protocol", scope="project/existing-project/task/debug", limit=10)
        assert hits and all(not hit["scope"].startswith("project/other") for hit in hits)
        assert all(hit.get("provenance") for hit in hits)
        bundle = memory.context_bundle(store, "public API compatibility", scope="project/existing-project/task/debug")
        assert bundle["items"] and bundle["authoritative"] is False

        sync_one = memory.sync_from_project(store)
        total_one = memory.status(store)["total"]
        sync_two = memory.sync_from_project(store)
        total_two = memory.status(store)["total"]
        assert total_one == total_two
        assert sync_two["deduplicated"] >= sync_one["deduplicated"]

        dashboard = dashboard_round_trip(project)
        assert dashboard["served"] and dashboard["adoption_mode"] == "adopt"
        assert dashboard["phase"] != "charter"
        assert dashboard["memory_visible"] and dashboard["routing_visible"]

        status = project_status(project)
        assert status["managed"] and status["adoption_mode"] == "adopt"
        assert status["dashboard"]["initialized"]

        migrated = migration_round_trip(temp)
        assert migrated

        print(json.dumps({
            "existing_project_inspected_before_write": True,
            "new_mode_refuses_existing_project": True,
            "non_destructive_adoption": True,
            "single_hidden_root": True,
            "dashboard_quick_start": dashboard,
            "memory_deduplicates": True,
            "memory_supersession": True,
            "memory_scope_isolation": True,
            "memory_provenance": True,
            "memory_context_bundle": True,
            "memory_sync_idempotent": True,
            "sqlite_v2_to_v3_migration": migrated,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
