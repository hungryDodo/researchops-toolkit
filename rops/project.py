from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import ROOT, VERSION
from .common import now, remove_path, run, write_json

FRAMEWORKS = json.loads((ROOT / "config/frameworks.json").read_text(encoding="utf-8"))["frameworks"]


def bundle_names(bundle: str) -> list[str]:
    bundles = json.loads((ROOT / "config/skill-bundles.json").read_text(encoding="utf-8"))["bundles"]
    if bundle not in bundles:
        raise ValueError(f"unknown bundle: {bundle}")
    return list(bundles[bundle])


def list_bundles() -> dict[str, list[str]]:
    return json.loads((ROOT / "config/skill-bundles.json").read_text(encoding="utf-8"))["bundles"]


def _destination(framework: str, scope: str, project: Path) -> Path:
    key = "skill_user" if scope == "user" else "skill_project"
    raw = FRAMEWORKS[framework][key]
    if scope == "user":
        return Path(os.path.expanduser(raw))
    return project / raw


def install(
    target: str,
    scope: str = "user",
    project: str | Path = ".",
    mode: str = "link",
    skills: str | None = None,
    bundle: str = "research-core",
    with_agents: bool = False,
    legacy_codex: bool = False,
) -> dict[str, Any]:
    project_path = Path(project).resolve()
    frameworks = ["codex", "claude", "gemini"] if target == "all" else [target]
    selected = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()} if skills == "all" else set(
        [x.strip() for x in skills.split(",") if x.strip()] if skills else bundle_names(bundle)
    )
    unknown = selected - {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    if unknown:
        raise ValueError(f"unknown skills: {', '.join(sorted(unknown))}")
    report: dict[str, Any] = {"target": target, "scope": scope, "mode": mode, "skills": sorted(selected), "frameworks": {}}
    for framework in frameworks:
        destination = _destination(framework, scope, project_path)
        destination.mkdir(parents=True, exist_ok=True)
        installed: list[str] = []
        for name in sorted(selected):
            source = ROOT / "skills" / name
            output = destination / name
            remove_path(output)
            if mode == "link":
                try:
                    output.symlink_to(source, target_is_directory=True)
                except OSError:
                    if os.name == "nt":
                        shutil.copytree(source, output)
                    else:
                        raise
            else:
                shutil.copytree(source, output)
            installed.append(name)
        report["frameworks"][framework] = {"path": str(destination), "installed": installed}
        if framework == "codex" and legacy_codex:
            old = (Path.home() / ".codex/skills") if scope == "user" else project_path / ".codex/skills"
            if not old.exists() and not old.is_symlink():
                old.parent.mkdir(parents=True, exist_ok=True)
                try:
                    old.symlink_to(destination, target_is_directory=True)
                except OSError:
                    pass
    if with_agents:
        if scope != "project":
            raise ValueError("--with-agents requires project scope")
        run([sys.executable, str(ROOT / "skills/adaptive-agent-orchestration/scripts/agent_registry.py"), "--root", str(project_path), "init"])
        native = "all" if target in {"all", "portable"} else target
        run([sys.executable, str(ROOT / "skills/adaptive-agent-orchestration/scripts/render_native_agents.py"), "--root", str(project_path), "--framework", native])
    return report


def _write_missing(path: Path, content: str, overwrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not path.exists():
        path.write_text(content, encoding="utf-8")


def _render_policy(skill_path: str, agent_path: str) -> str:
    template = (ROOT / "templates/agent-policy.md.tmpl").read_text(encoding="utf-8")
    return template.replace("{{SKILL_PATH}}", skill_path).replace("{{AGENT_PATH}}", agent_path)


def bootstrap(project: str | Path, title: str, install_target: str = "none", upgrade: bool = False) -> Path:
    project_path = Path(project).resolve()
    project_path.mkdir(parents=True, exist_ok=True)
    research = project_path / ".research"
    research.mkdir(exist_ok=True)
    project_md = f"""# {title}

## Research question

TBD

## Scope and exclusions

TBD

## Target audience / venue hypothesis

TBD

## Resources and budgets

TBD

## Human approval policy

Use ResearchOps Toolkit defaults until customized.
"""
    _write_missing(research / "PROJECT.md", project_md)
    _write_missing(project_path / "task_plan.md", "# Task plan\n\n- [ ] Complete research charter\n- [ ] Run Gate 0\n")
    _write_missing(project_path / "findings.md", "# Findings\n\nTransient findings; promote validated items to the evidence ledger.\n")
    _write_missing(project_path / "progress.md", f"# Progress\n\n- {now()}: project initialized or upgraded.\n")
    _write_missing(research / "decisions.md", "# Decisions\n\n")
    _write_missing(research / "human_actions.md", "# Human actions\n\n- [ ] Approve research charter and resource envelope.\n")
    for name in ("evidence", "runs", "designs", "survey", "hygiene", "agents", "archive", "trash", "proposals"):
        (research / name).mkdir(exist_ok=True)
    ledger = research / "evidence/ledger.json"
    if not ledger.exists():
        run([sys.executable, str(ROOT / "components/evidence-ledger/ledger.py"), "--file", str(ledger), "init"])
    dashboard = research / "dashboard/project.json"
    action = "upgrade" if dashboard.exists() else "init"
    command = [sys.executable, str(ROOT / "components/dashboard/dashboard.py"), action, "--root", str(project_path)]
    if action == "init":
        command += ["--title", title]
    run(command)
    for script in ("asset_lifecycle.py", "archive_manager.py", "repo_hygiene.py"):
        run([sys.executable, str(ROOT / f"skills/project-hygiene/scripts/{script}"), "--root", str(project_path), "init"])
    run([sys.executable, str(ROOT / "skills/adaptive-agent-orchestration/scripts/agent_registry.py"), "--root", str(project_path), "init"])
    governance = research / "governance"
    governance.mkdir(exist_ok=True)
    for name in ("trigger-registry.json", "artifact-contracts.json", "skill-bundles.json", "capability-proposals.json"):
        _write_missing(governance / name, (ROOT / "config" / name).read_text(encoding="utf-8"))
    write_json(research / "suite.lock.json", {
        "suite": "researchops-toolkit",
        "version": VERSION,
        "source": str(ROOT),
        "initialized_or_upgraded_at": now(),
    })
    policies = {
        "AGENTS.md": (".agents/skills", ".codex/agents"),
        "CLAUDE.md": (".claude/skills", ".claude/agents"),
        "GEMINI.md": (".gemini/skills", ".gemini/agents"),
    }
    for filename, paths in policies.items():
        _write_missing(project_path / filename, _render_policy(*paths))
    if install_target != "none":
        install(install_target, scope="project", project=project_path, mode="link", bundle="research-core")
    return project_path


def _git_commit(path: Path) -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else None


def doctor(target: str = "all", project: str | Path | None = None) -> dict[str, Any]:
    frameworks = ["codex", "claude", "gemini"] if target == "all" else [target]
    project_path = Path(project).resolve() if project else Path.cwd()
    report: dict[str, Any] = {"toolkit_version": VERSION, "toolkit_commit": _git_commit(ROOT), "targets": {}}
    for framework in frameworks:
        base = _destination(framework, "project" if project else "user", project_path)
        installed, missing = [], []
        for skill in sorted((ROOT / "skills").iterdir()):
            if not skill.is_dir():
                continue
            path = base / skill.name
            if path.exists():
                installed.append({"name": skill.name, "path": str(path), "link": path.is_symlink()})
            else:
                missing.append(skill.name)
        report["targets"][framework] = {"path": str(base), "installed": installed, "missing": missing}
    return report
