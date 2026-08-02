from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import ROOT
from .common import sha256


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError(f"{path}: unterminated YAML frontmatter")
    block = text[4:end]
    name = re.search(r"^name:\s*([^\n]+)", block, re.M)
    desc = re.search(r"^description:\s*>\s*\n((?:[ \t]+.*\n?)+)", block, re.M)
    if not desc:
        desc = re.search(r"^description:\s*([^\n]+)", block, re.M)
    description = " ".join(line.strip() for line in desc.group(1).splitlines()) if desc else ""
    return {"name": name.group(1).strip() if name else "", "description": description, "body": text[end + 5 :]}


def generate_catalog(root: Path = ROOT) -> dict[str, Any]:
    rows = []
    for skill_file in sorted((root / "skills").glob("*/SKILL.md")):
        metadata = parse_frontmatter(skill_file)
        rows.append({
            "name": metadata["name"] or skill_file.parent.name,
            "description": metadata["description"],
            "path": skill_file.relative_to(root).as_posix(),
            "description_chars": len(metadata["description"]),
        })
    chars = sum(len(row["name"]) + len(row["description"]) + len(row["path"]) + 8 for row in rows)
    data = {"schema_version": 1, "skill_count": len(rows), "startup_catalog_chars_estimate": chars, "skills": rows}
    catalog_dir = root / "catalog"
    catalog_dir.mkdir(exist_ok=True)
    (catalog_dir / "skills.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Skill catalog",
        "",
        "Generated from Skill frontmatter. Read this file to select the narrowest owner; do not load every `SKILL.md`.",
        "",
        f"- Skills: {len(rows)}",
        f"- Estimated startup catalog characters: {chars}",
        "",
        "| Skill | Description |",
        "|---|---|",
    ]
    lines += [f"| `{row['name']}` | {row['description'].replace('|', '/')} |" for row in rows]
    (catalog_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data


def context_budget(root: Path = ROOT, context_window: int = 400_000, percent: float = 2.0, hard_cap: int = 8_000) -> dict[str, Any]:
    catalog = generate_catalog(root)
    used = int(catalog["startup_catalog_chars_estimate"])
    allowed = min(int(context_window * percent / 100), hard_cap)
    return {
        "used_chars": used,
        "allowed_chars": allowed,
        "remaining_chars": allowed - used,
        "within_budget": used <= allowed,
        "skill_count": catalog["skill_count"],
    }


def validate_skills(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    names: set[str] = set()
    count = 0
    for directory in sorted((root / "skills").iterdir()):
        if not directory.is_dir():
            continue
        count += 1
        skill_file = directory / "SKILL.md"
        if not skill_file.exists():
            errors.append(f"{directory.name}: missing SKILL.md")
            continue
        try:
            metadata = parse_frontmatter(skill_file)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if metadata["name"] != directory.name:
            errors.append(f"{directory.name}: frontmatter name {metadata['name']}")
        if directory.name in names:
            errors.append(f"duplicate {directory.name}")
        names.add(directory.name)
        description = metadata["description"]
        if not description.startswith("Use ") or "Do not use" not in description:
            errors.append(f"{directory.name}: description needs positive and negative trigger boundaries")
        if len(description) > 500:
            errors.append(f"{directory.name}: description over 500 characters")
        if len(skill_file.read_text(encoding="utf-8").splitlines()) > 500:
            errors.append(f"{directory.name}: SKILL.md over 500 lines")
        if "## Trigger contract" not in metadata["body"]:
            errors.append(f"{directory.name}: missing Trigger contract section")
        if "## Progressive loading" not in metadata["body"]:
            errors.append(f"{directory.name}: missing Progressive loading section")
        for required in ("LICENSE", "evals/evals.json", "agents/openai.yaml"):
            if not (directory / required).exists():
                errors.append(f"{directory.name}: missing {required}")
        eval_file = directory / "evals/evals.json"
        if eval_file.exists():
            try:
                evaluation = json.loads(eval_file.read_text(encoding="utf-8"))
                if not evaluation.get("evals"):
                    errors.append(f"{directory.name}: no evals")
            except Exception as exc:
                errors.append(f"{directory.name}: invalid eval JSON {exc}")
        for match in re.findall(r"`((?:references|scripts|assets)/[^`\s]+)`", metadata["body"]):
            if not (directory / match.rstrip(".,;:")).exists():
                errors.append(f"{directory.name}: referenced path missing: {match}")
    registry = json.loads((root / "config/trigger-registry.json").read_text(encoding="utf-8"))["skills"]
    if set(registry) != names:
        errors.append("trigger registry and skill directories differ")
    empty_dirs = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir() and not any(p.iterdir()) and "/.git/" not in p.as_posix()]
    if empty_dirs:
        errors.append("empty directories: " + ", ".join(empty_dirs))
    return {"skills": count, "errors": errors}


def validate_triggers(root: Path = ROOT) -> dict[str, Any]:
    registry = json.loads((root / "config/trigger-registry.json").read_text(encoding="utf-8"))["skills"]
    cases = json.loads((root / "tests/trigger-cases.json").read_text(encoding="utf-8"))["cases"]
    errors: list[str] = []
    seen = set()
    coverage = {name: {"positive": 0, "negative": 0} for name in registry}
    for case in cases:
        key = (case["skill"], case["prompt"])
        if key in seen:
            errors.append(f"duplicate case: {key}")
        seen.add(key)
        if case["skill"] not in registry:
            errors.append(f"unknown skill in case: {case['skill']}")
            continue
        coverage[case["skill"]]["positive" if case["should_trigger"] else "negative"] += 1
    for name, counts in coverage.items():
        if not counts["positive"]:
            errors.append(f"{name}: no positive trigger case")
        if not counts["negative"]:
            errors.append(f"{name}: no negative trigger case")
    return {
        "skills": len(registry),
        "cases": len(cases),
        "coverage": coverage,
        "errors": errors,
        "note": "Structural fixture audit only; run prompts through each target harness/model for empirical routing evaluation.",
    }


def provenance_audit(root: Path = ROOT, write_manifest: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    provenance = json.loads((root / "PROVENANCE.json").read_text(encoding="utf-8"))
    skills = sorted(path.name for path in (root / "skills").iterdir() if path.is_dir())
    entries = provenance.get("skills", {})
    for name in skills:
        directory = root / "skills" / name
        if name not in entries:
            errors.append(f"{name}: missing provenance entry")
        else:
            entry = entries[name]
            if entry.get("implementation_origin") != "original_clean_room":
                errors.append(f"{name}: unexpected implementation origin")
            if entry.get("copied_files") not in ([], None):
                errors.append(f"{name}: copied_files must be empty for this release")
        if not (directory / "LICENSE").exists():
            errors.append(f"{name}: missing LICENSE")
    for name in entries:
        if name not in skills:
            errors.append(f"provenance references missing skill: {name}")
    lines = []
    excluded = {"release/MANIFEST.sha256"}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if not path.is_file() or path.is_symlink() or relative in excluded or "/.git/" in path.as_posix():
            continue
        lines.append(f"{sha256(path)}  {relative}")
    if write_manifest:
        (root / "release").mkdir(exist_ok=True)
        (root / "release/MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"skills": len(skills), "files_hashed": len(lines), "errors": errors, "manifest_written": write_manifest}


def verify_manifest(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    count = 0
    manifest = root / "release/MANIFEST.sha256"
    if not manifest.exists():
        return {"files": 0, "errors": ["release/MANIFEST.sha256 missing"]}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        path = root / relative
        count += 1
        if not path.is_file():
            errors.append(relative + ": missing")
        elif sha256(path) != expected:
            errors.append(relative + ": hash mismatch")
    return {"files": count, "errors": errors}


def markdown_links(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in root.rglob("*.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for target in pattern.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            clean = target.split("#", 1)[0]
            if not clean:
                continue
            resolved = (path.parent / clean).resolve()
            if not resolved.exists():
                errors.append(f"{path.relative_to(root)} -> {target}")
    return {"checked": len(list(root.rglob("*.md"))), "errors": errors}


def validate_all(root: Path = ROOT, write_manifest: bool = False) -> dict[str, Any]:
    catalog = generate_catalog(root)
    reports = {
        "skills": validate_skills(root),
        "triggers": validate_triggers(root),
        "context": context_budget(root),
        "provenance": provenance_audit(root, write_manifest=write_manifest),
        "links": markdown_links(root),
    }
    if write_manifest:
        reports["manifest"] = verify_manifest(root)
    errors = []
    for name, report in reports.items():
        if isinstance(report, dict):
            errors.extend(f"{name}: {error}" for error in report.get("errors", []))
            if name == "context" and not report.get("within_budget", True):
                errors.append("context: startup catalog exceeds budget")
    return {"catalog": catalog, "reports": reports, "errors": errors}
