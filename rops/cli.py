from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import ROOT, VERSION
from . import project, proposals, quality


def emit(data) -> None:
    if isinstance(data, Path):
        print(data)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def passthrough(script: Path, args: list[str]) -> int:
    return subprocess.call([sys.executable, str(script), *args])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rops", description="ResearchOps Toolkit")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="Install selected Skills into a framework")
    install.add_argument("--target", choices=["codex", "claude", "gemini", "portable", "all"], required=True)
    install.add_argument("--scope", choices=["user", "project"], default="user")
    install.add_argument("--project", default=".")
    install.add_argument("--mode", choices=["link", "copy"], default="link")
    group = install.add_mutually_exclusive_group()
    group.add_argument("--skills", help="all or comma-separated Skill names")
    group.add_argument("--bundle", default=None, help="Deprecated alias for --preset")
    group.add_argument("--preset", default=None, help="Installation preset; defaults to the package manifest default")
    install.add_argument("--with-agents", action="store_true")
    install.add_argument("--with-behavior", action="store_true", help="Install a replaceable project-local behavior runtime; presets with packs enable this automatically")
    install.add_argument("--behavior-mode", choices=["off", "observe", "guide", "enforce"], default="guide")
    install.add_argument("--legacy-codex", action="store_true")

    bootstrap = sub.add_parser("bootstrap", help="Inspect then initialize, adopt, migrate, or resume a project")
    bootstrap.add_argument("project", nargs="?", default=".")
    bootstrap.add_argument("--title")
    bootstrap.add_argument("--install", choices=["none", "codex", "claude", "gemini", "all"], default="none")
    bootstrap.add_argument("--upgrade", action="store_true")
    bootstrap.add_argument("--mode", choices=["auto", "new", "adopt", "migrate", "resume"], default="auto")
    bootstrap.add_argument("--write-policy-files", action="store_true", help="Create AGENTS.md/CLAUDE.md/GEMINI.md only when explicitly requested")

    inspect = sub.add_parser("inspect", help="Assess a repository before ResearchOps adoption")
    inspect.add_argument("project", nargs="?", default=".")
    inspect.add_argument("--write", action="store_true", help="Persist the assessment under .researchops/state/onboarding")

    status = sub.add_parser("status", help="Show compact project, routing, dashboard, and memory status")
    status.add_argument("--root", default=".")

    up = sub.add_parser("up", help="Adopt if needed, then start the live dashboard")
    up.add_argument("--root", default=".")
    up.add_argument("--title")
    up.add_argument("--host", default="127.0.0.1")
    up.add_argument("--port", type=int, default=8765)
    up.add_argument("--open", action="store_true")
    up.add_argument("--no-bootstrap", action="store_true")

    doctor = sub.add_parser("doctor", help="Inspect installed Skills")
    doctor.add_argument("--target", choices=["codex", "claude", "gemini", "portable", "all"], default="all")
    doctor.add_argument("--project")

    bundles = sub.add_parser("bundles", aliases=["presets"], help="List or print an installation preset (bundle is a compatibility name)")
    bundles.add_argument("name", nargs="?")
    bundles.add_argument("--format", choices=["json", "csv", "lines"], default="lines")

    proposal = sub.add_parser("proposal", help="Suggest or record consequential capabilities")
    proposal.add_argument("--root", default=".")
    proposal_sub = proposal.add_subparsers(dest="proposal_command", required=True)
    propose = proposal_sub.add_parser("propose")
    propose.add_argument("--stage", required=True)
    propose.add_argument("--action", required=True)
    propose.add_argument("--signal", action="append", default=[])
    propose.add_argument("--write", action="store_true")
    proposal_sub.add_parser("list")
    decide = proposal_sub.add_parser("decide")
    decide.add_argument("--id", required=True)
    decide.add_argument("--decision", choices=["approved", "dismissed", "snoozed", "completed"], required=True)
    decide.add_argument("--note", default="")

    validate = sub.add_parser("validate", help="Run structural and release checks")
    validate.add_argument("--write-manifest", action="store_true")
    validate.add_argument("--smoke", action="store_true")

    sub.add_parser("catalog", help="Regenerate the Skill catalog")

    evaluate = sub.add_parser("evaluate", help="Run the ResearchOps product benchmark")
    evaluate.add_argument("--candidate-root", default=str(ROOT))
    evaluate.add_argument("--baseline-root", action="append", default=[])
    evaluate.add_argument("--baseline-report", action="append", default=[])
    evaluate.add_argument("--out")

    package = sub.add_parser("package", help="Validate and create a release ZIP")
    package.add_argument("--out", default=str(ROOT.parent))
    package.add_argument("--skip-smoke", action="store_true")
    package.add_argument("--preset", default="full")
    package.add_argument("--target", choices=["portable", "codex", "claude", "gemini"], default="portable")

    dashboard = sub.add_parser("dashboard", help="Run the dashboard component")
    dashboard.add_argument("args", nargs=argparse.REMAINDER)
    ledger = sub.add_parser("ledger", help="Run the evidence-ledger component")
    ledger.add_argument("args", nargs=argparse.REMAINDER)
    intelligence = sub.add_parser("intelligence", help="Run the model-intelligence control plane")
    intelligence.add_argument("args", nargs=argparse.REMAINDER)
    models = sub.add_parser("models", help="Model gateway and compatibility commands")
    models.add_argument("args", nargs=argparse.REMAINDER)
    behavior = sub.add_parser("behavior", help="Behavior policy runtime")
    behavior.add_argument("args", nargs=argparse.REMAINDER)
    audit = sub.add_parser("skill-audit", help="Audit one Skill directory")
    audit.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] == "intelligence":
        from .intelligence.cli import main as intelligence_main
        return intelligence_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "models":
        from .models import main as models_main
        return models_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "behavior":
        from .behavior import main as behavior_main
        return behavior_main(raw_argv[1:])
    args = build_parser().parse_args(raw_argv)
    if args.command == "install":
        emit(project.install(args.target, args.scope, args.project, args.mode, args.skills, args.bundle or args.preset, args.with_agents, args.legacy_codex, preset=None if args.skills else (args.bundle or args.preset), with_behavior=args.with_behavior, behavior_mode=args.behavior_mode))
    elif args.command == "bootstrap":
        root = project.bootstrap(
            args.project,
            args.title,
            args.install,
            args.upgrade,
            mode=args.mode,
            write_policy_files=args.write_policy_files,
        )
        emit(project.project_status(root))
    elif args.command == "inspect":
        emit(project.inspect_project(args.project, write=args.write))
    elif args.command == "status":
        emit(project.project_status(args.root))
    elif args.command == "up":
        root = Path(args.root).resolve()
        if not args.no_bootstrap and not (root / ".researchops/state/dashboard/project.json").exists():
            project.bootstrap(root, args.title, mode="auto")
        dashboard_args = ["start", "--root", str(root), "--host", args.host, "--port", str(args.port)]
        if args.open:
            dashboard_args.append("--open")
        return passthrough(ROOT / "components/dashboard/dashboard.py", dashboard_args)
    elif args.command == "doctor":
        emit(project.doctor(args.target, args.project))
    elif args.command in {"bundles", "presets"}:
        bundles = project.list_preset_details()
        if not args.name:
            emit({name: {"skills": len(item["skills"]), "features": item["features"], "behavior_packs": item["behavior_packs"], "description": item["description"]} for name, item in bundles.items()})
        else:
            selected = project.list_preset_details().get(args.name)
            if selected is None: raise ValueError(f"unknown preset: {args.name}")
            values = selected["skills"]
            print(json.dumps(selected, indent=2) if args.format == "json" else (",".join(values) if args.format == "csv" else "\n".join(values)))
    elif args.command == "proposal":
        root = Path(args.root).resolve()
        if args.proposal_command == "propose":
            items = proposals.suggest(root, args.stage, args.action, args.signal)
            if args.write:
                proposals.record(root, items)
            emit({"schema_version": 2, "proposals": items, "recorded": bool(args.write), "executed": False})
        elif args.proposal_command == "list":
            emit(proposals.load_state(root))
        else:
            emit(proposals.decide(root, args.id, args.decision, args.note))
    elif args.command == "catalog":
        emit(quality.generate_catalog())
    elif args.command == "validate":
        report = quality.validate_all(write_manifest=args.write_manifest)
        if args.smoke:
            from .release import smoke
            report["smoke"] = smoke()
        emit(report)
        return 1 if report.get("errors") else 0
    elif args.command == "evaluate":
        from .evaluation import run_benchmark
        emit(run_benchmark(
            candidate_root=args.candidate_root,
            baseline_roots=args.baseline_root,
            baseline_reports=args.baseline_report,
            out=args.out,
        ))
    elif args.command == "package":
        from .release import package_release
        archive, checksum = package_release(Path(args.out), skip_smoke=args.skip_smoke, preset=args.preset, target=args.target)
        emit({"archive": str(archive), "checksum": str(checksum)})
    elif args.command == "intelligence":
        from .intelligence.cli import main as intelligence_main
        return intelligence_main(args.args)
    elif args.command == "models":
        from .models import main as models_main
        return models_main(args.args)
    elif args.command == "behavior":
        from .behavior import main as behavior_main
        return behavior_main(args.args)
    elif args.command == "dashboard":
        return passthrough(ROOT / "components/dashboard/dashboard.py", args.args)
    elif args.command == "ledger":
        return passthrough(ROOT / "components/evidence-ledger/ledger.py", args.args)
    elif args.command == "skill-audit":
        return passthrough(ROOT / "skills/skill-system-engineering/scripts/audit_skill.py", args.args)
    return 0
