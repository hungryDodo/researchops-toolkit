#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--out'); a=ap.parse_args(); root=Path(a.root).resolve(); tex=[]
    for p in root.rglob('*.tex'):
        if any(x in {'.git','.venv','build'} for x in p.parts): continue
        t=p.read_text(encoding='utf-8',errors='replace')
        tex.append({'path':p.relative_to(root).as_posix(),'documentclass':bool(re.search(r'\\documentclass',t)),'begin_document':bool(re.search(r'\\begin\{document\}',t)),'includes':re.findall(r'\\(?:input|include)\{([^}]+)\}',t),'bibliographies':re.findall(r'\\bibliography\{([^}]+)\}',t)})
    mains=[x['path'] for x in tex if x['documentclass'] and x['begin_document']]
    builds=[x for x in ('latexmkrc','Makefile','tectonic.toml') if (root/x).exists()]
    out={'schema_version':1,'root':str(root),'main_candidates':mains,'tex_files':tex,'build_files':builds,'pdf_files':[p.relative_to(root).as_posix() for p in root.rglob('*.pdf')]}
    text=json.dumps(out,ensure_ascii=False,indent=2)+'\n'
    if a.out: Path(a.out).write_text(text,encoding='utf-8')
    print(text,end='')
if __name__=='__main__':main()
