from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import ROOT, VERSION
from .common import atomic_json, now, remove_path, run, write_json
from .layout import layout, migrate_legacy_layout
from .intake import assess as assess_project, write_assessment
from .presets import default_name, list_presets, load_manifest, resolve

FRAMEWORKS = json.loads((ROOT / "config/frameworks.json").read_text(encoding="utf-8"))["frameworks"]


def bundle_names(bundle: str) -> list[str]:
    """Backward-compatible Skill list for the old Bundle API."""
    return list(resolve(bundle).skills)


def list_bundles() -> dict[str, list[str]]:
    return {name: list(item["skills"]) for name, item in list_presets().items()}


def list_preset_details() -> dict[str, dict[str, Any]]:
    return list_presets()


def _destination(framework: str, scope: str, project: Path) -> Path:
    key = "skill_user" if scope == "user" else "skill_project"
    raw = FRAMEWORKS[framework][key]
    return Path(os.path.expanduser(raw)) if scope == "user" else project / raw


def _codex_project_hook_group(event: str, script: Path) -> dict[str, Any]:
    unix_script = str(script)
    windows_script = str(script).replace("/", "\\")
    hook: dict[str, Any] = {
        "hooks": [{
            "type": "command",
            "command": f'python3 "{unix_script}" --framework codex',
            "commandWindows": f'py -3 "{windows_script}" --framework codex',
            "timeout": 10,
            "additionalContextLimit": 1200 if event == "PreToolUse" else 1800,
        }]
    }
    if event == "PreToolUse":
        hook["matcher"] = "Bash|apply_patch|Edit|Write|Agent|mcp__.*"
    return hook


def _is_researchops_hook_group(group: Any) -> bool:
    if not isinstance(group, dict):
        return False
    return any(
        isinstance(item, dict) and "researchops_hook.py" in str(item.get("command", ""))
        for item in group.get("hooks", [])
    )


def _install_codex_project_hooks(project_path: Path, script: Path) -> dict[str, Any]:
    """Merge project-local Codex hooks without replacing operator hooks."""

    target = project_path / ".codex" / "hooks.json"
    existed = target.exists()
    if existed:
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot merge invalid Codex hooks file: {target}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("hooks", {}), dict):
            raise ValueError(f"Codex hooks file must contain an object-valued 'hooks': {target}")
    else:
        payload = {"hooks": {}}

    events = ("SessionStart", "UserPromptSubmit", "PreToolUse", "SubagentStart")
    hooks = payload.setdefault("hooks", {})
    preserved = 0
    for event in events:
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"Codex hooks event must be an array: {target}: {event}")
        retained = [group for group in groups if not _is_researchops_hook_group(group)]
        preserved += len(retained)
        hooks[event] = [*retained, _codex_project_hook_group(event, script)]
    atomic_json(target, payload)
    return {
        "path": str(target),
        "events": list(events),
        "merged_existing": existed,
        "preserved_groups": preserved,
        "requires_trust": True,
    }


def _install_behavior_runtime(
    project_path: Path,
    selected_packs: tuple[str, ...] | list[str],
    mode: str,
    *,
    codex_hooks: bool = False,
) -> dict[str, Any]:
    if mode not in {"off", "observe", "guide", "enforce"}:
        raise ValueError(f"invalid behavior mode: {mode}")
    runtime_root = layout(project_path).ensure().runtime
    behavior_target = runtime_root / "behavior"
    hooks_target = runtime_root / "hooks"
    rops_target = runtime_root / "rops"
    for target in (behavior_target, hooks_target, rops_target):
        remove_path(target)
    behavior_target.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / "behavior").iterdir():
        if source.name == "packs":
            continue
        target = behavior_target / source.name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    (behavior_target / "packs").mkdir(parents=True, exist_ok=True)
    available = {path.name: path for path in (ROOT / "behavior/packs").iterdir() if path.is_dir()}
    missing = sorted(set(selected_packs) - set(available))
    if missing:
        raise ValueError("unknown behavior packs: " + ", ".join(missing))
    for pack in sorted(set(selected_packs)):
        shutil.copytree(available[pack], behavior_target / "packs" / pack)
    shutil.copytree(ROOT / "hooks", hooks_target)
    shutil.copytree(ROOT / "rops", rops_target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "VERSION", runtime_root / "VERSION")
    write_json(behavior_target / "config.json", {"schema_version": 1, "mode": mode, "updated_at": now()})
    report = {
        "root": str(runtime_root),
        "mode": mode,
        "packs": sorted(set(selected_packs)),
        "hook_manifests": [
            str(hooks_target / "claude-codex-hooks.json"),
            str(hooks_target / "hooks.json"),
            str(hooks_target / "codex-hooks.json"),
            str(hooks_target / "portable-hooks.json"),
        ],
        "replaceable": True,
    }
    if codex_hooks:
        report["codex_project_hooks"] = _install_codex_project_hooks(
            project_path, hooks_target / "researchops_hook.py"
        )
    return report


def install(
    target: str,
    scope: str = "user",
    project: str | Path = ".",
    mode: str = "link",
    skills: str | None = None,
    bundle: str | None = None,
    with_agents: bool = False,
    legacy_codex: bool = False,
    *,
    preset: str | None = None,
    with_behavior: bool = False,
    behavior_mode: str = "guide",
) -> dict[str, Any]:
    project_path = Path(project).resolve()
    frameworks = ["codex", "claude", "gemini"] if target == "all" else [target]
    chosen_preset = preset or bundle or default_name()
    resolved = resolve(chosen_preset)
    available = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    selected = available if skills == "all" else set(
        [x.strip() for x in skills.split(",") if x.strip()] if skills else resolved.skills
    )
    unknown = selected - available
    if unknown:
        raise ValueError(f"unknown skills: {', '.join(sorted(unknown))}")
    report: dict[str, Any] = {
        "target": target,
        "scope": scope,
        "mode": mode,
        "preset": None if skills else resolved.as_dict(),
        "skills": sorted(selected),
        "features": [] if skills else list(resolved.features),
        "behavior_packs": [] if skills else list(resolved.behavior_packs),
        "frameworks": {},
    }
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
        inventory_path = destination / ".researchops-install.json"
        atomic_json(inventory_path, {
            "schema_version": 1,
            "toolkit_version": VERSION,
            "source": str(ROOT),
            "installed_at": now(),
            "preset": None if skills else resolved.name,
            "skills": installed,
            "mode": mode,
        })
        report["frameworks"][framework] = {
            "path": str(destination),
            "installed": installed,
            "inventory": str(inventory_path),
        }
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
        run([sys.executable, "-m", "rops", "intelligence", "--root", str(project_path), "init"])
        native = "all" if target in {"all", "portable"} else target
        render = ROOT / "skills/adaptive-agent-orchestration/scripts/render_native_agents.py"
        if render.exists():
            run([sys.executable, str(render), "--root", str(project_path), "--framework", native])
    install_behavior = with_behavior or (scope == "project" and bool(resolved.behavior_packs) and not skills)
    if install_behavior:
        if scope != "project":
            raise ValueError("behavior runtime installation requires project scope; native plugins carry it for user scope")
        report["behavior_runtime"] = _install_behavior_runtime(
            project_path,
            resolved.behavior_packs,
            behavior_mode,
            codex_hooks="codex" in frameworks,
        )
    return report


def _write_missing(path: Path, content: str, overwrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not path.exists():
        path.write_text(content, encoding="utf-8")


def _render_policy(skill_path: str, agent_path: str) -> str:
    template = (ROOT / "templates/agent-policy.md.tmpl").read_text(encoding="utf-8")
    return template.replace("{{SKILL_PATH}}", skill_path).replace("{{AGENT_PATH}}", agent_path)


def _write_local_gitignore(paths) -> None:
    """Keep runtime/high-volume data local without editing the host repository.

    A project may already have a carefully maintained root ``.gitignore``.
    ResearchOps therefore owns only ``.researchops/.gitignore`` by default.
    """

    target = paths.home / ".gitignore"
    entries = [
        "intelligence/state.sqlite*",
        "intelligence/exports/",
        "runtime/",
        "cache/",
        "logs/",
        "artifacts/",
        "state/runs/*/raw/",
        "secrets/",
    ]
    target.write_text(
        "# ResearchOps local runtime and high-volume state\n" + "\n".join(entries) + "\n",
        encoding="utf-8",
    )


def _merge_missing(target: dict[str, Any], defaults: dict[str, Any]) -> None:
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
        elif isinstance(target[key], dict) and isinstance(value, dict):
            _merge_missing(target[key], value)


def _merge_governance_upgrade(destination_name: str, existing: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Add new routing defaults without overwriting operator-owned configuration."""

    if destination_name == "models.json":
        current = existing.setdefault("models", [])
        known = {str(item.get("arm_id") or item.get("id")) for item in current}
        current.extend(item for item in defaults.get("models", []) if str(item.get("arm_id") or item.get("id")) not in known)
    elif destination_name == "agents.json":
        current = existing.setdefault("agents", [])
        known = {str(item.get("name")) for item in current}
        current.extend(item for item in defaults.get("agents", []) if str(item.get("name")) not in known)
    else:
        _merge_missing(existing, defaults)
    existing["schema_version"] = max(int(existing.get("schema_version", 1)), int(defaults.get("schema_version", 1)))
    return existing


def _copy_governance_defaults(governance: Path, *, upgrade: bool = False) -> None:
    governance.mkdir(parents=True, exist_ok=True)
    for name in ("trigger-registry.json", "artifact-contracts.json", "skill-bundles.json", "capability-proposals.json"):
        source = ROOT / "config" / name
        if source.exists():
            _write_missing(governance / name, source.read_text(encoding="utf-8"))
    assets = ROOT / "skills/adaptive-agent-orchestration/assets"
    mapping = {
        "models.example.json": "models.json",
        "agents.example.json": "agents.json",
        "routing-policy.example.json": "routing-policy.json",
    }
    for source_name, destination_name in mapping.items():
        source = assets / source_name
        if source.exists():
            data = json.loads(source.read_text(encoding="utf-8"))
            if destination_name == "models.json":
                for model in data.get("models", []):
                    model.setdefault("arm_id", model.get("id"))
                    model.setdefault("model_family", model.get("model"))
                    # Operation-level aliases preserve old affinity declarations.
                    old = dict(model.get("task_affinity", {}))
                    aliases = {
                        "discover": max(old.get("search", 0.0), old.get("extraction", 0.0), old.get("classification", 0.0)),
                        "communicate": max(old.get("synthesis", 0.0), old.get("writing", 0.0), old.get("formatting", 0.0)),
                        "implement": max(old.get("implementation", 0.0), old.get("coding", 0.0)),
                        "validate": max(old.get("review", 0.0), old.get("validation", 0.0)),
                    }
                    for key, value in aliases.items():
                        if value:
                            model.setdefault("task_affinity", {})[key] = value
                data["schema_version"] = max(3, int(data.get("schema_version", 1)))
            if destination_name == "routing-policy.json":
                data["schema_version"] = max(3, int(data.get("schema_version", 1)))
                data["weights"] = {
                    "verified_progress": 0.25,
                    "quality": 0.35,
                    "success": 0.18,
                    "reasoning_fit": 0.12,
                    "cost": 0.07,
                    "latency": 0.05,
                    "correction": 0.04,
                    "verifier_disagreement": 0.03,
                    "operational_risk": 0.12
                }
                data.setdefault("latency_reference_seconds", 300)
                data.setdefault("exploration", {})["selection_probability"] = 0.10
            destination = governance / destination_name
            if upgrade and destination.exists():
                existing = json.loads(destination.read_text(encoding="utf-8"))
                data = _merge_governance_upgrade(destination_name, existing, data)
                _write_missing(destination, json.dumps(data, ensure_ascii=False, indent=2) + "\n", overwrite=True)
            else:
                _write_missing(destination, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    _write_missing(governance / "providers.json", json.dumps({"schema_version": 1, "providers": []}, indent=2) + "\n")


def _project_documents(title: str, mode: str, assessment: dict[str, Any]) -> dict[str, str]:
    inference = assessment.get("inference", {})
    if mode == "new":
        project_md = f"""# {title}

## Motivation and current direction

TBD. A project may begin with only a broad motivation; task details are refined per work unit.

## Scope and exclusions

TBD

## Target audience / venue hypothesis

TBD

## Resources and budgets

TBD

## Human approval policy

Use ResearchOps Toolkit defaults until customized. Prompt mitigations never grant high-risk operation approval.
"""
        plan = "# Task plan\n\n- [ ] Confirm motivation, scope, resources, and first falsifiable milestone.\n- [ ] Define the first bounded work unit and its acceptance evidence.\n- [ ] Run Gate 0.\n"
        actions = "# Human actions\n\n- [ ] Approve project charter and resource envelope.\n"
    else:
        project_md = f"""# {title}

## Adoption status

ResearchOps was attached to an existing project. Existing repository files remain authoritative until explicitly promoted into ResearchOps state.

- Adoption mode: `{mode}`
- Inferred phase: `{inference.get('phase', 'unknown')}`
- Inference confidence: `{inference.get('confidence', 0)}`
- Current focus: {inference.get('focus', 'Review existing project state.')}

## Motivation and current direction

Review the existing README, design documents, issues, commits, experiments, and artifacts before filling this section. Do not restart completed work.

## Scope, exclusions, resources, and approvals

TBD after intake confirmation.
"""
        plan = "# Task plan\n\n- [ ] Review `.researchops/state/onboarding/current.json`.\n- [ ] Confirm or correct the inferred phase and progress.\n- [ ] Map existing decisions, evidence, experiments, tests, and unresolved risks.\n- [ ] Select the next bounded work unit; do not recreate completed work.\n"
        actions = "# Human actions\n\n- [ ] Confirm the intake assessment, current phase, and next bounded work unit.\n"
    return {
        "PROJECT.md": project_md,
        "task_plan.md": plan,
        "findings.md": "# Findings\n\nTransient findings; promote validated items to the evidence ledger.\n",
        "progress.md": f"# Progress\n\n- {now()}: ResearchOps {mode} intake recorded.\n",
        "decisions.md": "# Decisions\n\n",
        "human_actions.md": actions,
    }


def bootstrap(
    project: str | Path,
    title: str | None = None,
    install_target: str = "none",
    upgrade: bool = False,
    *,
    mode: str = "auto",
    write_policy_files: bool = False,
) -> Path:
    """Initialize, adopt, migrate, or resume a project non-destructively.

    The repository is assessed before any ResearchOps state is written.  The
    scanner records facts; an agent or human remains responsible for confirming
    the semantic phase and deciding how much existing work should be imported.
    """

    project_path = Path(project).resolve()
    project_path.mkdir(parents=True, exist_ok=True)
    before = assess_project(project_path)
    detected = str(before.get("adoption_mode", "new"))
    if mode not in {"auto", "new", "adopt", "migrate", "resume"}:
        raise ValueError(f"invalid bootstrap mode: {mode}")
    selected_mode = detected if mode == "auto" else mode
    if selected_mode == "new" and detected not in {"new", "resume"}:
        raise ValueError(
            "refusing new-project initialization over an existing repository; "
            "use --mode adopt or --mode auto"
        )

    legacy_present = (project_path / ".research").exists() or (
        (project_path / ".researchops").exists() and not (project_path / ".researchops/state").exists()
    )
    if legacy_present and (upgrade or selected_mode == "migrate" or mode == "auto"):
        migrate_legacy_layout(project_path)
        selected_mode = "migrate"

    paths = layout(project_path).ensure()
    assessment = assess_project(project_path)
    assessment["adoption_mode"] = "resume" if detected == "resume" else selected_mode
    assessment["requested_mode"] = mode
    assessment_files = write_assessment(project_path, assessment)
    effective_mode = str(assessment["adoption_mode"])
    effective_title = title or str(assessment.get("title_hint") or project_path.name or "ResearchOps Project")

    documents = _project_documents(effective_title, effective_mode, assessment)
    for filename, content in documents.items():
        _write_missing(paths.state / filename, content)
    for name in ("evidence", "runs", "designs", "survey", "hygiene", "agents", "archive", "trash", "proposals", "dashboard", "hardware", "onboarding"):
        (paths.state / name).mkdir(parents=True, exist_ok=True)

    ledger = paths.state / "evidence/ledger.json"
    if not ledger.exists():
        run([sys.executable, str(ROOT / "components/evidence-ledger/ledger.py"), "--file", str(ledger), "init"], capture=True)

    dashboard = paths.state / "dashboard/project.json"
    action = "upgrade" if dashboard.exists() else "init"
    command = [sys.executable, str(ROOT / "components/dashboard/dashboard.py"), action, "--root", str(project_path)]
    if action == "init":
        command += ["--title", effective_title, "--intake-file", assessment_files["current"]]
    run(command, capture=True)

    for script in ("asset_lifecycle.py", "archive_manager.py", "repo_hygiene.py"):
        run([sys.executable, str(ROOT / f"skills/project-hygiene/scripts/{script}"), "--root", str(project_path), "init"], capture=True)
    _copy_governance_defaults(paths.governance, upgrade=upgrade)
    write_json(paths.runtime / "behavior" / "config.json", {"schema_version": 1, "mode": "guide", "updated_at": now()})

    from .intelligence.memory import sync_from_project
    from .intelligence.projections import rebuild_projections
    from .intelligence.store import IntelligenceStore

    store = IntelligenceStore(project_path)
    timestamp = now()
    project_id = str(assessment.get("project_id") or project_path.name or "default")
    metadata = {
        "adoption_mode": effective_mode,
        "intake_current": assessment_files["current"],
        "inferred_phase": assessment.get("inference", {}).get("phase"),
        "inference_confidence": assessment.get("inference", {}).get("confidence"),
    }
    snapshot_id = "snapshot-" + hashlib.sha256(
        (project_id + "\0" + str(assessment.get("root_digest")) + "\0" + timestamp).encode("utf-8")
    ).hexdigest()[:20]
    with store.transaction() as connection:
        existing = connection.execute("SELECT created_at FROM projects WHERE project_id=?", (project_id,)).fetchone()
        created_at = existing["created_at"] if existing else timestamp
        connection.execute(
            """
            INSERT INTO projects(project_id,root,title,created_at,updated_at,metadata_json)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(project_id) DO UPDATE SET root=excluded.root,title=excluded.title,
                updated_at=excluded.updated_at,metadata_json=excluded.metadata_json
            """,
            (project_id, str(project_path), effective_title, created_at, timestamp, json.dumps(metadata, ensure_ascii=False, sort_keys=True)),
        )
        connection.execute(
            "INSERT OR REPLACE INTO project_snapshots(snapshot_id,project_id,captured_at,adoption_mode,root_digest,assessment_json) VALUES (?,?,?,?,?,?)",
            (snapshot_id, project_id, timestamp, effective_mode, str(assessment.get("root_digest", "")), json.dumps(assessment, ensure_ascii=False, sort_keys=True)),
        )
    rebuild_projections(store)
    sync_from_project(store)
    rebuild_projections(store)

    write_json(paths.home / "suite.lock.json", {
        "suite": "researchops-toolkit",
        "version": VERSION,
        "source": str(ROOT),
        "initialized_or_upgraded_at": timestamp,
        "layout_version": 3,
        "adoption_mode": effective_mode,
        "state_authority": "sqlite+project-artifacts",
        "single_hidden_root": ".researchops",
        "preset_manifest_version": load_manifest().get("schema_version"),
    })
    if write_policy_files:
        policies = {
            "AGENTS.md": (".agents/skills", ".codex/agents"),
            "CLAUDE.md": (".claude/skills", ".claude/agents"),
            "GEMINI.md": (".gemini/skills", ".gemini/agents"),
        }
        for filename, agent_paths in policies.items():
            _write_missing(project_path / filename, _render_policy(*agent_paths))
    _write_local_gitignore(paths)
    run([sys.executable, str(ROOT / "components/dashboard/dashboard.py"), "sync", "--root", str(project_path)], capture=True)
    if install_target != "none":
        install(install_target, scope="project", project=project_path, mode="link", preset="research-routed")
    return project_path


def inspect_project(project: str | Path = ".", *, write: bool = False) -> dict[str, Any]:
    assessment = assess_project(project)
    if write:
        assessment["files"] = write_assessment(project, assessment)
    return assessment


def project_status(project: str | Path = ".") -> dict[str, Any]:
    project_path = Path(project).resolve()
    paths = layout(project_path)
    assessment_path = paths.state / "onboarding" / "current.json"
    assessment = (
        json.loads(assessment_path.read_text(encoding="utf-8"))
        if assessment_path.exists()
        else assess_project(project_path)
    )
    dashboard_view = paths.state / "dashboard" / "view.json"
    dashboard = {}
    if dashboard_view.exists():
        try:
            dashboard = json.loads(dashboard_view.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            dashboard = {"warning": "dashboard view is not valid JSON"}
    intelligence: dict[str, Any] = {"available": paths.database.exists()}
    if paths.database.exists():
        from .intelligence import memory
        from .intelligence.store import IntelligenceStore
        store = IntelligenceStore(project_path)
        intelligence.update({
            "events": int(store.scalar("SELECT COUNT(*) n FROM evaluation_events", default=0)),
            "profiles": int(store.scalar("SELECT COUNT(*) n FROM profile_slices", default=0)),
            "route_decisions": int(store.scalar("SELECT COUNT(*) n FROM route_decisions", default=0)),
            "memory": memory.status(store),
        })
    return {
        "toolkit_version": VERSION,
        "root": str(project_path),
        "managed": paths.home.exists(),
        "adoption_mode": assessment.get("adoption_mode"),
        "intake": assessment,
        "program_status": dashboard.get("status", {}),
        "model_intelligence": dashboard.get("model_intelligence", intelligence),
        "memory": dashboard.get("memory", intelligence.get("memory", {})),
        "dashboard": {
            "initialized": (paths.state / "dashboard" / "project.json").exists(),
            "view": str(dashboard_view),
            "start_command": f"python3 -m rops dashboard start --root {project_path}",
        },
    }


def _git_commit(path: Path) -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else None


def doctor(target: str = "all", project: str | Path | None = None) -> dict[str, Any]:
    frameworks = ["codex", "claude", "gemini"] if target == "all" else [target]
    project_path = Path(project).resolve() if project else Path.cwd()
    report: dict[str, Any] = {
        "toolkit_version": VERSION,
        "toolkit_commit": _git_commit(ROOT),
        "project_layout": layout(project_path).describe() if project else None,
        "targets": {},
    }
    for framework in frameworks:
        base = _destination(framework, "project" if project else "user", project_path)
        installed = []
        available: set[str] = set()
        for skill in sorted((ROOT / "skills").iterdir()):
            if not skill.is_dir():
                continue
            available.add(skill.name)
            path = base / skill.name
            if path.exists():
                installed.append({"name": skill.name, "path": str(path), "link": path.is_symlink()})
        installed_names = {item["name"] for item in installed}
        inventory_path = base / ".researchops-install.json"
        inventory: dict[str, Any] | None = None
        if inventory_path.exists():
            try:
                candidate = json.loads(inventory_path.read_text(encoding="utf-8"))
                if isinstance(candidate, dict) and isinstance(candidate.get("skills"), list):
                    inventory = candidate
            except (OSError, json.JSONDecodeError):
                inventory = None
        expected = (
            {str(name) for name in inventory["skills"] if str(name) in available}
            if inventory is not None
            else available
        )
        missing = sorted(expected - installed_names)
        extra = sorted(installed_names - expected)
        report["targets"][framework] = {
            "path": str(base),
            "installed": installed,
            "missing": missing,
            "extra": extra,
            "preset": inventory.get("preset") if inventory else None,
            "inventory": str(inventory_path) if inventory else None,
            "healthy": not missing and not extra,
        }
    return report
