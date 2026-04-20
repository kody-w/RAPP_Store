#!/usr/bin/env python3
"""
build.py — collapse the multi-file ExecBrief ensemble into one sacred
deployable agent.py.

Reads:
    source/brief_scout_agent.py      (leaf)
    source/brief_analyst_agent.py    (leaf)
    source/brief_strategist_agent.py (leaf)
    source/brief_writer_agent.py     (leaf)
    source/exec_brief_agent.py       (top-level composite)

Writes:
    singleton/execbrief_agent.py — ONE drop-in file.

The collapse is mechanical:
    1. Extract every SOUL constant
    2. Extract every leaf class body
    3. Inline ONE _llm_call + _post helper
    4. Inline the ExecBrief composite as the public entrypoint
    5. Add a unified __manifest__

Usage:
    python3 tools/build.py
"""

from __future__ import annotations
import re, ast, hashlib
from pathlib import Path

RAPP_DIR = Path(__file__).resolve().parent.parent
SOURCE   = RAPP_DIR / "source"
OUT_DIR  = RAPP_DIR / "singleton"
OUT_DIR.mkdir(exist_ok=True)
OUT      = OUT_DIR / "execbrief_agent.py"

LEAVES = [
    "brief_scout_agent.py",
    "brief_analyst_agent.py",
    "brief_strategist_agent.py",
    "brief_writer_agent.py",
]
COMPOSITES = [
    "exec_brief_agent.py",
]

path_src = {}

def load(path: Path):
    src = path.read_text()
    mod = ast.parse(src, filename=str(path))
    path_src[mod] = src
    return mod, src

def get_assigns(mod, name):
    src = path_src[mod]
    out = []
    for node in mod.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    out.append(ast.get_source_segment(src, node))
    return out

def get_classes(mod):
    src = path_src[mod]
    return [(n.name, ast.get_source_segment(src, n))
            for n in mod.body if isinstance(n, ast.ClassDef)]

souls = {}
leaf_classes = []

for name in LEAVES:
    p = SOURCE / name
    mod, src = load(p)
    soul_segs = get_assigns(mod, "SOUL")
    if soul_segs:
        souls[p.stem] = soul_segs[0]
    for cname, csrc in get_classes(mod):
        if cname.endswith("Agent") and cname != "BasicAgent":
            leaf_classes.append((cname, csrc, p.stem))

composite_classes = []
for name in COMPOSITES:
    p = SOURCE / name
    mod, src = load(p)
    for cname, csrc in get_classes(mod):
        if cname.endswith("Agent") and cname != "BasicAgent":
            composite_classes.append((cname, csrc))

# ── Emit ─────────────────────────────────────────────────────────────────

out = []
out.append('"""')
out.append('execbrief_agent.py — the deployable ExecBrief singleton.')
out.append('')
out.append('ONE sacred agent.py file containing the entire converged executive-brief')
out.append('pipeline. Drop it into any RAPP brainstem\'s agents/ directory and it works.')
out.append('')
out.append('Generated from:')
for name in LEAVES + COMPOSITES:
    out.append(f'  - source/{name}')
out.append('"""')
out.append('')
out.append('try:')
out.append('    from agents.basic_agent import BasicAgent')
out.append('except ImportError:')
out.append('    from basic_agent import BasicAgent')
out.append('import json')
out.append('import os')
out.append('import urllib.request')
out.append('import urllib.error')
out.append('')

# SOULs
for stem, soul_src in souls.items():
    short = stem.replace("_agent", "").upper()
    renamed = re.sub(r'^SOUL\s*=', f'_SOUL_{short} =', soul_src)
    out.append(renamed)
    out.append('')

# Leaf classes with _Internal prefix
for cname, csrc, stem in leaf_classes:
    short = stem.replace("_agent", "").upper()
    new = csrc
    new = re.sub(r'class (\w+)Agent\b', r'class _Internal\1', new)
    new = re.sub(r'\bSOUL\b', f'_SOUL_{short}', new)
    out.append(new)
    out.append('')

# Composite (ExecBrief) — rewrite delegate instantiations
RENAMES = {
    "BriefScoutAgent":      "_InternalBriefScout",
    "BriefAnalystAgent":    "_InternalBriefAnalyst",
    "BriefStrategistAgent": "_InternalBriefStrategist",
    "BriefWriterAgent":     "_InternalBriefWriter",
}

for cname, csrc in composite_classes:
    new = csrc
    new = re.sub(r'class ExecBriefAgent\(BasicAgent\)',
                 'class ExecBrief(BasicAgent)', new)
    for old, new_name in RENAMES.items():
        new = re.sub(rf'\b{re.escape(old)}\b', new_name, new)
    out.append(new)
    out.append('')

out.append('class ExecBriefAgent(ExecBrief):')
out.append('    pass')
out.append('')

# LLM helper (extract from first leaf)
writer_src = (SOURCE / "brief_scout_agent.py").read_text()
def_re = re.compile(r'(def _llm_call\b.*?)(?=\ndef (?!_llm_call)|\nclass |\n__manifest__|\Z)', re.DOTALL)
post_re = re.compile(r'(def _post\b.*?)(?=\ndef (?!_post)|\nclass |\n__manifest__|\Z)', re.DOTALL)
m_llm = def_re.search(writer_src)
m_post = post_re.search(writer_src)
if m_llm:
    out.append(m_llm.group(1).rstrip())
    out.append('')
if m_post:
    out.append(m_post.group(1).rstrip())
    out.append('')

result = '\n'.join(out) + '\n'
OUT.write_text(result)

sha = hashlib.sha256(result.encode()).hexdigest()
lines = len(result.split('\n'))
print(f"  wrote {OUT}")
print(f"    {lines} lines, {len(result):,} bytes")
print(f"    sha256: {sha}")
print(f"    {len(souls)} SOULs inlined")
print(f"    {len(leaf_classes)} leaf classes + {len(composite_classes)} composites")
