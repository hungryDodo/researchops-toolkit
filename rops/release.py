from __future__ import annotations

import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from . import ROOT, VERSION
from .common import sha256
from .presets import ResolvedPreset, resolve
from .quality import context_budget, generate_catalog, provenance_audit, validate_all, verify_manifest

FEATURE_COMPONENTS: dict[str, tuple[str, ...]] = {
    "dashboard": ("dashboard",),
    "research-dashboard": ("dashboard",),
    "evidence-ledger": ("evidence-ledger",),
    "engineering-assurance": ("engineering-assurance",),
    "model-gateway": ("model-gateway", "model-control-plane"),
    "model-intelligence": ("model-intelligence",),
    "visual-contracts": ("visual-contracts",),
}

SMOKE_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("legacy", ("tests/smoke.py",)),
    ("intelligence", ("tests/intelligence_smoke.py",)),
    ("behavior", ("tests/behavior_smoke.py",)),
    ("model-control-plane", ("tests/model_control_plane_smoke.py",)),
    ("model-effort-routing", ("tests/model_effort_routing_smoke.py",)),
    ("worker-dispatch", ("tests/worker_dispatch_smoke.py",)),
    ("adoption-memory", ("tests/adoption_memory_smoke.py",)),
    ("product-benchmark", ("tests/product_benchmark_smoke.py",)),
)

COPY_FILES = (
    "AGENTS.md",
    "CHANGELOG.md",
    "CITATION.cff",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "README_zh.md",
    "SECURITY.md",
    "VERSION",
)


def _run(args: list[str], *, capture: bool = True, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=capture)
    if result.returncode:
        raise RuntimeError(f"command failed: {' '.join(args)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _json_from_stdout(stdout: str) -> Any:
    positions = [index for index, char in enumerate(stdout) if char == "{"]
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
    for pattern in ("*.sqlite-wal", "*.sqlite-shm"):
        for path in root.rglob(pattern):
            path.unlink(missing_ok=True)


def smoke() -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for name, relative in SMOKE_COMMANDS:
        script = ROOT.joinpath(*relative)
        if not script.exists():
            reports[name] = {"status": "not-present"}
            continue
        result = _run([sys.executable, str(script)])
        reports[name] = _json_from_stdout(result.stdout)
    return reports


def write_validation(smoke_report: dict[str, Any], *, preset: str = "full", target: str = "portable") -> Path:
    catalog = generate_catalog()
    context = context_budget()
    trigger_count = len(json.loads((ROOT / "tests/trigger-cases.json").read_text(encoding="utf-8"))["cases"])
    timestamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    component_count = len([item for item in (ROOT / "components").iterdir() if item.is_dir()])
    behavior_count = len([item for item in (ROOT / "behavior/packs").iterdir() if item.is_dir()])
    lines = [
        f"# Release validation — v{VERSION}",
        "",
        f"- Completed: {timestamp}",
        f"- Package preset: `{preset}`",
        f"- Package target: `{target}`",
        f"- Python: {platform.python_version()}",
        f"- Platform: {platform.platform()}",
        f"- Top-level Skills: {catalog['skill_count']}",
        f"- Internal components: {component_count}",
        f"- Behavior Packs: {behavior_count}",
        f"- Startup catalog estimate: {catalog['startup_catalog_chars_estimate']} / {context['allowed_chars']} characters",
        f"- Trigger fixtures: {trigger_count} structural positive/negative cases",
        "",
        "## Successful automated checks",
        "",
        "- Inspect-before-write intake and non-destructive adoption of non-empty projects with one `.researchops/` root.",
        "- Light/standard/deep adoption protocol that separates deterministic inventory from agent/human semantic confirmation.",
        "- SQLite is authoritative from the first model-evaluation event; JSONL is import/export only.",
        "- One canonical Evaluation Event schema, one profile engine, and routing/dossier/dashboard/audit projections.",
        "- Finite profile scopes, posterior uncertainty, endpoint health, effective-dated price, and routing explanations.",
        "- Warmup/soft transfer with negative-transfer guard and visible project adaptation state.",
        "- Failure-pattern aggregation, scoped mitigation lifecycle, prompt compilation, and separate high-risk approvals.",
        "- Black-box behavior-drift signals and deployment epochs without claiming an unobservable provider cause.",
        "- Task-family-conditioned Judge calibration, position consistency, abstention, selective escalation, and weighted pairwise ranking.",
        "- Four-layer lifecycle-aware local Memory with scoped deduplication, supersession, temporal validity, provenance, relations, project sync, and bounded context assembly.",
        "- Actual HTTP Dashboard quick-start validation plus intake, Memory, Routing, warmup, cost, and project-status visibility.",
        "- Executable product regression benchmark and standardized external baseline-report contract.",
        "- Research-led and development-led R&D share engineering assurance while retaining different acceptance goals.",
        "- Preset composition, target-native manifests/hooks, behavior modes, and filtered plugin packaging.",
        "- Legacy research workflow, evidence ledger, dashboard, agent routing, archive/restore/purge, and worktree safety.",
        "",
        "## Smoke summary",
        "",
        "```json",
        json.dumps(smoke_report, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Validation boundary",
        "",
        "Structural tests do not prove empirical routing quality for every model, provider, Harness, or future deployment. Black-box drift detection reports observed behavior changes and cannot prove that a provider changed hidden weights. Hardware safety remains dependent on the actual topology, instrument state, platform sandbox, and human confirmation.",
        "",
    ]
    output = ROOT / "release/VALIDATION.md"
    output.parent.mkdir(exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def _copy(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(
            source,
            target,
            symlinks=False,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.sqlite", "*.sqlite-wal", "*.sqlite-shm"),
        )
    else:
        shutil.copy2(source, target)


def _selected_components(preset: ResolvedPreset) -> set[str]:
    selected: set[str] = set()
    for feature in preset.features:
        selected.update(FEATURE_COMPONENTS.get(feature, ()))
    return selected


def _filter_trigger_registry(package_root: Path, skills: set[str]) -> None:
    path = package_root / "config/trigger-registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["skills"] = {name: value for name, value in data.get("skills", {}).items() if name in skills}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _filter_trigger_cases(package_root: Path, skills: set[str]) -> None:
    source = ROOT / "tests/trigger-cases.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    data["cases"] = [case for case in data.get("cases", []) if case.get("skill") in skills]
    target = package_root / "tests/trigger-cases.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _filter_provenance(package_root: Path, skills: set[str]) -> None:
    data = json.loads((ROOT / "PROVENANCE.json").read_text(encoding="utf-8"))
    data["version"] = VERSION
    data["skills"] = {name: value for name, value in data.get("skills", {}).items() if name in skills}
    (package_root / "PROVENANCE.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_package_preset(package_root: Path, preset: ResolvedPreset) -> None:
    data = {
        "schema_version": 3,
        "terminology": "A preset is an installation and packaging recipe, not a code boundary or Git bundle.",
        "default_preset": preset.name,
        "package_is_filtered": True,
        "presets": {
            preset.name: {
                "description": preset.description,
                "skills": list(preset.skills),
                "features": list(preset.features),
                "behavior_packs": list(preset.behavior_packs),
            }
        },
    }
    target = package_root / "config/skill-bundles.json"
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_package_descriptor(package_root: Path, preset: ResolvedPreset, target: str) -> None:
    descriptor = {
        "schema_version": 1,
        "name": "researchops-toolkit" if preset.name == "full" else f"researchops-{preset.name}",
        "version": VERSION,
        "preset": preset.as_dict(),
        "target": target,
        "state_root": ".researchops/",
        "authoritative_model_state": ".researchops/intelligence/state.sqlite",
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    }
    (package_root / "PACKAGE.json").write_text(json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rewrite_native_name(path: Path, preset: ResolvedPreset) -> None:
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    package_name = "researchops-toolkit" if preset.name == "full" else f"researchops-{preset.name}"
    data["name"] = package_name
    data["version"] = VERSION
    if "plugins" in data:
        for plugin in data.get("plugins", []):
            plugin["name"] = package_name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_native_manifests(package_root: Path, preset: ResolvedPreset, target: str) -> None:
    targets: Iterable[str] = ("codex", "claude", "gemini") if target == "portable" else (target,)
    for native in targets:
        if native == "codex":
            _copy(ROOT / ".codex-plugin", package_root / ".codex-plugin")
            _rewrite_native_name(package_root / ".codex-plugin/plugin.json", preset)
        elif native == "claude":
            _copy(ROOT / ".claude-plugin", package_root / ".claude-plugin")
            _rewrite_native_name(package_root / ".claude-plugin/plugin.json", preset)
            _rewrite_native_name(package_root / ".claude-plugin/marketplace.json", preset)
        elif native == "gemini":
            _copy(ROOT / "gemini-extension.json", package_root / "gemini-extension.json")
            _rewrite_native_name(package_root / "gemini-extension.json", preset)


def _stage_package(package_root: Path, preset: ResolvedPreset, target: str) -> None:
    package_root.mkdir(parents=True, exist_ok=True)
    selected_skills = set(preset.skills)
    selected_components = _selected_components(preset)

    for name in COPY_FILES:
        _copy(ROOT / name, package_root / name)
    _filter_provenance(package_root, selected_skills)

    # The deterministic runtime is the thin waist and is shipped intact.  Domain
    # workflows and components remain filtered by the selected preset.
    _copy(ROOT / "rops", package_root / "rops")
    _copy(ROOT / "docs", package_root / "docs")
    _copy(ROOT / "templates", package_root / "templates")
    _copy(ROOT / "hooks", package_root / "hooks")
    if target == "codex":
        shutil.copy2(ROOT / "hooks/codex-hooks.json", package_root / "hooks/hooks.json")
    elif target == "portable":
        shutil.copy2(ROOT / "hooks/portable-hooks.json", package_root / "hooks/hooks.json")
    _copy(ROOT / "release/VALIDATION.md", package_root / "release/VALIDATION.md")
    _copy(ROOT / "release/product-benchmark.json", package_root / "release/product-benchmark.json")
    _copy(ROOT / "release/product-benchmark.md", package_root / "release/product-benchmark.md")

    _copy(ROOT / "config", package_root / "config")
    _filter_trigger_registry(package_root, selected_skills)
    _write_package_preset(package_root, preset)
    _filter_trigger_cases(package_root, selected_skills)

    for name in sorted(selected_skills):
        _copy(ROOT / "skills" / name, package_root / "skills" / name)
    for name in sorted(selected_components):
        _copy(ROOT / "components" / name, package_root / "components" / name)

    # Behavior core is always available to native hooks, but only selected
    # policy packs are present in a filtered artifact.
    for name in ("README.md", "policy.json", "runtime.py"):
        _copy(ROOT / "behavior" / name, package_root / "behavior" / name)
    for name in preset.behavior_packs:
        _copy(ROOT / "behavior/packs" / name, package_root / "behavior/packs" / name)

    _copy_native_manifests(package_root, preset, target)
    _write_package_descriptor(package_root, preset, target)
    generate_catalog(package_root)

    # A filtered package owns its own integrity manifest.
    provenance = provenance_audit(package_root, write_manifest=True)
    if provenance["errors"]:
        raise RuntimeError("filtered package provenance failed:\n" + "\n".join(provenance["errors"]))
    manifest = verify_manifest(package_root)
    if manifest["errors"]:
        raise RuntimeError("filtered package manifest failed:\n" + "\n".join(manifest["errors"]))
    report = validate_all(package_root, write_manifest=False)
    if report["errors"]:
        raise RuntimeError("filtered package validation failed:\n" + "\n".join(report["errors"]))


def package_release(
    out: Path,
    skip_smoke: bool = False,
    *,
    preset: str = "full",
    target: str = "portable",
) -> tuple[Path, Path]:
    if target not in {"portable", "codex", "claude", "gemini"}:
        raise ValueError(f"unsupported package target: {target}")
    selected = resolve(preset)
    clean_generated()
    report = validate_all(write_manifest=False)
    if report["errors"]:
        raise RuntimeError("validation failed:\n" + "\n".join(report["errors"]))
    smoke_report = {"status": "skipped"} if skip_smoke else smoke()
    _run([sys.executable, "-m", "compileall", "-q", "rops", "skills", "components", "behavior", "hooks", "tests"])
    write_validation(smoke_report, preset=preset, target=target)
    clean_generated()
    provenance = provenance_audit(write_manifest=True)
    if provenance["errors"]:
        raise RuntimeError("provenance failed:\n" + "\n".join(provenance["errors"]))
    manifest = verify_manifest()
    if manifest["errors"]:
        raise RuntimeError("manifest failed:\n" + "\n".join(manifest["errors"]))

    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    package_name = "researchops-toolkit" if preset == "full" else f"researchops-{preset}"
    archive_base = out / f"{package_name}-v{VERSION}-{target}"
    with tempfile.TemporaryDirectory(prefix="researchops-toolkit-package-") as temp:
        package_root = Path(temp) / package_name
        _stage_package(package_root, selected, target)
        archive = Path(shutil.make_archive(str(archive_base), "zip", Path(temp), package_name))
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    checksum.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="utf-8")
    return archive, checksum
