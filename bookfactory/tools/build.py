#!/usr/bin/env python3
"""
build-bookfactoryagent.py — collapse the multi-file ensemble into one
sacred deployable agent.py.

Reads:
    agents/persona_writer_agent.py
    agents/persona_editor_agent.py            (composite)
    agents/editor_strip_scaffolding_agent.py
    agents/editor_cutweak_agent.py
    agents/editor_restructure_agent.py
    agents/editor_factcheck_agent.py
    agents/editor_voicecheck_agent.py
    agents/persona_ceo_agent.py               (composite)
    agents/ceo_risk_agent.py
    agents/ceo_decision_agent.py
    agents/persona_publisher_agent.py
    agents/persona_reviewer_agent.py
    agents/book_factory_agent.py              (top-level composite)

Writes:
    agents/bookfactoryagent.py — ONE drop-in file.

The collapse is mechanical:
    1. Extract every SOUL constant
    2. Extract every leaf class body (drop their per-file _llm_call/_post)
    3. Extract every composite class body (drop the from agents.X imports)
    4. Inline ONE _llm_call + _post helper at the bottom
    5. Inline a single BookFactory class as the public entrypoint
    6. Add a unified __manifest__ that lists everything inlined

The output passes the same BasicAgent contract as any single-file agent.
Drop it in any RAPP brainstem's agents/ dir and it works.

Usage:
    python3 tools/build-bookfactoryagent.py
"""

from __future__ import annotations
import re, ast
from pathlib import Path
from textwrap import indent

RAPP_DIR  = Path(__file__).resolve().parent.parent          # rapp_store/bookfactory/
AGENTS    = RAPP_DIR / "source"                             # multi-file source
OUT_DIR   = RAPP_DIR / "singleton"                          # collapsed artifact lives here
OUT_DIR.mkdir(exist_ok=True)
OUT       = OUT_DIR / "bookfactory_agent.py"

# ── Order matters: leaves first, then composites that depend on them ─

LEAVES = [
    "persona_writer_agent.py",
    "editor_strip_scaffolding_agent.py",
    "editor_cutweak_agent.py",
    "editor_restructure_agent.py",
    "editor_factcheck_agent.py",
    "editor_voicecheck_agent.py",
    "ceo_risk_agent.py",
    "ceo_decision_agent.py",
    "persona_publisher_agent.py",
    "persona_reviewer_agent.py",
]
COMPOSITES = [
    "persona_editor_agent.py",      # uses 5 editor specialists
    "persona_ceo_agent.py",         # uses 2 ceo specialists
    "book_factory_agent.py",        # uses 5 personas
]


# ── Helpers ────────────────────────────────────────────────────────────

def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def get_assigns(mod: ast.Module, name: str):
    """Return source segments for module-level assignments matching name."""
    src = path_src.get(mod, "")
    out = []
    for node in mod.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    out.append(ast.get_source_segment(src, node))
    return out


def get_classes(mod: ast.Module):
    """Return list of (name, source) for ClassDef nodes."""
    src = path_src.get(mod, "")
    return [(n.name, ast.get_source_segment(src, n))
            for n in mod.body if isinstance(n, ast.ClassDef)]


def get_module_doc(mod: ast.Module) -> str:
    return ast.get_docstring(mod) or ""


# ── Build phase ────────────────────────────────────────────────────────

path_src = {}     # ast.Module → source string

souls = {}        # filename stem → SOUL string (verbatim)
leaf_classes = []     # list of (class_name, source) — with _llm_call calls already
composite_classes = []  # same shape; drop the `from agents.X import Y` lines

def load(path: Path):
    src = path.read_text()
    mod = ast.parse(src, filename=str(path))
    path_src[mod] = src
    return mod, src

# Process leaves: extract SOUL + class
for name in LEAVES:
    p = AGENTS / name
    mod, src = load(p)
    stem = p.stem
    # SOUL constant
    soul_segs = get_assigns(mod, "SOUL")
    if soul_segs:
        souls[stem] = soul_segs[0]
    # Class def (the *Agent class — exactly one per file)
    for cname, csrc in get_classes(mod):
        if cname.endswith("Agent") and cname != "BasicAgent":
            # Strip the leaf's per-file `from agents.basic_agent import BasicAgent`
            # and per-file _llm_call/_post (we use the unified helpers below)
            leaf_classes.append((cname, csrc))

# Process composites: extract class only (composites have no SOUL of their own;
# they orchestrate other agents). Strip the cross-agent imports.
for name in COMPOSITES:
    p = AGENTS / name
    mod, src = load(p)
    for cname, csrc in get_classes(mod):
        if cname.endswith("Agent") and cname != "BasicAgent":
            composite_classes.append((cname, csrc))


# ── Emit the singleton ────────────────────────────────────────────────

OUT_SRC = '''"""
bookfactoryagent.py — the deployable BookFactory singleton.

ONE sacred agent.py file containing the entire converged book-writing
pipeline. Drop it into any RAPP brainstem's agents/ directory and it works.

This file is generated by tools/build-bookfactoryagent.py from the
multi-file source under agents/. The multi-file form is editable and
iterable (the double-jump loop runs against it). This singleton is the
SHIP-TIME artifact: no sibling-import dependencies, no helper modules,
no repo layout assumptions. Just BasicAgent + an LLM key in the
environment, and the public BookFactory.perform(source, ...) → chapter.

Inlined personas (sacred SOULs preserved verbatim):
  - Writer
  - Editor (composite of 5 specialists: strip-scaffolding, cutweak,
    restructure, factcheck, voicecheck)
  - CEO (composite of 2 specialists: risk, decision)
  - Publisher
  - Reviewer

Public entrypoint: the BookFactory class. Every internal class is
prefixed with _Internal to keep them out of the brainstem's automatic
*Agent discovery — only BookFactory is exposed as a hot-loadable agent.

Generated from:
'''

# Append the source-file list
for name in LEAVES + COMPOSITES:
    OUT_SRC += f'  - agents/{name}\n'
OUT_SRC += '"""\n\n'

OUT_SRC += '''from agents.basic_agent import BasicAgent
import json
import os
import urllib.request
import urllib.error


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/book-factory-singleton",
    "tier": "core",
    "trust": "community",
    "version": "0.3.0",
    "tags": ["composite", "creative-pipeline", "twin-stack", "singleton"],
    "delegates_to_inlined": [
        "@rapp/persona-writer",
        "@rapp/persona-editor",
        "@rapp/editor-strip-scaffolding",
        "@rapp/editor-cutweak",
        "@rapp/editor-restructure",
        "@rapp/editor-factcheck",
        "@rapp/editor-voicecheck",
        "@rapp/persona-ceo",
        "@rapp/ceo-risk",
        "@rapp/ceo-decision",
        "@rapp/persona-publisher",
        "@rapp/persona-reviewer",
    ],
    "example_call": {"args": {"source": "raw notes...", "chapter_title": "Chapter 1"}},
}


# ─── SOUL constants (verbatim from each leaf agent.py) ─────────────────

'''

# Emit each SOUL with a distinct prefix
for stem, soul_src in souls.items():
    short = stem.replace("_agent", "").upper()
    # SOUL = "..." → SOUL_<SHORT> = "..."
    renamed = re.sub(r'^SOUL\s*=', f'_SOUL_{short} =', soul_src)
    OUT_SRC += renamed + '\n\n'

OUT_SRC += '''
# ─── Internal persona classes (prefixed to hide from *Agent discovery) ─

'''

# Function to rewrite a leaf class:
# - Rename the class with _Internal prefix
# - Rewrite SOUL → _SOUL_<STEM> reference
# - Replace _llm_call(SOUL, ...) with _llm_call(_SOUL_<STEM>, ...)
def rewrite_leaf(stem: str, csrc: str) -> str:
    short = stem.replace("_agent", "").upper()
    new = csrc
    # Rename class
    new = re.sub(r'class (\w+)Agent\b', r'class _Internal\1', new)
    # Replace SOUL refs (the only call site is _llm_call(SOUL, ...))
    new = re.sub(r'\bSOUL\b', f'_SOUL_{short}', new)
    return new

for (cname, csrc), name in zip(leaf_classes, LEAVES):
    stem = Path(name).stem
    OUT_SRC += rewrite_leaf(stem, csrc) + '\n\n'

OUT_SRC += '''
# ─── Internal composite classes ────────────────────────────────────────

'''

# Composites: rewrite the class name + rewrite class instantiations to
# use the new _Internal prefix.
COMPOSITE_RENAMES = {
    "EditorStripScaffoldingAgent": "_InternalEditorStripScaffolding",
    "EditorCutweakAgent":          "_InternalEditorCutweak",
    "EditorRestructureAgent":      "_InternalEditorRestructure",
    "EditorFactcheckAgent":        "_InternalEditorFactcheck",
    "EditorVoicecheckAgent":       "_InternalEditorVoicecheck",
    "CEORiskAgent":                "_InternalCEORisk",
    "CEODecisionAgent":            "_InternalCEODecision",
    "PersonaWriterAgent":          "_InternalPersonaWriter",
    "PersonaEditorAgent":          "_InternalPersonaEditor",
    "PersonaCEOAgent":             "_InternalPersonaCEO",
    "PersonaPublisherAgent":       "_InternalPersonaPublisher",
    "PersonaReviewerAgent":        "_InternalPersonaReviewer",
}

def rewrite_composite(csrc: str) -> str:
    new = csrc
    # Rename own class (composite class itself)
    new = re.sub(r'class (\w+)Agent\b', r'class _Internal\1', new)
    # Rewrite every instantiation of an old class name to its _Internal form
    for old, new_name in COMPOSITE_RENAMES.items():
        new = re.sub(rf'\b{re.escape(old)}\b', new_name, new)
    return new

# Process composites in order: editor first, then ceo, then book_factory
# (book_factory will be EXTRACTED — its perform() body becomes BookFactory.perform())
for (cname, csrc), name in zip(composite_classes, COMPOSITES):
    if name == "book_factory_agent.py":
        # We'll handle the top-level BookFactory specially below
        bookfactory_src = csrc
        continue
    OUT_SRC += rewrite_composite(csrc) + '\n\n'

# ── BookFactory (the public class — only one without _Internal prefix) ─

# Take the BookFactoryAgent source, rename internal class refs but KEEP
# the public class name as BookFactory (drop the trailing "Agent" too —
# this is the singleton's name, the brainstem will discover it via the
# trailing-Agent rule, so we keep "Agent" suffix actually).
public = bookfactory_src
public = re.sub(r'class BookFactoryAgent\b', 'class BookFactory(BasicAgent):  # type: ignore', public)
# Wait — the previous regex already gave us a class with parens. Let me
# do it more carefully: keep the original class declaration shape.
public = bookfactory_src  # reset
public = re.sub(r'class BookFactoryAgent\(BasicAgent\)', 'class BookFactory(BasicAgent)', public)
# Rewrite delegate instantiations to internal names
for old, new_name in COMPOSITE_RENAMES.items():
    public = re.sub(rf'\b{re.escape(old)}\b', new_name, public)
# Update self.name and metadata.name to "BookFactory" (was "BookFactory" already, fine)
# Make sure it's discoverable by the brainstem's "ends with Agent and != BasicAgent"
# rule — we add an alias class at the bottom.

OUT_SRC += '# ─── PUBLIC ENTRYPOINT ──────────────────────────────────────────────────\n\n'
OUT_SRC += public + '\n\n'

# Brainstem discovers classes whose names end in "Agent" and aren't BasicAgent.
# Our public class is "BookFactory" which doesn't end in Agent — add an alias.
OUT_SRC += '''
# Alias so the brainstem's "name ends in Agent" discovery picks it up.
# (BookFactory is the canonical name; BookFactoryAgent is the discovery hook.)
class BookFactoryAgent(BookFactory):
    pass


'''

# ─── The unified _llm_call + _post (one inlined helper for the whole file) ─

# Use the writer's helper as canonical (all 10 leaves had identical copies)
writer_src = (AGENTS / "persona_writer_agent.py").read_text()
# Extract the _llm_call function and _post function source
def_re = re.compile(r'(def _llm_call\b.*?)(?=\n(?:def |class |__manifest__|\Z))', re.DOTALL)
post_re = re.compile(r'(def _post\b.*?)(?=\n(?:def |class |__manifest__|\Z))', re.DOTALL)
m_llm = def_re.search(writer_src); m_post = post_re.search(writer_src)
llm_helper = m_llm.group(1).rstrip() if m_llm else ""
post_helper = m_post.group(1).rstrip() if m_post else ""

OUT_SRC += '\n# ─── Inlined LLM dispatch (one copy for the whole singleton) ──────────\n\n'
OUT_SRC += llm_helper + '\n\n\n'
OUT_SRC += post_helper + '\n'

# ── Write ─────────────────────────────────────────────────────────────

OUT.write_text(OUT_SRC)
n_lines = len(OUT_SRC.split('\n'))
n_chars = len(OUT_SRC)
print(f"  ✓ wrote {OUT}")
print(f"    {n_lines} lines, {n_chars:,} chars")
print(f"    {len(souls)} SOULs inlined")
print(f"    {len(leaf_classes)} leaf classes inlined (prefixed _Internal)")
print(f"    {len(composite_classes) - 1} internal composites + 1 public BookFactory")
