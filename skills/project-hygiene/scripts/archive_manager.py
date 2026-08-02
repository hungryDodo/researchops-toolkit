#!/usr/bin/env python3
"""Archive-first isolation, restore, and separately approved purge.

This tool is deliberately explicit: paths are selected by a human/owner, plans are
content-bound, apply is non-overwriting, and purge requires a second plan/token.
Archive on the same filesystem improves clarity but does not reclaim disk space.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,os,shutil,subprocess,tempfile
from pathlib import Path
from typing import Any
UTC=dt.timezone.utc

def now(): return dt.datetime.now(UTC)
def iso(v=None): return (v or now()).replace(microsecond=0).isoformat().replace('+00:00','Z')
def canonical(obj): return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def atomic(path:Path,data:Any):
    path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=str(path.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2,sort_keys=True); f.write('\n')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
def sha_file(path:Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()
def tree_snapshot(path:Path)->dict[str,Any]:
    if path.is_symlink(): raise SystemExit(f'symlink not allowed: {path}')
    if path.is_file():
        st=path.stat(); return {'kind':'file','size_bytes':st.st_size,'sha256':sha_file(path),'entries':1}
    if not path.is_dir(): raise SystemExit(f'not a file or directory: {path}')
    h=hashlib.sha256(); total=0; entries=0
    for p in sorted(path.rglob('*')):
        if p.is_symlink(): raise SystemExit(f'symlink inside archive candidate: {p}')
        if not p.is_file(): continue
        rel=p.relative_to(path).as_posix(); size=p.stat().st_size; digest=sha_file(p)
        h.update(rel.encode()); h.update(b'\0'); h.update(str(size).encode()); h.update(b'\0'); h.update(digest.encode()); h.update(b'\n')
        total+=size; entries+=1
    return {'kind':'directory','size_bytes':total,'sha256':h.hexdigest(),'entries':entries}
def safe_under(root:Path,p:Path):
    try:p.resolve(strict=False).relative_to(root.resolve()); return True
    except ValueError:return False
def rel(root:Path,p:Path): return p.resolve(strict=False).relative_to(root.resolve()).as_posix()
def git_tracked(root:Path,rp:str):
    cp=subprocess.run(['git','ls-files','--error-unmatch','--',rp],cwd=root,text=True,capture_output=True)
    return cp.returncode==0
def state_references(root:Path,rp:str)->list[str]:
    hits=[]
    for p in [root/'.research/evidence/ledger.json',root/'.research/dashboard/project.json',root/'.research/hygiene/asset-registry.json']:
        if p.exists() and rp in p.read_text(encoding='utf-8',errors='ignore'): hits.append(rel(root,p))
    return hits
def init(root:Path):
    for p in (root/'.research/archive',root/'.research/hygiene/archive-plans'): p.mkdir(parents=True,exist_ok=True)

def build_plan(root:Path,paths:list[str],reason:str,out:Path,allow_tracked:bool=False,allow_referenced:bool=False,archive_root:Path|None=None):
    init(root); archive_root=(archive_root or root/'.research/archive').resolve(); actions=[]
    forbidden={'.git','.research/archive','.research/trash'}
    for raw in paths:
        p=(root/raw).resolve(strict=False) if not Path(raw).is_absolute() else Path(raw).resolve(strict=False)
        if not safe_under(root,p): actions.append({'source':raw,'safe_to_apply':False,'reason':'outside project root'}); continue
        rp=rel(root,p)
        if any(rp==x or rp.startswith(x+'/') for x in forbidden): actions.append({'source':rp,'safe_to_apply':False,'reason':'protected control directory'}); continue
        if not p.exists(): actions.append({'source':rp,'safe_to_apply':False,'reason':'missing'}); continue
        active=(p/'.ACTIVE').exists() if p.is_dir() else any((parent/'.ACTIVE').exists() for parent in p.parents if safe_under(root,parent))
        tracked=git_tracked(root,rp); refs=state_references(root,rp); blockers=[]
        if active: blockers.append('ACTIVE marker')
        if tracked and not allow_tracked: blockers.append('tracked by Git')
        if refs and not allow_referenced: blockers.append('referenced by research state: '+', '.join(refs))
        snap=tree_snapshot(p)
        actions.append({'source':rp,'safe_to_apply':not blockers,'reason':reason if not blockers else '; '.join(blockers),'snapshot':snap,'tracked_by_git':tracked,'research_state_references':refs})
    batch=now().strftime('%Y%m%dT%H%M%SZ')+'-'+canonical([x.get('source') for x in actions])[:8]
    core={'schema_version':1,'operation':'archive','generated_at':iso(),'root':str(root),'archive_root':str(archive_root),'batch_id':batch,'reason':reason,'actions':actions}
    data={**core,'approval_token':canonical(core),'summary':{'selected':len(actions),'safe':sum(bool(x.get('safe_to_apply')) for x in actions),'bytes':sum(int(x.get('snapshot',{}).get('size_bytes',0)) for x in actions if x.get('safe_to_apply')),'same_filesystem_archive':False}}
    try:data['summary']['same_filesystem_archive']=os.stat(root).st_dev==os.stat(archive_root.parent if archive_root.exists() else archive_root.parent).st_dev
    except OSError:pass
    atomic(out,data); return data
def verify_plan(root:Path,plan:dict[str,Any],token:str,operation:str):
    if token!=plan.get('approval_token'): raise SystemExit('approval token mismatch')
    if str(root)!=plan.get('root'): raise SystemExit('plan root mismatch')
    core={k:v for k,v in plan.items() if k not in {'approval_token','summary'}}
    if canonical(core)!=token: raise SystemExit('plan content changed')
    if plan.get('operation')!=operation: raise SystemExit('wrong plan operation')
def move(src:Path,dst:Path):
    dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists(): raise SystemExit(f'destination exists: {dst}')
    try:os.replace(src,dst)
    except OSError:shutil.move(str(src),str(dst))
def apply_archive(root:Path,plan_path:Path,token:str):
    plan=json.loads(plan_path.read_text(encoding='utf-8')); verify_plan(root,plan,token,'archive'); archive_root=Path(plan['archive_root']); batch_root=archive_root/plan['batch_id']; events=[]
    for a in plan['actions']:
        if not a.get('safe_to_apply'): continue
        src=root/a['source']
        if not src.exists(): events.append({'source':a['source'],'status':'blocked','reason':'missing at apply'}); continue
        current=tree_snapshot(src)
        if current!=a['snapshot']: events.append({'source':a['source'],'status':'blocked','reason':'snapshot changed'}); continue
        dst=batch_root/'content'/a['source']; move(src,dst)
        events.append({'source':a['source'],'archive_path':str(dst.resolve()),'status':'archived','snapshot':current})
    manifest={'schema_version':1,'batch_id':plan['batch_id'],'archived_at':iso(),'root':str(root),'archive_root':str(archive_root),'reason':plan['reason'],'plan_token':token,'events':events,'restore_status':'available'}
    atomic(batch_root/'manifest.json',manifest); atomic(root/'.research/hygiene/last-archive.json',manifest); return manifest
def find_batch(root:Path,batch:str,archive_root:Path|None=None):
    ar=(archive_root or root/'.research/archive').resolve(); p=ar/batch
    if not (p/'manifest.json').exists(): raise SystemExit(f'archive batch not found: {p}')
    return p,json.loads((p/'manifest.json').read_text(encoding='utf-8'))
def restore_plan(root:Path,batch:str,out:Path,archive_root:Path|None=None):
    br,m=find_batch(root,batch,archive_root); actions=[]
    for e in m['events']:
        if e.get('status')!='archived': continue
        src=Path(e['archive_path']); dst=root/e['source']; blockers=[]
        if dst.exists(): blockers.append('destination exists')
        if not src.exists(): blockers.append('archive content missing')
        elif tree_snapshot(src)!=e['snapshot']: blockers.append('archive snapshot changed')
        actions.append({'source':str(src),'destination':e['source'],'snapshot':e['snapshot'],'safe_to_apply':not blockers,'reason':'; '.join(blockers) if blockers else 'restorable'})
    core={'schema_version':1,'operation':'restore','generated_at':iso(),'root':str(root),'batch_id':batch,'batch_root':str(br),'actions':actions}
    data={**core,'approval_token':canonical(core),'summary':{'safe':sum(bool(x['safe_to_apply']) for x in actions),'blocked':sum(not bool(x['safe_to_apply']) for x in actions)}}; atomic(out,data); return data
def apply_restore(root:Path,plan_path:Path,token:str):
    plan=json.loads(plan_path.read_text()); verify_plan(root,plan,token,'restore'); events=[]
    for a in plan['actions']:
        if not a['safe_to_apply']:continue
        src=Path(a['source']); dst=root/a['destination']
        if dst.exists() or not src.exists() or tree_snapshot(src)!=a['snapshot']: events.append({'destination':a['destination'],'status':'blocked'}); continue
        move(src,dst); events.append({'destination':a['destination'],'status':'restored'})
    br=Path(plan['batch_root']); m=json.loads((br/'manifest.json').read_text()); m['restore_status']='partially_or_fully_restored'; m['last_restore_at']=iso(); m['restore_events']=events; atomic(br/'manifest.json',m); return {'events':events}
def parse_time(s): return dt.datetime.fromisoformat(s.replace('Z','+00:00'))
def purge_plan(root:Path,batch:str,out:Path,min_age_days:int,archive_root:Path|None=None):
    br,m=find_batch(root,batch,archive_root); age=(now()-parse_time(m['archived_at'])).total_seconds()/86400; snap=tree_snapshot(br); safe=age>=min_age_days
    core={'schema_version':1,'operation':'archive-purge','generated_at':iso(),'root':str(root),'batch_id':batch,'batch_root':str(br),'snapshot':snap,'minimum_age_days':min_age_days,'age_days':age,'safe_to_apply':safe,'reason':'retention met' if safe else 'retention not met'}
    data={**core,'approval_token':canonical(core)}; atomic(out,data); return data
def apply_purge(root:Path,plan_path:Path,token:str):
    plan=json.loads(plan_path.read_text()); verify_plan(root,plan,token,'archive-purge')
    if not plan.get('safe_to_apply'): raise SystemExit('purge plan is not safe to apply')
    br=Path(plan['batch_root']); ar=root/'.research/archive'
    if not safe_under(ar,br): raise SystemExit('default purge only permits project .research/archive')
    if not br.exists() or tree_snapshot(br)!=plan['snapshot']: raise SystemExit('archive batch changed')
    shutil.rmtree(br); result={'batch_id':plan['batch_id'],'status':'purged','at':iso(),'plan_token':token}; atomic(root/'.research/hygiene/last-archive-purge.json',result); return result
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); sp=ap.add_subparsers(dest='cmd',required=True)
    sp.add_parser('init')
    p=sp.add_parser('plan'); p.add_argument('--path',action='append',required=True); p.add_argument('--reason',required=True); p.add_argument('--out',required=True); p.add_argument('--allow-tracked',action='store_true'); p.add_argument('--allow-referenced',action='store_true'); p.add_argument('--archive-root')
    p=sp.add_parser('apply'); p.add_argument('--plan',required=True); p.add_argument('--approve-token',required=True)
    p=sp.add_parser('restore-plan'); p.add_argument('--batch',required=True); p.add_argument('--out',required=True); p.add_argument('--archive-root')
    p=sp.add_parser('restore'); p.add_argument('--plan',required=True); p.add_argument('--approve-token',required=True)
    p=sp.add_parser('purge-plan'); p.add_argument('--batch',required=True); p.add_argument('--out',required=True); p.add_argument('--min-age-days',type=int,default=30); p.add_argument('--archive-root')
    p=sp.add_parser('purge'); p.add_argument('--plan',required=True); p.add_argument('--approve-token',required=True)
    a=ap.parse_args(); root=Path(a.root).resolve()
    if a.cmd=='init': init(root); print(root/'.research/archive'); return
    if a.cmd=='plan':
        d=build_plan(root,a.path,a.reason,Path(a.out),a.allow_tracked,a.allow_referenced,Path(a.archive_root) if a.archive_root else None); print(json.dumps({'approval_token':d['approval_token'],'summary':d['summary'],'batch_id':d['batch_id']},indent=2)); return
    if a.cmd=='apply': print(json.dumps(apply_archive(root,Path(a.plan),a.approve_token),indent=2)); return
    if a.cmd=='restore-plan':
        d=restore_plan(root,a.batch,Path(a.out),Path(a.archive_root) if a.archive_root else None); print(json.dumps({'approval_token':d['approval_token'],'summary':d['summary']},indent=2)); return
    if a.cmd=='restore': print(json.dumps(apply_restore(root,Path(a.plan),a.approve_token),indent=2)); return
    if a.cmd=='purge-plan':
        d=purge_plan(root,a.batch,Path(a.out),a.min_age_days,Path(a.archive_root) if a.archive_root else None); print(json.dumps({'approval_token':d['approval_token'],'safe_to_apply':d['safe_to_apply'],'age_days':d['age_days']},indent=2)); return
    if a.cmd=='purge': print(json.dumps(apply_purge(root,Path(a.plan),a.approve_token),indent=2)); return
if __name__=='__main__':main()
