#!/usr/bin/env python3
"""Capture and execute a command in an immutable run directory."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, platform, shlex, subprocess, sys, tempfile
from pathlib import Path

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def git_info(cwd):
    def run(args):
        p=subprocess.run(args,cwd=cwd,text=True,capture_output=True)
        return p.stdout.strip() if p.returncode==0 else None
    return {"commit":run(["git","rev-parse","HEAD"]),"branch":run(["git","branch","--show-current"]),"dirty":bool(run(["git","status","--porcelain"]))}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--run-id',required=True); ap.add_argument('--design-id',required=True); ap.add_argument('--config'); ap.add_argument('--timeout',type=int,default=0); ap.add_argument('command',nargs=argparse.REMAINDER)
    a=ap.parse_args(); cmd=a.command[1:] if a.command[:1]==['--'] else a.command
    if not cmd: raise SystemExit('command required after --')
    root=Path(a.root).resolve(); d=root/'.researchops'/'state'/'runs'/a.run_id
    if d.exists(): raise SystemExit(f'run directory exists: {d}')
    d.mkdir(parents=True)
    config=json.loads(Path(a.config).read_text()) if a.config else {}
    env={"captured_at":now(),"platform":platform.platform(),"python":sys.version,"machine":platform.machine(),"processor":platform.processor(),"cwd":str(root),"git":git_info(root),"selected_env":{k:v for k,v in os.environ.items() if k.startswith(('CUDA_','NVIDIA_','OMP_','MKL_','TOKENIZERS_'))}}
    (d/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    (d/'environment.json').write_text(json.dumps(env,indent=2)+'\n')
    (d/'command.txt').write_text(shlex.join(cmd)+'\n')
    start=now(); status='failed'; rc=None
    try:
        with (d/'stdout.log').open('w') as out,(d/'stderr.log').open('w') as err:
            p=subprocess.run(cmd,cwd=root,stdout=out,stderr=err,timeout=a.timeout or None)
        rc=p.returncode; status='complete' if rc==0 else 'failed'
    except subprocess.TimeoutExpired:
        status='failed'; rc=124; (d/'stderr.log').write_text('TIMEOUT\n',encoding='utf-8')
    artifacts=[]
    for p in sorted(d.iterdir()):
        if p.is_file() and p.name!='run.json': artifacts.append({"path":p.name,"bytes":p.stat().st_size,"sha256":sha(p)})
    run={"schema_version":1,"run_id":a.run_id,"design_id":a.design_id,"started_at":start,"finished_at":now(),"status":status,"return_code":rc,"command":cmd,"artifacts":artifacts}
    (d/'run.json').write_text(json.dumps(run,indent=2)+'\n')
    print(d); raise SystemExit(0 if status=='complete' else 1)
if __name__=='__main__': main()
