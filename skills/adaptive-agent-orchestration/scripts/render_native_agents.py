#!/usr/bin/env python3
"""Render framework-native sub-agent definitions from the shared registry.

Approved model-specific prompt overlays are appended at render time. Proposed
or unapproved overlays are never injected.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()


def q(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def model_for(agent: dict[str, Any], models: dict[str, dict[str, Any]], providers: set[str]) -> dict[str, Any] | None:
    for model_id in agent.get("candidate_models", []):
        model = models.get(model_id)
        if model and model.get("enabled", False) and model.get("provider") in providers:
            return model
    return None


def profile_overlay(root: Path, model: dict[str, Any] | None) -> str:
    if not model or not model.get("id"):
        return ""
    path = root / ".research" / "agents" / "model-profiles" / (slug(str(model["id"])) + ".json")
    if not path.exists():
        return ""
    try:
        data = load(path)
    except Exception:
        return ""
    prompt = data.get("prompt_overlay") or {}
    active = str(prompt.get("active", "")).strip()
    notes = [
        str(item.get("text"))
        for item in data.get("manual_notes", [])
        if item.get("kind") == "prompt" and item.get("status") == "active" and item.get("text")
    ]
    return "\n".join(part for part in [active, *notes] if part)


def instructions_for(agent: dict[str, Any], overlay: str) -> str:
    return "\n\n".join(
        part for part in [str(agent.get("instructions", "")).strip(), overlay.strip()] if part
    )


def render_codex(agent: dict[str, Any], model: dict[str, Any] | None, overlay: str = "") -> str:
    lines = [f"name = {q(agent['name'])}", f"description = {q(agent.get('description', ''))}"]
    if model:
        lines += [
            f"model = {q(model.get('model'))}",
            f"model_reasoning_effort = {q(agent.get('reasoning_effort', 'medium'))}",
        ]
    content = instructions_for(agent, overlay).replace("'''", "\\'\\'\\'")
    lines += [
        f"sandbox_mode = {q('read-only' if agent.get('allowed_mutability') == 'read-only' else 'workspace-write')}",
        "developer_instructions = '''",
        content,
        "'''",
        "",
    ]
    return "\n".join(lines)


def render_claude(agent: dict[str, Any], model: dict[str, Any] | None, overlay: str = "") -> str:
    model_name = model.get("model") if model else "inherit"
    isolation = "\nisolation: worktree" if agent.get("allowed_mutability") == "workspace-write" else ""
    return f"""---
name: {agent['name']}
description: {agent.get('description','')}
model: {model_name}
effort: {agent.get('reasoning_effort','medium')}{isolation}
---

{instructions_for(agent, overlay)}
"""


def render_gemini(agent: dict[str, Any], model: dict[str, Any] | None, overlay: str = "") -> str:
    model_name = model.get("model") if model else "inherit"
    return f"""---
name: {agent['name']}
description: {agent.get('description','')}
model: {model_name}
max_turns: {int(agent.get('max_turns', 12))}
timeout_mins: {int(agent.get('timeout_mins', 30))}
---

{instructions_for(agent, overlay)}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--framework", choices=["codex", "claude", "gemini", "all"], default="all")
    args = parser.parse_args()
    root = args.root.resolve()
    agents = load(root / ".research/agents/agents.json").get("agents", [])
    model_list = load(root / ".research/agents/models.json").get("models", [])
    models = {model.get("id"): model for model in model_list}
    specs = {
        "codex": (root / ".codex/agents", {"codex-native"}, ".toml", render_codex),
        "claude": (root / ".claude/agents", {"claude-native"}, ".md", render_claude),
        "gemini": (root / ".gemini/agents", {"gemini-native"}, ".md", render_gemini),
    }
    selected = specs if args.framework == "all" else {args.framework: specs[args.framework]}
    result: dict[str, list[str]] = {}
    for framework, (output_dir, providers, suffix, renderer) in selected.items():
        output_dir.mkdir(parents=True, exist_ok=True)
        result[framework] = []
        for agent in agents:
            output = output_dir / (slug(str(agent["name"])) + suffix)
            selected_model = model_for(agent, models, providers)
            output.write_text(
                renderer(agent, selected_model, profile_overlay(root, selected_model)),
                encoding="utf-8",
            )
            result[framework].append(str(output.relative_to(root)))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
