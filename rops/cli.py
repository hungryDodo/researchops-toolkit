from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import ROOT, VERSION
from . import behavior, models, project, proposals, quality


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
    install.add_argument("--with-behavior", action="store_true", help="Install the project Behavior Runtime and lifecycle hooks")
    install.add_argument("--behavior-mode", choices=["off", "observe", "guide", "enforce"], default="guide")

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


    behavior_parser = sub.add_parser("behavior", help="Manage the cross-cutting Behavior Runtime")
    behavior_parser.add_argument("--root", default=".")
    behavior_sub = behavior_parser.add_subparsers(dest="behavior_command", required=True)
    behavior_install = behavior_sub.add_parser("install")
    behavior_install.add_argument("--target", choices=["codex", "claude", "gemini", "all"], default="all")
    behavior_install.add_argument("--mode", choices=["off", "observe", "guide", "enforce"], default="guide")
    behavior_sub.add_parser("status")
    behavior_mode = behavior_sub.add_parser("mode")
    behavior_mode.add_argument("value", choices=["off", "observe", "guide", "enforce"])
    behavior_classify = behavior_sub.add_parser("classify")
    behavior_classify.add_argument("--text", required=True)
    behavior_classify.add_argument("--event", default="UserPromptSubmit")
    behavior_classify.add_argument("--tool-name", default="")
    behavior_eval = behavior_sub.add_parser("evaluate")
    behavior_eval.add_argument("--framework", choices=["portable", "codex", "claude", "gemini"], default="portable")
    behavior_eval.add_argument("--event", default="UserPromptSubmit")
    behavior_eval.add_argument("--text", default="")
    behavior_eval.add_argument("--tool-name", default="")
    behavior_eval.add_argument("--command", dest="tool_command", default="")
    behavior_eval.add_argument("--record", action="store_true")
    behavior_approve = behavior_sub.add_parser("approve")
    behavior_approve.add_argument("--kind", required=True)
    behavior_approve.add_argument("--command", dest="approved_command", required=True)
    behavior_approve.add_argument("--reason", required=True)
    behavior_approve.add_argument("--ttl", type=int, default=30)
    behavior_analyze = behavior_sub.add_parser("analyze", help="Parse and classify one command without executing it")
    behavior_analyze.add_argument("--command", dest="analyzed_command", required=True)
    behavior_semantic = behavior_sub.add_parser("semantic", help="Configure optional semantic risk review")
    behavior_semantic.add_argument("--mode", choices=["off", "advisory", "required"], required=True)
    behavior_semantic.add_argument("--command", dest="reviewer_command")
    behavior_semantic.add_argument("--timeout", type=int)
    behavior_semantic.add_argument("--scope", choices=["uncertain", "all"], default="uncertain")
    behavior_feedback = behavior_sub.add_parser("feedback", help="Record operator feedback for one behavior event")
    behavior_feedback.add_argument("--event-id", required=True)
    behavior_feedback.add_argument("--label", choices=["true-positive", "false-positive", "missed-risk", "acceptable-risk", "needs-policy-update"], required=True)
    behavior_feedback.add_argument("--note", default="")
    behavior_sub.add_parser("report", help="Summarize behavior feedback without auto-changing policy")

    models_parser = sub.add_parser("models", help="Onboard, test, dispatch, and profile model providers")
    models_parser.add_argument("--root", default=".")
    models_sub = models_parser.add_subparsers(dest="models_command", required=True)
    models_recipes = models_sub.add_parser("recipes", help="List built-in provider recipes")
    models_recipes.add_argument("provider", nargs="?")
    models_onboard = models_sub.add_parser("onboard", help="Create a non-secret provider/model onboarding plan")
    models_onboard.add_argument("--provider", required=True)
    models_onboard.add_argument("--model", required=True)
    models_onboard.add_argument("--base-url")
    models_onboard.add_argument("--protocol", choices=["openai-chat", "anthropic-messages", "google-generate-content"])
    models_onboard.add_argument("--credential-env")
    models_onboard.add_argument("--capability", action="append", default=[])
    models_onboard.add_argument("--risk-ceiling", choices=["low", "medium", "high", "critical"], default="low")
    models_onboard.add_argument("--trust-zone")
    models_onboard.add_argument("--agent", action="append", default=[], help="Attach the enrolled model to an existing agent candidate list")
    models_secret = models_sub.add_parser("secret-template", help="Show or create the user-level secret template")
    models_secret.add_argument("--provider", required=True)
    models_secret.add_argument("--write", action="store_true")
    models_doctor = models_sub.add_parser("doctor", help="Check credential presence without printing secret values")
    models_doctor.add_argument("--provider", required=True)
    models_probe = models_sub.add_parser("probe", help="Run a small connectivity and exact-format probe")
    models_probe.add_argument("--plan", required=True)
    models_probe.add_argument("--timeout", type=float, default=60.0)
    models_probe.add_argument("--enroll", action="store_true")
    models_enroll = models_sub.add_parser("enroll", help="Enroll a model after a successful probe")
    models_enroll.add_argument("--plan", required=True)
    models_enroll.add_argument("--probe")
    models_sub.add_parser("list", help="List configured providers and models")
    models_remote = models_sub.add_parser("remote-list", help="List provider model IDs when the provider exposes an endpoint")
    models_remote.add_argument("--provider", required=True)
    models_remote.add_argument("--timeout", type=float, default=30.0)
    models_dispatch = models_sub.add_parser("dispatch", help="Run one bounded model request with the approved model prompt overlay")
    models_dispatch.add_argument("--model-id", required=True)
    models_dispatch.add_argument("--prompt-file", type=Path, required=True)
    models_dispatch.add_argument("--system-file", type=Path)
    models_dispatch.add_argument("--output", type=Path, required=True)
    models_dispatch.add_argument("--max-tokens", type=int, default=2048)
    models_dispatch.add_argument("--temperature", type=float, default=0.0)
    models_dispatch.add_argument("--timeout", type=float, default=120.0)
    models_dispatch.add_argument("--dry-run", action="store_true")
    models_dispatch.add_argument("--agent", help="Apply an existing agent role prompt and require candidate-model approval")
    models_dispatch.add_argument("--privacy", choices=["public", "internal", "confidential", "restricted"], default="public")
    models_dispatch.add_argument("--risk", choices=["low", "medium", "high", "critical"], default="low")
    models_delegate = models_sub.add_parser("delegate", help="Route a task to an eligible model and dispatch it; evaluation remains a separate gate")
    models_delegate.add_argument("--task-file", type=Path, required=True)
    models_delegate.add_argument("--prompt-file", type=Path, required=True)
    models_delegate.add_argument("--system-file", type=Path)
    models_delegate.add_argument("--output-dir", type=Path, required=True)
    models_delegate.add_argument("--agent")
    models_delegate.add_argument("--max-tokens", type=int, default=2048)
    models_delegate.add_argument("--temperature", type=float, default=0.0)
    models_delegate.add_argument("--timeout", type=float, default=120.0)
    models_delegate.add_argument("--dry-run", action="store_true")
    models_smoke = models_sub.add_parser("smoke", help="Run small deterministic onboarding tests without updating performance profiles")
    models_smoke.add_argument("--model-id", required=True)
    models_smoke.add_argument("--timeout", type=float, default=60.0)
    models_profile = models_sub.add_parser("profile", help="Rebuild or inspect model dossiers")
    models_profile.add_argument("--model-id")
    models_profile.add_argument("--approve-prompt", action="store_true")
    models_note = models_sub.add_parser("profile-note", help="Add a human-authored model note")
    models_note.add_argument("--model-id", required=True)
    models_note.add_argument("--kind", choices=["strength", "weakness", "prompt", "general"], default="general")
    models_note.add_argument("--text", required=True)

    validate = sub.add_parser("validate", help="Run structural and release checks")
    validate.add_argument("--write-manifest", action="store_true")
    validate.add_argument("--smoke", action="store_true")

    sub.add_parser("catalog", help="Regenerate the Skill catalog")

    package = sub.add_parser("package", help="Validate and create a release ZIP")
    package.add_argument("--out", default=str(ROOT.parent))
    package.add_argument("--skip-smoke", action="store_true")

    sub.add_parser("dashboard", help="Run the dashboard component")
    sub.add_parser("ledger", help="Run the evidence-ledger component")
    sub.add_parser("skill-audit", help="Audit one Skill directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    passthrough_scripts = {
        "dashboard": ROOT / "components/dashboard/dashboard.py",
        "ledger": ROOT / "components/evidence-ledger/ledger.py",
        "skill-audit": ROOT / "skills/skill-system-engineering/scripts/audit_skill.py",
    }
    if argv and argv[0] in passthrough_scripts:
        return passthrough(passthrough_scripts[argv[0]], argv[1:])
    args = build_parser().parse_args(argv)
    if args.command == "install":
        emit(project.install(args.target, args.scope, args.project, args.mode, args.skills, args.bundle, args.with_agents, args.legacy_codex, args.with_behavior, args.behavior_mode))
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
    elif args.command == "behavior":
        root = Path(args.root).resolve()
        if args.behavior_command == "install":
            emit(behavior.install(root, args.target, args.mode))
        elif args.behavior_command == "status":
            emit(behavior.status(root))
        elif args.behavior_command == "mode":
            emit(behavior.set_mode(root, args.value))
        elif args.behavior_command == "classify":
            emit(behavior.classify(args.text, args.event, args.tool_name))
        elif args.behavior_command == "evaluate":
            payload = {
                "hook_event_name": args.event,
                "cwd": str(root),
                "prompt": args.text,
                "tool_name": args.tool_name,
                "tool_input": {"command": args.tool_command} if args.tool_command else {},
            }
            emit(behavior.evaluate(root, payload, args.framework, args.record))
        elif args.behavior_command == "approve":
            emit(behavior.approve(root, args.kind, args.approved_command, args.reason, args.ttl))
        elif args.behavior_command == "analyze":
            emit(behavior.analyze(root, args.analyzed_command))
        elif args.behavior_command == "semantic":
            emit(behavior.set_semantic_review(root, args.mode, args.reviewer_command, args.timeout, args.scope))
        elif args.behavior_command == "feedback":
            emit(behavior.feedback(root, args.event_id, args.label, args.note))
        else:
            emit(behavior.feedback_report(root))
    elif args.command == "models":
        root = Path(args.root).resolve()
        if args.models_command == "recipes":
            emit(models.list_recipes(args.provider))
        elif args.models_command == "onboard":
            emit(models.create_plan(root, args.provider, args.model, args.base_url, args.protocol, args.credential_env, args.capability or None, args.risk_ceiling, args.trust_zone, args.agent or None))
        elif args.models_command == "secret-template":
            emit(models.secret_template(args.provider, args.write))
        elif args.models_command == "doctor":
            emit(models.secret_status(args.provider, root))
        elif args.models_command == "probe":
            emit(models.probe(root, args.plan, args.timeout, args.enroll))
        elif args.models_command == "enroll":
            emit(models.enroll(root, args.plan, args.probe))
        elif args.models_command == "list":
            emit(models.configured(root))
        elif args.models_command == "remote-list":
            emit(models.list_remote_models(root, args.provider, args.timeout))
        elif args.models_command == "dispatch":
            emit(models.dispatch(root, args.model_id, args.prompt_file, args.output, args.system_file, args.max_tokens, args.temperature, args.timeout, args.dry_run, args.agent, args.privacy, args.risk))
        elif args.models_command == "delegate":
            emit(models.route_and_dispatch(root, args.task_file, args.prompt_file, args.output_dir, args.agent, args.system_file, args.max_tokens, args.temperature, args.timeout, args.dry_run))
        elif args.models_command == "smoke":
            emit(models.smoke(root, args.model_id, args.timeout))
        elif args.models_command == "profile":
            if args.approve_prompt:
                if not args.model_id:
                    raise SystemExit("--approve-prompt requires --model-id")
                emit(models.approve_prompt(root, args.model_id))
            elif args.model_id:
                emit(models.rebuild_dossier(root, args.model_id))
            else:
                emit(models.rebuild_all_dossiers(root))
        elif args.models_command == "profile-note":
            emit(models.add_profile_note(root, args.model_id, args.kind, args.text))
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
    return 0
