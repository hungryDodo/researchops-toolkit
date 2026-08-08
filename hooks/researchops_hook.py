#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path


def _root() -> Path:
    for name in ("PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT"):
        value = os.environ.get(name)
        if value:
            return Path(value).resolve()
    return Path(__file__).resolve().parents[1]


def _load_runtime(root: Path):
    path = root / "behavior" / "runtime.py"
    spec = importlib.util.spec_from_file_location("researchops_behavior_runtime", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load behavior runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _detect_framework(payload: dict, explicit: str) -> str:
    if explicit != "auto":
        return explicit
    event = str(payload.get("hook_event_name") or "")
    if event in {"BeforeAgent", "AfterAgent", "BeforeTool", "AfterTool", "BeforeModel", "AfterModel"}:
        return "gemini"
    if os.environ.get("PLUGIN_ROOT"):
        return "codex"
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return "claude"
    return "portable"


def _project_root(payload: dict) -> Path:
    cwd = Path(payload.get("cwd") or os.environ.get("GEMINI_PROJECT_DIR") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".researchops").exists() or (candidate / ".git").exists():
            return candidate
    return cwd


def _configured_enforce(payload: dict) -> bool:
    if os.environ.get("ROPS_HOOK_FAIL_CLOSED") == "1":
        return True
    config = _project_root(payload) / ".researchops" / "runtime" / "behavior" / "config.json"
    try:
        return json.loads(config.read_text(encoding="utf-8")).get("mode") == "enforce"
    except (OSError, json.JSONDecodeError):
        return False


def _deny_on_failure(framework: str, event: str, message: str) -> dict:
    if framework == "gemini":
        return {"decision": "deny", "reason": message}
    return {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny", "permissionDecisionReason": message}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--framework", choices=["auto", "codex", "claude", "gemini", "portable"], default="auto")
    args = parser.parse_args()
    payload: dict = {}
    framework = args.framework
    event = ""
    try:
        payload = json.load(sys.stdin)
        root = _root()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        framework = _detect_framework(payload, args.framework)
        event = str(payload.get("hook_event_name") or "")
        runtime = _load_runtime(root)
        result = runtime.evaluate(payload, framework=framework, runtime_root=root / "behavior")
        sys.stdout.write(json.dumps(runtime.render_hook_output(result, framework, event), ensure_ascii=False))
        return 0
    except Exception as exc:
        message = f"ROPS guardrail failed before evaluating this tool call: {type(exc).__name__}: {exc}"
        print(message, file=sys.stderr)
        if event.lower() in {"pretooluse", "beforetool", "permissionrequest"} and _configured_enforce(payload):
            sys.stdout.write(json.dumps(_deny_on_failure(framework, event, message), ensure_ascii=False))
        else:
            sys.stdout.write("{}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
