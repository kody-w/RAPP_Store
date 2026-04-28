"""Throwaway singleton used to e2e-test the rapp_store submission pipeline."""
from agents.basic_agent import BasicAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "id": "pipeline_e2e_check",
    "version": "0.1.0",
    "publisher": "@kody-w",
}


class PipelineE2ECheckAgent(BasicAgent):
    metadata = {
        "name": "pipeline_e2e_check",
        "description": "Echoes back its input so the e2e pipeline can verify routing.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Anything to echo."}
            },
            "required": ["message"],
        },
    }

    def perform(self, **kwargs) -> str:
        msg = kwargs.get("message", "")
        return f"pipeline_e2e_check echoes: {msg}"
