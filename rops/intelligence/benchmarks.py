from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import ROOT
from .events import OPERATIONS, ORIENTATIONS


def pack_root(root: Path | None = None) -> Path:
    return (root or ROOT) / "components" / "model-intelligence" / "benchmark-packs"


def load_packs(root: Path | None = None) -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    base = pack_root(root)
    if not base.exists():
        return packs
    for path in sorted(base.glob("*/pack.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["path"] = str(path)
        data["name"] = path.parent.name
        packs.append(data)
    return packs


def validate_pack(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if int(data.get("schema_version", 0)) < 1:
        errors.append("schema_version must be >= 1")
    if not str(data.get("id", "")).strip():
        errors.append("id is required")
    operations = data.get("operations", [])
    if not isinstance(operations, list) or not operations:
        errors.append("operations must be a non-empty list")
    else:
        unknown = sorted({str(item) for item in operations} - OPERATIONS)
        if unknown:
            errors.append("unknown operations: " + ", ".join(unknown))
    orientation = data.get("orientation")
    if orientation is not None and orientation not in ORIENTATIONS:
        errors.append(f"unknown orientation: {orientation}")
    metrics = data.get("metrics", [])
    evaluators = data.get("evaluators", [])
    if not metrics and not evaluators:
        errors.append("at least one metric or evaluator is required")
    return errors


def validate_all(root: Path | None = None) -> dict[str, Any]:
    packs = load_packs(root)
    seen: set[str] = set()
    errors: list[dict[str, Any]] = []
    for pack in packs:
        identifier = str(pack.get("id", ""))
        if identifier in seen:
            errors.append({"pack": identifier, "errors": ["duplicate id"]})
        seen.add(identifier)
        pack_errors = validate_pack(pack)
        if pack_errors:
            errors.append({"pack": identifier or pack.get("name"), "errors": pack_errors})
    return {
        "packs": [
            {
                "id": pack.get("id"),
                "name": pack.get("name"),
                "orientation": pack.get("orientation"),
                "operations": pack.get("operations", []),
                "metrics": pack.get("metrics", []),
                "evaluators": pack.get("evaluators", []),
                "path": pack.get("path"),
            }
            for pack in packs
        ],
        "errors": errors,
    }


def get(identifier: str, root: Path | None = None) -> dict[str, Any]:
    for pack in load_packs(root):
        if identifier in {pack.get("id"), pack.get("name")}:
            return pack
    raise ValueError(f"unknown benchmark pack: {identifier}")
