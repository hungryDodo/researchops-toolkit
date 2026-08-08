from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import select
import signal
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from . import ROOT, VERSION
from .common import atomic_json, now

BENCHMARK_VERSION = "researchops-product-benchmark-v1"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _parse_json_output(text: str) -> Any:
    candidates = [index for index, char in enumerate(text) if char in "[{" ]
    for index in candidates:
        try:
            return json.loads(text[index:])
        except json.JSONDecodeError:
            continue
    return None


def _run(
    toolkit_root: Path,
    *args: str,
    cwd: Path | None = None,
    timeout: int = 90,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(toolkit_root) + (os.pathsep + existing if existing else "")
    return subprocess.run(
        [sys.executable, "-m", "rops", *args],
        cwd=cwd or toolkit_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _read_version(toolkit_root: Path) -> str:
    path = toolkit_root / "VERSION"
    return path.read_text(encoding="utf-8").strip() if path.exists() else "unknown"


def _fixture(root: Path) -> dict[str, str]:
    files = {
        "README.md": "# Existing project\n\nA streaming systems project already in progress.\n",
        "pyproject.toml": '[project]\nname = "existing-research-project"\nversion = "0.4.0"\n',
        "src/pipeline.py": "def transform(x):\n    return x + 1\n",
        "tests/test_pipeline.py": "from src.pipeline import transform\n\ndef test_transform():\n    assert transform(1) == 2\n",
        "experiments/run_latency.py": "print({'latency_ms': 12.4})\n",
        "results/latency.json": '{"latency_ms": 12.4}\n',
        "paper/main.tex": "\\documentclass{article}\\begin{document}Existing result.\\end{document}\n",
        "docs/decision.md": "# Decision\n\nKeep the streaming baseline for comparison.\n",
    }
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return {rel: _sha(root / rel) for rel in files}


def _dashboard_sync(toolkit_root: Path, project: Path) -> tuple[bool, float]:
    start = time.perf_counter()
    result = _run(toolkit_root, "dashboard", "sync", "--root", str(project), timeout=30)
    elapsed = (time.perf_counter() - start) * 1000.0
    view = project / ".researchops/state/dashboard/view.json"
    return result.returncode == 0 and view.exists(), elapsed




def _process_group_alive(pgid: int) -> bool:
    """Return whether any process still belongs to *pgid*.

    ``killpg(pgid, 0)`` can transiently report a just-terminated group as
    present while descendants are being reaped.  Reading the process table is
    a more useful product-level assertion: the dashboard benchmark passes only
    when no member of the spawned group remains visible.
    """

    if os.name != "posix":
        return False
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pgid="],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
        if completed.returncode == 0:
            return any(
                value.strip().isdigit() and int(value.strip()) == pgid
                for value in completed.stdout.splitlines()
            )
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def _wait_for_process_group_cleanup(pgid: int, *, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_group_alive(pgid):
            return True
        time.sleep(0.05)
    return not _process_group_alive(pgid)


def _dashboard_quick_start(toolkit_root: Path, project: Path) -> dict[str, Any]:
    """Start the real HTTP dashboard on an ephemeral port and fetch view.json."""

    if not _command_supported(toolkit_root, "dashboard", "start"):
        return {"supported": False, "ready": False, "startup_latency_ms": None, "view_loaded": False, "process_group_cleaned": None}
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(toolkit_root) + (os.pathsep + existing if existing else "")
    started = time.perf_counter()
    process = subprocess.Popen(
        [
            sys.executable, "-m", "rops", "dashboard", "start",
            "--root", str(project), "--host", "127.0.0.1", "--port", "0",
        ],
        cwd=toolkit_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    url = ""
    view_loaded = False
    error = ""
    try:
        assert process.stdout is not None
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.2)
            if ready:
                line = process.stdout.readline().strip()
                if line.startswith("http://"):
                    url = line
                    break
            if process.poll() is not None:
                break
        if url:
            with urllib.request.urlopen(url + "/view.json", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                view_loaded = bool(payload.get("view", {}).get("generated"))
        elif process.stderr:
            error = process.stderr.read()[-1000:]
    except Exception as exc:  # benchmark records failure instead of aborting the suite
        error = str(exc)
    finally:
        # ``python -m rops dashboard start`` launches the component through a
        # compatibility facade. Terminate the entire process group so the HTTP
        # child cannot survive as an orphan after the benchmark.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=4)
    process_group_cleaned = _wait_for_process_group_cleanup(process.pid)
    return {
        "supported": True,
        "ready": bool(url and view_loaded),
        "startup_latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "view_loaded": view_loaded,
        "ephemeral_port": bool(url and not url.endswith(":0")),
        "process_group_cleaned": process_group_cleaned,
        "error": error,
    }

def _command_supported(toolkit_root: Path, *args: str) -> bool:
    result = _run(toolkit_root, *args, "--help", timeout=20)
    return result.returncode == 0


def _database_metrics(project: Path) -> dict[str, Any]:
    path = project / ".researchops/intelligence/state.sqlite"
    if not path.exists():
        return {"sqlite_authority": False, "tables": [], "memory_items": 0, "memory_relations": 0}
    connection = sqlite3.connect(path)
    try:
        tables = sorted(row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        memory_items = int(connection.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]) if "memory_items" in tables else 0
        relations = int(connection.execute("SELECT COUNT(*) FROM memory_relations").fetchone()[0]) if "memory_relations" in tables else 0
        return {"sqlite_authority": True, "tables": tables, "memory_items": memory_items, "memory_relations": relations}
    finally:
        connection.close()


def _memory_benchmark(toolkit_root: Path, project: Path) -> dict[str, Any]:
    base = ["intelligence", "--root", str(project)]
    enhanced = _command_supported(toolkit_root, *base, "memory-status")
    metrics: dict[str, Any] = {
        "enhanced_cli": enhanced,
        "deduplication": False,
        "supersession": False,
        "scope_isolation": False,
        "provenance_coverage": 0.0,
        "context_bundle": False,
        "sync_idempotent": False,
        "temporal_validity": False,
        "superseded_excluded": False,
        "layer_coverage": 0,
        "search_latency_ms": None,
    }
    if not enhanced:
        # Older builds may still expose basic add/search. Record capability,
        # but do not emulate lifecycle semantics that are not implemented.
        metrics["basic_search"] = _command_supported(toolkit_root, *base, "memory-search")
        return metrics

    common = [
        *base,
        "memory-add",
        "--scope", "project/bench/task/debug",
        "--layer", "semantic",
        "--kind", "decision",
        "--title", "Preserve the public API",
        "--body", "The compatibility layer must preserve the public API during refactoring.",
        "--source-type", "benchmark",
        "--source-id", "decision-current",
        "--provenance-json", '{"fixture":"product-benchmark"}',
    ]
    first = _parse_json_output(_run(toolkit_root, *common).stdout) or {}
    second = _parse_json_output(_run(toolkit_root, *common).stdout) or {}
    metrics["deduplication"] = bool(first.get("memory_id") and first.get("memory_id") == second.get("memory_id") and second.get("deduplicated"))

    new = _parse_json_output(_run(
        toolkit_root,
        *base,
        "memory-add",
        "--scope", "project/bench/task/debug",
        "--layer", "semantic",
        "--kind", "decision",
        "--title", "Preserve and version the public API",
        "--body", "The compatibility layer must preserve the public API and record its schema revision.",
        "--source-type", "benchmark",
        "--source-id", "decision-v2",
        "--provenance-json", '{"fixture":"product-benchmark","revision":2}',
    ).stdout) or {}
    if first.get("memory_id") and new.get("memory_id"):
        sup = _run(toolkit_root, *base, "memory-supersede", first["memory_id"], new["memory_id"], "--reason", "benchmark revision")
        old = _parse_json_output(_run(toolkit_root, *base, "memory-get", first["memory_id"]).stdout) or {}
        metrics["supersession"] = sup.returncode == 0 and old.get("status") == "superseded"

    expired = _parse_json_output(_run(
        toolkit_root,
        *base,
        "memory-add",
        "--scope", "project/bench/task/debug",
        "--layer", "episodic",
        "--kind", "temporary-observation",
        "--title", "Expired protocol note",
        "--body", "This obsolete protocol should not be recalled after its validity window.",
        "--valid-to", "2000-01-01T00:00:00+00:00",
        "--provenance-json", '{"fixture":"expired"}',
    ).stdout) or {}

    for layer, title in (("procedural", "Debug checklist"), ("preference", "Review preference")):
        _run(
            toolkit_root,
            *base,
            "memory-add",
            "--scope", "project/bench/task/debug",
            "--layer", layer,
            "--kind", "benchmark-layer",
            "--title", title,
            "--body", f"Benchmark memory in the {layer} layer for API review.",
            "--provenance-json", '{"fixture":"layer-coverage"}',
        )

    _run(
        toolkit_root,
        *base,
        "memory-add",
        "--scope", "project/other/task/debug",
        "--layer", "semantic",
        "--kind", "decision",
        "--title", "Unrelated private decision",
        "--body", "Use a different protocol for the unrelated project.",
        "--provenance-json", '{"fixture":"other-project"}',
    )
    start = time.perf_counter()
    result = _run(
        toolkit_root,
        *base,
        "memory-search",
        "public API protocol",
        "--scope", "project/bench/task/debug",
        "--limit", "10",
    )
    metrics["search_latency_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
    search = _parse_json_output(result.stdout) or {}
    hits = search.get("hits", []) if isinstance(search, dict) else []
    metrics["scope_isolation"] = bool(hits) and all(not str(hit.get("scope", "")).startswith("project/other") for hit in hits)
    metrics["provenance_coverage"] = round(
        sum(1 for hit in hits if hit.get("provenance")) / len(hits), 6
    ) if hits else 0.0
    returned_ids = {hit.get("memory_id") for hit in hits}
    metrics["superseded_excluded"] = bool(first.get("memory_id")) and first.get("memory_id") not in returned_ids
    expired_search = _parse_json_output(_run(
        toolkit_root, *base, "memory-search", "obsolete protocol validity",
        "--scope", "project/bench/task/debug", "--limit", "10",
    ).stdout) or {}
    expired_ids = {hit.get("memory_id") for hit in expired_search.get("hits", [])}
    metrics["temporal_validity"] = bool(expired.get("memory_id")) and expired.get("memory_id") not in expired_ids
    layer_status = _parse_json_output(_run(toolkit_root, *base, "memory-status").stdout) or {}
    active_layers = {row.get("layer") for row in layer_status.get("by_layer_status", []) if row.get("status") == "active"}
    metrics["layer_coverage"] = len(active_layers.intersection({"episodic", "semantic", "procedural", "preference"}))
    context = _parse_json_output(_run(
        toolkit_root,
        *base,
        "memory-context",
        "public API compatibility",
        "--scope", "project/bench/task/debug",
    ).stdout) or {}
    metrics["context_bundle"] = bool(context.get("items")) and context.get("authoritative") is False

    before = _parse_json_output(_run(toolkit_root, *base, "memory-status").stdout) or {}
    _run(toolkit_root, *base, "memory-sync")
    after_one = _parse_json_output(_run(toolkit_root, *base, "memory-status").stdout) or {}
    _run(toolkit_root, *base, "memory-sync")
    after_two = _parse_json_output(_run(toolkit_root, *base, "memory-status").stdout) or {}
    metrics["sync_idempotent"] = (
        isinstance(after_one.get("total"), int)
        and after_one.get("total") == after_two.get("total")
        and after_two.get("total", 0) >= before.get("total", 0)
    )
    return metrics


def evaluate_toolkit(toolkit_root: str | Path, *, label: str | None = None) -> dict[str, Any]:
    toolkit = Path(toolkit_root).resolve()
    version = _read_version(toolkit)
    with tempfile.TemporaryDirectory(prefix="rops-product-bench-") as temp:
        project = Path(temp) / "existing-project"
        project.mkdir()
        original_hashes = _fixture(project)
        root_before = {path.name for path in project.iterdir()}
        started = time.perf_counter()
        bootstrap = _run(
            toolkit,
            "bootstrap",
            str(project),
            "--title", "Existing Project Benchmark",
            "--upgrade",
            timeout=120,
        )
        bootstrap_ms = (time.perf_counter() - started) * 1000.0
        root_after = {path.name for path in project.iterdir()}
        added = sorted(root_after - root_before)
        preserved = {
            rel: ((project / rel).exists() and _sha(project / rel) == digest)
            for rel, digest in original_hashes.items()
        }
        intake_path = project / ".researchops/state/onboarding/current.json"
        intake = json.loads(intake_path.read_text(encoding="utf-8")) if intake_path.exists() else {}
        dashboard_path = project / ".researchops/state/dashboard/project.json"
        dashboard = json.loads(dashboard_path.read_text(encoding="utf-8")) if dashboard_path.exists() else {}
        dashboard_ok, dashboard_ms = _dashboard_sync(toolkit, project)
        root_pollution = [
            name for name in added
            if name not in {".researchops", ".research", ".codex", ".claude", ".gemini", ".agents", ".agent-skills"}
        ]
        database = _database_metrics(project)
        memory = _memory_benchmark(toolkit, project)
        dashboard_view = project / ".researchops/state/dashboard/view.json"
        view = json.loads(dashboard_view.read_text(encoding="utf-8")) if dashboard_view.exists() else {}
        status_supported = _command_supported(toolkit, "status")
        inspect_supported = _command_supported(toolkit, "inspect")
        start_supported = _command_supported(toolkit, "dashboard", "start")
        quick_start = _dashboard_quick_start(toolkit, project)
        single_hidden_root = (project / ".researchops").exists() and not (project / ".research").exists()
        return {
            "benchmark_version": BENCHMARK_VERSION,
            "generated_at": now(),
            "tool": label or f"ResearchOps {version}",
            "toolkit_root": str(toolkit),
            "version": version,
            "bootstrap": {
                "returncode": bootstrap.returncode,
                "latency_ms": round(bootstrap_ms, 3),
                "stderr": bootstrap.stderr[-2000:],
            },
            "adoption": {
                "existing_file_preservation_rate": round(sum(preserved.values()) / len(preserved), 6),
                "preserved": preserved,
                "host_root_files_added": root_pollution,
                "single_hidden_root": single_hidden_root,
                "assessment_present": bool(intake),
                "adoption_mode": intake.get("adoption_mode"),
                "phase_inferred": (intake.get("inference") or {}).get("phase"),
                "requires_review": intake.get("requires_agent_review"),
                "dashboard_initial_phase": (dashboard.get("status") or {}).get("phase"),
            },
            "dashboard": {
                "initialized": dashboard_path.exists(),
                "view_ready": dashboard_ok,
                "sync_latency_ms": round(dashboard_ms, 3),
                "start_command_supported": start_supported,
                "quick_start": quick_start,
                "status_command_supported": status_supported,
                "intake_visible": bool(view.get("onboarding")),
                "memory_visible": bool(view.get("memory")),
                "routing_visible": "model_intelligence" in view,
            },
            "state": database,
            "memory": memory,
            "coverage": {
                "dashboard_process_cleanup": bool(quick_start.get("supported")),
            },
        }


def _score(report: dict[str, Any]) -> dict[str, Any]:
    adoption = report.get("adoption", {})
    dashboard = report.get("dashboard", {})
    memory = report.get("memory", {})
    quick_start = dashboard.get("quick_start", {}) if isinstance(dashboard.get("quick_start"), dict) else {}
    checks = {
        "preserves_existing_files": adoption.get("existing_file_preservation_rate") == 1.0,
        "avoids_host_root_pollution": not adoption.get("host_root_files_added", []),
        "records_adoption_mode": bool(adoption.get("adoption_mode")),
        "infers_non_charter_phase": adoption.get("phase_inferred") not in {None, "charter"},
        "single_hidden_root": bool(adoption.get("single_hidden_root")),
        "dashboard_ready": bool(dashboard.get("view_ready")),
        "dashboard_quick_start": bool(quick_start.get("ready")),
        "dashboard_process_cleanup": bool(quick_start.get("process_group_cleaned")),
        "dashboard_shows_intake": bool(dashboard.get("intake_visible")),
        "dashboard_shows_memory": bool(dashboard.get("memory_visible")),
        "memory_deduplicates": bool(memory.get("deduplication")),
        "memory_supersedes": bool(memory.get("supersession")),
        "memory_scope_isolation": bool(memory.get("scope_isolation")),
        "memory_has_provenance": float(memory.get("provenance_coverage", 0.0)) >= 0.99,
        "memory_context_bundle": bool(memory.get("context_bundle")),
        "memory_sync_idempotent": bool(memory.get("sync_idempotent")),
        "memory_temporal_validity": bool(memory.get("temporal_validity")),
        "memory_superseded_excluded": bool(memory.get("superseded_excluded")),
        "memory_four_layer_coverage": int(memory.get("layer_coverage", 0)) >= 4,
    }
    coverage_decl = report.get("coverage", {}) if isinstance(report.get("coverage"), dict) else {}

    def is_covered(name: str) -> bool:
        if name in coverage_decl:
            return bool(coverage_decl[name])
        category = "memory" if name.startswith("memory_") else "dashboard" if name.startswith("dashboard_") else "adoption"
        if category in coverage_decl:
            return bool(coverage_decl[category])
        return True

    coverage = {name: is_covered(name) for name in checks}
    covered = sum(coverage.values())
    passed = sum(bool(value) for name, value in checks.items() if coverage[name])
    return {
        "passed": passed,
        "covered": covered,
        "total": len(checks),
        "rate": round(passed / covered, 6) if covered else None,
        "coverage_rate": round(covered / len(checks), 6),
        "checks": checks,
        "coverage": coverage,
    }


def compare(candidate: dict[str, Any], baselines: list[dict[str, Any]]) -> dict[str, Any]:
    candidate = {**candidate, "score": _score(candidate)}
    scored = [{**baseline, "score": _score(baseline)} for baseline in baselines]
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": now(),
        "candidate": candidate,
        "baselines": scored,
        "interpretation": {
            "scope": "deterministic local product behavior; not a general scientific-agent quality claim",
            "higher_is_better": ["score.rate", "adoption.existing_file_preservation_rate", "memory.provenance_coverage"],
            "lower_is_better": ["adoption.host_root_files_added", "dashboard.sync_latency_ms", "dashboard.quick_start.startup_latency_ms", "memory.search_latency_ms"],
            "third_party_note": "External products require explicit adapters and equivalent fixtures before comparative performance claims are valid.",
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    candidate = report["candidate"]
    rows = [candidate, *report.get("baselines", [])]
    lines = [
        "# ResearchOps Product Benchmark",
        "",
        f"Generated: `{report['generated_at']}`  ",
        f"Suite: `{report['benchmark_version']}`",
        "",
        "This report measures deterministic local product behavior. It does not by itself prove superior research quality against third-party products.",
        "",
        "## Summary",
        "",
        "| Tool | Checks (covered) | Coverage | Existing files preserved | Host-root files added | Intake mode | Dashboard start | Memory lifecycle |",
        "|---|---:|---:|---:|---:|---|---|---|",
    ]
    for row in rows:
        memory_checks = sum(bool(row["memory"].get(key)) for key in (
            "deduplication", "supersession", "scope_isolation", "context_bundle",
            "sync_idempotent", "temporal_validity", "superseded_excluded"
        )) + int(int(row["memory"].get("layer_coverage", 0)) >= 4)
        lines.append(
            f"| {row['tool']} | {row['score']['passed']}/{row['score']['covered']} | "
            f"{row['score']['coverage_rate']:.0%} | "
            f"{float(row.get('adoption', {}).get('existing_file_preservation_rate', 0.0)):.0%} | "
            f"{len(row.get('adoption', {}).get('host_root_files_added', []))} | "
            f"{row.get('adoption', {}).get('adoption_mode') or '—'} | "
            f"{'yes' if row['dashboard'].get('quick_start', {}).get('ready') else 'no'} | {memory_checks}/8 |"
        )
    lines.extend(["", "## Candidate checks", ""])
    for name, passed in candidate["score"]["checks"].items():
        if not candidate["score"]["coverage"].get(name, True):
            lines.append(f"- [-] `{name}` — uncovered")
        else:
            lines.append(f"- [{'x' if passed else ' '}] `{name}`")
    lines.extend([
        "",
        "## Interpretation boundary",
        "",
        "- The fixture represents adopting a non-empty software/research repository.",
        "- Latencies are local-process measurements and should not be compared across machines.",
        "- Third-party observability, research-agent, or memory products need adapters, equivalent data, and their own configured services before head-to-head claims are valid.",
        "- Product usability should additionally be evaluated with user studies and longitudinal project outcomes.",
        "",
    ])
    return "\n".join(lines)


def run_benchmark(
    *,
    candidate_root: str | Path = ROOT,
    baseline_roots: list[str | Path] | None = None,
    baseline_reports: list[str | Path] | None = None,
    out: str | Path | None = None,
) -> dict[str, Any]:
    candidate = evaluate_toolkit(candidate_root, label=f"ResearchOps {_read_version(Path(candidate_root))}")
    baselines = [
        evaluate_toolkit(path, label=f"ResearchOps {_read_version(Path(path))}")
        for path in (baseline_roots or [])
    ]
    for path_value in baseline_reports or []:
        payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "candidate" in payload:
            payload = payload["candidate"]
        if not isinstance(payload, dict) or not {"adoption", "dashboard", "memory"}.issubset(payload):
            raise ValueError(f"invalid product benchmark report: {path_value}")
        baselines.append(payload)
    report = compare(candidate, baselines)
    if out:
        output = Path(out)
        output.mkdir(parents=True, exist_ok=True)
        atomic_json(output / "product-benchmark.json", report)
        (output / "product-benchmark.md").write_text(render_markdown(report), encoding="utf-8")
        report["files"] = {
            "json": str(output / "product-benchmark.json"),
            "markdown": str(output / "product-benchmark.md"),
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rops evaluate", description="Evaluate ResearchOps as a product")
    parser.add_argument("--candidate-root", default=str(ROOT))
    parser.add_argument("--baseline-root", action="append", default=[])
    parser.add_argument("--baseline-report", action="append", default=[], help="Ingest a report emitted by an external benchmark adapter")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    report = run_benchmark(
        candidate_root=args.candidate_root,
        baseline_roots=args.baseline_root,
        baseline_reports=args.baseline_report,
        out=args.out,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
