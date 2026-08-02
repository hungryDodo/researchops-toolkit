#!/usr/bin/env python3
"""Render framework-native sub-agent definitions from the shared registry."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    with path.open(encoding="utf-8") as f: return json.load(f)


def slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", s).strip("-").lower()


def q(s: Any) -> str:
    return json.dumps(str(s), ensure_ascii=False)


def model_for(agent: dict[str, Any], models: dict[str, dict[str, Any]], providers: set[str]) -> dict[str, Any] | None:
    for mid in agent.get("candidate_models", []):
        m = models.get(mid)
        if m and m.get("enabled", False) and m.get("provider") in providers: return m
    return None


def render_codex(agent: dict[str, Any], model: dict[str, Any] | None) -> str:
    lines = [f"name = {q(agent['name'])}", f"description = {q(agent.get('description', ''))}"]
    if model:
        lines += [f"model = {q(model.get('model'))}", f"model_reasoning_effort = {q(agent.get('reasoning_effort', 'medium'))}"]
    lines += [f"sandbox_mode = {q('read-only' if agent.get('allowed_mutability') == 'read-only' else 'workspace-write')}", "developer_instructions = '''", str(agent.get("instructions", "")).replace("'''", "\'\'\'"), "'''", ""]
    return "\n".join(lines)


def render_claude(agent: dict[str, Any], model: dict[str, Any] | None) -> str:
    model_name = model.get("model") if model else "inherit"
    isolation = "\nisolation: worktree" if agent.get("allowed_mutability") == "workspace-write" else ""
    return f"""---
name: {agent['name']}
description: {agent.get('description','')}
model: {model_name}
effort: {agent.get('reasoning_effort','medium')}{isolation}
---

{agent.get('instructions','')}
"""


def render_gemini(agent: dict[str, Any], model: dict[str, Any] | None) -> str:
    model_name = model.get("model") if model else "inherit"
    return f"""---
name: {agent['name']}
description: {agent.get('description','')}
model: {model_name}
max_turns: {int(agent.get('max_turns', 12))}
timeout_mins: {int(agent.get('timeout_mins', 30))}
---

{agent.get('instructions','')}
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--framework", choices=["codex", "claude", "gemini", "all"], default="all")
    args = ap.parse_args(); root = args.root.resolve()
    agents = load(root / ".research/agents/agents.json").get("agents", [])
    models_list = load(root / ".research/agents/models.json").get("models", [])
    models = {m.get("id"): m for m in models_list}
    specs = {
        "codex": (root / ".codex/agents", {"codex-native"}, ".toml", render_codex),
        "claude": (root / ".claude/agents", {"claude-native"}, ".md", render_claude),
        "gemini": (root / ".gemini/agents", {"gemini-native"}, ".md", render_gemini),
    }
    selected = specs if args.framework == "all" else {args.framework: specs[args.framework]}
    result: dict[str, list[str]] = {}
    for fw, (out, providers, suffix, renderer) in selected.items():
        out.mkdir(parents=True, exist_ok=True); result[fw] = []
        for a in agents:
            path = out / (slug(str(a["name"])) + suffix)
            path.write_text(renderer(a, model_for(a, models, providers)), encoding="utf-8")
            result[fw].append(str(path.relative_to(root)))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
