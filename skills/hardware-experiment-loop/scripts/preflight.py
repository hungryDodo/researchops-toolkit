#!/usr/bin/env python3
"""Validate a declarative hardware envelope before any action."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('envelope'); ap.add_argument('--action'); ap.add_argument('--params',default='{}'); a=ap.parse_args()
    data=json.loads(Path(a.envelope).read_text())
    errors=[]
    for k in ('schema_version','devices','allowed_actions','stop_triggers','rollback'):
        if not data.get(k): errors.append(f'missing {k}')
    if a.action:
        allowed={x.get('name'):x for x in data.get('allowed_actions',[])}
        if a.action not in allowed: errors.append(f'action not allowlisted: {a.action}')
        else:
            params=json.loads(a.params)
            spec=allowed[a.action]
            for key,val in params.items():
                lim=spec.get('parameters',{}).get(key)
                if lim and isinstance(val,(int,float)):
                    if 'min' in lim and val<lim['min']: errors.append(f'{key} below min')
                    if 'max' in lim and val>lim['max']: errors.append(f'{key} above max')
            if spec.get('human_approval_required') and not data.get('approval',{}).get('approved'):
                errors.append('human approval required')
    report={'valid':not errors,'errors':errors,'envelope':str(a.envelope),'action':a.action}
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if not errors else 1)
if __name__=='__main__': main()
