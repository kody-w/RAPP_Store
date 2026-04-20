"""
moment_factory_agent.py — top-level composite for the Rappterbook Drop forge.

The MomentFactory turns any moment (code commit, voice memo, web bookmark,
agent run, location, conversation, decision, reading note) into a single Drop
ready to land on the Rappterbook feed.

Pipeline order:
    Sensorium → SignificanceFilter → (gate) → HookWriter → BodyWriter →
    ChannelRouter → CardForger → SeedStamper

If SignificanceFilter returns ship=false, the pipeline short-circuits and
returns a skipped Drop — saving 5 LLM calls. The filter is the platform's
defining constraint, encoded as one persona with veto power.

Run via the sacred OG path:
    POST /api/swarm/{guid}/agent  {"name":"MomentFactory","args":{...}}

Returns the full Drop as a JSON string.
"""
from agents.basic_agent              import BasicAgent
from agents.sensorium_agent          import SensoriumAgent
from agents.significance_filter_agent import SignificanceFilterAgent
from agents.hook_writer_agent        import HookWriterAgent
from agents.body_writer_agent        import BodyWriterAgent
from agents.channel_router_agent     import ChannelRouterAgent
from agents.card_forger_agent        import CardForgerAgent
from agents.seed_stamper_agent       import SeedStamperAgent
import json
import re


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/moment-factory",
    "tier": "core",
    "trust": "community",
    "version": "0.1.0",
    "tags": ["composite", "moment-pipeline", "rapplication", "rappterbook-engine"],
    "delegates_to": [
        "@rapp/sensorium",
        "@rapp/significance-filter",
        "@rapp/hook-writer",
        "@rapp/body-writer",
        "@rapp/channel-router",
        "@rapp/card-forger",
        "@rapp/seed-stamper",
    ],
    "example_call": {"args": {"source": "git commit hash + diff + message", "source_type": "code-commit"}},
}


SHIP_THRESHOLD = 0.5  # Default cutoff. Override with significance_threshold kwarg.


def _safe_json(s, fallback=None):
    """Best-effort JSON parse — strip code fences and pull the first {..} block."""
    if not s:
        return fallback if fallback is not None else {}
    s = s.strip()
    # strip ``` fences if the LLM wrapped the JSON
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return fallback if fallback is not None else {}


class MomentFactoryAgent(BasicAgent):
    def __init__(self):
        self.name = "MomentFactory"
        self.metadata = {
            "name": self.name,
            "description": "Turns a raw moment (commit, voice memo, bookmark, agent run, location, "
                           "conversation, decision, reading note) into a Rappterbook Drop. "
                           "Returns JSON with hook, body, channel, card, seed, incantation, "
                           "significance_score, ship, skipped_reason.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source":       {"type": "string", "description": "Raw moment text"},
                    "source_type":  {"type": "string", "description": "code-commit | voice-memo | web-bookmark | agent-run | location | conversation | decision | reading-note"},
                    "significance_threshold": {"type": "number", "description": "0..1 cutoff. Default 0.5."},
                },
                "required": ["source"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, source="", source_type="unknown",
                significance_threshold=None, **kwargs):
        threshold = significance_threshold if significance_threshold is not None else SHIP_THRESHOLD

        # 1. Sensorium — normalize raw moment
        normalized_raw = SensoriumAgent().perform(source=source, source_type=source_type)

        # 2. SignificanceFilter — early gate. May veto everything below.
        sig_raw = SignificanceFilterAgent().perform(normalized_moment=normalized_raw)
        sig = _safe_json(sig_raw, fallback={"significance_score": 0.5, "ship": True, "reason": "filter parse failed — defaulting ship=true"})
        score = float(sig.get("significance_score", 0.5))
        ship  = bool(sig.get("ship", True)) and score >= threshold

        if not ship:
            return json.dumps({
                "source_type":        source_type,
                "skipped":            True,
                "skipped_reason":     sig.get("reason", "below significance threshold"),
                "significance_score": score,
                "threshold":          threshold,
                "normalized":         _safe_json(normalized_raw),
            }, indent=2)

        # 3. HookWriter
        hook = HookWriterAgent().perform(normalized_moment=normalized_raw).strip()

        # 4. BodyWriter
        body = BodyWriterAgent().perform(normalized_moment=normalized_raw, hook=hook).strip()

        # 5. ChannelRouter
        channel = ChannelRouterAgent().perform(hook=hook, body=body).strip()

        # 6. CardForger
        card_raw = CardForgerAgent().perform(hook=hook, body=body, channel=channel)
        card = _safe_json(card_raw, fallback={"name": "(card parse failed)"})

        # 7. SeedStamper — pure function, deterministic
        seed_raw = SeedStamperAgent().perform(hook=hook, body=body, channel=channel)
        seed_obj = _safe_json(seed_raw, fallback={"seed": 0, "incantation": ""})

        return json.dumps({
            "source_type":        source_type,
            "skipped":            False,
            "significance_score": score,
            "ship_reason":        sig.get("reason", ""),
            "hook":               hook,
            "body":               body,
            "channel":            channel,
            "card":               card,
            "seed":               seed_obj.get("seed"),
            "incantation":        seed_obj.get("incantation"),
        }, indent=2)
