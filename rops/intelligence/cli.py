from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from ..common import now
from . import benchmarks, drift, judges, memory, mitigations, patterns, warmup
from .events import record_event
from .projections import rebuild_projections
from .routing import recommend
from .store import IntelligenceStore


def _load_json(value: str | None, path: str | None) -> dict[str, Any]:
    if value:
        data = json.loads(value)
    elif path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        data = json.load(sys.stdin)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def _emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _bool(value: str | None) -> bool | None:
    if value is None or value == "unknown":
        return None
    return value == "true"


def _export_jsonl(store: IntelligenceStore, path: Path) -> dict[str, Any]:
    rows = store.query("SELECT raw_json FROM evaluation_events ORDER BY occurred_at,event_id")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(json.loads(row["raw_json"]), ensure_ascii=False, sort_keys=True) + "\n")
    return {"path": str(path), "events": len(rows), "authority": False, "format": "audit-export"}


def _import_jsonl(store: IntelligenceStore, path: Path, project_id: str | None) -> dict[str, Any]:
    imported, skipped, errors = 0, 0, []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            record_event(store, raw, project_id=project_id)
            imported += 1
        except Exception as exc:  # migration must report, never silently lose data
            if "UNIQUE constraint failed" in str(exc):
                skipped += 1
            else:
                errors.append({"line": line_number, "error": str(exc)})
    result = {"path": str(path), "imported": imported, "skipped": skipped, "errors": errors}
    if imported:
        result["projections"] = rebuild_projections(store)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rops intelligence", description="Project-scoped model intelligence")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("status")

    record = sub.add_parser("record")
    record.add_argument("--event-json")
    record.add_argument("--event-file")
    record.add_argument("--project-id")
    record.add_argument("--no-rebuild", action="store_true")

    sub.add_parser("rebuild")
    sub.add_parser("benchmark-list")
    bv = sub.add_parser("benchmark-validate")
    bv.add_argument("--pack")
    export = sub.add_parser("export-jsonl")
    export.add_argument("--out", required=True)
    imp = sub.add_parser("import-jsonl")
    imp.add_argument("path")
    imp.add_argument("--project-id")

    route = sub.add_parser("route")
    route.add_argument("--task-json")
    route.add_argument("--task-file")
    route.add_argument("--agent")
    route.add_argument("--no-write", action="store_true")
    route.add_argument("--seed", type=int)

    wi = sub.add_parser("warmup-init")
    wi.add_argument("--project-id", required=True)
    wi.add_argument("--arm-id", required=True)
    wi.add_argument("--operation", required=True)
    wi.add_argument("--primary-artifact", default="unknown")
    wi.add_argument("--acceptance-profile")
    wi.add_argument("--mode", choices=["zero", "conservative", "normal"], default="conservative")
    ws = sub.add_parser("warmup-status")
    ws.add_argument("--project-id")
    ws.add_argument("--arm-id")
    ws.add_argument("--operation")

    sub.add_parser("patterns-rebuild")
    pl = sub.add_parser("patterns-list")
    pl.add_argument("--status")
    pc = sub.add_parser("pattern-confirm")
    pc.add_argument("--id", required=True)
    pc.add_argument("--by", required=True)

    mp = sub.add_parser("mitigation-propose")
    mp.add_argument("--type", required=True)
    mp.add_argument("--scope-json", required=True)
    mp.add_argument("--content-json", required=True)
    mp.add_argument("--pattern-id", action="append", default=[])
    ma = sub.add_parser("mitigation-approve")
    ma.add_argument("--id", required=True)
    ma.add_argument("--by", required=True)
    ms = sub.add_parser("mitigation-status")
    ms.add_argument("--id", required=True)
    ms.add_argument("--status", required=True)
    mc = sub.add_parser("mitigation-compile")
    mc.add_argument("--arm-id", required=True)
    mc.add_argument("--project-id", required=True)
    mc.add_argument("--operation", required=True)
    mc.add_argument("--task-contract", required=True)
    mc.add_argument("--role", default="")
    mc.add_argument("--task-id")

    ep = sub.add_parser("endpoint-record")
    ep.add_argument("--endpoint-id", required=True)
    ep.add_argument("--arm-id")
    ep.add_argument("--success", action="store_true")
    ep.add_argument("--latency", type=float, default=0.0)
    ep.add_argument("--ttft", type=float)
    ep.add_argument("--error-class")
    ep.add_argument("--rate-limited", action="store_true")

    price = sub.add_parser("price-set")
    price.add_argument("--provider", required=True)
    price.add_argument("--model-family", required=True)
    price.add_argument("--endpoint-id")
    price.add_argument("--valid-from", default=None)
    price.add_argument("--valid-to")
    price.add_argument("--rule-json", required=True)

    identity = sub.add_parser("identity-record")
    identity.add_argument("--arm-id", required=True)
    identity.add_argument("--endpoint-id")
    identity.add_argument("--declared-json", required=True)
    identity.add_argument("--fingerprint-json", required=True)
    dd = sub.add_parser("drift-detect")
    dd.add_argument("--arm-id", required=True)
    dd.add_argument("--endpoint-id")
    epoch = sub.add_parser("epoch-create")
    epoch.add_argument("--arm-id", required=True)
    epoch.add_argument("--endpoint-id")
    epoch.add_argument("--declared-json", default="{}")
    epoch.add_argument("--fingerprint-json", default="{}")

    jr = sub.add_parser("judge-record")
    jr.add_argument("--judge-arm-id", required=True)
    jr.add_argument("--task-family", required=True)
    jr.add_argument("--agrees", choices=["true", "false", "unknown"], default="unknown")
    jr.add_argument("--position-consistent", choices=["true", "false", "unknown"], default="unknown")
    jr.add_argument("--abstained", action="store_true")
    jr.add_argument("--confidence", type=float)
    jp = sub.add_parser("judge-profile")
    jp.add_argument("--judge-arm-id", required=True)
    jp.add_argument("--task-family", required=True)
    jc = sub.add_parser("judge-cascade")
    jc.add_argument("--judge-arm-id", action="append", required=True)
    jc.add_argument("--task-family", required=True)
    jc.add_argument("--high-risk", action="store_true")
    jpr = sub.add_parser("judge-pairwise-record")
    jpr.add_argument("--judge-arm-id", required=True)
    jpr.add_argument("--task-family", required=True)
    jpr.add_argument("--item-a", required=True)
    jpr.add_argument("--item-b", required=True)
    jpr.add_argument("--result", choices=["a", "b", "tie", "abstain"], required=True)
    jpr.add_argument("--swapped-result", choices=["a", "b", "tie", "abstain"])
    jpr.add_argument("--evidence-package-hash")
    jpr.add_argument("--rubric-revision")
    jpr.add_argument("--prompt-revision")
    jpr.add_argument("--confidence", type=float)
    jrank = sub.add_parser("judge-rank")
    jrank.add_argument("--task-family", required=True)

    mm = sub.add_parser("memory-add")
    mm.add_argument("--scope", required=True)
    mm.add_argument("--layer", choices=sorted(memory.LAYERS), default="semantic")
    mm.add_argument("--kind", required=True)
    mm.add_argument("--title", required=True)
    mm.add_argument("--body", required=True)
    mm.add_argument("--status", choices=sorted(memory.STATUSES), default="active")
    mm.add_argument("--confidence", type=float, default=1.0)
    mm.add_argument("--salience", type=float, default=0.5)
    mm.add_argument("--source-type")
    mm.add_argument("--source-id")
    mm.add_argument("--valid-from")
    mm.add_argument("--valid-to")
    mm.add_argument("--metadata-json", default="{}")
    mm.add_argument("--provenance-json", default="{}")
    msearch = sub.add_parser("memory-search")
    msearch.add_argument("query")
    msearch.add_argument("--scope", default="*")
    msearch.add_argument("--as-of")
    msearch.add_argument("--limit", type=int, default=10)
    msearch.add_argument("--layer", action="append", choices=sorted(memory.LAYERS))
    msearch.add_argument("--include-candidates", action="store_true")
    mget = sub.add_parser("memory-get")
    mget.add_argument("memory_id")
    mstatus = sub.add_parser("memory-status")
    msync = sub.add_parser("memory-sync")
    mcontext = sub.add_parser("memory-context")
    mcontext.add_argument("query")
    mcontext.add_argument("--scope", default="*")
    mcontext.add_argument("--max-items", type=int, default=8)
    mcontext.add_argument("--max-chars", type=int, default=6000)
    mretire = sub.add_parser("memory-retire")
    mretire.add_argument("memory_id")
    mretire.add_argument("--reason", default="")
    msuper = sub.add_parser("memory-supersede")
    msuper.add_argument("old_id")
    msuper.add_argument("new_id")
    msuper.add_argument("--reason", default="")
    mr = sub.add_parser("memory-relate")
    mr.add_argument("source_id")
    mr.add_argument("target_id")
    mr.add_argument("relation_type")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command
    # Benchmark-pack inspection is package-local and read-only.  Do not create
    # a project database merely because a maintainer validates bundled packs.
    if command == "benchmark-list":
        _emit(benchmarks.validate_all())
        return 0
    if command == "benchmark-validate":
        if args.pack:
            pack = benchmarks.get(args.pack)
            _emit({"pack": pack, "errors": benchmarks.validate_pack(pack)})
        else:
            _emit(benchmarks.validate_all())
        return 0

    store = IntelligenceStore(Path(args.root).resolve())
    if command == "init":
        _emit({"initialized": True, "layout": store.layout.describe(), "database": str(store.path), "authority": "sqlite"})
    elif command == "status":
        _emit({
            "database": str(store.path),
            "events": int(store.scalar("SELECT COUNT(*) n FROM evaluation_events", default=0)),
            "profiles": int(store.scalar("SELECT COUNT(*) n FROM profile_slices", default=0)),
            "patterns": int(store.scalar("SELECT COUNT(*) n FROM failure_patterns", default=0)),
            "mitigations": int(store.scalar("SELECT COUNT(*) n FROM mitigations", default=0)),
            "route_decisions": int(store.scalar("SELECT COUNT(*) n FROM route_decisions", default=0)),
            "warmup": warmup.all_warmup_states(store),
            "memory": memory.status(store),
        })
    elif command == "record":
        event = record_event(store, _load_json(args.event_json, args.event_file), project_id=args.project_id)
        result: dict[str, Any] = {"recorded": event}
        if not args.no_rebuild:
            patterns.rebuild_patterns(store)
            result["memory_sync"] = memory.sync_from_project(store)
            result["projections"] = rebuild_projections(store)
        _emit(result)
    elif command == "rebuild":
        rebuilt_patterns = patterns.rebuild_patterns(store)
        memory_sync = memory.sync_from_project(store)
        _emit({"patterns": rebuilt_patterns, "memory_sync": memory_sync, "projections": rebuild_projections(store)})
    elif command == "export-jsonl":
        _emit(_export_jsonl(store, Path(args.out)))
    elif command == "import-jsonl":
        _emit(_import_jsonl(store, Path(args.path), args.project_id))
    elif command == "route":
        _emit(recommend(store, _load_json(args.task_json, args.task_file), agent_name=args.agent, write=not args.no_write, random_seed=args.seed))
    elif command == "warmup-init":
        _emit(warmup.initialize_transfer(store, project_id=args.project_id, arm_id=args.arm_id, operation=args.operation, primary_artifact=args.primary_artifact, acceptance_profile=args.acceptance_profile, mode=args.mode))
    elif command == "warmup-status":
        if args.project_id and args.arm_id and args.operation:
            _emit(warmup.warmup_state(store, args.project_id, args.arm_id, args.operation))
        else:
            _emit({"warmup": warmup.all_warmup_states(store)})
    elif command == "patterns-rebuild":
        _emit(patterns.rebuild_patterns(store))
    elif command == "patterns-list":
        sql, params = "SELECT * FROM failure_patterns", ()
        if args.status:
            sql, params = sql + " WHERE status=?", (args.status,)
        _emit({"patterns": store.json_rows(sql + " ORDER BY last_seen DESC", params, ("representative_json",))})
    elif command == "pattern-confirm":
        _emit(patterns.approve_pattern(store, args.id, args.by))
    elif command == "mitigation-propose":
        _emit(mitigations.propose(store, args.type, json.loads(args.scope_json), json.loads(args.content_json), pattern_ids=args.pattern_id))
    elif command == "mitigation-approve":
        _emit(mitigations.approve(store, args.id, args.by))
    elif command == "mitigation-status":
        _emit(mitigations.set_status(store, args.id, args.status))
    elif command == "mitigation-compile":
        _emit(mitigations.compile_prompt(store, arm_id=args.arm_id, project_id=args.project_id, operation=args.operation, task_contract=args.task_contract, role=args.role, task_id=args.task_id))
    elif command == "endpoint-record":
        _emit(drift.record_endpoint_observation(store, endpoint_id=args.endpoint_id, arm_id=args.arm_id, success=args.success, latency_seconds=args.latency, ttft_seconds=args.ttft, error_class=args.error_class, rate_limited=args.rate_limited))
    elif command == "price-set":
        rule_id = "price-" + uuid.uuid4().hex[:16]
        with store.transaction() as connection:
            connection.execute("INSERT INTO pricing_rules(price_rule_id,provider,model_family,endpoint_id,valid_from,valid_to,rule_json) VALUES (?,?,?,?,?,?,?)", (rule_id, args.provider, args.model_family, args.endpoint_id, args.valid_from or now(), args.valid_to, args.rule_json))
        _emit({"price_rule_id": rule_id})
    elif command == "identity-record":
        _emit(drift.record_identity_observation(store, arm_id=args.arm_id, endpoint_id=args.endpoint_id, declared_identity=json.loads(args.declared_json), fingerprint=json.loads(args.fingerprint_json)))
    elif command == "drift-detect":
        _emit(drift.detect(store, arm_id=args.arm_id, endpoint_id=args.endpoint_id))
    elif command == "epoch-create":
        _emit(drift.create_epoch(store, arm_base_id=args.arm_id, endpoint_id=args.endpoint_id, declared_identity=json.loads(args.declared_json), fingerprint=json.loads(args.fingerprint_json)))
    elif command == "judge-record":
        _emit(judges.record(store, judge_arm_id=args.judge_arm_id, task_family=args.task_family, agrees_with_reference=_bool(args.agrees), position_consistent=_bool(args.position_consistent), abstained=args.abstained, confidence=args.confidence))
    elif command == "judge-profile":
        _emit(judges.profile(store, args.judge_arm_id, args.task_family))
    elif command == "judge-cascade":
        _emit(judges.cascade(store, args.judge_arm_id, args.task_family, high_risk=args.high_risk))
    elif command == "judge-pairwise-record":
        _emit(judges.record_pairwise(
            store,
            judge_arm_id=args.judge_arm_id,
            task_family=args.task_family,
            item_a=args.item_a,
            item_b=args.item_b,
            first_result=args.result,
            swapped_result=args.swapped_result,
            evidence_package_hash=args.evidence_package_hash,
            rubric_revision=args.rubric_revision,
            prompt_revision=args.prompt_revision,
            confidence=args.confidence,
        ))
    elif command == "judge-rank":
        _emit(judges.rank_pairwise(store, args.task_family))
    elif command == "memory-add":
        _emit(memory.add(
            store,
            scope=args.scope,
            layer=args.layer,
            kind=args.kind,
            title=args.title,
            body=args.body,
            status=args.status,
            confidence=args.confidence,
            salience=args.salience,
            source_type=args.source_type,
            source_id=args.source_id,
            valid_from=args.valid_from,
            valid_to=args.valid_to,
            metadata=json.loads(args.metadata_json),
            provenance=json.loads(args.provenance_json),
        ))
    elif command == "memory-search":
        _emit({"hits": memory.search(
            store,
            args.query,
            scope=args.scope,
            limit=args.limit,
            as_of=args.as_of,
            layers=args.layer,
            include_candidates=args.include_candidates,
        )})
    elif command == "memory-get":
        _emit(memory.get(store, args.memory_id))
    elif command == "memory-status":
        _emit(memory.status(store))
    elif command == "memory-sync":
        result = memory.sync_from_project(store)
        result["projections"] = rebuild_projections(store)
        _emit(result)
    elif command == "memory-context":
        _emit(memory.context_bundle(
            store,
            args.query,
            scope=args.scope,
            max_items=args.max_items,
            max_chars=args.max_chars,
        ))
    elif command == "memory-retire":
        _emit(memory.retire(store, args.memory_id, reason=args.reason))
    elif command == "memory-supersede":
        _emit(memory.supersede(store, args.old_id, args.new_id, reason=args.reason))
    elif command == "memory-relate":
        _emit(memory.relate(store, args.source_id, args.target_id, args.relation_type))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
