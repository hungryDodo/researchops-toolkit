#!/usr/bin/env python3
from __future__ import annotations
import argparse,datetime as dt,json,hashlib
from pathlib import Path

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def token(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def main():
    ap=argparse.ArgumentParser(); sp=ap.add_subparsers(dest='cmd',required=True)
    p=sp.add_parser('new-spec'); p.add_argument('--out',required=True); p.add_argument('--title',required=True); p.add_argument('--risk',choices=['low','medium','high'],required=True)
    p=sp.add_parser('verify'); p.add_argument('--spec',required=True); p.add_argument('--evidence',required=True)
    a=ap.parse_args()
    if a.cmd=='new-spec':
        core={'schema_version':1,'title':a.title,'risk':a.risk,'created_at':now(),'desired_behavior':[],'invariants':[],'forbidden_behavior':[],'interfaces':[],'dependency_budget':{'new_dependencies':[]},'acceptance_evidence':[],'approval':None,'red_observation':None}
        core['spec_hash']=token(core); Path(a.out).write_text(json.dumps(core,indent=2)+'\n',encoding='utf-8'); print(core['spec_hash']); return
    spec=json.loads(Path(a.spec).read_text(encoding='utf-8')); ev=json.loads(Path(a.evidence).read_text(encoding='utf-8')); errors=[]
    if not spec.get('red_observation'): errors.append('missing observed RED')
    if spec.get('risk') in {'medium','high'} and not spec.get('approval'): errors.append('missing approval')
    for k in ('commands','environment','checks','residual_risks','artifacts'):
        if not ev.get(k): errors.append('evidence missing '+k)
    out={'accepted':not errors,'spec_hash':spec.get('spec_hash'),'errors':errors}; print(json.dumps(out,indent=2)); raise SystemExit(1 if errors else 0)
if __name__=='__main__':main()
