from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .common import atomic_json, now
from .layout import layout

SCHEMA_VERSION = 1
MAX_FILES = 25_000
MAX_TEXT_BYTES = 512_000

IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".researchops", ".research", ".idea", ".vscode",
    "node_modules", "vendor", "dist", "build", "target", "coverage", ".next",
    ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".nox", ".cache", "site-packages",
}

LANGUAGE_EXTENSIONS = {
    ".py": "Python", ".pyi": "Python", ".ipynb": "Jupyter",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
    ".c": "C", ".h": "C/C++", ".cc": "C++", ".cpp": "C++", ".hpp": "C++",
    ".rs": "Rust", ".go": "Go", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell",
    ".sql": "SQL", ".r": "R", ".R": "R", ".jl": "Julia",
    ".tex": "LaTeX", ".bib": "BibTeX", ".md": "Markdown",
    ".html": "HTML", ".css": "CSS", ".scss": "CSS",
    ".yaml": "YAML", ".yml": "YAML", ".json": "JSON", ".toml": "TOML",
}

SOURCE_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".java", ".c", ".h",
    ".cc", ".cpp", ".hpp", ".rs", ".go", ".rb", ".php", ".swift", ".kt",
    ".kts", ".scala", ".sh", ".bash", ".zsh", ".ps1", ".sql", ".r", ".R", ".jl",
}

MANIFEST_NAMES = {
    "pyproject.toml", "requirements.txt", "environment.yml", "setup.py", "setup.cfg",
    "package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json", "Cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "CMakeLists.txt", "Makefile",
    "Dockerfile", "compose.yaml", "docker-compose.yml",
}

CI_DIRS = {".github/workflows", ".gitlab-ci.yml", ".circleci", "Jenkinsfile"}
TEST_TOKENS = {"test", "tests", "spec", "specs", "pytest", "unittest"}
RESULT_TOKENS = {"result", "results", "output", "outputs", "figure", "figures", "plot", "plots", "metrics"}
EXPERIMENT_TOKENS = {"experiment", "experiments", "run", "runs", "benchmark", "benchmarks", "eval", "evals"}
DATA_TOKENS = {"data", "dataset", "datasets", "corpus", "samples"}
PAPER_TOKENS = {"paper", "manuscript", "submission", "article", "thesis", "dissertation"}
DOC_TOKENS = {"doc", "docs", "documentation", "design", "adr", "proposal", "notes"}


def _run_git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _walk(root: Path) -> Iterable[Path]:
    seen = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in IGNORED_DIRS and not name.endswith(".egg-info")]
        base = Path(current)
        for name in files:
            path = base / name
            try:
                if path.is_symlink():
                    continue
            except OSError:
                continue
            yield path
            seen += 1
            if seen >= MAX_FILES:
                return


def _tokens(path: Path, root: Path) -> set[str]:
    rel = path.relative_to(root).as_posix().lower()
    return {token for token in re.split(r"[^a-z0-9]+", rel) if token}


def _contains_any(tokens: set[str], candidates: set[str]) -> bool:
    return bool(tokens.intersection(candidates))


def _root_digest(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        [(row["path"], row["size"], row["mtime_ns"]) for row in rows],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _project_title(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if pyproject.exists() and pyproject.stat().st_size <= MAX_TEXT_BYTES:
        text = pyproject.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"(?m)^name\s*=\s*[\"']([^\"']+)", text)
        if match:
            return match.group(1)
    package = root / "package.json"
    if package.exists() and package.stat().st_size <= MAX_TEXT_BYTES:
        try:
            name = json.loads(package.read_text(encoding="utf-8")).get("name")
            if name:
                return str(name)
        except (OSError, json.JSONDecodeError):
            pass
    return root.name or "ResearchOps Project"


def assess(root: str | Path) -> dict[str, Any]:
    project = Path(root).resolve()
    if project.exists() and not project.is_dir():
        raise ValueError(f"project root is not a directory: {project}")
    rows: list[dict[str, Any]] = []
    language_counts: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    examples: dict[str, list[str]] = {
        "source": [], "tests": [], "documents": [], "experiments": [],
        "results": [], "manuscripts": [], "data": [], "manifests": [],
    }
    total_bytes = 0
    truncated = False
    for index, path in enumerate(_walk(project)):
        if index >= MAX_FILES:
            truncated = True
            break
        try:
            stat = path.stat()
            rel = path.relative_to(project).as_posix()
        except OSError:
            continue
        row = {"path": rel, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        rows.append(row)
        total_bytes += stat.st_size
        suffix = path.suffix
        language = LANGUAGE_EXTENSIONS.get(suffix)
        if language:
            language_counts[language] += 1
        tokens = _tokens(path, project)
        lower_name = path.name.lower()
        is_source = suffix in SOURCE_EXTENSIONS
        is_notebook = suffix == ".ipynb"
        is_test = _contains_any(tokens, TEST_TOKENS) or lower_name.startswith("test_") or lower_name.endswith("_test.py")
        is_manifest = path.name in MANIFEST_NAMES or lower_name in {name.lower() for name in MANIFEST_NAMES}
        is_manuscript = suffix == ".tex" or _contains_any(tokens, PAPER_TOKENS)
        is_experiment = is_notebook or _contains_any(tokens, EXPERIMENT_TOKENS)
        is_result = _contains_any(tokens, RESULT_TOKENS)
        is_data = _contains_any(tokens, DATA_TOKENS)
        is_document = suffix in {".md", ".rst", ".txt"} or _contains_any(tokens, DOC_TOKENS)
        flags = {
            "source": is_source,
            "tests": is_test,
            "documents": is_document,
            "experiments": is_experiment,
            "results": is_result,
            "manuscripts": is_manuscript,
            "data": is_data,
            "manifests": is_manifest,
        }
        for category, active in flags.items():
            if active:
                categories[category] += 1
                if len(examples[category]) < 8:
                    examples[category].append(rel)

    meaningful_rows = [row for row in rows if row["path"] not in {".gitignore", ".DS_Store"}]
    canonical = layout(project)
    has_current_state = (canonical.home / "suite.lock.json").exists() or (canonical.state / "dashboard/project.json").exists()
    old_runtime = canonical.home.exists() and not canonical.state.exists()
    has_legacy_state = canonical.legacy_state.exists() or old_runtime
    if has_current_state:
        mode = "resume"
    elif has_legacy_state:
        mode = "migrate"
    elif not meaningful_rows:
        mode = "new"
    else:
        mode = "adopt"

    git_root = _run_git(project, "rev-parse", "--show-toplevel")
    branch = _run_git(project, "branch", "--show-current") if git_root else None
    commit_count_raw = _run_git(project, "rev-list", "--count", "HEAD") if git_root else None
    dirty_raw = _run_git(project, "status", "--porcelain") if git_root else None
    latest_commit = _run_git(project, "log", "-1", "--format=%H%x09%aI%x09%s") if git_root else None
    commit_count = int(commit_count_raw) if commit_count_raw and commit_count_raw.isdigit() else 0

    score = 0
    if categories["documents"]:
        score += 10
    if categories["manifests"]:
        score += 10
    if categories["source"]:
        score += 25
    if categories["tests"]:
        score += 15
    if categories["experiments"]:
        score += 15
    if categories["results"]:
        score += 10
    if categories["manuscripts"]:
        score += 10
    if commit_count >= 5:
        score += 5
    score = min(100, score)

    if mode == "new":
        phase, progress, confidence = "charter", 3, 0.95
    elif categories["manuscripts"] and categories["results"]:
        phase, progress, confidence = "communication", max(70, score), 0.72
    elif categories["experiments"] and categories["results"]:
        phase, progress, confidence = "analysis", max(58, score), 0.70
    elif categories["tests"] and categories["source"]:
        phase, progress, confidence = "validation", max(48, score), 0.68
    elif categories["source"]:
        phase, progress, confidence = "implementation", max(32, score), 0.65
    elif categories["documents"] or categories["manifests"]:
        phase, progress, confidence = "planning", max(15, score), 0.58
    else:
        phase, progress, confidence = "discovery", max(8, score), 0.45
    if mode == "resume":
        confidence = max(confidence, 0.85)
    if truncated:
        confidence = min(confidence, 0.55)

    signals = []
    for name in ("documents", "manifests", "source", "tests", "experiments", "results", "manuscripts", "data"):
        if categories[name]:
            signals.append({"kind": name, "count": categories[name], "examples": examples[name]})
    if git_root:
        signals.append({"kind": "git", "commits": commit_count, "branch": branch, "dirty": bool(dirty_raw)})

    if mode == "new":
        actions = [
            "Confirm the project motivation, scope, resources, and first falsifiable milestone.",
            "Select a Research-led, Development-led, or mixed initial orientation.",
            "Define the first work unit and its acceptance evidence before execution.",
        ]
        blocking = "Project charter and first acceptance contract are not confirmed."
        focus = "Initialize an evidence-bearing project without assuming a final technical stack."
    elif mode in {"adopt", "migrate"}:
        actions = [
            "Review the generated inventory and correct the inferred phase before routing work.",
            "Map existing artifacts, experiments, tests, decisions, and unresolved risks into ResearchOps state.",
            "Choose the next bounded work unit; do not restart completed work or rewrite existing project files.",
        ]
        blocking = "Current project state is inferred and requires agent/human confirmation."
        focus = "Adopt the existing project non-destructively and establish an evidence baseline."
    else:
        actions = [
            "Validate that the persisted ResearchOps state still matches the repository and active branch.",
            "Reconcile new artifacts or work completed outside the toolkit.",
            "Resume from the next open gate rather than reinitializing the project.",
        ]
        blocking = "State reconciliation may be required before the next gate."
        focus = "Resume the managed project and reconcile repository drift."

    assessment = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "root": str(project),
        "project_id": project.name or "default",
        "title_hint": _project_title(project),
        "adoption_mode": mode,
        "requires_agent_review": mode != "new",
        "inference": {
            "phase": phase,
            "progress_estimate": min(95, progress),
            "confidence": round(confidence, 3),
            "focus": focus,
            "blocking_uncertainty": blocking,
            "next_gate": "Intake confirmation" if mode != "new" else "Gate 0",
            "method": "deterministic repository signals; interpretation must be reviewed by the orchestrator",
        },
        "inventory": {
            "file_count": len(rows),
            "total_bytes": total_bytes,
            "scan_truncated": truncated,
            "languages": [{"name": name, "files": count} for name, count in language_counts.most_common(12)],
            "categories": dict(sorted(categories.items())),
            "signals": signals,
        },
        "git": {
            "is_repository": bool(git_root),
            "root": git_root,
            "branch": branch,
            "commit_count": commit_count,
            "dirty": bool(dirty_raw),
            "dirty_entries": len(dirty_raw.splitlines()) if dirty_raw else 0,
            "latest_commit": latest_commit,
        },
        "root_digest": _root_digest(rows),
        "recommended_actions": actions,
        "safety": {
            "overwrite_existing_project_files": False,
            "delete_or_move_existing_assets": False,
            "auto_advance_gate": False,
            "notes": "The scanner gathers evidence; a capable agent or human confirms project meaning and phase.",
        },
    }
    return assessment


def write_assessment(root: str | Path, assessment: dict[str, Any]) -> dict[str, str]:
    paths = layout(root).ensure()
    directory = paths.state / "onboarding"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = str(assessment.get("generated_at", now())).replace(":", "").replace("+", "_")
    history = directory / f"assessment-{stamp}.json"
    current = directory / "current.json"
    atomic_json(history, assessment)
    atomic_json(current, assessment)
    return {"current": str(current), "history": str(history)}
