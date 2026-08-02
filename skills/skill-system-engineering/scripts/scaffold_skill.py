#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re,shutil
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('name'); ap.add_argument('--root',default='.'); ap.add_argument('--description',required=True); ap.add_argument('--force',action='store_true'); a=ap.parse_args()
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',a.name): raise SystemExit('name must be kebab-case')
    root=Path(a.root).resolve(); d=root/'skills'/a.name
    if d.exists() and not a.force: raise SystemExit(f'exists: {d}')
    for x in ('references','scripts','assets','evals','agents'): (d/x).mkdir(parents=True,exist_ok=True)
    body=("---\nname: "+a.name+"\ndescription: >\n  "+a.description.strip()+"\n---\n"
          "# "+a.name.replace('-',' ').title()+"\n\n## Trigger contract\n\nUse when ... Do not use when ...\n\n"
          "## Inputs\n\n- ...\n\n## Workflow\n\n1. ...\n\n## Output contract\n\n- ...\n\n"
          "## Conditional references\n\nRead `references/PROTOCOL.md` only when ...\n")
    (d/'SKILL.md').write_text(body,encoding='utf-8')
    (d/'references/PROTOCOL.md').write_text('# Protocol\n\nDetailed material loaded by condition.\n',encoding='utf-8')
    (d/'evals/evals.json').write_text(json.dumps({'evals':[{'id':'positive','prompt':'...','should_trigger':True},{'id':'negative','prompt':'...','should_trigger':False}]},indent=2)+'\n',encoding='utf-8')
    (d/'agents/openai.yaml').write_text('interface:\n  display_name: "'+a.name.replace('-',' ').title()+'"\n  short_description: "'+a.description[:100].replace('"','')+'"\n',encoding='utf-8')
    lic=root/'LICENSE'
    if lic.exists(): shutil.copy2(lic,d/'LICENSE')
    print(d)
if __name__=='__main__':main()
