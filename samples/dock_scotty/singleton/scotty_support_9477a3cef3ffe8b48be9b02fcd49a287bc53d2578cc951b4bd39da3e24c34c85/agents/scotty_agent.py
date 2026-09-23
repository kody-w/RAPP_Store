"""Inert scoped implementation used only to demonstrate the complete layout."""
import json

from agents.basic_agent import BasicAgent


class ScottyAgent(BasicAgent):
    def __init__(self):
        super().__init__(name="scotty", metadata={
            "name": "scotty", "description": "Non-executing synthetic authoring example.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        })

    def perform(self, **kwargs):
        return json.dumps({
            "status": "blocked",
            "code": "authoring-template-only",
            "message": "This synthetic template does not run Docker, call providers or produce job artifacts.",
            "fresh_install": "pending",
            "journeys": ["web-research", "editable-deck", "seo-project", "knowledge-answer", "captioned-shorts"],
        }, sort_keys=True)
