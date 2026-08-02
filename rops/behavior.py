from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from . import ROOT
from .common import load_json, write_json


def _runtime_module(runtime_root: Path | None = None):
    behavior_root = (runtime_root or (ROOT / "behavior")).resolve()
    path = behavior_root / "runtime.py"
    spec = importlib.util.spec_from_file_location("researchops_behavior_runtime_cli", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load behavior runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _merge_hook_groups(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    output = dict(existing)
    hooks = output.setdefault("hooks", {})
    for event, groups in incoming.get("hooks", {}).items():
        target = hooks.setdefault(event, [])
        known = {
            json.dumps(group, sort_keys=True, ensure_ascii=False)
            for group in target
        }
        for group in groups:
            marker = json.dumps(group, sort_keys=True, ensure_ascii=False)
            if marker not in known:
                target.append(group)
                known.add(marker)
    return output


def _project_hook_config(framework: str, project: Path) -> dict[str, Any]:
    posix = f'python3 "{project.as_posix()}/.researchops/hooks/researchops_hook.py" --framework {framework}'
    windows = f'py -3 "{str(project)}\\.researchops\\hooks\\researchops_hook.py" --framework {framework}'
    if framework == "gemini":
        return {
            "hooks": {
                "SessionStart": [{"hooks": [{"name": "researchops-session", "type": "command", "command": posix, "timeout": 10000}]}],
                "BeforeAgent": [{"hooks": [{"name": "researchops-task-behavior", "type": "command", "command": posix, "timeout": 10000}]}],
                "BeforeTool": [{"matcher": "run_shell_command|write_file|replace|mcp_.*", "hooks": [{"name": "researchops-tool-policy", "type": "command", "command": posix, "timeout": 10000}]}],
            }
        }
    common = {"type": "command", "command": posix, "commandWindows": windows, "timeout": 10}
    return {
        "description": "ResearchOps task behavior and deterministic high-risk checks.",
        "hooks": {
            "SessionStart": [{"hooks": [{**common, "additionalContextLimit": 1800}]}],
            "UserPromptSubmit": [{"hooks": [{**common, "additionalContextLimit": 1800}]}],
            "PreToolUse": [{"matcher": "Bash|apply_patch|Edit|Write|Agent|mcp__.*", "hooks": [{**common, "additionalContextLimit": 1200}]}],
            "SubagentStart": [{"hooks": [{**common, "additionalContextLimit": 1800}]}],
        },
    }


def install(project: str | Path, target: str = "all", mode: str = "guide") -> dict[str, Any]:
    project_path = Path(project).resolve()
    runtime_root = project_path / ".researchops"
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    (runtime_root / "hooks").mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "behavior", runtime_root / "behavior")
    shutil.copy2(ROOT / "hooks/researchops_hook.py", runtime_root / "hooks/researchops_hook.py")
    runtime = _runtime_module(runtime_root / "behavior")
    runtime.set_mode(project_path, mode)
    targets = ["codex", "claude", "gemini"] if target in {"all", "portable"} else [target]
    paths: dict[str, str] = {}
    for framework in targets:
        if framework == "codex":
            path = project_path / ".codex/hooks.json"
        elif framework == "claude":
            path = project_path / ".claude/settings.json"
        elif framework == "gemini":
            path = project_path / ".gemini/settings.json"
        else:
            continue
        existing = load_json(path, {}) or {}
        write_json(path, _merge_hook_groups(existing, _project_hook_config(framework, project_path)))
        paths[framework] = str(path)
    return {
        "schema_version": 1,
        "project": str(project_path),
        "mode": mode,
        "runtime": str(runtime_root),
        "hook_configs": paths,
        "trust_required": [name for name in paths],
    }


def status(project: str | Path) -> dict[str, Any]:
    project_path = Path(project).resolve()
    runtime_root = project_path / ".researchops"
    runtime = _runtime_module((runtime_root / "behavior") if runtime_root.exists() else None)
    registry = runtime.load_registry((runtime_root / "behavior") if runtime_root.exists() else None)
    state = load_json(project_path / ".research/runtime/config.json", {}) or {}
    return {
        "project": str(project_path),
        "installed": runtime_root.exists(),
        "mode": state.get("mode", registry.get("default_mode", "guide")),
        "packs": sorted(runtime.load_packs((runtime_root / "behavior") if runtime_root.exists() else None)),
        "hook_configs": {
            "codex": (project_path / ".codex/hooks.json").exists(),
            "claude": (project_path / ".claude/settings.json").exists(),
            "gemini": (project_path / ".gemini/settings.json").exists(),
        },
        "events": str(project_path / ".research/runtime/events.jsonl"),
    }


def classify(text: str, event: str = "UserPromptSubmit", tool_name: str = "") -> dict[str, Any]:
    runtime = _runtime_module()
    payload = {"hook_event_name": event, "prompt": text, "tool_name": tool_name, "cwd": str(Path.cwd())}
    classes = runtime.classify(payload)
    registry = runtime.load_registry()
    return {"task_classes": classes, "active_packs": runtime._active_packs(classes, payload, registry)}


def evaluate(project: str | Path, payload: dict[str, Any], framework: str = "portable", record: bool = False) -> dict[str, Any]:
    project_path = Path(project).resolve()
    runtime_root = project_path / ".researchops/behavior"
    runtime = _runtime_module(runtime_root if runtime_root.exists() else None)
    return runtime.evaluate(
        payload,
        framework=framework,
        runtime_root=runtime_root if runtime_root.exists() else None,
        explicit_project_root=project_path,
        record=record,
    )


def set_mode(project: str | Path, mode: str) -> dict[str, Any]:
    project_path = Path(project).resolve()
    runtime_root = project_path / ".researchops/behavior"
    runtime = _runtime_module(runtime_root if runtime_root.exists() else None)
    return runtime.set_mode(project_path, mode)


def approve(project: str | Path, kind: str, command: str, reason: str, ttl: int = 30) -> dict[str, Any]:
    # An Agent must not silently authorize itself. Normal approvals are created
    # by an operator in an interactive terminal outside the Agent Harness. The
    # environment escape hatch exists only for automated tests.
    if not sys.stdin.isatty() and os.environ.get("RESEARCHOPS_ALLOW_NONINTERACTIVE_APPROVAL") != "1":
        raise RuntimeError(
            "approval creation requires an interactive operator terminal outside the Agent Harness; "
            "RESEARCHOPS_ALLOW_NONINTERACTIVE_APPROVAL=1 is reserved for isolated automated tests"
        )
    project_path = Path(project).resolve()
    runtime_root = project_path / ".researchops/behavior"
    runtime = _runtime_module(runtime_root if runtime_root.exists() else None)
    return runtime.create_approval(project_path, kind, command, reason, ttl)
