"""Transcript2PrototypeAgent - transcript in, working prototype out, one cubby per prototype.

A single-file rapplication for the RAPP brainstem. Paste a business transcript
and this agent walks the full prototyping pipeline conversationally, keeping
every prototype isolated in its own cubby (~/.brainstem/cubbies/<slug>/, the
same rapp-cubby/1.0 anatomy RappAgent uses, so cubby_list / super_rar /
cubby_egg all see it).

THE PIPELINE (one prototype, one cubby, one state machine):

  1. start      transcript -> analysis -> turn-by-turn demo script ->
                the static M365 Copilot demo template is generated with the
                script injected, base64-encoded ("bytecode"), and surfaced in
                an iframe inside the rapplication shell HTML. Scripted mode:
                every send is answered from the embedded script. Drive it
                with the Up arrow + Enter, exactly like the house demos.
  2. adjust     conversational edits to any turn, at any stage, regenerate
                the injected bytecode in place. The iframe always reflects
                the current demo script.
  3. build      the ACTUAL agent.py files are generated into the cubby's
                agents/ folder, grounded in the same analysis the demo used.
  4. test local the generated agent.pys are loaded in-process (a local twin)
                and the demo script is replayed against them turn by turn,
                scored, and reported.
  5. test twin  the agent.pys are injected into a live twin/brainstem
                (hot-reload, git-invisible to the twin) and the SAME demo is
                replayed over HTTP against /chat. The same rapplication
                iframe is regenerated in live mode pointed at the twin, so
                the demo you rehearsed now drives the real agents.
  6. export     everything is bundled into ONE factory singleton
                <slug>_factory_agent.py in the cubby's exports/ folder.
                THIS IS A GATE: the pipeline stops here. The singleton is
                the handoff artifact for the next stage of the process.

Browse prototypes with list / search (super-rar style, metadata + file
content) and pick one with focus. Everything runs fully local.

THE CALLER CONTRACT (nothing hardcoded): the LLM hosting this agent is the
intelligence; this file is the plumbing. Every input arrives as a parameter
and every parameter description tells the caller exactly what to provide -
that metadata is ALL the caller has. The preferred start path is the caller
analyzing the transcript itself and passing capabilities= (see the parameter
description for the exact JSON shape); the built-in keyword heuristic is only
the documented floor, and even its knobs (pain_markers, capability_vocabulary,
max_capabilities) are parameters. Free-text adjust instructions are returned
to the caller with the current script so the CALLER decides the wording and
re-calls with structured edits.

MIT (c) Kody Wildfeuer.
"""

from __future__ import annotations

import base64
import glob
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

try:
    from agents.basic_agent import BasicAgent  # type: ignore
except ImportError:
    try:
        from basic_agent import BasicAgent  # type: ignore
    except ImportError:
        class BasicAgent:
            def __init__(self, name="Agent", metadata=None):
                self.name = name
                self.metadata = metadata or {}

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@kody-w/transcript2prototype",
    "version": "1.0.0",
    "display_name": "Transcript2Prototype",
    "description": ("Transcript -> demo script -> injected M365 demo iframe -> "
                    "generated agent.pys -> local twin run -> live twin run -> "
                    "factory singleton export (gate). One cubby per prototype."),
    "author": "Kody Wildfeuer",
    "tags": ["rapplication", "pipeline", "prototype", "demo", "cubby",
             "factory", "twin", "m365"],
    "category": "workflow",
    "quality_tier": "official",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
}

PROTO_SCHEMA = "t2p-prototype/1.0"
RESULT_SCHEMA = "t2p-result/1.0"
CUBBY_SCHEMA = "rapp-cubby/1.0"
CUBBY_ANATOMY = ("agents", "organs", "senses", "rapplications",
                 "neighborhoods", "eggs", "show-and-tell")
STAGES = ("demo", "built", "local_passed", "twin_passed", "exported")
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do",
    "for", "from", "get", "had", "has", "have", "i", "if", "in", "into",
    "is", "it", "its", "just", "lot", "me", "my", "no", "not", "of", "on",
    "or", "our", "out", "so", "some", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "to", "up", "us",
    "was", "we", "were", "what", "when", "where", "which", "who", "will",
    "with", "would", "you", "your", "really", "also", "very", "every",
    "about", "all", "one", "two", "could", "should", "right", "now",
    "like", "want", "need", "wish", "time", "way", "things", "thing",
    "going", "know", "yeah", "okay", "well", "team", "people", "someone",
    "still", "even", "back", "over", "more", "much", "today", "currently",
    "because", "takes", "make", "makes", "gets", "goes", "comes", "keeps",
    "honestly", "basically", "biggest", "same", "own", "each", "other",
}

# DEFAULT capability vocabulary (prefix match) for the no-capabilities
# fallback ONLY - callers override it with capability_vocabulary=, or skip
# the heuristic entirely by passing capabilities= (the preferred path).
DEFAULT_CAP_LEXICON = (
    "setup", "configur", "assist", "train", "deliver", "proposal", "creat",
    "content", "customiz", "pricing", "price", "optimiz", "onboard", "triag",
    "draft", "letter", "template", "search", "resolution", "claim", "email",
    "queue", "invoice", "contract", "report", "schedul", "approval", "return",
    "order", "ticket", "support", "integration", "workflow", "summar",
    "escalat", "routing", "compliance", "audit", "forecast", "renewal",
    "quote", "catalog", "inventory", "payment", "billing", "enrollment",
    "intake", "walkthrough", "adoption", "guided", "document", "tracking",
)

# speaker labels like "Maria (Ops Lead):" / "Kunal:" at the start of a line -
# 1-3 capitalized words + optional (role). A sentence that happens to contain
# a colon ("Pricing optimization never happens: we ...") does NOT match.
_SPEAKER_RE = re.compile(
    r"^[A-Z][a-zA-Z.'-]{1,15}(?: [A-Z][a-zA-Z.'-]{1,15}){0,2}\s*"
    r"(?:\([^)]{0,40}\))?\s*:\s*")
# DEFAULT pain/need sentence markers for the fallback analyzer ONLY -
# callers override with pain_markers=, or bypass via capabilities=.
DEFAULT_PAIN_MARKERS = (
    "we need", "we want", "wish we", "would love", "problem", "manually",
    "by hand", "takes hours", "takes days", "takes weeks", "spend", "spends",
    "every time", "hard to", "difficult", "slow", "error-prone", "errors",
    "no way to", "can't", "cannot", "have to", "struggle", "pain", "bottleneck",
    "tedious", "repetitive", "falls through", "miss", "missed", "backlog",
)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slugify(text, fallback="prototype"):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:48] or fallback


def _camel(text):
    parts = re.split(r"[^A-Za-z0-9]+", text or "")
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _words(text):
    return [w for w in re.findall(r"[a-zA-Z][a-zA-Z'-]+", (text or "").lower())
            if w not in _STOPWORDS and len(w) > 2]


def _sentences(text):
    raw = re.split(r"(?<=[.!?])\s+|\n{2,}", text or "")
    out = []
    for s in raw:
        s = " ".join(s.split())
        s = _SPEAKER_RE.sub("", s).strip()
        if len(s) > 12:
            out.append(s)
    return out


def _lex_hit(word, lexicon):
    return any(word.startswith(lx) for lx in lexicon)


def _csv_tuple(raw):
    """'a, b,c' -> ('a','b','c') lowercased; None/empty -> ()."""
    return tuple(w.strip().lower() for w in (raw or "").split(",") if w.strip())


CAPABILITIES_SCHEMA_HINT = (
    'capabilities must be a JSON array of 1-8 objects: [{"name": "2-3 word '
    'capability name", "description": "one sentence on what it does for the '
    'customer", "triggers": ["4-6", "lowercase", "routing", "keywords"], '
    '"knowledge": ["2-3 short facts quoted or derived from the transcript"], '
    '"response": "the ideal assistant reply for the demo (markdown ok, no '
    'emojis); SHOULD contain every trigger keyword - any missing ones are '
    'appended automatically", "demo_user": "what the user types in the demo '
    'to invoke this capability"}]')


def _coerce_capabilities(raw):
    """Validate + repair caller-provided capabilities. Raises ValueError with
    an instructive message; auto-repairs everything repairable so a slightly
    sloppy caller still succeeds (triggers from name, response gets missing
    trigger keywords appended, demo_user defaulted)."""
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    if isinstance(parsed, dict):
        parsed = parsed.get("capabilities") or parsed.get("items")
    if not isinstance(parsed, list) or not parsed:
        raise ValueError(CAPABILITIES_SCHEMA_HINT)
    caps, used_keys = [], set()
    for i, c in enumerate(parsed[:8]):
        if not isinstance(c, dict) or not str(c.get("name") or "").strip():
            raise ValueError(f"capabilities[{i}] needs at least a 'name'. "
                             + CAPABILITIES_SCHEMA_HINT)
        name = str(c["name"]).strip()
        key = _slugify(name, f"cap{i + 1}").replace("-", "_")
        if key in used_keys:
            key = f"{key}_{i + 1}"
        used_keys.add(key)
        triggers = [str(t).strip().lower() for t in (c.get("triggers") or [])
                    if str(t).strip()][:6]
        if not triggers:
            triggers = [w for w in _words(name)][:4] or [key]
        description = str(c.get("description") or f"{name} capability").strip()
        knowledge = [str(k).strip() for k in (c.get("knowledge") or [])
                     if str(k).strip()][:3]
        response = str(c.get("response") or "").strip()
        if not response:
            response = (f"Here is how the prototype handles **{name}**: "
                        f"{description}")
        missing = [t for t in triggers if t not in response.lower()]
        if missing:
            response += "\n\nKey elements: " + ", ".join(triggers) + "."
        demo_user = str(c.get("demo_user") or "").strip() \
            or f"Show me how you handle {name.lower()}."
        caps.append({"key": key, "name": name,
                     "class_name": _camel(name) or f"Capability{i + 1}",
                     "description": description, "triggers": triggers,
                     "knowledge": knowledge, "response": response,
                     "demo_user": demo_user})
    return caps


def _kw_score(expected, actual_text):
    """Fraction of expected keywords present in actual_text (case-blind)."""
    if not expected:
        return 1.0, []
    t = (actual_text or "").lower()
    hits = [w for w in expected if w and w.lower() in t]
    return len(hits) / max(1, len(expected)), hits


def _post_json(url, payload, timeout=90):
    """POST JSON -> (parsed_json|None, error|None). stdlib only."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 - offline must never crash an agent
        return None, str(e)


# ---------------------------------------------------------------------------
# the injected M365 Copilot demo template ("bytecode" payload)
# tokens are replaced with .replace() - never .format() (CSS braces).
# ---------------------------------------------------------------------------
M365_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', -apple-system, sans-serif; background: #f3f3f3; height: 100vh; display: flex; overflow: hidden; }
.nav-rail { width: 48px; background: #2b2b2b; display: flex; flex-direction: column; align-items: center; padding: 12px 0; gap: 14px; flex-shrink: 0; }
.nav-icon { width: 30px; height: 30px; border-radius: 6px; display: flex; align-items: center; justify-content: center; color: #999; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; cursor: pointer; }
.nav-icon:hover { background: #444; color: #fff; }
.nav-icon.copilot { background: linear-gradient(135deg, #7b61ff 0%, #5b5fc7 100%); color: #fff; }
.nav-spacer { flex: 1; }
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.top-bar { height: 48px; background: #fff; border-bottom: 1px solid #e0e0e0; display: flex; align-items: center; padding: 0 20px; gap: 12px; flex-shrink: 0; }
.copilot-badge { display: flex; align-items: center; gap: 8px; }
.copilot-icon { width: 24px; height: 24px; border-radius: 6px; background: linear-gradient(135deg, #7b61ff, #5b5fc7); display: flex; align-items: center; justify-content: center; color: #fff; font-size: 9px; font-weight: 700; }
.copilot-name { font-size: 14px; font-weight: 600; color: #242424; }
.copilot-sub { font-size: 12px; color: #616161; }
.spacer { flex: 1; }
.demo-badge { font-size: 10px; padding: 3px 10px; border-radius: 10px; background: rgba(91,95,199,0.1); color: #5b5fc7; border: 1px solid rgba(91,95,199,0.3); font-weight: 700; letter-spacing: 0.5px; }
.chat-area { flex: 1; overflow-y: auto; padding: 24px 0; background: #f5f5f5; display: flex; flex-direction: column; }
.chat-inner { max-width: 800px; width: 100%; margin: 0 auto; padding: 0 24px; display: flex; flex-direction: column; gap: 20px; }
.msg-row { display: flex; gap: 12px; align-items: flex-start; }
.msg-row.user { flex-direction: row-reverse; }
.msg-avatar { width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }
.msg-avatar.copilot-av { background: linear-gradient(135deg, #7b61ff, #5b5fc7); color: #fff; }
.msg-avatar.user-av { background: #0078d4; color: #fff; }
.msg-bubble { max-width: 680px; border-radius: 12px; padding: 14px 18px; font-size: 14px; line-height: 1.65; word-wrap: break-word; }
.msg-row.user .msg-bubble { background: #e8ebfa; color: #242424; border-bottom-right-radius: 4px; }
.msg-row.copilot .msg-bubble { background: #fff; color: #242424; border: 1px solid #e0e0e0; border-bottom-left-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.rendered h1, .rendered h2, .rendered h3 { color: #242424; margin: 12px 0 6px; }
.rendered h1 { font-size: 17px; border-bottom: 1px solid #e0e0e0; padding-bottom: 6px; }
.rendered h2 { font-size: 15px; }
.rendered h3 { font-size: 14px; color: #5b5fc7; }
.rendered code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 13px; color: #5b5fc7; }
.rendered pre { background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 8px; overflow-x: auto; margin: 8px 0; }
.rendered pre code { background: none; padding: 0; color: #d4d4d4; }
.rendered blockquote { border-left: 3px solid #5b5fc7; padding: 8px 14px; margin: 8px 0; background: #f8f8ff; border-radius: 0 6px 6px 0; color: #444; }
.rendered ul, .rendered ol { padding-left: 22px; margin: 6px 0; }
.rendered li { margin: 4px 0; }
.rendered a { color: #0078d4; text-decoration: underline; }
.rendered table { border-collapse: collapse; margin: 8px 0; font-size: 13px; width: 100%; }
.rendered th, .rendered td { border: 1px solid #e0e0e0; padding: 6px 10px; text-align: left; }
.rendered th { background: #f0f0f0; font-weight: 600; }
.rendered tr:nth-child(even) { background: #fafafa; }
.rendered hr { border: none; border-top: 1px solid #e0e0e0; margin: 12px 0; }
.typing-row { display: flex; gap: 12px; align-items: flex-start; }
.typing-dots { padding: 14px 18px; color: #999; font-size: 14px; }
.typing-dots span { animation: blink 1.4s infinite; }
.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%,80%,100% { opacity: 0.2; } 40% { opacity: 1; } }
.input-area { padding: 16px 24px 20px; background: #fff; border-top: 1px solid #e0e0e0; flex-shrink: 0; }
.input-wrap { max-width: 800px; margin: 0 auto; display: flex; gap: 10px; align-items: center; background: #f5f5f5; border: 1px solid #d0d0d0; border-radius: 24px; padding: 4px 6px 4px 18px; }
.input-wrap:focus-within { border-color: #5b5fc7; box-shadow: 0 0 0 2px rgba(91,95,199,0.15); }
.input-wrap input { flex: 1; border: none; background: none; font-size: 14px; color: #242424; outline: none; padding: 10px 0; }
.input-wrap input::placeholder { color: #999; }
.send-btn { width: 36px; height: 36px; border-radius: 50%; border: none; background: #5b5fc7; color: #fff; font-size: 15px; cursor: pointer; }
.send-btn:disabled { background: #ccc; cursor: default; }
.prompter { position: fixed; bottom: 90px; right: 20px; width: 340px; background: #1e1e1e; border: 1px solid #333; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.4); z-index: 9999; overflow: hidden; transition: opacity 0.2s; }
.prompter.hidden { opacity: 0; pointer-events: none; }
.prompter-bar { display: flex; align-items: center; gap: 8px; padding: 8px 14px; background: #2b2b2b; border-bottom: 1px solid #333; }
.pr-title { font-size: 11px; color: #5b5fc7; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
.pr-count { margin-left: auto; font-size: 11px; color: #888; font-family: monospace; }
.pr-toggle { background: none; border: none; color: #666; font-size: 14px; cursor: pointer; }
.prompter-body { padding: 12px 14px; }
.pr-step { font-size: 12px; color: #ccc; line-height: 1.5; margin-bottom: 8px; }
.pr-num { color: #5b5fc7; font-weight: 700; margin-right: 6px; }
.pr-expect { font-size: 11px; color: #4ade80; line-height: 1.5; padding: 6px 10px; background: rgba(74,222,128,0.08); border-radius: 6px; border-left: 3px solid #4ade80; }
.pr-expect::before { content: "EXPECT: "; font-weight: 700; font-size: 10px; }
.pr-keys { padding: 6px 14px 10px; font-size: 10px; color: #555; text-align: center; border-top: 1px solid #333; }
.pr-keys kbd { background: #333; padding: 1px 6px; border-radius: 3px; border: 1px solid #444; color: #aaa; }
.welcome { max-width: 600px; margin: 40px auto; text-align: center; padding: 0 24px; }
.w-icon { width: 56px; height: 56px; border-radius: 16px; background: linear-gradient(135deg, #7b61ff, #5b5fc7); display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: 700; color: #fff; margin: 0 auto 16px; }
.welcome h2 { font-size: 22px; color: #242424; margin-bottom: 8px; }
.welcome p { font-size: 14px; color: #616161; line-height: 1.6; }
.chips { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; margin-top: 16px; }
.chip { padding: 6px 14px; background: #e8ebfa; border-radius: 16px; font-size: 12px; color: #5b5fc7; font-weight: 600; }
</style>
</head>
<body>
<div class="nav-rail">
  <div class="nav-icon copilot" title="Copilot">AI</div>
  <div class="nav-icon" title="Chat">CH</div>
  <div class="nav-icon" title="Teams">TM</div>
  <div class="nav-icon" title="Calendar">CA</div>
  <div class="nav-icon" title="Files">FI</div>
  <div class="nav-spacer"></div>
  <div class="nav-icon" title="Settings">ST</div>
</div>
<div class="main">
  <div class="top-bar">
    <div class="copilot-badge">
      <div class="copilot-icon">AI</div>
      <div>
        <div class="copilot-name">__AGENT_NAME__</div>
        <div class="copilot-sub">__AGENT_SUB__</div>
      </div>
    </div>
    <div class="spacer"></div>
    <span class="demo-badge">__BADGE__</span>
  </div>
  <div class="chat-area" id="chat">
    <div class="chat-inner" id="chat-inner">
      <div class="welcome">
        <div class="w-icon">AI</div>
        <h2>__AGENT_NAME__</h2>
        <p>__WELCOME_TEXT__</p>
        <div class="chips">__CHIPS_HTML__</div>
      </div>
    </div>
  </div>
  <div class="input-area">
    <div class="input-wrap">
      <input type="text" id="input" placeholder="Ask __AGENT_NAME__..." autofocus>
      <button class="send-btn" id="send-btn" title="Send">&#8593;</button>
    </div>
  </div>
</div>
<div class="prompter" id="prompter">
  <div class="prompter-bar">
    <span class="pr-title">Demo Script</span>
    <span class="pr-count" id="pr-count"></span>
    <button class="pr-toggle" id="pr-toggle" title="Hide">&times;</button>
  </div>
  <div class="prompter-body" id="pr-body"></div>
  <div class="pr-keys"><kbd>&#8593;</kbd> queue next &nbsp; <kbd>Enter</kbd> send &nbsp; <kbd>&#8595;</kbd> previous &nbsp; <kbd>Esc</kbd> toggle script</div>
</div>
<script>
var MODE = "__MODE__";                 // "scripted" | "live"
var API_URL = "__API_URL__";
var GUID = "__GUID__";
var DEMO = __DEMO_JSON__;              // [{q, e, a}]
var conversationHistory = [];
var demoIdx = -1;
var sending = false;

function updatePrompter() {
  var body = document.getElementById('pr-body');
  var count = document.getElementById('pr-count');
  if (demoIdx < 0 || demoIdx >= DEMO.length) {
    body.innerHTML = '<div class="pr-step" style="color:#888">Press <kbd style="background:#333;padding:1px 4px;border-radius:2px;border:1px solid #444;color:#aaa">&#8593;</kbd> to queue the first demo step</div>';
    count.textContent = '0 / ' + DEMO.length;
    return;
  }
  var s = DEMO[demoIdx];
  body.innerHTML = '<div class="pr-step"><span class="pr-num">' + (demoIdx + 1) + '.</span>' + s.q + '</div><div class="pr-expect">' + s.e + '</div>';
  count.textContent = (demoIdx + 1) + ' / ' + DEMO.length;
}

function renderMarkdown(text) {
  var html = String(text || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>')
    .replace(/^---$/gm, '<hr>');
  html = html.replace(/(^\|.+\|$\n?)+/gm, function (block) {
    var rows = block.trim().split('\n').filter(function (r) { return !r.match(/^\|[\s\-:|]+\|$/); });
    if (!rows.length) return block;
    var t = '<table>';
    rows.forEach(function (row, i) {
      var cells = row.split('|').filter(function (c) { return c.trim() !== ''; });
      var tag = i === 0 ? 'th' : 'td';
      t += '<tr>' + cells.map(function (c) { return '<' + tag + '>' + c.trim() + '</' + tag + '>'; }).join('') + '</tr>';
    });
    return t + '</table>';
  });
  html = html.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>[\s\S]*?<\/li>\n?)+/g, '<ul>$&</ul>');
  html = html.replace(/\n\n/g, '</p><p>');
  html = '<p>' + html + '</p>';
  html = html.replace(/<p>\s*(<h[123]|<table|<ul|<hr|<blockquote|<pre)/g, '$1');
  html = html.replace(/(<\/h[123]>|<\/table>|<\/ul>|<hr>|<\/blockquote>|<\/pre>)\s*<\/p>/g, '$1');
  return html;
}

var chatInner = document.getElementById('chat-inner');
var chatArea = document.getElementById('chat');
var input = document.getElementById('input');
var sendBtn = document.getElementById('send-btn');

function scrollBottom() { chatArea.scrollTop = chatArea.scrollHeight; }

function addMessage(role, text) {
  var welcome = chatInner.querySelector('.welcome');
  if (welcome) welcome.remove();
  var row = document.createElement('div');
  row.className = 'msg-row ' + (role === 'user' ? 'user' : 'copilot');
  var av = document.createElement('div');
  av.className = 'msg-avatar ' + (role === 'user' ? 'user-av' : 'copilot-av');
  av.textContent = role === 'user' ? 'Y' : 'AI';
  var bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  if (role === 'user') {
    bubble.textContent = text;
  } else {
    var rendered = document.createElement('div');
    rendered.className = 'rendered';
    rendered.innerHTML = renderMarkdown(text);
    bubble.appendChild(rendered);
  }
  row.appendChild(av);
  row.appendChild(bubble);
  chatInner.appendChild(row);
  scrollBottom();
}

function showTyping() {
  var row = document.createElement('div');
  row.className = 'typing-row';
  row.id = 'typing';
  var av = document.createElement('div');
  av.className = 'msg-avatar copilot-av';
  av.textContent = 'AI';
  var dots = document.createElement('div');
  dots.className = 'typing-dots';
  dots.innerHTML = 'Thinking <span>.</span><span>.</span><span>.</span>';
  row.appendChild(av);
  row.appendChild(dots);
  chatInner.appendChild(row);
  scrollBottom();
}
function hideTyping() { var el = document.getElementById('typing'); if (el) el.remove(); }

function overlap(a, b) {
  var wa = String(a).toLowerCase().match(/[a-z]{3,}/g) || [];
  var wb = {};
  (String(b).toLowerCase().match(/[a-z]{3,}/g) || []).forEach(function (w) { wb[w] = 1; });
  if (!wa.length) return 0;
  var hit = 0;
  wa.forEach(function (w) { if (wb[w]) hit++; });
  return hit / wa.length;
}

function scriptedAnswer(text) {
  if (demoIdx >= 0 && demoIdx < DEMO.length && overlap(DEMO[demoIdx].q, text) > 0.7) {
    return DEMO[demoIdx].a;
  }
  var best = -1, bestScore = 0.34;
  for (var i = 0; i < DEMO.length; i++) {
    var s = overlap(DEMO[i].q, text);
    if (s > bestScore) { bestScore = s; best = i; }
  }
  if (best >= 0) return DEMO[best].a;
  return 'This panel is playing the scripted demo preview. Use the Up arrow to queue the next scripted step, or adjust the script through your brainstem ("adjust turn N ...") and regenerate.';
}

async function send(text) {
  if (!text.trim() || sending) return;
  sending = true;
  input.disabled = true; sendBtn.disabled = true;
  addMessage('user', text);
  conversationHistory.push({ role: 'user', content: text });
  showTyping();
  var response = '';
  if (MODE === 'scripted') {
    await new Promise(function (r) { setTimeout(r, 700); });
    response = scriptedAnswer(text);
  } else {
    try {
      var res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_input: text,
          user_guid: GUID,
          conversation_history: conversationHistory.slice(-12)
        })
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var data = await res.json();
      response = (data.response || data.assistant_response || '').split('|||VOICE|||')[0].trim();
      if (!response) response = '(empty response from twin)';
    } catch (err) {
      response = 'Error reaching the twin at ' + API_URL + ': ' + err.message + '. Make sure the twin/brainstem is running.';
    }
  }
  hideTyping();
  addMessage('assistant', response);
  conversationHistory.push({ role: 'assistant', content: response });
  sending = false;
  input.disabled = false; sendBtn.disabled = false;
  input.value = '';
  input.focus();
}

sendBtn.addEventListener('click', function () { send(input.value); });
input.addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send(input.value);
    if (demoIdx >= 0 && demoIdx < DEMO.length - 1) { demoIdx++; updatePrompter(); }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (demoIdx < DEMO.length - 1) { demoIdx++; input.value = DEMO[demoIdx].q; updatePrompter(); }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (demoIdx > 0) { demoIdx--; input.value = DEMO[demoIdx].q; updatePrompter(); }
    else if (demoIdx === 0) { demoIdx = -1; input.value = ''; updatePrompter(); }
  } else if (e.key === 'Escape') {
    e.preventDefault();
    document.getElementById('prompter').classList.toggle('hidden');
  }
});
document.getElementById('pr-toggle').addEventListener('click', function () {
  document.getElementById('prompter').classList.toggle('hidden');
});
updatePrompter();
</script>
</body>
</html>
"""

# the rapplication shell: stage tracker + the demo iframe injected as bytecode
SHELL_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', -apple-system, sans-serif; background: #1b1b1f; color: #e6e6e6; height: 100vh; display: flex; flex-direction: column; }
.hdr { padding: 14px 22px 10px; border-bottom: 1px solid #2e2e34; background: #222227; }
.hdr-row { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.hdr h1 { font-size: 17px; font-weight: 600; color: #fff; }
.hdr .sub { font-size: 12px; color: #9a9aa3; }
.hdr .mode { margin-left: auto; font-size: 11px; font-weight: 700; letter-spacing: 0.6px; padding: 3px 10px; border-radius: 10px; background: rgba(91,95,199,0.18); color: #9fa3ff; border: 1px solid rgba(91,95,199,0.45); }
.stages { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
.stage { font-size: 11px; padding: 4px 12px; border-radius: 12px; border: 1px solid #3a3a42; color: #8a8a94; background: #26262c; }
.stage.done { border-color: #2f6b3a; color: #7fd18f; background: rgba(47,107,58,0.15); }
.stage.current { border-color: #5b5fc7; color: #c3c5ff; background: rgba(91,95,199,0.18); font-weight: 700; }
.stage.gate { border-style: dashed; }
.frame-wrap { flex: 1; padding: 14px 22px; min-height: 0; }
iframe { width: 100%; height: 100%; border: 1px solid #2e2e34; border-radius: 10px; background: #fff; }
.ftr { padding: 10px 22px 14px; border-top: 1px solid #2e2e34; background: #222227; font-size: 12px; color: #9a9aa3; line-height: 1.7; }
.ftr code { background: #2c2c33; color: #c3c5ff; padding: 1px 7px; border-radius: 4px; font-size: 11px; }
.ftr .lbl { color: #c9c9d2; font-weight: 600; }
</style>
</head>
<body>
<div class="hdr">
  <div class="hdr-row">
    <h1>__TITLE__</h1>
    <span class="sub">__SUBTITLE__</span>
    <span class="mode">__MODE_BADGE__</span>
  </div>
  <div class="stages">__STAGES_HTML__</div>
</div>
<div class="frame-wrap">
  <iframe src="data:text/html;base64,__BYTECODE__" title="M365 Copilot demo"></iframe>
</div>
<div class="ftr">
  <span class="lbl">Drive the demo:</span> click into the panel, press Up arrow to queue each step, Enter to send.
  <span class="lbl">Direct this pipeline from your brainstem chat:</span>
  <code>adjust turn 2 ...</code> <code>build the agents</code> <code>run the local test</code> <code>run it against my twin</code> <code>export the factory singleton</code>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# generated-agent source template
# ---------------------------------------------------------------------------
AGENT_IMPORT_BLOCK = '''try:
    from agents.basic_agent import BasicAgent  # type: ignore
except ImportError:
    try:
        from basic_agent import BasicAgent  # type: ignore
    except ImportError:
        class BasicAgent:
            def __init__(self, name="Agent", metadata=None):
                self.name = name
                self.metadata = metadata or {}
'''

AGENT_CLASS_TEMPLATE = '''
class {class_name}(BasicAgent):
    """{description}"""

    KNOWLEDGE = {knowledge!r}
    TRIGGERS = {triggers!r}
    RESPONSE = {response!r}

    def __init__(self):
        self.name = {agent_name!r}
        self.metadata = {{
            "name": self.name,
            "description": {tool_description!r},
            "parameters": {{
                "type": "object",
                "properties": {{
                    "user_input": {{
                        "type": "string",
                        "description": "The user's request, in their own words.",
                    }}
                }},
                "required": ["user_input"],
            }},
        }}
        super().__init__(self.name, self.metadata)

    def perform(self, **kwargs):
        user_input = kwargs.get("user_input", "")
        grounding = "\\n".join("- " + k for k in self.KNOWLEDGE)
        reply = self.RESPONSE
        if grounding:
            reply += "\\n\\nGrounded in what you told us:\\n" + grounding
        if user_input:
            reply += "\\n\\n(Responding to: " + user_input[:160] + ")"
        return reply
'''

FACTORY_TEMPLATE = '''"""{display_name} factory singleton - the whole {slug} prototype in one file.

Exported by Transcript2Prototype (the gate artifact for the next stage).
Drop this single file into any brainstem's agents/ directory: it carries
every generated agent for the prototype plus a factory that lists, calls,
and keyword-routes across them.

Generated {generated_at} from cubby '{slug}'.
"""

{import_block}

{member_classes}

MEMBER_CLASSES = [{member_class_names}]


class {factory_class}(BasicAgent):
    """Factory singleton over the {display_name} prototype agents."""

    def __init__(self):
        self.name = {factory_name!r}
        self.members = {{}}
        for cls in MEMBER_CLASSES:
            inst = cls()
            self.members[inst.name] = inst
        self.metadata = {{
            "name": self.name,
            "description": (
                "Factory singleton for the {display_name} prototype. "
                "action=manifest lists member agents; action=call runs one by "
                "name; action=route keyword-routes user_input to the best member."
            ),
            "parameters": {{
                "type": "object",
                "properties": {{
                    "action": {{
                        "type": "string",
                        "enum": ["manifest", "call", "route"],
                        "description": "what to do",
                    }},
                    "agent": {{
                        "type": "string",
                        "description": "call: the member agent name",
                    }},
                    "user_input": {{
                        "type": "string",
                        "description": "call/route: the user's request",
                    }},
                }},
                "required": ["action"],
            }},
        }}
        super().__init__(self.name, self.metadata)

    def perform(self, **kwargs):
        import json as _json
        action = (kwargs.get("action") or "manifest").lower()
        if action == "manifest":
            return _json.dumps({{
                "schema": "t2p-factory/1.0",
                "factory": self.name,
                "prototype": {slug!r},
                "members": [
                    {{"name": n, "description": a.metadata.get("description", "")}}
                    for n, a in sorted(self.members.items())
                ],
            }}, indent=2)
        if action == "call":
            name = kwargs.get("agent") or ""
            agent = self.members.get(name)
            if not agent:
                return _json.dumps({{"status": "error",
                                     "error": "unknown member agent " + repr(name),
                                     "members": sorted(self.members)}})
            return agent.perform(user_input=kwargs.get("user_input", ""))
        if action == "route":
            text = (kwargs.get("user_input") or "").lower()
            best, best_score = None, 0
            for agent in self.members.values():
                hay = (agent.metadata.get("description", "") + " "
                       + " ".join(getattr(agent, "TRIGGERS", []))).lower()
                score = sum(1 for w in set(text.split()) if len(w) > 3 and w in hay)
                if score > best_score:
                    best, best_score = agent, score
            if best is None:
                best = next(iter(self.members.values()))
            return best.perform(user_input=kwargs.get("user_input", ""))
        return _json.dumps({{"status": "error", "error": "action must be manifest | call | route"}})
'''


# ---------------------------------------------------------------------------
# the agent
# ---------------------------------------------------------------------------
class Transcript2PrototypeAgent(BasicAgent):
    def __init__(self):
        self.name = "Transcript2Prototype"
        self.metadata = {
            "name": self.name,
            "description": (
                "Turn a pasted business transcript into a working agent prototype, "
                "end to end, one isolated cubby per prototype: generate a turn-by-turn "
                "demo script, surface it as a static M365 Copilot demo injected as "
                "base64 bytecode in the rapplication iframe, adjust it conversationally, "
                "build the actual agent.py files, replay the demo against them on a "
                "local twin and then a live twin, and export everything as one factory "
                "singleton agent.py (the gate). Browse prototypes with list/search/focus."),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["help", "spec", "start", "list", "search", "focus",
                                 "status", "show_demo", "adjust", "build", "test",
                                 "export", "open"],
                        "description": "what to do (help for the map)",
                    },
                    "transcript": {
                        "type": "string",
                        "description": ("start (REQUIRED): the full transcript text, "
                                        "verbatim, exactly as the user pasted it. Do "
                                        "not summarize it - pass the whole thing.")},
                    "capabilities": {
                        "type": "string",
                        "description": ("start (STRONGLY PREFERRED): YOU are the "
                                        "analyst. Read the transcript yourself, "
                                        "identify the 3-5 concrete things the customer "
                                        "needs an agent to do, and pass them here as a "
                                        "JSON array string. " + CAPABILITIES_SCHEMA_HINT
                                        + " If you omit this, a deterministic keyword "
                                        "heuristic analyzes the transcript instead - "
                                        "it works but your analysis is better.")},
                    "name": {"type": "string",
                             "description": ("start: short prototype name; becomes the "
                                             "cubby slug, e.g. 'contoso-claims'. "
                                             "Defaults from customer/transcript.")},
                    "customer_name": {"type": "string",
                                      "description": ("start: the customer/company the "
                                                      "prototype is for; appears in the "
                                                      "demo UI. Extract it from the "
                                                      "transcript if you can.")},
                    "agent_name": {"type": "string",
                                   "description": ("start: display name of the demoed "
                                                   "copilot, e.g. 'Northwind Onboarding "
                                                   "Assistant'. Default: '<customer> "
                                                   "Assistant'.")},
                    "pain_markers": {
                        "type": "string",
                        "description": ("start, fallback analyzer only: comma-separated "
                                        "phrases that mark a pain/need sentence in this "
                                        "transcript (e.g. 'we need,takes hours,no way "
                                        "to'). Only used when capabilities= is omitted; "
                                        "sensible defaults exist.")},
                    "capability_vocabulary": {
                        "type": "string",
                        "description": ("start, fallback analyzer only: comma-separated "
                                        "domain words (prefixes ok) that make good "
                                        "capability names for this customer (e.g. "
                                        "'triage,claims,drafting'). Only used when "
                                        "capabilities= is omitted; defaults exist.")},
                    "max_capabilities": {
                        "type": "integer",
                        "description": ("start, fallback analyzer only: cap on how many "
                                        "capabilities to extract (default 5).")},
                    "cubby": {"type": "string",
                              "description": "focus/status/...: prototype cubby slug"},
                    "query": {"type": "string",
                              "description": "search: term to find across prototype cubbies"},
                    "turn": {"type": "integer",
                             "description": "adjust: 1-based demo turn number"},
                    "user": {"type": "string",
                             "description": "adjust: replacement user message for the turn"},
                    "assistant": {"type": "string",
                                  "description": "adjust: replacement scripted response"},
                    "expect": {"type": "string",
                               "description": "adjust: comma-separated expected keywords"},
                    "remove": {"type": "boolean",
                               "description": "adjust: remove the turn instead"},
                    "add": {"type": "boolean",
                            "description": "adjust: append a new turn (user= and assistant=)"},
                    "instruction": {
                        "type": "string",
                        "description": ("adjust: free-text change request. The agent "
                                        "does NOT interpret it - it returns the current "
                                        "demo script so YOU can decide the new wording "
                                        "and re-call adjust with the structured fields "
                                        "(turn=, user=, assistant=, expect=, remove=, "
                                        "add=). Prefer the structured fields directly.")},
                    "target": {"type": "string", "enum": ["local", "twin"],
                               "description": "test: local in-process twin or live twin over HTTP"},
                    "twin_url": {"type": "string",
                                 "description": "test target=twin: twin /chat base url (default http://localhost:7071)"},
                    "twin_dir": {"type": "string",
                                 "description": "test target=twin: agents dir to inject into (default this brainstem's agents/)"},
                    "inject": {"type": "boolean",
                               "description": "test target=twin: copy the built agent.pys into twin_dir first (default true)"},
                    "threshold": {"type": "number",
                                  "description": "test: pass threshold for keyword score (local 0.6, twin 0.35)"},
                    "skip_twin": {"type": "boolean",
                                  "description": "export: allow exporting with only the local run passed"},
                    "force": {"type": "boolean",
                              "description": "start: overwrite an existing prototype cubby"},
                },
                "required": ["action"],
            },
        }
        super().__init__(self.name, self.metadata)

    def system_context(self):
        return (
            "Transcript2Prototype is loaded: the transcript-to-prototype pipeline "
            "rapplication. YOU do the thinking; the agent does the plumbing - every "
            "input is a parameter, nothing is hardcoded. When a user pastes a "
            "meeting/discovery transcript and wants a prototype, demo, or agents "
            "built from it: (1) read the transcript YOURSELF, identify the 3-5 "
            "capabilities the customer needs, and call action=start with "
            "transcript=<full verbatim text>, customer_name=, name=, and "
            "capabilities=<JSON array per the parameter description> - that is the "
            "high-quality path; omitting capabilities falls back to a keyword "
            "heuristic. (2) When the user asks for changes in plain language ('make "
            "turn 2 about refunds'), decide the new wording yourself and call "
            "action=adjust with the structured fields (turn=, user=, assistant=, "
            "expect=, add=, remove=) - one call per turn changed; the iframe bytecode "
            "regenerates automatically. (3) Then action=build, action=test "
            "target=local, action=test target=twin, action=export (the GATE - the "
            "pipeline stops there and hands off the factory singleton). Browse "
            "prototypes with action=list / search / focus. ALWAYS relay the returned "
            "rapplication HTML path so the user can open the demo in a browser, and "
            "summarize test pass rates when tests run.")

    # ---- context -----------------------------------------------------------
    def _home(self, kwargs):
        return kwargs.get("_home_dir") or os.path.expanduser("~")

    def _cubby_root(self, kwargs):
        return os.path.join(self._home(kwargs), ".brainstem", "cubbies")

    def _focus_file(self, kwargs):
        return os.path.join(self._home(kwargs), ".brainstem", "t2p_focus.json")

    def _bs_agents_dir(self, kwargs):
        explicit = kwargs.get("twin_dir")
        if explicit:
            return explicit
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents")

    def _env(self, action, status, **fields):
        return json.dumps({"schema": RESULT_SCHEMA, "action": action,
                           "status": status, **fields},
                          indent=2, ensure_ascii=False)

    def _resolve(self, kwargs, need_proto=True):
        """-> (slug, cubby_dir, proto|None, error_json|None)"""
        root = self._cubby_root(kwargs)
        slug = (kwargs.get("cubby") or kwargs.get("name") or "").strip()
        if not slug:
            focus = _read_json(self._focus_file(kwargs)) or {}
            slug = focus.get("cubby") or ""
        if not slug:
            return None, None, None, self._env(
                kwargs.get("action", "?"), "error",
                error="no prototype in focus - pass cubby=<slug> or run action=focus first.",
                hint="action=list shows every prototype cubby.")
        if not _SLUG_RE.match(slug):
            return None, None, None, self._env(
                kwargs.get("action", "?"), "error", error="unsafe cubby slug")
        cubby = os.path.join(root, slug)
        proto = _read_json(os.path.join(cubby, "prototype.json"))
        if need_proto and not proto:
            return None, None, None, self._env(
                kwargs.get("action", "?"), "error",
                error=f"'{slug}' is not a prototype cubby (no prototype.json).",
                hint="action=start transcript=... name=... creates one.")
        return slug, cubby, proto, None

    def _save(self, cubby, proto):
        proto["updated_at"] = _now()
        _write_json(os.path.join(cubby, "prototype.json"), proto)

    # ---- perform -----------------------------------------------------------
    def perform(self, **kwargs):
        action = (kwargs.get("action") or "help").lower()
        try:
            if action == "help":
                return self._help()
            if action == "spec":
                return self._spec()
            if action == "start":
                return self._start(kwargs)
            if action == "list":
                return self._list(kwargs)
            if action == "search":
                return self._search(kwargs)
            if action == "focus":
                return self._focus(kwargs)
            if action == "status":
                return self._status(kwargs)
            if action == "show_demo":
                return self._show_demo(kwargs)
            if action == "adjust":
                return self._adjust(kwargs)
            if action == "build":
                return self._build(kwargs)
            if action == "test":
                return self._test(kwargs)
            if action == "export":
                return self._export(kwargs)
            if action == "open":
                return self._open(kwargs)
            return self._help()
        except Exception as e:  # noqa: BLE001 - agents must not crash the loop
            return self._env(action, "error", error=f"{type(e).__name__}: {e}")

    # ---- orient ------------------------------------------------------------
    def _help(self):
        return (
            "Transcript2Prototype - transcript in, working prototype out. One cubby per prototype.\n"
            "  start    transcript=<text> capabilities=<JSON you authored - preferred>\n"
            "           [name=...] [customer_name=...] [agent_name=...]\n"
            "           (fallback tuning: pain_markers=, capability_vocabulary=, max_capabilities=)\n"
            "           -> cubby + demo script + M365 demo iframe rapplication (scripted bytecode)\n"
            "  adjust   turn=N [user=...] [assistant=...] [expect=a,b] [remove=true] | add=true | instruction=...\n"
            "           -> edits the demo script, regenerates the injected bytecode (any stage)\n"
            "  build    -> generates the real agent.py files into the cubby's agents/\n"
            "  test     target=local  -> replay the demo against the generated agents in-process\n"
            "           target=twin [twin_url=...] [twin_dir=...] -> inject + replay over HTTP; iframe goes live\n"
            "  export   [skip_twin=true] -> ONE factory singleton agent.py in exports/ - THE GATE (stops here)\n"
            "  browse   list | search query=... | focus cubby=... | status | show_demo | open\n"
            "  orient   spec (the pipeline map)\n")

    def _spec(self):
        return (
            "# Transcript2Prototype pipeline\n\n"
            "Stages per prototype (state in <cubby>/prototype.json):\n"
            "  intake+demo -> built -> local_passed -> twin_passed -> exported (GATE)\n\n"
            "1. start: the transcript is analyzed (LLM when reachable, deterministic\n"
            "   heuristics otherwise) into capabilities. A turn-by-turn demo script is\n"
            "   generated and injected into a static M365 Copilot demo template; that\n"
            "   page is base64-encoded and embedded as the iframe bytecode of the\n"
            "   rapplication shell (rapplications/<slug>_rapplication.html). Scripted\n"
            "   mode: sends are answered from the embedded script.\n"
            "2. adjust: any turn can be edited conversationally at any stage; the\n"
            "   bytecode is regenerated so the iframe always plays the current script.\n"
            "   Adjusting after a test run invalidates the test results.\n"
            "3. build: one agent.py per capability lands in <cubby>/agents/, grounded\n"
            "   in the same analysis the demo script came from.\n"
            "4. test target=local: the agent.pys are loaded in-process (the local twin)\n"
            "   and every demo turn is replayed and scored against its expected\n"
            "   keywords. Report: show-and-tell/test_report_local.json.\n"
            "5. test target=twin: the agent.pys are injected into a live twin's agents/\n"
            "   (hot-reload) and the SAME demo replays over HTTP against /chat. The\n"
            "   rapplication iframe is regenerated in live mode pointed at the twin.\n"
            "   Report: show-and-tell/test_report_twin.json.\n"
            "6. export: all generated agents are bundled into ONE factory singleton\n"
            "   <slug>_factory_agent.py in <cubby>/exports/. THE PIPELINE STOPS HERE -\n"
            "   the singleton is the handoff artifact for the next stage.\n\n"
            "Cubbies are standard rapp-cubby/1.0 (RappAgent's cubby_list, super_rar and\n"
            "cubby_egg all work on them). Everything is local-first; no cloud required.\n")

    # ---- start -------------------------------------------------------------
    def _start(self, kwargs):
        transcript = (kwargs.get("transcript") or "").strip()
        if len(transcript) < 40:
            return self._env("start", "error",
                             error="pass transcript=<the pasted transcript text> (at least a few sentences).")
        customer = (kwargs.get("customer_name") or "").strip()
        name = (kwargs.get("name") or "").strip()
        slug = _slugify(name or customer or " ".join(transcript.split()[:4]))
        root = self._cubby_root(kwargs)
        cubby = os.path.join(root, slug)
        existing = _read_json(os.path.join(cubby, "prototype.json"))
        if existing and not kwargs.get("force"):
            return self._env("start", "already_exists", cubby=slug, path=cubby,
                             stage=existing.get("stage"),
                             hint=("prototype cubby already exists - focus cubby=%s to work on it, "
                                   "or pass force=true to overwrite." % slug))

        # cubby anatomy (first-class rapp-cubby/1.0 so RappAgent sees it)
        for d in CUBBY_ANATOMY:
            os.makedirs(os.path.join(cubby, d), exist_ok=True)
            gk = os.path.join(cubby, d, ".gitkeep")
            if not os.path.exists(gk):
                open(gk, "w").close()
        os.makedirs(os.path.join(cubby, "exports"), exist_ok=True)
        if not os.path.isfile(os.path.join(cubby, "cubby.json")):
            _write_json(os.path.join(cubby, "cubby.json"), {
                "schema": CUBBY_SCHEMA, "github_login": None, "slug": slug,
                "display_name": slug,
                "what_im_cooking": f"transcript2prototype pipeline for {customer or slug}",
                "created_at": _now(), "estate": {"anatomy": list(CUBBY_ANATOMY)},
                "streamable": {"agents": True}})
        _write_text(os.path.join(cubby, "transcript.txt"), transcript)

        try:
            analysis, source = self._analyze(transcript, customer, kwargs)
        except (ValueError, TypeError) as e:
            msg = f"capabilities parameter invalid: {e}"
            if "JSON array" not in msg:
                msg += ". " + CAPABILITIES_SCHEMA_HINT
            return self._env("start", "error", error=msg)
        demo_script = self._demo_script(analysis)
        proto = {
            "schema": PROTO_SCHEMA, "slug": slug,
            "display_name": analysis.get("agent_name") or _camel(slug),
            "customer": analysis.get("company") or customer or "the customer",
            "created_at": _now(), "updated_at": _now(),
            "stage": "demo", "stages_done": ["intake", "demo"],
            "analysis_source": source,
            "analysis": analysis,
            "demo_script": demo_script,
            "agents_built": [],
            "tests": {},
            "export": None,
            "gate": {"stopped": False},
        }
        paths = self._regen_html(cubby, proto, mode="scripted")
        self._save(cubby, proto)
        _write_json(self._focus_file(kwargs), {"cubby": slug, "at": _now()})
        return self._env(
            "start", "success", cubby=slug, path=cubby, stage="demo",
            analysis_source=source, customer=proto["customer"],
            capabilities=[c["name"] for c in analysis["capabilities"]],
            demo_turns=len(demo_script),
            rapplication=paths["shell"], demo_page=paths["demo"],
            note=("demo script generated and injected into the M365 demo iframe as "
                  "base64 bytecode (scripted playback). Open the rapplication HTML, "
                  "drive it with Up arrow + Enter. Adjust any turn conversationally, "
                  "then 'build' when the demo tells the right story."))

    # ---- analysis ----------------------------------------------------------
    def _analyze(self, transcript, customer, kwargs):
        """Caller-provided capabilities are the preferred path (the caller is
        the analyst); the deterministic heuristic is the documented floor."""
        raw = kwargs.get("capabilities")
        if raw:
            caps = _coerce_capabilities(raw)  # ValueError -> instructive error upstream
            company = customer or "the customer"
            agent_name = (kwargs.get("agent_name")
                          or (f"{company} Assistant" if company != "the customer"
                              else "Prototype Assistant"))
            return {
                "company": company,
                "agent_name": agent_name,
                "summary": (f"Prototype agent set for {company} drawn from the "
                            "transcript: "
                            + ", ".join(c["name"] for c in caps) + "."),
                "capabilities": caps,
            }, "caller"
        analysis = self._analyze_offline(transcript, customer, kwargs)
        if kwargs.get("agent_name"):
            analysis["agent_name"] = str(kwargs["agent_name"]).strip()
        return analysis, "deterministic_fallback"

    def _analyze_offline(self, transcript, customer, kwargs):
        sentences = _sentences(transcript)
        company = customer
        if not company:
            m = re.search(r"(?:Customer|Company|Client)\s*[:\-]\s*([A-Z][\w&. ]{2,40})",
                          transcript)
            if m:
                company = m.group(1).strip().rstrip(".")
        if not company:
            m = re.search(r"\b(?:at|for|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
                          transcript)
            company = m.group(1) if m else "the customer"

        markers = _csv_tuple(kwargs.get("pain_markers")) or DEFAULT_PAIN_MARKERS
        lexicon = _csv_tuple(kwargs.get("capability_vocabulary")) or DEFAULT_CAP_LEXICON
        max_caps = max(1, min(8, int(kwargs.get("max_capabilities") or 5)))
        pains = []
        for i, s in enumerate(sentences):
            low = s.lower()
            if any(marker in low for marker in markers):
                pains.append((i, s))
        if not pains:
            pains = list(enumerate(sentences))[:3]

        tf = {}
        for s in sentences:
            for w in _words(s):
                tf[w] = tf.get(w, 0) + 1

        caps, seen, used_prefixes, consumed = [], set(), set(), set()
        for i, s in pains:
            if i in consumed:
                continue  # restatement of a capability we already captured
            kws = _words(s)
            if not kws:
                continue
            # score every distinct word: capability vocabulary + transcript
            # frequency + length; penalize words already naming another
            # capability so five pains don't all become "Proposal ...".
            scored, first_pos = [], {}
            for pos, w in enumerate(kws):
                if w in first_pos:
                    continue
                first_pos[w] = pos
                score = ((3 if _lex_hit(w, lexicon) else 0)
                         + min(tf.get(w, 0), 3)
                         + (1 if len(w) > 5 else 0)
                         - (4 if w[:6] in used_prefixes else 0))
                scored.append((score, pos, w))
            best = sorted(scored, key=lambda t: (-t[0], t[1]))[:2]
            name_words = [w for _, _, w in sorted(best, key=lambda t: t[1])]
            used_prefixes.update(w[:6] for w in name_words)
            top = list(name_words)
            for w in kws:
                if w not in top:
                    top.append(w)
                if len(top) == 6:
                    break
            name = " ".join(w.capitalize() for w in name_words) or f"Capability {len(caps) + 1}"
            key = _slugify(name).replace("-", "_")
            if key in seen:
                continue
            seen.add(key)
            consumed.add(i)
            neighbor = sentences[i + 1] if i + 1 < len(sentences) else ""
            if neighbor.endswith("?"):
                neighbor = ""  # interviewer question, not customer knowledge
            knowledge = [s] + ([neighbor] if neighbor else [])
            if neighbor:
                consumed.add(i + 1)
            response = (
                f"Here is how the prototype handles **{name}** for {company}:\n\n"
                f"- It addresses the situation you described: \"{s[:180]}\"\n"
                f"- Key elements it works with: {', '.join(top)}.\n"
                f"- Next step: confirm this matches the workflow, then we wire it to "
                f"your real systems.")
            caps.append({
                "key": key, "name": name, "class_name": _camel(name),
                "description": f"Handles {name.lower()} for {company}: {s[:140]}",
                "triggers": top,
                "knowledge": knowledge,
                "response": response,
                "demo_user": f"Show me how you handle {name.lower()}. {s[:120]}",
            })
            if len(caps) == max_caps:
                break
        if not caps:
            caps = [{
                "key": "general_assist", "name": "General Assist",
                "class_name": "GeneralAssist",
                "description": f"General assistant for {company}",
                "triggers": ["assist", "general", "help"],
                "knowledge": sentences[:2] or [transcript[:200]],
                "response": (f"Here is how the prototype can assist {company} - "
                             f"general help grounded in the transcript."),
                "demo_user": "What can you help me with?",
            }]
        agent_name = f"{company} Assistant" if company != "the customer" else "Prototype Assistant"
        return {
            "company": company,
            "agent_name": agent_name,
            "summary": f"Prototype agent set for {company} drawn from the transcript: "
                       + ", ".join(c["name"] for c in caps) + ".",
            "capabilities": caps,
        }

    # ---- demo script -------------------------------------------------------
    def _demo_script(self, analysis):
        caps = analysis["capabilities"]
        turns = []
        overview = ("Here is what this prototype covers for "
                    f"{analysis['company']}:\n\n"
                    + "\n".join(f"- **{c['name']}** - {c['description']}" for c in caps)
                    + "\n\nQueue the next demo step to see each one in action.")
        turns.append({
            "turn": 1, "agent": None,
            "user": "What can you help me with?",
            "assistant": overview,
            "expect": [c["name"].split()[0].lower() for c in caps][:4],
        })
        for c in caps:
            turns.append({
                "turn": len(turns) + 1, "agent": c["key"],
                "user": c["demo_user"],
                "assistant": c["response"],
                "expect": list(c["triggers"][:4]),
            })
        turns.append({
            "turn": len(turns) + 1, "agent": None,
            "user": "Summarize what we just set up.",
            "assistant": (f"We walked through the {analysis['agent_name']} prototype: "
                          + ", ".join(c["name"] for c in caps)
                          + ". Each capability is grounded in your transcript and is "
                            "generated as a real agent.py in the next stage."),
            "expect": ["prototype"],
        })
        return turns

    # ---- html generation ---------------------------------------------------
    def _render_demo_page(self, proto, mode, api_url=""):
        analysis = proto["analysis"]
        demo = [{"q": t["user"], "e": ", ".join(t.get("expect") or []),
                 "a": t.get("assistant") or ""} for t in proto["demo_script"]]
        chips = "".join(f'<span class="chip">{c["name"]}</span>'
                        for c in analysis["capabilities"])
        badge = "SCRIPTED PREVIEW" if mode == "scripted" else "LIVE TWIN"
        html = (M365_TEMPLATE
                .replace("__TITLE__", f"M365 Copilot - {analysis['agent_name']} Demo")
                .replace("__AGENT_NAME__", analysis["agent_name"])
                .replace("__AGENT_SUB__", f"{proto['customer']} - Copilot Agent")
                .replace("__WELCOME_TEXT__", analysis.get("summary") or
                         "Drive the demo with the Up arrow, then Enter to send.")
                .replace("__CHIPS_HTML__", chips)
                .replace("__BADGE__", badge)
                .replace("__MODE__", mode)
                .replace("__API_URL__", api_url or "")
                .replace("__GUID__", f"t2p-{proto['slug']}")
                .replace("__DEMO_JSON__", json.dumps(demo, ensure_ascii=False)))
        return html

    def _render_shell(self, proto, demo_html, mode):
        bytecode = base64.b64encode(demo_html.encode("utf-8")).decode("ascii")
        stage = proto["stage"]
        order = ["demo", "built", "local_passed", "twin_passed", "exported"]
        labels = {"demo": "1 Demo script", "built": "2 Agents built",
                  "local_passed": "3 Local twin run", "twin_passed": "4 Live twin run",
                  "exported": "5 Factory export (gate)"}
        idx = order.index(stage) if stage in order else 0
        chips = []
        for i, key in enumerate(order):
            cls = "stage"
            if i < idx or (i == idx and stage == "exported"):
                cls += " done"
            elif i == idx:
                cls += " current"
            if key == "exported":
                cls += " gate"
            chips.append(f'<span class="{cls}">{labels[key]}</span>')
        mode_badge = ("SCRIPTED BYTECODE" if mode == "scripted"
                      else "LIVE BYTECODE - TWIN")
        return (SHELL_TEMPLATE
                .replace("__TITLE__", f"{proto['display_name']} - Transcript2Prototype")
                .replace("__SUBTITLE__",
                         f"{proto['customer']} | cubby: {proto['slug']}")
                .replace("__MODE_BADGE__", mode_badge)
                .replace("__STAGES_HTML__", "".join(chips))
                .replace("__BYTECODE__", bytecode))

    def _regen_html(self, cubby, proto, mode, api_url=""):
        demo_html = self._render_demo_page(proto, mode, api_url)
        shell_html = self._render_shell(proto, demo_html, mode)
        rapps = os.path.join(cubby, "rapplications")
        demo_path = os.path.join(rapps, f"{proto['slug']}_demo.html")
        shell_path = os.path.join(rapps, f"{proto['slug']}_rapplication.html")
        _write_text(demo_path, demo_html)
        _write_text(shell_path, shell_html)
        proto["html"] = {"demo": demo_path, "shell": shell_path,
                         "mode": mode, "api_url": api_url,
                         "bytecode_sha256": _sha256_text(demo_html)}
        return {"demo": demo_path, "shell": shell_path}

    # ---- browse ------------------------------------------------------------
    def _list(self, kwargs):
        root = self._cubby_root(kwargs)
        focus = (_read_json(self._focus_file(kwargs)) or {}).get("cubby")
        out = []
        if os.path.isdir(root):
            for slug in sorted(os.listdir(root)):
                proto = _read_json(os.path.join(root, slug, "prototype.json"))
                if not proto:
                    continue
                out.append({"cubby": slug, "display_name": proto.get("display_name"),
                            "customer": proto.get("customer"),
                            "stage": proto.get("stage"),
                            "gated": bool((proto.get("gate") or {}).get("stopped")),
                            "demo_turns": len(proto.get("demo_script") or []),
                            "agents_built": len(proto.get("agents_built") or []),
                            "focused": slug == focus})
        return self._env("list", "success", root=root, prototypes=out,
                         count=len(out), focused=focus)

    def _search(self, kwargs):
        q = (kwargs.get("query") or "").strip().lower()
        if not q:
            return self._env("search", "error", error="pass query=<term>")
        root = self._cubby_root(kwargs)
        hits = []
        if os.path.isdir(root):
            for slug in sorted(os.listdir(root)):
                cubby = os.path.join(root, slug)
                proto = _read_json(os.path.join(cubby, "prototype.json"))
                if not proto:
                    continue
                for path in sorted(glob.glob(os.path.join(cubby, "**", "*"),
                                             recursive=True)):
                    if not os.path.isfile(path) or os.path.basename(path).startswith("."):
                        continue
                    rel = os.path.relpath(path, cubby)
                    matched_on = None
                    if q in rel.lower() or q in slug.lower():
                        matched_on = "name"
                    elif (os.path.getsize(path) <= 1024 * 1024
                          and os.path.splitext(path)[1] in
                          (".py", ".json", ".txt", ".md", ".html")):
                        try:
                            with open(path, encoding="utf-8", errors="ignore") as f:
                                if q in f.read().lower():
                                    matched_on = "content"
                        except OSError:
                            pass
                    if matched_on:
                        hits.append({"cubby": slug, "stage": proto.get("stage"),
                                     "path": rel, "matched_on": matched_on})
        by_cubby = {}
        for h in hits:
            by_cubby.setdefault(h["cubby"], 0)
            by_cubby[h["cubby"]] += 1
        return self._env("search", "success", query=q, matches=len(hits),
                         by_cubby=by_cubby, results=hits[:40],
                         hint="action=focus cubby=<slug> to work on one.")

    def _focus(self, kwargs):
        slug, cubby, proto, err = self._resolve(kwargs)
        if err:
            return err
        _write_json(self._focus_file(kwargs), {"cubby": slug, "at": _now()})
        return self._env("focus", "success", cubby=slug, stage=proto.get("stage"),
                         display_name=proto.get("display_name"),
                         note="prototype in focus - status / adjust / build / test / export now target it.")

    def _status(self, kwargs):
        slug, cubby, proto, err = self._resolve(kwargs)
        if err:
            return err
        gate = proto.get("gate") or {}
        return self._env(
            "status", "success", cubby=slug, path=cubby,
            display_name=proto.get("display_name"), customer=proto.get("customer"),
            stage=proto.get("stage"), stages_done=proto.get("stages_done"),
            analysis_source=proto.get("analysis_source"),
            demo_turns=len(proto.get("demo_script") or []),
            capabilities=[c["name"] for c in proto["analysis"]["capabilities"]],
            agents_built=proto.get("agents_built"),
            tests={k: {kk: v.get(kk) for kk in ("passed", "pass_rate", "at", "target")}
                   for k, v in (proto.get("tests") or {}).items()},
            export=proto.get("export"),
            gated=bool(gate.get("stopped")), gate_note=gate.get("note"),
            html=proto.get("html"),
            next=self._next_hint(proto))

    def _next_hint(self, proto):
        stage = proto.get("stage")
        if (proto.get("gate") or {}).get("stopped"):
            return ("GATE: exported and stopped. The factory singleton is the handoff "
                    "for the next stage of the process.")
        return {
            "demo": "review the demo in the rapplication iframe; adjust turns, then action=build",
            "built": "action=test target=local (replay the demo against the generated agents)",
            "local_passed": "action=test target=twin (inject into the live twin and replay over HTTP)",
            "twin_passed": "action=export (bundle the factory singleton - the gate)",
            "exported": "gate reached - pipeline stopped",
        }.get(stage, "action=status")

    def _show_demo(self, kwargs):
        slug, cubby, proto, err = self._resolve(kwargs)
        if err:
            return err
        return self._env("show_demo", "success", cubby=slug,
                         mode=(proto.get("html") or {}).get("mode"),
                         demo_script=proto["demo_script"])

    def _open(self, kwargs):
        slug, cubby, proto, err = self._resolve(kwargs)
        if err:
            return err
        html = proto.get("html") or {}
        return self._env("open", "success", cubby=slug,
                         rapplication=html.get("shell"), demo_page=html.get("demo"),
                         mode=html.get("mode"),
                         note="open the rapplication path in a browser; the demo plays in the iframe.")

    # ---- adjust ------------------------------------------------------------
    def _adjust(self, kwargs):
        slug, cubby, proto, err = self._resolve(kwargs)
        if err:
            return err
        if (proto.get("gate") or {}).get("stopped"):
            return self._env("adjust", "gated", cubby=slug,
                             note="this prototype is exported and gated - start a new "
                                  "prototype (or force a new start) to keep iterating.")
        script = proto["demo_script"]
        changed = []

        instruction = (kwargs.get("instruction") or "").strip()
        if instruction and not kwargs.get("user") and not kwargs.get("assistant") \
                and not kwargs.get("remove") and not kwargs.get("add"):
            # the agent does not interpret free text - the CALLER is the
            # intelligence. Hand back the script and the exact follow-up calls.
            return self._env(
                "adjust", "needs_structured", cubby=slug,
                instruction=instruction,
                demo_script=proto["demo_script"],
                note=("CALLER: apply the instruction yourself - the current demo "
                      "script is included above. Decide the new wording and call "
                      "this agent again with the structured form: adjust turn=N "
                      "user=... assistant=... expect=a,b (or remove=true, or "
                      "add=true user=... assistant=...). One call per turn you "
                      "change."))
        elif kwargs.get("add"):
            n = len(script) + 1
            script.append({
                "turn": n, "agent": None,
                "user": kwargs.get("user") or f"Demo step {n}",
                "assistant": kwargs.get("assistant") or "(scripted response)",
                "expect": [w.strip() for w in (kwargs.get("expect") or "").split(",") if w.strip()],
            })
            changed.append(f"added turn {n}")
        else:
            turn_no = kwargs.get("turn")
            if not turn_no:
                return self._env("adjust", "error",
                                 error="pass turn=N (1-based) with user=/assistant=/expect=/remove=, "
                                       "add=true for a new turn, or instruction=... for an LLM rewrite.")
            turn_no = int(turn_no)
            if turn_no < 1 or turn_no > len(script):
                return self._env("adjust", "error",
                                 error=f"turn {turn_no} out of range 1..{len(script)}")
            if kwargs.get("remove"):
                script.pop(turn_no - 1)
                for i, t in enumerate(script):
                    t["turn"] = i + 1
                changed.append(f"removed turn {turn_no}")
            else:
                t = script[turn_no - 1]
                if kwargs.get("user"):
                    t["user"] = kwargs["user"]
                    changed.append(f"turn {turn_no} user")
                if kwargs.get("assistant"):
                    t["assistant"] = kwargs["assistant"]
                    changed.append(f"turn {turn_no} assistant")
                if kwargs.get("expect"):
                    t["expect"] = [w.strip() for w in kwargs["expect"].split(",") if w.strip()]
                    changed.append(f"turn {turn_no} expect")
                if not changed:
                    return self._env("adjust", "error",
                                     error="nothing to change - pass user=, assistant=, expect= or remove=true.")

        # downstream invalidation: demo changed -> prior test runs are stale
        stale = bool(proto.get("tests"))
        proto["tests"] = {}
        if proto["stage"] in ("local_passed", "twin_passed"):
            proto["stage"] = "built" if proto.get("agents_built") else "demo"
        html = proto.get("html") or {}
        paths = self._regen_html(cubby, proto, mode=html.get("mode") or "scripted",
                                 api_url=html.get("api_url") or "")
        self._save(cubby, proto)
        return self._env("adjust", "success", cubby=slug, changed=changed,
                         demo_turns=len(proto["demo_script"]),
                         tests_invalidated=stale, stage=proto["stage"],
                         rapplication=paths["shell"],
                         note="bytecode regenerated - the iframe now plays the updated script.")

    # ---- build -------------------------------------------------------------
    def _build(self, kwargs):
        slug, cubby, proto, err = self._resolve(kwargs)
        if err:
            return err
        if (proto.get("gate") or {}).get("stopped"):
            return self._env("build", "gated", cubby=slug, note="exported and gated.")
        slug_camel = _camel(slug)
        agents_dir = os.path.join(cubby, "agents")
        built, errors = [], []
        for cap in proto["analysis"]["capabilities"]:
            class_name = f"{slug_camel}{cap['class_name']}Agent"
            agent_name = f"{slug_camel}{cap['class_name']}"
            filename = f"{slug.replace('-', '_')}_{cap['key']}_agent.py"
            source = (
                f'"""{cap["name"]} agent for the {proto["display_name"]} prototype.\n\n'
                f'Generated by Transcript2Prototype from cubby {slug!r}.\n'
                f'{cap["description"]}\n"""\n\n'
                + AGENT_IMPORT_BLOCK
                + AGENT_CLASS_TEMPLATE.format(
                    class_name=class_name,
                    description=cap["description"].replace('"', "'"),
                    knowledge=cap["knowledge"],
                    triggers=cap["triggers"],
                    response=cap["response"],
                    agent_name=agent_name,
                    tool_description=(f"{cap['name']} for {proto['customer']}: "
                                      f"{cap['description']}")[:300],
                ))
            try:
                compile(source, filename, "exec")
            except SyntaxError as e:
                errors.append({"file": filename, "error": str(e)})
                continue
            path = os.path.join(agents_dir, filename)
            _write_text(path, source)
            built.append({"file": filename, "class": class_name,
                          "agent": agent_name, "capability": cap["key"],
                          "sha256": _sha256_text(source)})
        if errors:
            return self._env("build", "error", cubby=slug, errors=errors, built=built)
        proto["agents_built"] = built
        proto["stage"] = "built"
        if "build" not in proto["stages_done"]:
            proto["stages_done"].append("build")
        proto["tests"] = {}
        self._save(cubby, proto)
        return self._env("build", "success", cubby=slug,
                         agents=[b["file"] for b in built],
                         path=agents_dir, stage="built",
                         note="real agent.py files generated. Next: action=test target=local "
                              "to replay the demo against them on the local twin.")

    # ---- the local twin: load generated agents in-process -------------------
    def _load_built_agents(self, cubby, proto):
        """exec each generated agent file -> {agent_name: instance}. The inline
        BasicAgent fallback in every generated file makes this hermetic."""
        registry = {}
        agents_dir = os.path.join(cubby, "agents")
        for rec in proto.get("agents_built") or []:
            path = os.path.join(agents_dir, rec["file"])
            with open(path, encoding="utf-8") as f:
                source = f.read()
            ns = {"__name__": f"t2p_local.{rec['capability']}"}
            exec(compile(source, path, "exec"), ns)  # noqa: S102 - our own generated file
            cls = ns.get(rec["class"])
            if cls:
                inst = cls()
                registry[inst.name] = inst
        return registry

    def _grade_turns(self, proto, respond, threshold, live):
        """Replay every demo turn through respond(turn)->text and score it."""
        results, all_pass = [], True
        for t in proto["demo_script"]:
            expected = t.get("expect") or []
            narrative = t.get("agent") is None
            if narrative and not live:
                results.append({"turn": t["turn"], "mode": "narrative",
                                "passed": True,
                                "note": "scripted narrative turn - no generated agent behind it"})
                continue
            actual, err = respond(t)
            if err:
                results.append({"turn": t["turn"], "passed": False, "error": err})
                all_pass = False
                continue
            if narrative:
                ok = bool((actual or "").strip())
                results.append({"turn": t["turn"], "mode": "narrative", "passed": ok,
                                "actual_excerpt": (actual or "")[:200]})
                all_pass = all_pass and ok
                continue
            score, hits = _kw_score(expected, actual or "")
            ok = score >= threshold and bool((actual or "").strip())
            results.append({"turn": t["turn"], "agent": t.get("agent"),
                            "expected": expected, "hit": hits,
                            "score": round(score, 2), "passed": ok,
                            "actual_excerpt": (actual or "")[:200]})
            all_pass = all_pass and ok
        graded = [r for r in results if "score" in r]
        pass_rate = (sum(1 for r in results if r["passed"]) / max(1, len(results)))
        return results, all_pass, round(pass_rate, 2), graded

    def _test(self, kwargs):
        slug, cubby, proto, err = self._resolve(kwargs)
        if err:
            return err
        if (proto.get("gate") or {}).get("stopped"):
            return self._env("test", "gated", cubby=slug, note="exported and gated.")
        if not proto.get("agents_built"):
            return self._env("test", "error", cubby=slug,
                             error="no agents built yet - action=build first.")
        target = (kwargs.get("target") or
                  ("twin" if proto["stage"] == "local_passed" else "local")).lower()
        if target == "local":
            return self._test_local(kwargs, slug, cubby, proto)
        return self._test_twin(kwargs, slug, cubby, proto)

    def _test_local(self, kwargs, slug, cubby, proto):
        threshold = float(kwargs.get("threshold") or 0.6)
        registry = self._load_built_agents(cubby, proto)
        by_cap = {}
        for rec in proto["agents_built"]:
            inst = registry.get(rec["agent"])
            if inst:
                by_cap[rec["capability"]] = inst

        def respond(turn):
            agent = by_cap.get(turn.get("agent"))
            if not agent:
                return None, f"no generated agent for capability {turn.get('agent')!r}"
            try:
                return agent.perform(user_input=turn["user"]), None
            except Exception as e:  # noqa: BLE001
                return None, f"{type(e).__name__}: {e}"

        results, all_pass, pass_rate, graded = self._grade_turns(
            proto, respond, threshold, live=False)
        report = {"schema": "t2p-test-report/1.0", "target": "local",
                  "cubby": slug, "at": _now(), "threshold": threshold,
                  "passed": all_pass, "pass_rate": pass_rate,
                  "agents_loaded": sorted(registry), "turns": results}
        _write_json(os.path.join(cubby, "show-and-tell", "test_report_local.json"),
                    report)
        proto.setdefault("tests", {})["local"] = {
            "target": "local", "passed": all_pass, "pass_rate": pass_rate,
            "at": report["at"],
            "report": os.path.join(cubby, "show-and-tell", "test_report_local.json")}
        if all_pass:
            proto["stage"] = "local_passed"
            if "test_local" not in proto["stages_done"]:
                proto["stages_done"].append("test_local")
        self._save(cubby, proto)
        return self._env(
            "test", "success" if all_pass else "failed", cubby=slug, target="local",
            passed=all_pass, pass_rate=pass_rate, threshold=threshold,
            turns=results, report=proto["tests"]["local"]["report"],
            stage=proto["stage"],
            note=("local twin run passed - the generated agents reproduce the demo. "
                  "Next: action=test target=twin to replay against a live twin."
                  if all_pass else
                  "some turns missed their expected keywords - adjust the demo or "
                  "rebuild, then re-run."))

    def _test_twin(self, kwargs, slug, cubby, proto):
        if not (proto.get("tests", {}).get("local") or {}).get("passed"):
            return self._env("test", "error", cubby=slug,
                             error="run (and pass) test target=local before the live twin run.")
        threshold = float(kwargs.get("threshold") or 0.35)
        twin_url = (kwargs.get("twin_url") or "http://localhost:7071").rstrip("/")
        chat_url = twin_url if twin_url.endswith("/chat") else twin_url + "/chat"
        inject = kwargs.get("inject", True)
        injected = []
        twin_dir = self._bs_agents_dir(kwargs)
        if inject:
            os.makedirs(twin_dir, exist_ok=True)
            for rec in proto["agents_built"]:
                src = os.path.join(cubby, "agents", rec["file"])
                dst = os.path.join(twin_dir, rec["file"])
                with open(src, encoding="utf-8") as f:
                    _write_text(dst, f.read())
                injected.append(dst)

        history = []

        def respond(turn):
            payload = {"user_input": turn["user"],
                       "conversation_history": history[-10:],
                       "session_id": f"t2p-{slug}"}
            data, err = _post_json(chat_url, payload, timeout=120)
            if err:
                return None, f"twin unreachable or errored at {chat_url}: {err}"
            text = (data.get("response") or data.get("assistant_response") or "")
            text = text.split("|||VOICE|||")[0].strip()
            history.append({"role": "user", "content": turn["user"]})
            history.append({"role": "assistant", "content": text})
            return text, None

        results, all_pass, pass_rate, graded = self._grade_turns(
            proto, respond, threshold, live=True)
        unreachable = any("unreachable" in (r.get("error") or "") for r in results)
        report = {"schema": "t2p-test-report/1.0", "target": "twin",
                  "cubby": slug, "at": _now(), "twin_url": chat_url,
                  "threshold": threshold, "injected": injected,
                  "passed": all_pass, "pass_rate": pass_rate, "turns": results}
        _write_json(os.path.join(cubby, "show-and-tell", "test_report_twin.json"),
                    report)
        proto.setdefault("tests", {})["twin"] = {
            "target": "twin", "passed": all_pass, "pass_rate": pass_rate,
            "at": report["at"], "twin_url": chat_url,
            "report": os.path.join(cubby, "show-and-tell", "test_report_twin.json")}
        paths = None
        if all_pass:
            proto["stage"] = "twin_passed"
            if "test_twin" not in proto["stages_done"]:
                proto["stages_done"].append("test_twin")
            # the same rapplication iframe now drives the REAL agents on the twin
            paths = self._regen_html(cubby, proto, mode="live", api_url=chat_url)
        self._save(cubby, proto)
        status = "success" if all_pass else ("needs_twin" if unreachable else "failed")
        return self._env(
            "test", status, cubby=slug, target="twin", twin_url=chat_url,
            injected=len(injected), passed=all_pass, pass_rate=pass_rate,
            threshold=threshold, turns=results,
            report=proto["tests"]["twin"]["report"], stage=proto["stage"],
            rapplication=(paths or {}).get("shell"),
            note=("live twin run passed - the rapplication iframe was regenerated in "
                  "LIVE mode pointed at the twin, so the same demo now drives the real "
                  "agents. Next: action=export (the gate)." if all_pass else
                  ("twin not reachable - start your brainstem/twin and re-run, or pass "
                   "twin_url=..." if unreachable else
                   "some live turns scored below threshold - the twin's LLM may route "
                   "differently; adjust expectations or re-run.")))

    # ---- export: the factory singleton + THE GATE ---------------------------
    def _export(self, kwargs):
        slug, cubby, proto, err = self._resolve(kwargs)
        if err:
            return err
        if (proto.get("gate") or {}).get("stopped"):
            return self._env("export", "gated", cubby=slug,
                             export=proto.get("export"),
                             note="already exported and gated - the factory singleton is the handoff artifact.")
        if not proto.get("agents_built"):
            return self._env("export", "error", cubby=slug,
                             error="nothing to export - action=build first.")
        tests = proto.get("tests") or {}
        if not (tests.get("local") or {}).get("passed"):
            return self._env("export", "refused", cubby=slug,
                             error="export requires a passing local twin run (action=test target=local).")
        if not (tests.get("twin") or {}).get("passed") and not kwargs.get("skip_twin"):
            return self._env("export", "refused", cubby=slug,
                             error=("export requires a passing live twin run (action=test "
                                    "target=twin), or pass skip_twin=true to gate on the "
                                    "local run only."))

        slug_camel = _camel(slug)
        member_sources, member_class_names = [], []
        agents_dir = os.path.join(cubby, "agents")
        for rec in proto["agents_built"]:
            with open(os.path.join(agents_dir, rec["file"]), encoding="utf-8") as f:
                source = f.read()
            # strip each member's docstring header + import block; the factory
            # carries ONE import block at the top.
            body = source.split(AGENT_IMPORT_BLOCK, 1)[-1].strip("\n")
            member_sources.append(body)
            member_class_names.append(rec["class"])

        factory_class = f"{slug_camel}FactoryAgent"
        factory_name = f"{slug_camel}Factory"
        factory_source = FACTORY_TEMPLATE.format(
            display_name=proto["display_name"],
            slug=slug,
            generated_at=_now(),
            import_block=AGENT_IMPORT_BLOCK,
            member_classes="\n\n".join(member_sources),
            member_class_names=", ".join(member_class_names),
            factory_class=factory_class,
            factory_name=factory_name,
        )
        out_name = f"{slug.replace('-', '_')}_factory_agent.py"
        out_path = os.path.join(cubby, "exports", out_name)
        compile(factory_source, out_name, "exec")  # must be valid standalone python
        _write_text(out_path, factory_source)
        sha = _sha256_text(factory_source)
        proto["export"] = {"path": out_path, "file": out_name, "sha256": sha,
                           "factory_class": factory_class,
                           "factory_name": factory_name,
                           "members": member_class_names, "at": _now()}
        proto["stage"] = "exported"
        if "export" not in proto["stages_done"]:
            proto["stages_done"].append("export")
        proto["gate"] = {
            "stopped": True,
            "note": ("GATE: pipeline stopped at export. The factory singleton is the "
                     "handoff artifact for the next stage of the process."),
            "at": _now()}
        self._save(cubby, proto)
        return self._env(
            "export", "success", cubby=slug, factory=out_path, sha256=sha,
            factory_class=factory_class, members=member_class_names,
            stage="exported", gated=True,
            note=("THE GATE: pipeline stopped here by design. "
                  f"{out_name} is one self-contained agent.py carrying the whole "
                  "prototype (drop it into any brainstem's agents/ or feed it to the "
                  "next stage, e.g. the Copilot Studio packaging pipeline)."))
