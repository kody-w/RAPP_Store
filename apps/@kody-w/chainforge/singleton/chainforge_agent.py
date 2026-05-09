"""chainforge_agent — design + plant: compose chain plans AND create fresh public seeds.

Two intents in one singleton:

  intent="compose"  — turns a high-level operator prompt into a multi-primitive
                      rapp-chain-plan/1.0 envelope using the canonical RAPP
                      toolbox (BondRhythm + ant pheromones + art submissions +
                      braintrust + vbrainstem + tick_twin + holo card grail +
                      etc.). Calls a fresh `claude` CLI session under the hood.
                      Writes plan JSON + executable bash script. Operator runs.

  intent="plant"    — creates a fresh public planted seed (neighborhood OR
                      twin) via gh CLI, with the FULL front-door grail
                      (rappid v2 + soul + card.json (rappcards/1.1.2) +
                      holo.svg + holo-qr.svg + holo.md + specs/ bundle +
                      members + agents + .nojekyll + README + rar/). Default
                      dry_run=True; set dry_run=False to actually create.

Both intents are operator-mediated (per ANTIPATTERNS §9): the agent
SUGGESTS / DESIGNS; the operator runs / approves global writes.

Schema: `rapp-chainforge-result/1.0`. Default `dry_run=True`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import uuid

try:
    from agents.basic_agent import BasicAgent
except ModuleNotFoundError:
    from basic_agent import BasicAgent


__manifest__ = {
    "schema":      "rapp-application/1.0",
    "id":          "chainforge",
    "name":        "ChainForge",
    "version":     "0.1.0",
    "publisher":   "@kody-w",
    "kind":        "rapplication",
    "description": "Compose multi-primitive RAPP chain plans + plant fresh public seeds. Design the chain; plant the seed; operator approves; ChainForge ships.",
    "category":    "meta",
    "tags":        ["chain", "compose", "plant", "neighborhood", "twin", "holocard", "grail", "operator-mediated"],
    "license":     "BSD-style",
}


_RESULT_SCHEMA = "rapp-chainforge-result/1.0"
_DEFAULT_OUT_DIR = os.path.expanduser("~/RAPP-sim/chain-plans")
_CLAUDE_TIMEOUT_S = 120
SUPPORTED_KINDS = {"neighborhood", "ant-farm", "braintrust", "workspace", "twin"}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _slugify(s: str) -> str:
    out = []
    for c in (s or "").lower():
        if c.isalnum(): out.append(c)
        elif c in (" ", "-", "_"): out.append("-")
    return "".join(out).strip("-")[:64] or "untitled"


# ─── compose intent — chain plan composer ─────────────────────────────────

_TOOLBOX_SUMMARY = """
Available RAPP primitives. Each is invocable from a tick or a script.

IDENTITY / PLANTING
  graft_neighborhood_agent       — plant a neighborhood on an existing public repo
  launch_to_public_agent         — push local brainstem → new public repo
  rar_loader_agent               — pull a planted seed's participation kit
  plant_seed_agent (or this rapp's intent='plant') — fresh public seed
  tools/holo_card_generator.py   — rappcards/1.1.2 card.json + holo.svg + holo-qr.svg
  tools/front_door_specs.py      — bundled specs/ that travel with each planting

HEARTBEAT / OBSERVATION
  bond_rhythm_agent              — BondRhythm.pulse_once (operator-mediated)
  tools/ecosystem_audit.py       — drift detector, stdlib-only
  tools/sim/observe.py           — simulation observer

PER-KIND NATIVE PRIMITIVES
  ant_agent / colony_observer_agent           — pheromone + aggregation
  art_submit / art_vote / art_remix           — submission/vote/remix
  braintrust_request / contribute / synthesize — federated research

CROSS-ORGANISM COMMS
  twin_agent                     — rapp-twin-chat/1.0 envelopes
  vbrainstem (browser)           — Playwright; pre-set vbs_rappid for identity portability
  tools/sim/tick_twin.py         — autonomous claude CLI tick per twin
  tools/sim/loop_orchestrator.sh — cron unit
  tools/sim/push_canvas.sh       — local→public bridge
  tests/osi/browser/cross-device.spec.mjs — N browser contexts joining

DISCOVERY / CEREMONIES
  proximity_discovery_agent      — geohash matching
  lineage_rollup_agent           — MMR aggregation
  resurrection_ceremony_agent    — stasis recovery
  Dream Catcher                  — frame-scope contradiction reassimilation
""".strip()


_PLAN_INSTRUCTIONS = """
You are a CHAIN COMPOSER. Operator gives you a high-level request.
Design a chain of RAPP primitives that achieves it.

Respond with ONE JSON object inside a single ```json fenced block. Schema:

```json
{
  "schema": "rapp-chain-plan/1.0",
  "name": "<slug-friendly>",
  "title": "<human title>",
  "user_request": "<verbatim>",
  "trigger": {"kind": "cron|event|manual|proximity|issue-label", "spec": "..."},
  "primitives_used": ["..."],
  "steps": [
    {"n": 1, "agent_or_tool": "...", "action": "...", "inputs": {}, "outputs": {},
     "operator_approval_required": false}
  ],
  "expected_artifacts": [
    {"kind": "Issue|PR|submission|pheromone|aggregation|egg|report",
     "path_or_url_template": "...", "schema": "rapp-*/N.M"}
  ],
  "antipattern_checks": ["no fake mode", "operator-mediated for global writes",
                          "specs travel with new plantings"],
  "rough_cost_estimate": {"llm_calls_per_run": 0, "cost_usd_per_run": "...",
                          "wall_time_per_run": "..."},
  "executable_script_outline": ["bash/python pseudocode line 1", "..."],
  "operator_next_step": "<one sentence>"
}
```

Hard constraints:
1. Every primitive must be in the toolbox. No invented agents.
2. No fake/deterministic/pre-scripted modes. Real LLM ticks always.
3. Global-write steps (push, merge, deploy) → operator_approval_required: true.
4. New plantings include the holo card grail (card + holo.md + holo.svg + holo-qr + specs/).
5. Embodying a planted twin uses identity portability (preset vbs_rappid).

Respond with ONLY the JSON block.
""".strip()


def _call_claude(prompt: str, timeout_s: int = _CLAUDE_TIMEOUT_S) -> str:
    p = subprocess.run(["claude", "--print", prompt], capture_output=True, text=True, timeout=timeout_s)
    if p.returncode != 0:
        raise RuntimeError(f"claude exit {p.returncode}: {p.stderr[:500]}")
    return p.stdout


def _parse_plan(response: str) -> dict:
    m = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
    if not m: return json.loads(response.strip())
    return json.loads(m.group(1))


def _executable_script(plan: dict) -> str:
    name = plan.get("name", "untitled-chain")
    title = plan.get("title", name)
    outline = plan.get("executable_script_outline", [])
    lines = [
        "#!/usr/bin/env bash",
        f"# {title}",
        f"# Generated by chainforge_agent (intent=compose) at {_now_iso()}",
        f"# Plan: {name}",
        "set -euo pipefail",
        "",
    ]
    for i, step in enumerate(plan.get("steps", []), start=1):
        lines.append(f"# Step {i}: {step.get('agent_or_tool','?')} — {step.get('action','')}")
        if step.get("operator_approval_required"):
            lines.append(f"echo 'STEP {i} requires operator approval — review:'")
            lines.append(f"read -p 'proceed? [y/N] ' -n 1 -r; echo; [[ $REPLY =~ ^[Yy]$ ]] || exit 1")
        lines.append(outline[i-1] if i-1 < len(outline)
                     else f"echo 'Step {i}: invoke {step.get('agent_or_tool','?')}'")
        lines.append("")
    return "\n".join(lines) + "\n"


def _do_compose(user_prompt: str, out_dir: str, timeout_s: int) -> dict:
    if not user_prompt.strip():
        return {"ok": False, "error": "user_prompt is required for compose intent"}
    full_prompt = f"{_PLAN_INSTRUCTIONS}\n\nTOOLBOX:\n{_TOOLBOX_SUMMARY}\n\nOPERATOR REQUEST:\n{user_prompt.strip()}\n"
    try:
        response = _call_claude(full_prompt, timeout_s=timeout_s)
        plan = _parse_plan(response)
    except Exception as e:
        return {"ok": False, "error": f"compose failed: {e}"}
    for k in ("schema", "name", "title", "primitives_used", "steps"):
        if k not in plan:
            return {"ok": False, "error": f"plan missing required field: {k}", "plan": plan}
    os.makedirs(out_dir, exist_ok=True)
    slug = _slugify(plan.get("name", "chain"))
    utc_safe = _now_iso().replace(":", "-")
    plan_path = os.path.join(out_dir, f"{utc_safe}-{slug}.plan.json")
    script_path = os.path.join(out_dir, f"{utc_safe}-{slug}.sh")
    with open(plan_path, "w") as f: json.dump(plan, f, indent=2); f.write("\n")
    with open(script_path, "w") as f: f.write(_executable_script(plan))
    os.chmod(script_path, 0o755)
    return {
        "ok": True, "intent": "compose",
        "plan_name": plan.get("name"), "plan_title": plan.get("title"),
        "primitives_used": plan.get("primitives_used", []),
        "step_count": len(plan.get("steps", [])),
        "approval_steps": [i for i, s in enumerate(plan.get("steps", []), start=1)
                           if s.get("operator_approval_required")],
        "expected_artifacts": plan.get("expected_artifacts", []),
        "rough_cost": plan.get("rough_cost_estimate"),
        "operator_next_step": plan.get("operator_next_step"),
        "files_written": {"plan_json": plan_path, "executable_script": script_path},
        "_inline_plan": plan,
    }


# ─── plant intent — fresh public seed creator ─────────────────────────────

def _try_import_grail():
    try:
        for cand in (
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), "tools"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))), "tools"),
        ):
            if os.path.isfile(os.path.join(cand, "holo_card_generator.py")) \
               and os.path.isfile(os.path.join(cand, "front_door_specs.py")):
                if cand not in sys.path: sys.path.insert(0, cand)
                import holo_card_generator, front_door_specs
                return holo_card_generator, front_door_specs
    except (ImportError, OSError): pass
    return None, None


def _gh(args, timeout=30):
    p = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def _do_plant(kind: str, name: str, display_name: str, owner: str,
              purpose: str, voice_paragraph: str, dry_run: bool) -> dict:
    if kind not in SUPPORTED_KINDS:
        return {"ok": False, "error": f"unsupported kind {kind!r}"}
    if not name or not display_name:
        return {"ok": False, "error": "name and display_name required"}
    if kind == "twin" and not voice_paragraph:
        return {"ok": False, "error": "twin kind requires voice_paragraph"}
    if kind != "twin" and not purpose:
        return {"ok": False, "error": f"{kind} kind requires purpose"}

    hcg, fds = _try_import_grail()
    if hcg is None or fds is None:
        return {"ok": False,
                "error": "tools/holo_card_generator.py + tools/front_door_specs.py not on path",
                "_hint": "ChainForge plant intent requires the kody-w/RAPP tools/ modules. Install or link the parent project."}

    rappid = f"rappid:v2:{kind}:@{owner}/{name}:{uuid.uuid4().hex}@github.com/{owner}/{name}"
    seed = hcg.derive_seed(rappid)
    gate_url = f"https://{owner}.github.io/{name}/"

    # Build files (delegated to the sibling plant_seed_agent's logic — we keep this
    # singleton concise by importing the canonical builders if available).
    try:
        from plant_seed_agent import _build_neighborhood_files, _build_twin_files
    except ModuleNotFoundError:
        return {"ok": False,
                "error": "plant_seed_agent.py not loadable (sibling agent required for plant intent)",
                "_hint": "Install kody-w/RAPP's plant_seed_agent.py alongside this rapplication's singleton."}

    if kind == "twin":
        files = _build_twin_files(rappid, owner, name, display_name, voice_paragraph, hcg, fds)
        description = f"Planted RAPP twin — {display_name}. {voice_paragraph[:80]}"
    else:
        files = _build_neighborhood_files(rappid, kind, owner, name, display_name, purpose, hcg, fds)
        description = f"Planted RAPP {kind} — {display_name}. {purpose[:80]}"

    plan = {"ok": True, "intent": "plant", "dry_run": dry_run,
            "kind": kind, "owner": owner, "name": name, "display_name": display_name,
            "minted_rappid": rappid, "minted_seed": seed,
            "incantation": hcg.seed_to_words(seed),
            "target_repo": f"https://github.com/{owner}/{name}",
            "files_to_create": sorted(files.keys()), "file_count": len(files),
            "description": description}

    if dry_run:
        plan["next_step"] = (f"Re-call with intent='plant' and dry_run=False to actually create "
                             f"{owner}/{name} ({len(files)} files via gh repo create + contents API).")
        return plan

    rc, _, _ = _gh(["api", f"/repos/{owner}/{name}"])
    if rc == 0:
        plan["ok"] = False
        plan["error"] = f"repo {owner}/{name} already exists; refusing to clobber"
        return plan
    rc, _, err = _gh(["repo", "create", f"{owner}/{name}", "--public",
                       "--description", description])
    if rc != 0:
        plan["ok"] = False
        plan["error"] = f"gh repo create failed: {err.strip()[:300]}"
        return plan
    plan["repo_created"] = True

    created, failed = [], []
    for path, content in files.items():
        rc, _, err = _gh(["api", "-X", "PUT",
                           f"/repos/{owner}/{name}/contents/{path}",
                           "-f", f"message=plant_seed: {path}",
                           "-f", f"content={base64.b64encode(content).decode('ascii')}"])
        if rc == 0: created.append(path)
        else: failed.append({"path": path, "error": err[:200]})

    plan["files_created"] = len(created)
    plan["files_failed"] = len(failed)
    if failed: plan["failed_paths"] = failed
    plan["live_url"] = f"https://github.com/{owner}/{name}"
    plan["holo_md_url"] = f"https://raw.githubusercontent.com/{owner}/{name}/main/holo.md"
    plan["next_step"] = f"Planting complete. Browse {plan['live_url']}. Embody in browser: localStorage.setItem('vbs_rappid', '{rappid}')."
    return plan


# ─── Agent class ──────────────────────────────────────────────────────────

class ChainForgeAgent(BasicAgent):
    metadata = {
        "name": "ChainForge",
        "description": (
            "Two intents in one rapplication. intent='compose' turns any high-level "
            "operator prompt into a rapp-chain-plan/1.0 envelope (multi-primitive "
            "chain with operator-approval gates + cost estimate + executable script). "
            "intent='plant' creates a fresh public planted seed (neighborhood OR twin) "
            "with the full front-door grail (rappid + holocard + soul + specs/ + agents/), "
            "ready for use. Default dry_run=True for both intents — operator-mediated."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": ["compose", "plant"]},
                # compose-intent params
                "user_prompt": {"type": "string",
                                "description": "(intent=compose) Operator's high-level chain request."},
                "out_dir":     {"type": "string", "default": _DEFAULT_OUT_DIR,
                                "description": "(intent=compose) Where to write plan + script."},
                "timeout_s":   {"type": "integer", "default": _CLAUDE_TIMEOUT_S},
                # plant-intent params
                "kind":        {"type": "string",
                                "enum": ["neighborhood", "ant-farm", "braintrust", "workspace", "twin"]},
                "name":        {"type": "string"},
                "display_name":{"type": "string"},
                "owner":       {"type": "string", "default": "kody-w"},
                "purpose":     {"type": "string"},
                "voice_paragraph": {"type": "string"},
                "dry_run":     {"type": "boolean", "default": True},
            },
            "required": ["intent"],
        },
    }

    def __init__(self):
        self.name = "ChainForge"

    def perform(self, **kwargs) -> str:
        intent = (kwargs.get("intent") or "").strip().lower()
        if intent == "compose":
            result = _do_compose(
                kwargs.get("user_prompt") or "",
                kwargs.get("out_dir") or _DEFAULT_OUT_DIR,
                int(kwargs.get("timeout_s") or _CLAUDE_TIMEOUT_S),
            )
        elif intent == "plant":
            result = _do_plant(
                kind=(kwargs.get("kind") or "").strip(),
                name=(kwargs.get("name") or "").strip(),
                display_name=(kwargs.get("display_name") or "").strip(),
                owner=(kwargs.get("owner") or "kody-w").strip(),
                purpose=(kwargs.get("purpose") or "").strip(),
                voice_paragraph=(kwargs.get("voice_paragraph") or "").strip(),
                dry_run=bool(kwargs.get("dry_run", True)),
            )
        else:
            result = {"ok": False,
                      "error": f"intent must be 'compose' or 'plant'; got {intent!r}"}
        return json.dumps({"schema": _RESULT_SCHEMA,
                           "rapplication": "@kody-w/chainforge",
                           "version": "0.1.0",
                           "completed_at": _now_iso(),
                           **result}, indent=2)
