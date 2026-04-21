"""
exec_brief_agent.py — Four-agent pipeline that produces executive briefs.

Scout -> Analyst -> Strategist -> Writer. Each persona has its own SOUL prompt
and makes its own LLM call. The pipeline passes structured data between steps.

Drop this file + the four brief_*_agent.py files into any RAPP brainstem's
agents/ directory and the pipeline works. Or converge with SwarmFactory
into a single deployable file.
"""

from agents.basic_agent import BasicAgent
from agents.brief_scout_agent import BriefScoutAgent
from agents.brief_analyst_agent import BriefAnalystAgent
from agents.brief_strategist_agent import BriefStrategistAgent
from agents.brief_writer_agent import BriefWriterAgent
import importlib.util
import json
import os
import re
import time

# Best-effort index-card import. If the brainstem bound a turn to this
# thread, card() writes live progress that the UI polls. If the helper
# is missing (older brainstem) or no turn is bound, card() is a no-op.
try:
    from utils.index_card import current as _card
except Exception:
    def _card():
        class _N:
            def __getattr__(self, _): return lambda *a, **k: self
        return _N()


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/exec-brief",
    "version": "1.0.0",
    "display_name": "Executive Brief",
    "description": "Four-agent pipeline that produces polished executive briefs on any topic.",
    "author": "@rapp",
    "tags": ["composite", "exec-brief-pipeline"],
    "category": "analysis",
    "quality_tier": "official",
    "requires_env": [],
    "delegates_to": [
        "@rapp/brief-scout",
        "@rapp/brief-analyst",
        "@rapp/brief-strategist",
        "@rapp/brief-writer",
        "@rapp/pitch_deck",
    ],
    "example_call": {
        "args": {"topic": "Why our org needs a unified agent sharing standard"}
    },
}


class ExecBriefAgent(BasicAgent):
    def __init__(self):
        self.name = "ExecBrief"
        self.metadata = {
            "name": self.name,
            "description": (
                "Runs a four-agent pipeline (Scout, Analyst, Strategist, Writer) "
                "to produce a polished executive brief on any business topic. Use "
                "when the user wants an executive brief, strategic analysis, or "
                "leadership-ready summary on a topic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The business topic or question to brief on",
                    },
                },
                "required": ["topic"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, topic="", **kwargs):
        if not topic.strip():
            return json.dumps({"status": "error", "message": "No topic provided"})

        ws = os.path.join(
            os.environ.get("TWIN_WORKSPACE", "/tmp"), "exec-brief")
        os.makedirs(ws, exist_ok=True)

        def _save(name, content):
            with open(os.path.join(ws, name), "w") as f:
                f.write(content if isinstance(content, str) else str(content))

        def _extract(raw, key):
            try:
                parsed = json.loads(raw)
                return parsed.get(key, raw)
            except (json.JSONDecodeError, TypeError):
                return raw

        print(f'[ExecBrief] Starting pipeline: "{topic}"')

        # Live index card — one surface the UI polls for the whole run.
        c = _card()
        c.start(
            title=f"Executive Brief: {topic}",
            subtitle="5-agent pipeline",
            stages=[
                ("scout",      "Scout"),
                ("analyst",    "Analyst"),
                ("strategist", "Strategist"),
                ("writer",     "Writer"),
                ("deckforge",  "DeckForge"),
            ],
        )

        # ── Step 1: Scout ────────────────────────────────────────────────
        c.stage("scout", status="running", note="gathering intelligence")
        print("[ExecBrief] Step 1/4: Scout gathering intelligence...")
        try:
            scout_raw = BriefScoutAgent().perform(topic=topic)
            _save("01-scout.md", scout_raw)
            research = _extract(scout_raw, "research")
            c.stage("scout", status="done", note="intelligence gathered")
        except Exception as e:
            c.stage("scout", status="failed", note=str(e)[:80])
            c.fail(f"Scout failed: {e}"); raise

        # ── Step 2: Analyst ──────────────────────────────────────────────
        c.stage("analyst", status="running", note="extracting insights")
        print("[ExecBrief] Step 2/4: Analyst extracting insights...")
        try:
            analyst_raw = BriefAnalystAgent().perform(research=research)
            _save("02-analyst.md", analyst_raw)
            analysis = _extract(analyst_raw, "analysis")
            c.stage("analyst", status="done", note="insights extracted")
        except Exception as e:
            c.stage("analyst", status="failed", note=str(e)[:80])
            c.fail(f"Analyst failed: {e}"); raise

        # ── Step 3: Strategist ───────────────────────────────────────────
        c.stage("strategist", status="running", note="forming recommendations")
        print("[ExecBrief] Step 3/4: Strategist forming recommendations...")
        try:
            strategist_raw = BriefStrategistAgent().perform(
                analysis=analysis, topic=topic)
            _save("03-strategist.md", strategist_raw)
            strategy = _extract(strategist_raw, "strategy")
            c.stage("strategist", status="done", note="recommendations formed")
        except Exception as e:
            c.stage("strategist", status="failed", note=str(e)[:80])
            c.fail(f"Strategist failed: {e}"); raise

        # ── Step 4: Writer ───────────────────────────────────────────────
        c.stage("writer", status="running", note="composing brief")
        print("[ExecBrief] Step 4/4: Writer composing executive brief...")
        try:
            writer_raw = BriefWriterAgent().perform(
                topic=topic, research=research,
                analysis=analysis, strategy=strategy)
            _save("04-brief.md", writer_raw)
            brief = _extract(writer_raw, "brief")
            c.stage("writer", status="done", note="brief ready")
        except Exception as e:
            c.stage("writer", status="failed", note=str(e)[:80])
            c.fail(f"Writer failed: {e}"); raise

        # ── Step 5: DeckForge — the presentation-ready deliverable ───────
        c.stage("deckforge", status="running", note="building pitch deck")
        print("[ExecBrief] Step 5/5: DeckForge building pitch deck...")
        deck = _build_pitch_deck(topic, brief, research, analysis, strategy, ws)
        if deck.get("url"):
            c.stage("deckforge", status="done", note="deck ready")
        else:
            c.stage("deckforge", status="failed", note="deck not built")

        print("[ExecBrief] Pipeline complete — 5 agents, 1 brief, 1 deck.")

        # Freeze the card: metrics + artifacts, then finish.
        c.metric("agents", 5)
        c.metric("topic", topic)
        if deck.get("url"):
            c.metric("deck", deck["url"])
        c.artifact(
            kind="brief",
            title=f"Executive Brief: {topic}",
            body_md=brief if isinstance(brief, str) else json.dumps(brief, indent=2),
        )
        if deck.get("url"):
            c.artifact(
                kind="deck",
                title="Pitch deck",
                url=deck["url"],
                meta={"path": deck.get("path")},
            )
        c.finish()

        summary_parts = ["### Executive Brief", "", brief]
        if deck.get("url"):
            summary_parts += [
                "",
                "---",
                "",
                "### Presentation-ready pitch deck",
                "",
                f"**[Click to open your pitch deck in a new tab →]({deck['url']})**",
                "",
                "Light/dark theme (`T`) · Exec + rehearse modes (`R`) · "
                "Arrow keys or swipe to navigate. Rehearse mode adds the "
                "email draft, 3-minute video script, and run commands.",
            ]

        return json.dumps({
            "status": "success",
            "brief": brief,
            "deck_url": deck.get("url"),
            "deck_path": deck.get("path"),
            "pipeline": {
                "steps": 5,
                "agents": [
                    "BriefScout", "BriefAnalyst",
                    "BriefStrategist", "BriefWriter", "DeckForge",
                ],
            },
            "workspace": ws,
            "summary": "\n".join(summary_parts),
            "presentation_hint": (
                "Render the summary field verbatim to the user — keep the "
                "markdown link to the deck so the chat UI shows it as a "
                "clickable 'Open in new tab' button."
            ),
            "data_slush": {
                "topic": topic,
                "brief_ready": True,
                "deck_ready": bool(deck.get("url")),
                "deck_url": deck.get("url"),
            },
        })


# ─── DeckForge: turn the brief into a presentation-ready HTML deck ───────
# Uses @rapp/pitch_deck if available. Graceful degradation if not.

def _build_pitch_deck(topic, brief, research, analysis, strategy, workspace):
    """Generate an HTML pitch deck and return {url, path} for the chat CTA."""
    web_dir = _find_brainstem_web_dir()
    slug = re.sub(r"[^a-z0-9]+", "-", (topic or "brief").lower()).strip("-")[:40] or "brief"
    filename = f"execbrief-{slug}-{int(time.time())}.html"

    if web_dir:
        pitches_dir = os.path.join(web_dir, "pitches")
        path = os.path.join(pitches_dir, filename)
        url = f"/web/pitches/{filename}"
    else:
        # No brainstem web dir — fall back to workspace with file:// URL
        pitches_dir = workspace
        path = os.path.join(pitches_dir, filename)
        url = f"file://{path}"
    os.makedirs(pitches_dir, exist_ok=True)

    pitch_deck = _load_pitch_deck_agent()
    if pitch_deck is None:
        print("[DeckForge] @rapp/pitch_deck not available — skipping deck")
        return {}

    try:
        thesis = (brief or "").strip()[:800]
        result_raw = pitch_deck.perform(
            topic=topic,
            thesis=thesis,
            audience="executive leadership",
            product_name=(topic.split(":")[0].strip() or "Executive Brief")[:40],
            output_path=path,
        )
        try:
            result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
        except (json.JSONDecodeError, TypeError):
            result = {}
        if result.get("status") == "success" and os.path.exists(path):
            return {"url": url, "path": path}
    except Exception as e:
        print(f"[DeckForge] generation failed: {e}")
    return {}


def _find_brainstem_web_dir():
    """Walk up from this file looking for a brainstem web/ directory —
    the place whose contents brainstem serves at /web/<path>."""
    cur = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        candidate = os.path.join(cur, "web")
        # A real brainstem web dir contains index.html or mobile/ or onboard/
        if os.path.isdir(candidate) and any(
            os.path.exists(os.path.join(candidate, m))
            for m in ("onboard", "mobile", "index.html")
        ):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def _load_pitch_deck_agent():
    """Locate and instantiate @rapp/pitch_deck dynamically so we don't hard-require it."""
    candidates = []
    here = os.path.dirname(os.path.abspath(__file__))
    # Most likely: pitch_deck_agent.py lives next to us in agents/
    for rel in ("pitch_deck_agent.py", "../pitch_deck_agent.py"):
        candidates.append(os.path.normpath(os.path.join(here, rel)))
    # Also search brainstem/agents/
    web_dir = _find_brainstem_web_dir()
    if web_dir:
        candidates.append(os.path.join(os.path.dirname(web_dir), "agents", "pitch_deck_agent.py"))

    for path in candidates:
        if os.path.exists(path):
            try:
                spec = importlib.util.spec_from_file_location("pitch_deck_agent_dyn", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod.PitchDeckAgent()
            except Exception as e:
                print(f"[DeckForge] failed to load {path}: {e}")
                continue
    return None
