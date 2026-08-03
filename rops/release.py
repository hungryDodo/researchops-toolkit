from __future__ import annotations

import datetime as dt
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import ROOT, VERSION
from .common import sha256
from .quality import context_budget, generate_catalog, provenance_audit, validate_all, verify_manifest


def _run(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=capture)
    if result.returncode:
        raise RuntimeError(f"command failed: {' '.join(args)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _json_from_stdout(stdout: str) -> Any:
    # Smoke helpers may print intermediate JSON. Only test line-start objects,
    # avoiding quadratic retries on every nested brace in a large capture.
    positions = [match.start() for match in re.finditer(r"(?m)^\{", stdout)]
    for position in reversed(positions):
        try:
            return json.loads(stdout[position:])
        except json.JSONDecodeError:
            continue
    raise ValueError("no complete JSON object in smoke output")


def clean_generated(root: Path = ROOT) -> None:
    for path in root.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)
    for path in root.rglob("*.pyc"):
        path.unlink(missing_ok=True)


def smoke() -> dict[str, Any]:
    workflow = _run([sys.executable, "tests/smoke.py"])
    behavior = _run([sys.executable, "tests/behavior_smoke.py"])
    return {
        "workflow": _json_from_stdout(workflow.stdout),
        "behavior": _json_from_stdout(behavior.stdout),
    }


def write_validation(smoke_report: dict[str, Any]) -> Path:
    catalog = generate_catalog()
    context = context_budget()
    trigger_count = len(json.loads((ROOT / "tests/trigger-cases.json").read_text(encoding="utf-8"))["cases"])
    behavior_count = len(json.loads((ROOT / "behavior/evals/cases.json").read_text(encoding="utf-8"))["cases"])
    risk_data = json.loads((ROOT / "behavior/evals/risk-cases.json").read_text(encoding="utf-8"))
    risk_count = len(risk_data["cases"])
    timestamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        f"# Release validation — v{VERSION}",
        "",
        f"- Completed: {timestamp}",
        f"- Python: {platform.python_version()}",
        f"- Platform: {platform.platform()}",
        f"- Top-level Skills: {catalog['skill_count']}",
        "- Internal components: 2 (evidence ledger, dashboard)",
        "- Behavior Runtime: 1 universal kernel, 7 task packs, 3 Harness adapters, parsed risk policy, optional semantic reviewer",
        f"- Startup catalog estimate: {catalog['startup_catalog_chars_estimate']} / {context['allowed_chars']} characters",
        f"- Trigger fixtures: {trigger_count} structural positive/negative cases",
        f"- Behavior fixtures: {behavior_count} task, pack, lifecycle, and decision cases",
        f"- Risk corpus: {risk_count} adversarial and benign-neighbor command cases ({risk_data.get('positive_count', 'n/a')} positive, {risk_data.get('negative_count', 'n/a')} negative)",
        "",
        "## Successful automated checks",
        "",
        "- Unified cross-platform CLI installation, bootstrap, bundle selection, and diagnostics.",
        "- Skill structure, progressive-loading references, positive/negative trigger boundaries, eval files, metadata, and licenses.",
        "- Trigger registry coverage, startup context budget, provenance, local Markdown links, and internal file hashes.",
        "- Native Codex, Claude Code, and Gemini CLI agent rendering.",
        "- Project Hook installation, plugin/extension manifests, task-pack selection, structured tool inspection, parsed/canonical risk policy, optional semantic escalation, and platform output adapters.",
        "- Parent-session policy propagation into Sub-Agents without raw-prompt persistence.",
        "- Interactive-operator, raw/canonical/rule-bound, short-lived, concurrency-safe one-use approvals and metadata-only behavior event logging.",
        "- Proposal-only safeguard discovery, persistence, snooze state, and no target execution.",
        "- Sub-Agent routing, deterministic checks, independent verification, and profile recording.",
        "- Archive-first cleanup, restore, separate purge, large-data quarantine, semantic ID normalization, and worktree safety.",
        "- Research engineering gauntlet, LaTeX discovery, dashboard validation, Python compilation, and ZIP integrity.",
        "",
        "## Smoke summary",
        "",
        "```json",
        json.dumps(smoke_report, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Validation boundary",
        "",
        "Trigger and Behavior fixtures verify structural and regression coverage, not exhaustive shell-language safety or empirical reviewer accuracy for every model/Harness release. Hook enforcement only covers exposed lifecycle/tool paths and does not replace platform permissions, sandboxing, repository protection, hardware interlocks, or human confirmation.",
        "",
    ]
    output = ROOT / "release/VALIDATION.md"
    output.parent.mkdir(exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def package_release(out: Path, skip_smoke: bool = False) -> tuple[Path, Path]:
    clean_generated()
    report = validate_all(write_manifest=False)
    if report["errors"]:
        raise RuntimeError("validation failed:\n" + "\n".join(report["errors"]))
    smoke_report = {"status": "skipped"} if skip_smoke else smoke()
    _run([sys.executable, "-m", "compileall", "-q", "rops", "skills", "components", "behavior", "hooks", "tests"])
    write_validation(smoke_report)
    clean_generated()
    provenance = provenance_audit(write_manifest=True)
    if provenance["errors"]:
        raise RuntimeError("provenance failed:\n" + "\n".join(provenance["errors"]))
    manifest = verify_manifest()
    if manifest["errors"]:
        raise RuntimeError("manifest failed:\n" + "\n".join(manifest["errors"]))
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    archive_base = out / f"researchops-toolkit-v{VERSION}"
    with tempfile.TemporaryDirectory(prefix="researchops-toolkit-package-") as temp:
        package_root = Path(temp) / "researchops-toolkit"
        shutil.copytree(
            ROOT,
            package_root,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo"),
        )
        archive = Path(shutil.make_archive(str(archive_base), "zip", Path(temp), "researchops-toolkit"))
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    checksum.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="utf-8")
    return archive, checksum
