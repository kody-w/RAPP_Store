"""Synthetic, non-production artifact for the RAPP Zoo v2 Store example."""
from agents.basic_agent import BasicAgent

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@synthetic/synthetic-echo",
    "version": "0.1.0",
    "description": "Echoes synthetic text for a Store v2 prototype example.",
}


class SyntheticEchoAgent(BasicAgent):
    def __init__(self):
        self.name = "synthetic_echo"
        self.metadata = {
            "name": self.name,
            "description": "Echo synthetic demonstration text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Synthetic demonstration text.",
                    }
                },
                "required": ["text"],
            },
        }
        super().__init__()

    def perform(self, text="", **kwargs):
        return f"Synthetic echo: {text}"
