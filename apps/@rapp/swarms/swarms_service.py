"""
swarms_service.py — CRUD for agent swarms (named groups of agents).

A swarm is a named subset of installed agents that the chat UI can
toggle on or off. State lives in .brainstem_data/swarms.json.

Endpoints:
    GET    /api/swarms             — list all swarms + active set
    POST   /api/swarms/active      — set active swarms (body: {"swarms": [...]})
    PUT    /api/swarms/<name>      — create or update a swarm
    DELETE /api/swarms/<name>      — delete a swarm

Swarm modes:
    "stack"     — agents are merged additively when active
    "converged" — the swarm is treated as a single unified agent

The swarm itself is a JSON object: {"agents": [...filenames...], "mode": "stack"|"converged"}.
"""

import json
import os

name = "swarms"

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


def handle(method, path, body):
    state = _read()

    # GET /api/swarms — list all swarms + active set
    if method == "GET" and path == "":
        return state, 200

    # POST /api/swarms/active — set active swarms list
    if method == "POST" and path == "active":
        state["active"] = body.get("swarms", [])
        _write(state)
        return {"active": state["active"]}, 200

    # PUT /api/swarms/<name> — create or update a swarm
    if method == "PUT" and path:
        swarm_name = path.split("/")[0]
        existing = state["swarms"].get(swarm_name, {})
        if "agents" in body:
            existing["agents"] = body["agents"]
        if "mode" in body:
            existing["mode"] = body["mode"]
        if not existing.get("mode"):
            existing["mode"] = "stack"
        if "agents" not in existing:
            existing["agents"] = []
        state["swarms"][swarm_name] = existing
        _write(state)
        return {"status": "ok", "swarm": swarm_name}, 200

    # DELETE /api/swarms/<name> — delete a swarm
    if method == "DELETE" and path:
        swarm_name = path.split("/")[0]
        state["swarms"].pop(swarm_name, None)
        state["active"] = [s for s in state.get("active", []) if s != swarm_name]
        _write(state)
        return {"status": "ok"}, 200

    return {"error": "not found"}, 404
