#!/usr/bin/env python3
"""Heuristic static audit for third-party Agent Skills. Not a security proof."""
from __future__ import annotations
import argparse, hashlib, json, os, re
from pathlib import Path

PATTERNS={
 "critical":[r"rm\s+-rf\s+/",r"mkfs\b",r"dd\s+if=",r"curl\b.*\|\s*(sh|bash)",r"wget\b.*\|\s*(sh|bash)",r"os\.system\(",r"subprocess\..*shell\s*=\s*True"],
 "high":[r"\.ssh",r"AWS_SECRET",r"OPENAI_API_KEY",r"ANTHROPIC_API_KEY",r"sudo\b",r"chmod\s+777",r"eval\(",r"exec\(",r"git\s+push",r"gh\s+release",r"flash|firmware|dfu"],
 "medium":[r"curl\b",r"wget\b",r"requests\.",r"urllib",r"npm\s+install\s+-g",r"pip\s+install",r"brew\s+install",r"docker\s+run",r"ssh\b",r"scp\b"]
}
TEXT_EXT={'.md','.txt','.py','.sh','.bash','.zsh','.ps1','.js','.ts','.json','.yaml','.yml','.toml','.ini','.cfg'}
def sha(p):
 h=hashlib.sha256(); h.update(p.read_bytes()); return h.hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('path'); ap.add_argument('--json'); a=ap.parse_args(); root=Path(a.path).resolve()
 findings=[]; files=[]; licenses=[]
 for p in sorted(root.rglob('*')):
  if p.is_symlink(): findings.append({'severity':'high','file':str(p.relative_to(root)),'pattern':'symlink','line':0,'text':os.readlink(p)}); continue
  if not p.is_file(): continue
  rel=str(p.relative_to(root)); files.append({'path':rel,'bytes':p.stat().st_size,'sha256':sha(p)})
  if 'license' in p.name.lower(): licenses.append(rel)
  if p.suffix.lower() not in TEXT_EXT or p.stat().st_size>2_000_000: continue
  try: lines=p.read_text(errors='replace').splitlines()
  except Exception: continue
  for i,line in enumerate(lines,1):
   for sev,pats in PATTERNS.items():
    for pat in pats:
     if re.search(pat,line,re.I): findings.append({'severity':sev,'file':rel,'line':i,'pattern':pat,'text':line[:240]})
 skill=root/'SKILL.md'
 if not skill.exists(): findings.append({'severity':'high','file':'SKILL.md','line':0,'pattern':'missing','text':'No SKILL.md'})
 if not licenses: findings.append({'severity':'medium','file':'','line':0,'pattern':'license','text':'No license file found inside audited path'})
 counts={s:sum(f['severity']==s for f in findings) for s in ('critical','high','medium')}
 verdict='reject' if counts['critical'] else ('quarantine' if counts['high'] else ('allow-with-review' if counts['medium'] else 'allow-after-human-review'))
 report={'root':str(root),'verdict':verdict,'counts':counts,'licenses':licenses,'findings':findings,'files':files,'note':'Heuristic static scan; manually inspect all instructions, scripts, dependencies, and licenses.'}
 out=json.dumps(report,ensure_ascii=False,indent=2)
 print(out)
 if a.json: Path(a.json).write_text(out+'\n')
 raise SystemExit(2 if counts['critical'] else 0)
if __name__=='__main__': main()
