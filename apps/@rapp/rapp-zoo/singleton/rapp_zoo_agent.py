"""
rapp_zoo_agent.py — agent face of the rapp-zoo rapplication.

The rapp-zoo IS a rapplication — same kind of organism as anything else in
the catalog (Constitution Article XXXVII). Its primary surface is the
Pokédex UI bundled in rapp_ui/rapp-zoo/index.html (open in any browser
or hatch into a brainstem to view at /rapp_ui/rapp-zoo/). This agent
exists so the rapp has the canonical agent + UI shape every rapplication
shares — and so a user can chat with rapp-zoo from inside their brainstem
to ask it questions about itself.

Today the FULL zoo (with local-collection / drag-drop import / lay-egg /
summon / hatch / start-stop) still runs as its own Flask process at
localhost:7070 — installed via the manifest's install_one_liner. This
agent reports honestly about that and points users at the right command.

Future work refactors the zoo's API endpoints into a brainstem organ at
/api/zoo/* so the entire zoo hatches into a brainstem like any other
rapp. When that lands, this agent gets a thicker perform() that drives
the organ. Until then, it's the agent face for a rapplication that runs
its body somewhere else.
"""

from agents.basic_agent import BasicAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/rapp_zoo",
    "version": "0.2.0",
    "display_name": "rapp-zoo",
    "description": "Agent face of the rapp-zoo rapplication. Tells you about the local Pokédex and how to install / launch it.",
    "author": "RAPP",
    "tags": ["pokedex", "rapp-zoo", "browse", "tool"],
    "category": "platform",
    "quality_tier": "official",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": "How do I install rapp-zoo?",
}


_INSTALL_ONE_LINER = (
    "curl -fsSL https://kody-w.github.io/rapp-zoo/installer/install.sh | bash && "
    "bash ~/.rapp-zoo/installer/start.sh"
)
_STATIC_URL = "https://kody-w.github.io/rapp-zoo/"
_REPO_URL = "https://github.com/kody-w/rapp-zoo"


class RappZooAgent(BasicAgent):
    """Agent face for the rapp-zoo Pokédex rapplication."""

    def __init__(self):
        self.name = "rapp_zoo"
        self.metadata = {
            "name": self.name,
            "description": (
                "Agent face of the rapp-zoo rapplication — the local-first "
                "Pokédex of digital organisms. Use this agent when the user "
                "asks how to install / launch / use rapp-zoo, or what the "
                "Pokédex is, or how to manage the eggs they've collected."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "What the user wants to know about rapp-zoo.",
                    },
                },
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, question: str = "", **kwargs) -> str:
        # Stateless help-style agent. Returns a focused factual response
        # the LLM can paraphrase or quote into chat. The UI bundle is
        # the real surface; this agent just tells the user where it lives.
        return (
            "🥚 **rapp-zoo** is the local-first Pokédex of digital organisms.\n\n"
            "It runs as its own small Flask process at `localhost:7070` and "
            "lets you browse / import / export / hatch / start / stop every "
            "organism on this device, plus pull from the global catalog.\n\n"
            "**Two ways to use it right now:**\n\n"
            "1. **Static read-only Pokédex** (no install required) — open "
            f"<{_STATIC_URL}> in any browser. Browse the global catalog, "
            "inspect any `.egg` locally, hot-load into your brainstem.\n\n"
            "2. **Full local Pokédex** (collection + import + lay/summon/hatch):\n"
            f"```\n{_INSTALL_ONE_LINER}\n```\n"
            f"Then open <http://localhost:7070>.\n\n"
            f"Source: <{_REPO_URL}>. The user's specific question, for "
            f"context: {question or '(no question — just describe rapp-zoo)'}"
        )
