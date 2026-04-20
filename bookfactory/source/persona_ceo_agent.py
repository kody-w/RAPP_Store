"""
persona_ceo_agent.py — CEO persona, composite of two specialist agents.

Delegates to ceo_risk + ceo_decision specialists. Same agent.py-all-the-way-down
pattern as the Editor persona.
"""
from agents.basic_agent import BasicAgent
from agents.ceo_risk_agent     import CEORiskAgent
from agents.ceo_decision_agent import CEODecisionAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/persona-ceo",
    "tier": "core",
    "trust": "community",
    "version": "0.2.0",
    "tags": ["persona", "creative-pipeline", "composite"],
    "delegates_to": ["@rapp/ceo-risk", "@rapp/ceo-decision"],
    "example_call": {"args": {"input": "edited chapter"}},
}


class PersonaCEOAgent(BasicAgent):
    def __init__(self):
        self.name = "CEO"
        self.metadata = {
            "name": self.name,
            "description": "The CEO persona. Delegates to risk + decision specialists "
                           "and composes a strategic-message-discipline review.",
            "parameters": {
                "type": "object",
                "properties": {"input": {"type": "string", "description": "Content under review"}},
                "required": ["input"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, input="", **kwargs):
        risks    = CEORiskAgent().perform(input=input)
        decision = CEODecisionAgent().perform(input=input)
        return f"**Decision**\n{decision}\n\n**Partner-conversation risks**\n{risks}\n"
