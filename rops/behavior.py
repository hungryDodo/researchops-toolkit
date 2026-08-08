from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import shlex
import sys
import uuid
from pathlib import Path
from typing import Any

from . import ROOT
from .common import now
from .intelligence.store import IntelligenceStore

# Deterministic, non-executing first-pass rules.  The runtime never treats this
# list as a complete OS sandbox; Harness/platform permissions remain final.
PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("credential-exposure", "block", re.compile(r"(?:cat|print|echo|env|set).*?(?:secret|token|api[_-]?key|password)", re.I)),
    ("destructive-filesystem", "approval", re.compile(r"\brm\s+(?:-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)\b|\bmkfs(?:\.[a-z0-9]+)?\b|\bshred\b|\bdd\s+.*\bof=/dev/", re.I)),
    ("history-rewrite", "approval", re.compile(r"\bgit\s+(?:push\s+.*(?:--force|-f)\b|reset\s+--hard\b|clean\s+-[a-z]*f)", re.I)),
    ("hardware-power-write", "approval", re.compile(r"\b(?:nrfjprog|openocd|west\s+flash|esptool|dfu-util|ppk2).*(?:program|flash|erase|recover|write|output|power)?\b|/sys/class/(?:gpio|power_supply)", re.I)),
    ("external-disclosure", "approval", re.compile(r"\b(?:curl|wget|scp|rsync)\b.*(?:--data|--upload-file|@|\bscp\b|\brsync\b)", re.I)),
    ("privileged-container", "approval", re.compile(r"\b(?:docker|podman)\s+run\b.*(?:--privileged|--pid=host|--network=host|-v\s+/:)", re.I)),
    ("recursive-permissions", "approval", re.compile(r"\bchmod\s+-R\s+(?:777|a\+rwx)\b|\bchown\s+-R\b", re.I)),
    ("policy-bypass", "block", re.compile(r"(?:\.researchops/(?:runtime|governance)|ROPS_HOOK_FAIL_CLOSED|behavior-events\.jsonl).*(?:delete|remove|truncate|overwrite)|\b(?:rm|truncate)\b.*\.researchops/(?:runtime|governance)", re.I)),
]


def _emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _load_runtime():
    path = ROOT / "behavior" / "runtime.py"
    spec = importlib.util.spec_from_file_location("researchops_behavior_runtime_cli", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load behavior runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def command_hash(command: str, category: str) -> str:
    try:
        normalized = " ".join(shlex.split(command))
    except ValueError:
        normalized = " ".join(command.split())
    return hashlib.sha256(f"{category}\n{normalized}".encode()).hexdigest()


def analyze(command: str) -> dict[str, Any]:
    findings = []
    for category, action, pattern in PATTERNS:
        if pattern.search(command):
            findings.append({"category": category, "action": action})
    disposition = "block" if any(item["action"] == "block" for item in findings) else "approval-required" if findings else "allow"
    return {
        "command": command,
        "disposition": disposition,
        "findings": findings,
        "metadata_only_logging": True,
        "executed": False,
        "boundary": "guardrail-not-complete-sandbox",
    }


def approve(store: IntelligenceStore, command: str, category: str, approved_by: str, ttl_minutes: int = 15) -> dict[str, Any]:
    analysis = analyze(command)
    if category not in {item["category"] for item in analysis["findings"]}:
        raise ValueError(f"command was not classified as {category}")
    if any(item["category"] == category and item["action"] == "block" for item in analysis["findings"]):
        raise ValueError("blocked categories cannot be approved")
    approval_id = "approval-op-" + uuid.uuid4().hex[:16]
    approved_at = dt.datetime.now(dt.timezone.utc)
    expires = approved_at + dt.timedelta(minutes=ttl_minutes)
    digest = command_hash(command, category)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO approvals(approval_id,approval_kind,subject_id,scope_json,approved_by,approved_at,expires_at,one_use,content_hash,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                approval_id,
                "high-risk-operation",
                category,
                json.dumps({"category": category}, sort_keys=True),
                approved_by,
                approved_at.replace(microsecond=0).isoformat(),
                expires.replace(microsecond=0).isoformat(),
                1,
                digest,
                json.dumps({"command_preview": command[:120]}, sort_keys=True),
            ),
        )
    return {
        "approval_id": approval_id,
        "category": category,
        "expires_at": expires.replace(microsecond=0).isoformat(),
        "one_use": True,
        "prompt_mitigation_approval_granted": False,
    }


def check(store: IntelligenceStore, command: str, *, consume: bool = False) -> dict[str, Any]:
    result = analyze(command)
    if result["disposition"] in {"allow", "block"}:
        result["approved"] = result["disposition"] == "allow"
        return result
    matches = []
    for finding in result["findings"]:
        digest = command_hash(command, finding["category"])
        row = store.one(
            """
            SELECT * FROM approvals WHERE approval_kind='high-risk-operation' AND subject_id=? AND content_hash=?
              AND consumed_at IS NULL AND (expires_at IS NULL OR expires_at>?)
            ORDER BY approved_at DESC LIMIT 1
            """,
            (finding["category"], digest, now()),
        )
        if row:
            matches.append(row)
    result["approved"] = len(matches) == len(result["findings"])
    result["approval_ids"] = [row["approval_id"] for row in matches]
    result["disposition"] = "allow-approved" if result["approved"] else "approval-required"
    if consume and result["approved"]:
        with store.transaction() as connection:
            for row in matches:
                if row["one_use"]:
                    connection.execute("UPDATE approvals SET consumed_at=? WHERE approval_id=?", (now(), row["approval_id"]))
        result["consumed"] = True
    return result


def packs() -> list[dict[str, Any]]:
    items = []
    for path in sorted((ROOT / "behavior/packs").glob("*/pack.json")):
        items.append(json.loads(path.read_text(encoding="utf-8")))
    return items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rops behavior")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("packs")
    sub.add_parser("status")
    mode = sub.add_parser("mode"); mode.add_argument("value", choices=["off", "observe", "guide", "enforce"])
    classify = sub.add_parser("classify"); classify.add_argument("text"); classify.add_argument("--active-skill")
    evaluate = sub.add_parser("evaluate"); evaluate.add_argument("--payload-json"); evaluate.add_argument("--payload-file"); evaluate.add_argument("--framework", default="portable")
    analyze_parser = sub.add_parser("analyze"); analyze_parser.add_argument("command_line")
    approve_parser = sub.add_parser("approve"); approve_parser.add_argument("command_line"); approve_parser.add_argument("--category", required=True); approve_parser.add_argument("--by", required=True); approve_parser.add_argument("--ttl-minutes", type=int, default=15)
    check_parser = sub.add_parser("check"); check_parser.add_argument("command_line"); check_parser.add_argument("--consume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    runtime = _load_runtime()
    if args.command == "packs":
        _emit({"packs": packs()}); return 0
    if args.command == "status":
        store = IntelligenceStore(root)
        _emit({"root": str(root), "mode": runtime.current_mode(root), "packs": [item["id"] for item in packs()], "database": str(store.path), "authority": "sqlite", "high_risk_approval": "separate-from-prompt-mitigation"}); return 0
    if args.command == "mode":
        _emit(runtime.set_mode(root, args.value)); return 0
    if args.command == "classify":
        _emit(runtime.classify(args.text, active_skill=args.active_skill, runtime_root=ROOT / "behavior")); return 0
    if args.command == "evaluate":
        if bool(args.payload_json) == bool(args.payload_file):
            raise ValueError("provide exactly one of --payload-json or --payload-file")
        payload = json.loads(args.payload_json) if args.payload_json else json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
        _emit(runtime.evaluate(payload, framework=args.framework, runtime_root=ROOT / "behavior", project_root=root)); return 0
    store = IntelligenceStore(root)
    if args.command == "analyze":
        _emit(analyze(args.command_line))
    elif args.command == "approve":
        _emit(approve(store, args.command_line, args.category, args.by, args.ttl_minutes))
    elif args.command == "check":
        _emit(check(store, args.command_line, consume=args.consume))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
