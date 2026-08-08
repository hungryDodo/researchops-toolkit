from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ROOT


@dataclass(frozen=True)
class ResolvedPreset:
    name: str
    skills: tuple[str, ...]
    features: tuple[str, ...]
    behavior_packs: tuple[str, ...]
    lineage: tuple[str, ...]
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "skills": list(self.skills),
            "features": list(self.features),
            "behavior_packs": list(self.behavior_packs),
            "lineage": list(self.lineage),
        }


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    target = path or ROOT / "config/skill-bundles.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    if "presets" not in data:
        # Backward-compatible view of v1/v2 Skill-only bundles.
        data = {
            "schema_version": 3,
            "default_preset": "research-routed",
            "presets": {
                name: {"skills": skills, "features": [], "behavior_packs": []}
                for name, skills in data.get("bundles", {}).items()
            },
        }
    return data



def default_name(manifest: dict[str, Any] | None = None) -> str:
    data = manifest or load_manifest()
    name = str(data.get("default_preset") or "research-routed")
    if name not in data.get("presets", {}):
        raise ValueError(f"default preset is not defined: {name}")
    return name

def resolve(name: str, manifest: dict[str, Any] | None = None) -> ResolvedPreset:
    data = manifest or load_manifest()
    presets = data.get("presets", {})
    if name not in presets:
        raise ValueError(f"unknown preset: {name}")
    skills: set[str] = set()
    features: set[str] = set()
    behavior: set[str] = set()
    lineage: list[str] = []
    visiting: set[str] = set()

    def visit(current: str) -> None:
        if current in visiting:
            raise ValueError(f"preset inheritance cycle at {current}")
        if current in lineage:
            return
        entry = presets.get(current)
        if entry is None:
            raise ValueError(f"unknown inherited preset: {current}")
        visiting.add(current)
        for parent in entry.get("extends", []) or []:
            visit(str(parent))
        visiting.remove(current)
        skills.update(str(item) for item in entry.get("skills", []) or [])
        features.update(str(item) for item in entry.get("features", []) or [])
        behavior.update(str(item) for item in entry.get("behavior_packs", []) or [])
        lineage.append(current)

    visit(name)
    entry = presets[name]
    return ResolvedPreset(
        name=name,
        skills=tuple(sorted(skills)),
        features=tuple(sorted(features)),
        behavior_packs=tuple(sorted(behavior)),
        lineage=tuple(lineage),
        description=str(entry.get("description", "")),
    )


def list_presets() -> dict[str, dict[str, Any]]:
    data = load_manifest()
    return {name: resolve(name, data).as_dict() for name in sorted(data.get("presets", {}))}
