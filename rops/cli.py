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
    group.add_argument("--bundle", default="research-core")
    install.add_argument("--with-agents", action="store_true")
    install.add_argument("--legacy-codex", action="store_true")

    bootstrap = sub.add_parser("bootstrap", help="Initialize or upgrade a research project")
    bootstrap.add_argument("project")
    bootstrap.add_argument("--title", required=True)
    bootstrap.add_argument("--install", choices=["none", "codex", "claude", "gemini", "all"], default="none")
    bootstrap.add_argument("--upgrade", action="store_true")

    doctor = sub.add_parser("doctor", help="Inspect installed Skills")
    doctor.add_argument("--target", choices=["codex", "claude", "gemini", "portable", "all"], default="all")
    doctor.add_argument("--project")

    bundles = sub.add_parser("bundles", help="List or print a Skill bundle")
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

    package = sub.add_parser("package", help="Validate and create a release ZIP")
    package.add_argument("--out", default=str(ROOT.parent))
    package.add_argument("--skip-smoke", action="store_true")

    dashboard = sub.add_parser("dashboard", help="Run the dashboard component")
    dashboard.add_argument("args", nargs=argparse.REMAINDER)
    ledger = sub.add_parser("ledger", help="Run the evidence-ledger component")
    ledger.add_argument("args", nargs=argparse.REMAINDER)
    audit = sub.add_parser("skill-audit", help="Audit one Skill directory")
    audit.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "install":
        emit(project.install(args.target, args.scope, args.project, args.mode, args.skills, args.bundle, args.with_agents, args.legacy_codex))
    elif args.command == "bootstrap":
        emit(project.bootstrap(args.project, args.title, args.install, args.upgrade))
    elif args.command == "doctor":
        emit(project.doctor(args.target, args.project))
    elif args.command == "bundles":
        bundles = project.list_bundles()
        if not args.name:
            emit({name: len(skills) for name, skills in bundles.items()})
        else:
            selected = project.bundle_names(args.name)
            print(json.dumps(selected, indent=2) if args.format == "json" else (",".join(selected) if args.format == "csv" else "\n".join(selected)))
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
    elif args.command == "package":
        from .release import package_release
        archive, checksum = package_release(Path(args.out), skip_smoke=args.skip_smoke)
        emit({"archive": str(archive), "checksum": str(checksum)})
    elif args.command == "dashboard":
        return passthrough(ROOT / "components/dashboard/dashboard.py", args.args)
    elif args.command == "ledger":
        return passthrough(ROOT / "components/evidence-ledger/ledger.py", args.args)
    elif args.command == "skill-audit":
        return passthrough(ROOT / "skills/skill-system-engineering/scripts/audit_skill.py", args.args)
    return 0
