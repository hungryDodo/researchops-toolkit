#!/usr/bin/env python3
"""End-to-end smoke test for routing, evaluation, hygiene, cleanup, and adapters."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get("PYTHON", "python3")


def run(*args: str, cwd: Path | None = None, capture: bool = True, expect: int = 0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(list(args), cwd=cwd or ROOT, text=True, capture_output=capture)
    if completed.returncode != expect:
        raise RuntimeError(
            f"command failed ({completed.returncode}, expected {expect}): {' '.join(args)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def tool(skill: str, script: str) -> str:
    return str(ROOT / "skills" / skill / "scripts" / script)


def project_test(base: Path) -> dict[str, Any]:
    project = base / "project"
    project.mkdir()
    run("git", "init", "-q", "-b", "main", cwd=project)
    run("git", "config", "user.email", "release-test@example.com", cwd=project)
    run("git", "config", "user.name", "Release Test", cwd=project)
    run(PYTHON, "-m", "rops", "bootstrap", str(project), "--title", "Release Validation", "--upgrade")

    (project / ".gitignore").write_text("logs/\n.research/runs/*/raw/\n", encoding="utf-8")
    for directory in (project / ".research/runs/E01/raw", project / "logs", project / "tests", project / "docs"):
        directory.mkdir(parents=True, exist_ok=True)
    raw = project / ".research/runs/E01/raw/samples.bin"
    log = project / "logs/old.log"
    raw.write_text("raw samples\n", encoding="utf-8")
    log.write_text("temporary log\n", encoding="utf-8")
    (project / "tests/test_smoke_old.py").write_text("def test_smoke_old():\n    assert True\n", encoding="utf-8")
    (project / "docs/results.md").write_text("We compare B1 with E01 and A2.\n", encoding="utf-8")
    (project / "main.py").write_text('print("ok")\n', encoding="utf-8")

    hygiene = project / ".research/hygiene"
    write_json(hygiene / "naming-registry.json", {
        "schema_version": 1,
        "identifiers": [
            {"internal_id": "B1", "public_label": "local execution baseline", "semantic_slug": "local-execution-baseline"},
            {"internal_id": "E01", "public_label": "streaming overlap method", "semantic_slug": "streaming-overlap-method"},
            {"internal_id": "A2", "public_label": "without overlap ablation", "semantic_slug": "without-overlap-ablation"},
        ],
    })
    write_json(hygiene / "test-inventory.json", {
        "schema_version": 1,
        "tests": [{
            "path": "tests/test_smoke_old.py",
            "status": "retired",
            "replacement": "main.py",
            "cleanup_approved": True,
            "approved_by": "release-test",
        }],
    })
    write_json(hygiene / "asset-registry.json", {
        "schema_version": 1,
        "assets": [{
            "path": ".research/runs/E01/raw/samples.bin",
            "class": "raw-reproducible",
            "run_status": "complete",
            "derived_status": "verified",
            "derived_artifacts": ["docs/results.md"],
            "regeneration_command": "python main.py",
            "environment_manifest": "main.py",
            "cleanup_approved": True,
            "approved_by": "release-test",
        }],
    })
    run("git", "add", ".", cwd=project)
    run("git", "commit", "-qm", "initial", cwd=project)
    old = 1_600_000_000
    os.utime(raw, (old, old))
    os.utime(log, (old, old))
    archive_candidate = project / "scratch/archive_me.txt"
    obsolete_candidate = project / "scratch/obsolete_old.bak"
    archive_candidate.parent.mkdir(parents=True, exist_ok=True)
    archive_candidate.write_text("restore me\n", encoding="utf-8")
    obsolete_candidate.write_text("obsolete\n", encoding="utf-8")
    os.utime(obsolete_candidate, (old, old))

    run(PYTHON, "-m", "rops", "install", "--target", "all", "--scope", "project", "--project", str(project), "--mode", "link", "--skills", "all", "--with-agents")
    native_files = [
        project / ".codex/agents/research_scout.toml",
        project / ".claude/agents/research_scout.md",
        project / ".gemini/agents/research_scout.md",
    ]
    assert all(path.is_file() for path in native_files)
    bundle_project = base / "bundle-project"
    bundle_project.mkdir()
    run(PYTHON, "-m", "rops", "install", "--target", "portable", "--scope", "project", "--project", str(bundle_project), "--mode", "copy", "--bundle", "discovery")
    assert len(list((bundle_project / ".agent-skills/skills").iterdir())) == 4

    next_step = read_json_from_stdout(run(PYTHON, tool("research-program-orchestrator", "next_step.py"), "--root", str(project), capture=True).stdout)
    assert next_step["next"]["kind"] == "human-gate"
    assert next_step["executed_proposals"] is False

    proposal = read_json_from_stdout(run(
        PYTHON, "-m", "rops", "proposal", "--root", str(project), "propose",
        "--stage", "analysis", "--action", "Remove raw traces and free disk after analysis", "--write", capture=True,
    ).stdout)
    assert proposal["executed"] is False
    assert any(x["skill"] == "project-hygiene" for x in proposal["proposals"])
    proposal_id = next(x["id"] for x in proposal["proposals"] if x["skill"] == "project-hygiene")
    decision = read_json_from_stdout(run(
        PYTHON, "-m", "rops", "proposal", "--root", str(project), "decide",
        "--id", proposal_id, "--decision", "snoozed", "--note", "wait until current analysis completes", capture=True,
    ).stdout)
    assert decision["status"] == "snoozed"

    routed = read_json_from_stdout(run(
        PYTHON, tool("adaptive-agent-orchestration", "agent_registry.py"), "--root", str(project), "recommend",
        "--task-json", json.dumps({
            "stage": "survey", "type": "extraction", "risk": "low", "privacy": "internal",
            "mutability": "read-only", "required_capabilities": ["extraction"], "deterministic_tests": True,
        }), "--agent", "research_scout", "--no-write", capture=True,
    ).stdout)
    assert routed["primary"]["model_id"]

    contract = base / "contract.json"
    result = base / "result.json"
    verifier = base / "verifier.json"
    evaluation_missing = base / "evaluation-missing.json"
    evaluation = base / "evaluation.json"
    event = base / "event.json"
    write_json(contract, {
        "task_id": "task-01",
        "task": {"stage": "survey", "type": "extraction", "risk": "medium", "privacy": "internal", "mutability": "read-only"},
        "minimum_verified_quality": 0.8,
        "requires_independent_verifier": True,
        "acceptance_tests": [
            {"name": "status complete", "type": "json_path_equals", "source": "result", "json_path": "status", "expected": "complete", "required": True, "weight": 1.0},
            {"name": "artifact exists", "type": "file_exists", "path": "docs/results.md", "required": True, "weight": 1.0},
        ],
    })
    write_json(result, {"model_id": routed["primary"]["model_id"], "agent_revision": "research_scout@1", "status": "complete", "latency_seconds": 3.2, "cost": 0.01, "artifacts": ["docs/results.md"]})
    write_json(verifier, {"verifier_id": "independent-reviewer@1", "model_id": "strong-verifier", "independent": True, "confidence": 0.9, "disposition": "accepted", "dimensions": {"correctness": 0.9, "evidence_quality": 0.9, "scope_discipline": 1.0}, "failure_modes": [], "verifier_disagreement": 0.0})
    run(PYTHON, tool("adaptive-agent-orchestration", "evaluate_dispatch.py"), "--root", str(project), "--contract", str(contract), "--result", str(result), "--output", str(evaluation_missing))
    assert not read_json(evaluation_missing)["accepted"]
    run(PYTHON, tool("adaptive-agent-orchestration", "evaluate_dispatch.py"), "--root", str(project), "--contract", str(contract), "--result", str(result), "--verifier", str(verifier), "--output", str(evaluation))
    verified = read_json(evaluation)
    assert verified["accepted"]
    write_json(event, verified["event_for_registry"])
    run(PYTHON, tool("adaptive-agent-orchestration", "agent_registry.py"), "--root", str(project), "record", "--event-file", str(event))

    inventory = base / "hygiene-inventory.json"
    run(PYTHON, tool("project-hygiene", "repo_hygiene.py"), "--root", str(project), "scan", "--out", str(inventory))
    scanned = read_json(inventory)
    assert all(".agents/skills" not in item.get("path", "") for item in scanned.get("candidate_files", []))
    id_plan = base / "id-plan.json"
    run(PYTHON, tool("project-hygiene", "repo_hygiene.py"), "--root", str(project), "normalize-ids", "--out", str(id_plan))
    id_token = read_json(id_plan)["approval_token"]
    run(PYTHON, tool("project-hygiene", "repo_hygiene.py"), "--root", str(project), "normalize-ids", "--apply", "--approve-token", "wrong", expect=1, capture=True)
    run(PYTHON, tool("project-hygiene", "repo_hygiene.py"), "--root", str(project), "normalize-ids", "--apply", "--approve-token", id_token, "--out", str(base / "id-applied.json"))
    public_text = (project / "docs/results.md").read_text(encoding="utf-8")
    assert all(label in public_text for label in ("local execution baseline", "streaming overlap method", "without overlap ablation"))

    repo_inventory = base / "repo-inventory.json"
    repo_plan = base / "repo-plan.json"
    run(PYTHON, tool("project-hygiene", "repo_hygiene.py"), "--root", str(project), "scan", "--out", str(repo_inventory))
    run(PYTHON, tool("project-hygiene", "repo_hygiene.py"), "--root", str(project), "plan", "--inventory", str(repo_inventory), "--out", str(repo_plan))
    repo_data = read_json(repo_plan)
    assert any(x.get("path") == "scratch/obsolete_old.bak" and x.get("action") == "archive" for x in repo_data["actions"])
    run(PYTHON, tool("project-hygiene", "repo_hygiene.py"), "--root", str(project), "apply", "--plan", str(repo_plan), "--approve-token", "wrong", expect=1, capture=True)
    run(PYTHON, tool("project-hygiene", "repo_hygiene.py"), "--root", str(project), "apply", "--plan", str(repo_plan), "--approve-token", repo_data["approval_token"])
    assert not obsolete_candidate.exists()
    assert list((project / ".research/archive/repository-hygiene").glob("*/scratch/obsolete_old.bak"))

    archive_plan = base / "archive-plan.json"
    run(PYTHON, tool("project-hygiene", "archive_manager.py"), "--root", str(project), "plan", "--path", "scratch/archive_me.txt", "--reason", "release archive smoke", "--out", str(archive_plan))
    archive_data = read_json(archive_plan)
    run(PYTHON, tool("project-hygiene", "archive_manager.py"), "--root", str(project), "apply", "--plan", str(archive_plan), "--approve-token", "wrong", expect=1, capture=True)
    run(PYTHON, tool("project-hygiene", "archive_manager.py"), "--root", str(project), "apply", "--plan", str(archive_plan), "--approve-token", archive_data["approval_token"])
    assert not archive_candidate.exists()
    restore_plan = base / "restore-plan.json"
    run(PYTHON, tool("project-hygiene", "archive_manager.py"), "--root", str(project), "restore-plan", "--batch", archive_data["batch_id"], "--out", str(restore_plan))
    restore_data = read_json(restore_plan)
    run(PYTHON, tool("project-hygiene", "archive_manager.py"), "--root", str(project), "restore", "--plan", str(restore_plan), "--approve-token", "wrong", expect=1, capture=True)
    run(PYTHON, tool("project-hygiene", "archive_manager.py"), "--root", str(project), "restore", "--plan", str(restore_plan), "--approve-token", restore_data["approval_token"])
    assert archive_candidate.exists()
    archive_purge_plan = base / "archive-purge-plan.json"
    run(PYTHON, tool("project-hygiene", "archive_manager.py"), "--root", str(project), "purge-plan", "--batch", archive_data["batch_id"], "--min-age-days", "0", "--out", str(archive_purge_plan))
    archive_purge = read_json(archive_purge_plan)
    run(PYTHON, tool("project-hygiene", "archive_manager.py"), "--root", str(project), "purge", "--plan", str(archive_purge_plan), "--approve-token", "wrong", expect=1, capture=True)
    run(PYTHON, tool("project-hygiene", "archive_manager.py"), "--root", str(project), "purge", "--plan", str(archive_purge_plan), "--approve-token", archive_purge["approval_token"])

    asset_inventory = base / "asset-inventory.json"
    asset_plan = base / "asset-plan.json"
    run(PYTHON, tool("project-hygiene", "asset_lifecycle.py"), "--root", str(project), "scan", "--include-small", "--out", str(asset_inventory))
    run(PYTHON, tool("project-hygiene", "asset_lifecycle.py"), "--root", str(project), "plan", "--inventory", str(asset_inventory), "--out", str(asset_plan))
    planned = read_json(asset_plan)
    safe_paths = {item.get("path") for item in planned["actions"] if item.get("safe_to_apply")}
    assert {"logs/old.log", ".research/runs/E01/raw/samples.bin"}.issubset(safe_paths)
    run(PYTHON, tool("project-hygiene", "asset_lifecycle.py"), "--root", str(project), "apply", "--plan", str(asset_plan), "--approve-token", "wrong", expect=1, capture=True)
    run(PYTHON, tool("project-hygiene", "asset_lifecycle.py"), "--root", str(project), "apply", "--plan", str(asset_plan), "--approve-token", planned["approval_token"])
    assert not raw.exists() and not log.exists()

    purge_plan = base / "purge-plan.json"
    run(PYTHON, tool("project-hygiene", "asset_lifecycle.py"), "--root", str(project), "purge-plan", "--grace-days", "0", "--out", str(purge_plan))
    purge = read_json(purge_plan)
    run(PYTHON, tool("project-hygiene", "asset_lifecycle.py"), "--root", str(project), "purge", "--plan", str(purge_plan), "--approve-token", "wrong", expect=1, capture=True)
    run(PYTHON, tool("project-hygiene", "asset_lifecycle.py"), "--root", str(project), "purge", "--plan", str(purge_plan), "--approve-token", purge["approval_token"])

    spec_path = base / "gauntlet-spec.json"
    run(PYTHON, tool("research-engineering", "gauntlet.py"), "new-spec", "--out", str(spec_path), "--title", "parser change", "--risk", "medium")
    spec = read_json(spec_path); spec["approval"] = {"by": "release-test"}; spec["red_observation"] = {"command": "pytest", "observed": "failed before fix"}; write_json(spec_path, spec)
    evidence_path = base / "gauntlet-evidence.json"
    write_json(evidence_path, {"commands": ["pytest"], "environment": {"python": "test"}, "checks": [{"name": "unit", "passed": True}], "residual_risks": ["smoke only"], "artifacts": ["docs/results.md"]})
    run(PYTHON, tool("research-engineering", "gauntlet.py"), "verify", "--spec", str(spec_path), "--evidence", str(evidence_path))
    latex_root = base / "latex"; latex_root.mkdir(); (latex_root / "main.tex").write_text("\\documentclass{article}\n\\begin{document}x\\end{document}\n", encoding="utf-8")
    latex = read_json_from_stdout(run(PYTHON, tool("research-writing", "latex_audit.py"), "--root", str(latex_root), capture=True).stdout)
    assert latex["main_candidates"] == ["main.tex"]

    run(PYTHON, str(project / ".research/dashboard/dashboard.py"), "validate", "--root", str(project))
    doctor = read_json_from_stdout(run(PYTHON, "-m", "rops", "doctor", "--target", "all", "--project", str(project), capture=True).stdout)
    assert all(not value["missing"] for value in doctor["targets"].values())
    run("git", "fsck", "--no-progress", cwd=project)
    return {
        "router_primary": routed["primary"]["model_id"],
        "verified_quality": verified["quality"],
        "skills_per_framework": len(next(iter(doctor["targets"].values()))["installed"]),
        "semantic_ids_normalized": True,
        "quarantine_and_purge": True,
        "archive_restore_and_purge": True,
        "repository_archive": True,
        "bundle_install": True,
        "gauntlet_and_latex_audit": True,
        "idempotent_next_step": True,
        "proposal_only_broker": True,
        "symlink_boundary": True,
    }


def read_json_from_stdout(stdout: str) -> Any:
    start = stdout.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in stdout: {stdout}")
    return json.loads(stdout[start:])


def worktree_test(base: Path) -> dict[str, Any]:
    main = base / "worktree-main"
    child = base / "worktree-child"
    main.mkdir()
    run("git", "init", "-q", "-b", "main", cwd=main)
    run("git", "config", "user.email", "release-test@example.com", cwd=main)
    run("git", "config", "user.name", "Release Test", cwd=main)
    (main / "README.md").write_text("base\n", encoding="utf-8")
    run("git", "add", "README.md", cwd=main)
    run("git", "commit", "-qm", "base", cwd=main)
    run("git", "worktree", "add", "-q", "-b", "completed-route", str(child), "main", cwd=main)
    run(PYTHON, tool("project-hygiene", "asset_lifecycle.py"), "--root", str(main), "init")
    write_json(main / ".research/hygiene/worktree-registry.json", {
        "schema_version": 1,
        "worktrees": [{"path": str(child.resolve()), "task_id": "route-01", "status": "merged", "lease_expires_at": "2020-01-01T00:00:00Z"}],
    })
    inventory = base / "worktree-inventory.json"
    plan = base / "worktree-plan.json"
    run(PYTHON, tool("project-hygiene", "asset_lifecycle.py"), "--root", str(main), "scan", "--out", str(inventory))
    run(PYTHON, tool("project-hygiene", "asset_lifecycle.py"), "--root", str(main), "plan", "--inventory", str(inventory), "--out", str(plan))
    data = read_json(plan)
    worktrees = [item for item in data["actions"] if item.get("kind") == "worktree"]
    assert any(item.get("path") == str(child.resolve()) and item.get("safe_to_apply") for item in worktrees)
    assert any("main worktree" in item.get("reason", "") and not item.get("safe_to_apply") for item in worktrees)
    run(PYTHON, tool("project-hygiene", "asset_lifecycle.py"), "--root", str(main), "apply", "--plan", str(plan), "--approve-token", data["approval_token"])
    assert not child.exists() and (main / ".git").exists()
    return {"eligible_child_removed": True, "main_blocked": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args()
    if args.keep_temp:
        base = Path(tempfile.mkdtemp(prefix="researchops-toolkit-smoke-"))
        summary = {"project": project_test(base), "worktree": worktree_test(base), "temp": str(base)}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    with tempfile.TemporaryDirectory(prefix="researchops-toolkit-smoke-") as temp:
        base = Path(temp)
        summary = {"project": project_test(base), "worktree": worktree_test(base)}
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
