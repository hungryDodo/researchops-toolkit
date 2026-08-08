#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def digest(obj): return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def main():
 p=argparse.ArgumentParser(); s=p.add_subparsers(dest='cmd',required=True)
 n=s.add_parser('new'); n.add_argument('--out',required=True); n.add_argument('--title',required=True); n.add_argument('--risk',choices=['low','medium','high','critical'],default='medium')
 v=s.add_parser('verify'); v.add_argument('--contract',required=True); v.add_argument('--evidence',required=True)
 a=p.parse_args()
 if a.cmd=='new':
  obj={'schema_version':1,'title':a.title,'risk':a.risk,'objective':'','non_goals':[],'acceptance':[],'interfaces':[],'dependency_budget':[],'rollback':'','baseline_or_red':None}; obj['contract_hash']=digest(obj); Path(a.out).write_text(json.dumps(obj,indent=2)+'\n'); print(obj['contract_hash']); return
 c=json.loads(Path(a.contract).read_text()); e=json.loads(Path(a.evidence).read_text()); errors=[]
 if not c.get('acceptance'): errors.append('missing acceptance contract')
 if c.get('risk') in {'medium','high','critical'} and not c.get('baseline_or_red'): errors.append('missing baseline/RED observation')
 for k in ('commands','checks','artifacts','residual_risks'):
  if k not in e: errors.append('evidence missing '+k)
 print(json.dumps({'accepted':not errors,'contract_hash':c.get('contract_hash'),'errors':errors},indent=2)); raise SystemExit(1 if errors else 0)
if __name__=='__main__':main()
