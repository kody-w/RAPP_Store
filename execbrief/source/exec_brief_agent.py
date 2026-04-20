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
import json
import os


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

        # ── Step 1: Scout ────────────────────────────────────────────────
        print("[ExecBrief] Step 1/4: Scout gathering intelligence...")
        scout_raw = BriefScoutAgent().perform(topic=topic)
        _save("01-scout.md", scout_raw)
        research = _extract(scout_raw, "research")

        # ── Step 2: Analyst ──────────────────────────────────────────────
        print("[ExecBrief] Step 2/4: Analyst extracting insights...")
        analyst_raw = BriefAnalystAgent().perform(research=research)
        _save("02-analyst.md", analyst_raw)
        analysis = _extract(analyst_raw, "analysis")

        # ── Step 3: Strategist ───────────────────────────────────────────
        print("[ExecBrief] Step 3/4: Strategist forming recommendations...")
        strategist_raw = BriefStrategistAgent().perform(
            analysis=analysis, topic=topic)
        _save("03-strategist.md", strategist_raw)
        strategy = _extract(strategist_raw, "strategy")

        # ── Step 4: Writer ───────────────────────────────────────────────
        print("[ExecBrief] Step 4/4: Writer composing executive brief...")
        writer_raw = BriefWriterAgent().perform(
            topic=topic, research=research,
            analysis=analysis, strategy=strategy)
        _save("04-brief.md", writer_raw)
        brief = _extract(writer_raw, "brief")

        print("[ExecBrief] Pipeline complete — 4 agents, 1 brief.")

        return json.dumps({
            "status": "success",
            "brief": brief,
            "pipeline": {
                "steps": 4,
                "agents": [
                    "BriefScout", "BriefAnalyst",
                    "BriefStrategist", "BriefWriter",
                ],
            },
            "workspace": ws,
            "data_slush": {"topic": topic, "brief_ready": True},
        })
