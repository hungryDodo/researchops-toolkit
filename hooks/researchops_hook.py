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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--framework", choices=["auto", "codex", "claude", "gemini", "portable"], default="auto")
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        root = _root()
        runtime = _load_runtime(root)
        framework = _detect_framework(payload, args.framework)
        event = str(payload.get("hook_event_name") or "")
        result = runtime.evaluate(payload, framework=framework, runtime_root=root / "behavior")
        output = runtime.render_hook_output(result, framework, event)
        sys.stdout.write(json.dumps(output, ensure_ascii=False))
        return 0
    except Exception as exc:  # fail open; platform permissions remain authoritative
        print(f"ResearchOps hook warning: {exc}", file=sys.stderr)
        sys.stdout.write("{}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
