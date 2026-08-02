#!/usr/bin/env python3
"""Minimal, dependency-free claim/evidence ledger CLI."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, sys, tempfile
from pathlib import Path

SCHEMA = 1

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def default():
    return {"schema_version": SCHEMA, "updated_at": now(), "claims": [], "evidence": [], "relations": [], "decisions": [], "limitations": []}
def load(path: Path):
    if not path.exists(): return default()
    return json.loads(path.read_text(encoding="utf-8"))
def atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2); f.write("\n")
        if path.exists(): path.with_suffix(path.suffix + ".bak").write_bytes(path.read_bytes())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
def parse_json(s):
    try: return json.loads(s)
    except json.JSONDecodeError: return s
def find(items, key): return next((x for x in items if x.get("id") == key), None)

def validate(data):
    errors=[]
    ids=set()
    for coll in ("claims","evidence","decisions","limitations"):
        for x in data.get(coll,[]):
            if not x.get("id"): errors.append(f"{coll}: missing id")
            elif x["id"] in ids: errors.append(f"duplicate id {x['id']}")
            else: ids.add(x["id"])
    claim_ids={x.get("id") for x in data.get("claims",[])}
    ev_ids={x.get("id") for x in data.get("evidence",[])}
    for r in data.get("relations",[]):
        if r.get("claim_id") not in claim_ids: errors.append(f"relation missing claim {r.get('claim_id')}")
        if r.get("evidence_id") not in ev_ids: errors.append(f"relation missing evidence {r.get('evidence_id')}")
    for c in data.get("claims",[]):
        if c.get("status") in {"supported","independently_verified","approved_for_writing"}:
            if not any(r.get("claim_id")==c.get("id") and r.get("type") in {"supports","reproduces","bounds"} for r in data.get("relations",[])):
                errors.append(f"claim {c.get('id')} has supported status but no supporting relation")
    return errors

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--file", default=".research/evidence/ledger.json")
    sp=ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("init")
    add=sp.add_parser("add"); add.add_argument("kind", choices=["claim","evidence","decision","limitation"]); add.add_argument("--id", required=True); add.add_argument("--json", required=True)
    link=sp.add_parser("link"); link.add_argument("--claim", required=True); link.add_argument("--evidence", required=True); link.add_argument("--type", choices=["supports","contradicts","bounds","contextualizes","reproduces","supersedes"], required=True); link.add_argument("--note", default="")
    status=sp.add_parser("status"); status.add_argument("--claim", required=True); status.add_argument("--value", required=True)
    sp.add_parser("validate"); sp.add_parser("coverage")
    args=ap.parse_args(); path=Path(args.file); data=load(path)
    if args.cmd=="init": atomic(path,data); print(path); return
    if args.cmd=="add":
        coll=args.kind+"s" if args.kind!="evidence" else "evidence"
        obj=parse_json(args.json)
        if not isinstance(obj,dict): raise SystemExit("--json must be an object")
        obj={"id":args.id,"created_at":now(),**obj}
        if find(data[coll],args.id): raise SystemExit(f"duplicate id {args.id}")
        data[coll].append(obj); atomic(path,data); print(args.id); return
    if args.cmd=="link":
        data["relations"].append({"id":f"REL-{len(data['relations'])+1:04d}","claim_id":args.claim,"evidence_id":args.evidence,"type":args.type,"note":args.note,"created_at":now()}); atomic(path,data); return
    if args.cmd=="status":
        c=find(data["claims"],args.claim)
        if not c: raise SystemExit("claim not found")
        c["status"]=args.value; atomic(path,data); return
    errs=validate(data)
    if args.cmd=="validate":
        if errs: print("\n".join(errs)); raise SystemExit(1)
        print("ledger valid"); return
    if args.cmd=="coverage":
        rel={r.get("claim_id") for r in data.get("relations",[]) if r.get("type") in {"supports","reproduces","bounds"}}
        total=len(data.get("claims",[])); covered=sum(c.get("id") in rel for c in data.get("claims",[]))
        print(json.dumps({"claims":total,"covered":covered,"coverage": covered/total if total else 0,"errors":errs},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
