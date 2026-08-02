#!/usr/bin/env python3
"""Initialize, upgrade, patch, validate, and serve the ResearchOps Toolkit dashboard."""
from __future__ import annotations
import argparse, datetime as dt, http.server, json, os, shutil, socketserver, tempfile
from pathlib import Path
VERSION="1.4.0"
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def dash(root): return Path(root).resolve()/'.research'/'dashboard'
def state_path(root): return dash(root)/'project.json'
def initial(title):
 return {"schema_version":2,"meta":{"title":title,"suite_version":VERSION,"updated_at":now()},"status":{"phase":"charter","health":"yellow","objective":"Define the research objective and evidence plan.","focus":"Project initialization","owner":"human+agent","next_gate":"Gate 0","blocking_uncertainty":"Research charter not approved","progress":5},"routes":[],"experiments":[],"agents":{"active_dispatches":0,"completed":0,"failed":0,"pending_evaluation":0,"profiles":[]},"evidence":[],"storage":{"total_bytes":0,"cleanup_candidate_bytes":0,"large_files":0,"last_scan":None,"worktrees":[]},"hygiene":{"open_items":0,"bare_public_ids":0,"temporary_tests":0,"last_scan":None,"items":[]},"literature":{"screened":0,"included":0,"queries":0,"items":[]},"capability_proposals":[],"human_actions":[{"id":"HA-001","public_label":"Approve research charter and resource envelope","priority":"high","owner":"human","status":"open"}],"decisions":[],"risks":[],"logs":[{"at":now(),"actor":"dashboard","event":"Project dashboard initialized"}]}
def upgrade_data(data):
 data["schema_version"]=2; data.setdefault("meta",{})["suite_version"]=VERSION
 data.setdefault("agents",{"active_dispatches":0,"completed":0,"failed":0,"pending_evaluation":0,"profiles":[]})
 data.setdefault("storage",{"total_bytes":0,"cleanup_candidate_bytes":0,"large_files":0,"last_scan":None,"worktrees":[]})
 data.setdefault("hygiene",{"open_items":0,"bare_public_ids":0,"temporary_tests":0,"last_scan":None,"items":[]})
 data.setdefault("capability_proposals",[])
 for coll in ("routes","experiments","evidence","human_actions","decisions","risks"):
  for x in data.setdefault(coll,[]):
   if "public_label" not in x:
    x["public_label"]=x.get("name") or x.get("purpose") or x.get("claim") or x.get("title") or x.get("text") or x.get("id","Unnamed")
 return data
def load(root): return json.loads(state_path(root).read_text(encoding='utf-8'))
def save(root,data):
 p=state_path(root); p.parent.mkdir(parents=True,exist_ok=True); data.setdefault('meta',{})['updated_at']=now(); fd,tmp=tempfile.mkstemp(prefix='project.',suffix='.json',dir=str(p.parent))
 try:
  with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2); f.write('\n')
  if p.exists(): shutil.copy2(p,p.with_suffix('.json.bak'))
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp): os.unlink(tmp)
def parts(path): return [int(x) if x.isdigit() else x for x in path.split('.') if x!='']
def get_parent(data,path,create=False):
 ps=parts(path); cur=data
 for k in ps[:-1]:
  if isinstance(k,int): cur=cur[k]
  else:
   if create and k not in cur: cur[k]={}
   cur=cur[k]
 return cur,ps[-1]
def parse(v):
 try:return json.loads(v)
 except json.JSONDecodeError:return v
def validate(data):
 e=[]
 for k in ('schema_version','meta','status','routes','experiments','agents','evidence','storage','hygiene','literature','capability_proposals','human_actions','decisions','risks','logs'):
  if k not in data:e.append(f'missing {k}')
 for coll in ('routes','experiments','evidence','human_actions','decisions','risks'):
  seen=set()
  for x in data.get(coll,[]):
   if not isinstance(x,dict):e.append(f'{coll}: non-object');continue
   i=x.get('id')
   if not i:e.append(f'{coll}: missing internal id')
   elif i in seen:e.append(f'{coll}: duplicate id {i}')
   seen.add(i)
   if not (x.get('public_label') or x.get('name') or x.get('title') or x.get('purpose') or x.get('claim') or x.get('text')): e.append(f'{coll}:{i}: missing semantic/public label')
 return e
def copy_assets(root):
 script_dir=Path(__file__).resolve().parent; canonical=script_dir/'web'; src=canonical if canonical.exists() else script_dir; out=dash(root); out.mkdir(parents=True,exist_ok=True)
 for name in ('index.html','styles.css','app.js'):
  source=src/name; target=out/name
  if source.resolve()!=target.resolve(): shutil.copy2(source,target)
 script_target=out/'dashboard.py'
 if Path(__file__).resolve()!=script_target.resolve(): shutil.copy2(Path(__file__).resolve(),script_target)
def main():
 ap=argparse.ArgumentParser(); sp=ap.add_subparsers(dest='cmd',required=True)
 p=sp.add_parser('init');p.add_argument('--root',default='.');p.add_argument('--title',required=True);p.add_argument('--force',action='store_true')
 p=sp.add_parser('upgrade');p.add_argument('--root',default='.')
 for c in ('set','append'):
  p=sp.add_parser(c);p.add_argument('--root',default='.');p.add_argument('--path',required=True);p.add_argument('--value',required=True)
 p=sp.add_parser('upsert');p.add_argument('--root',default='.');p.add_argument('--path',required=True);p.add_argument('--id',required=True);p.add_argument('--value',required=True)
 p=sp.add_parser('transition');p.add_argument('--root',default='.');p.add_argument('--phase',required=True);p.add_argument('--gate',required=True);p.add_argument('--actor',default='agent')
 p=sp.add_parser('validate');p.add_argument('--root',default='.')
 p=sp.add_parser('serve');p.add_argument('--root',default='.');p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8765)
 a=ap.parse_args(); pth=state_path(a.root)
 if a.cmd=='init':
  if pth.exists() and not a.force: raise SystemExit(f'exists: {pth}')
  copy_assets(a.root); save(a.root,initial(a.title)); print(pth); return
 if not pth.exists(): raise SystemExit('dashboard not initialized')
 if a.cmd=='upgrade': copy_assets(a.root); data=upgrade_data(load(a.root)); save(a.root,data); print(pth); return
 if a.cmd=='validate':
  errs=validate(load(a.root)); print('\n'.join(errs) if errs else 'dashboard valid'); raise SystemExit(1 if errs else 0)
 if a.cmd=='serve':
  copy_assets(a.root); os.chdir(dash(a.root)); handler=http.server.SimpleHTTPRequestHandler
  with socketserver.TCPServer((a.host,a.port),handler) as s: print(f'http://{a.host}:{a.port}'); s.serve_forever()
 data=upgrade_data(load(a.root))
 if a.cmd=='set': parent,key=get_parent(data,a.path,True); parent[key]=parse(a.value)
 elif a.cmd=='append': parent,key=get_parent(data,a.path,True); parent.setdefault(key,[]).append(parse(a.value))
 elif a.cmd=='upsert':
  parent,key=get_parent(data,a.path,True); arr=parent.setdefault(key,[]); obj=parse(a.value)
  if not isinstance(obj,dict): raise SystemExit('--value must be JSON object')
  obj['id']=a.id; hit=next((i for i,x in enumerate(arr) if x.get('id')==a.id),None)
  if hit is None: arr.append(obj)
  else: arr[hit]={**arr[hit],**obj}
 elif a.cmd=='transition':
  old=data['status'].get('phase'); data['status']['phase']=a.phase; data['status']['next_gate']=a.gate; data['logs'].insert(0,{"at":now(),"actor":a.actor,"event":f"Phase {old} → {a.phase}","detail":a.gate})
 errs=validate(data)
 if errs: raise SystemExit('invalid patch: '+'; '.join(errs))
 save(a.root,data); print(pth)
if __name__=='__main__': main()
