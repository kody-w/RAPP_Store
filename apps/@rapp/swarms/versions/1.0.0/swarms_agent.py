"""
swarms_agent.py — Talk to your swarm groupings.

Agent-first wrapper for the swarms service: lets the LLM list, create,
update, activate, or delete agent swarms (named groups of agents)
through conversation. The optional swarms_service.py exposes the same
surface over HTTP for the chat UI's swarm bar.

Storage: .brainstem_data/swarms.json (managed by swarms_service).
"""

import json
import os
from agents.basic_agent import BasicAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/swarms",
    "version": "1.0.0",
    "display_name": "Swarms",
    "description": "Group your agents into named swarms and toggle which swarms are active per turn.",
    "author": "RAPP",
    "tags": ["organization", "agents", "rapplication"],
    "category": "platform",
    "quality_tier": "official",
    "requires_env": [],
    "example_call": "Create a swarm called 'research' with the dashboard and webhook agents",
}

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".brainstem_data")
_STATE_FILE = os.path.join(_DATA_DIR, "swarms.json")


def _read():
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE) as f:
            return json.load(f)
    return {"swarms": {}, "active": []}


def _write(data):
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


class SwarmsAgent(BasicAgent):
    def __init__(self):
        self.name = "Swarms"
        self.metadata = {
            "name": self.name,
            "description": (
                "Manage agent swarms — named groups of agents the user can toggle on/off "
                "for a turn. Use this to list swarms, create or update one, set the active "
                "swarms, or delete a swarm. Call whenever the user wants to organize, "
                "activate, or deactivate groupings of agents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "create", "update", "activate", "delete"],
                        "description": "What to do.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Swarm name (for create/update/delete).",
                    },
                    "agents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of agent filenames in the swarm (for create/update).",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["stack", "converged"],
                        "description": "stack = additive merge; converged = treated as one unified agent.",
                    },
                    "active": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names of swarms to set as active (for activate). Empty list = all agents.",
                    },
                },
                "required": ["action"],
            },
        }

    def perform(self, **kwargs):
        action = kwargs.get("action")
        state = _read()
        try:
            if action == "list":
                return json.dumps(state)
            if action in ("create", "update"):
                swarm_name = kwargs.get("name", "")
                if not swarm_name:
                    return json.dumps({"error": "name required"})
                existing = state["swarms"].get(swarm_name, {})
                if "agents" in kwargs:
                    existing["agents"] = kwargs["agents"]
                if "mode" in kwargs:
                    existing["mode"] = kwargs["mode"]
                existing.setdefault("mode", "stack")
                existing.setdefault("agents", [])
                state["swarms"][swarm_name] = existing
                _write(state)
                return json.dumps({"ok": True, "swarm": swarm_name, "data": existing})
            if action == "activate":
                state["active"] = kwargs.get("active", [])
                _write(state)
                return json.dumps({"ok": True, "active": state["active"]})
            if action == "delete":
                swarm_name = kwargs.get("name", "")
                if not swarm_name:
                    return json.dumps({"error": "name required"})
                state["swarms"].pop(swarm_name, None)
                state["active"] = [s for s in state.get("active", []) if s != swarm_name]
                _write(state)
                return json.dumps({"ok": True, "deleted": swarm_name})
            return json.dumps({"error": f"unknown action: {action}"})
        except Exception as e:
            return json.dumps({"error": str(e)})
