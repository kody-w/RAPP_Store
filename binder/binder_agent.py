"""
binder_agent.py — Talk to the package manager.

Agent-first wrapper for the binder service: lets the LLM list installed
rapplications, browse the catalog, install, or uninstall — all through
conversation. The optional binder_service.py exposes the same surface
over HTTP for the settings panel.

Storage: .brainstem_data/binder.json (managed by binder_service).
"""

import hashlib
import json
import os
from agents.basic_agent import BasicAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/binder",
    "version": "1.0.0",
    "display_name": "Binder",
    "description": "Package manager. Install or uninstall rapplications from the RAPPstore catalog through conversation.",
    "author": "RAPP",
    "tags": ["package-manager", "store", "rapplication"],
    "category": "platform",
    "quality_tier": "official",
    "requires_env": [],
    "example_call": "Install the dashboard rapplication",
}

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, ".brainstem_data")
_STATE_FILE = os.path.join(_DATA_DIR, "binder.json")
_AGENTS_DIR = os.path.join(_BASE_DIR, "agents")
_SERVICES_DIR = os.path.join(_BASE_DIR, "services")
_CATALOG_URL = "https://raw.githubusercontent.com/kody-w/RAPP/main/rapp_store/index.json"


def _read():
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE) as f:
            return json.load(f)
    return {"installed": []}


def _write(data):
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _fetch_catalog():
    import requests
    resp = requests.get(_CATALOG_URL, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"catalog fetch failed: HTTP {resp.status_code}")
    return resp.json()


def _download(url, expected_sha=None):
    import requests
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"download failed: HTTP {resp.status_code}")
    content = resp.text
    if expected_sha:
        actual = hashlib.sha256(content.encode()).hexdigest()
        if actual != expected_sha:
            raise RuntimeError("SHA256 mismatch — file may be corrupted")
    return content


def _install_id(rapp_id):
    catalog = _fetch_catalog()
    entry = next((r for r in catalog.get("rapplications", []) if r.get("id") == rapp_id), None)
    if not entry:
        return {"error": f"not in catalog: {rapp_id}"}
    installed = {"id": rapp_id, "version": entry.get("version", "?")}

    if entry.get("singleton_url") and entry.get("singleton_filename"):
        content = _download(entry["singleton_url"], entry.get("singleton_sha256"))
        os.makedirs(_AGENTS_DIR, exist_ok=True)
        with open(os.path.join(_AGENTS_DIR, entry["singleton_filename"]), "w", encoding="utf-8") as f:
            f.write(content)
        installed["agent_filename"] = entry["singleton_filename"]
        installed["filename"] = entry["singleton_filename"]

    if entry.get("service_url") and entry.get("service_filename"):
        content = _download(entry["service_url"], entry.get("service_sha256"))
        os.makedirs(_SERVICES_DIR, exist_ok=True)
        with open(os.path.join(_SERVICES_DIR, entry["service_filename"]), "w", encoding="utf-8") as f:
            f.write(content)
        installed["service_filename"] = entry["service_filename"]

    state = _read()
    state["installed"] = [e for e in state["installed"] if e.get("id") != rapp_id]
    state["installed"].append(installed)
    _write(state)
    return {"ok": True, "installed": installed}


def _uninstall_id(rapp_id):
    state = _read()
    entry = next((e for e in state["installed"] if e.get("id") == rapp_id), None)
    if not entry:
        return {"error": f"not installed: {rapp_id}"}
    for d, fn in (
        (_AGENTS_DIR, entry.get("agent_filename") or entry.get("filename")),
        (_SERVICES_DIR, entry.get("service_filename")),
    ):
        if fn:
            p = os.path.join(d, fn)
            if os.path.exists(p):
                os.remove(p)
    state["installed"] = [e for e in state["installed"] if e.get("id") != rapp_id]
    _write(state)
    return {"ok": True, "uninstalled": rapp_id}


class BinderAgent(BasicAgent):
    def __init__(self):
        self.name = "Binder"
        self.metadata = {
            "name": self.name,
            "description": (
                "Package manager for rapplications. Use this to list what's installed, "
                "browse the RAPPstore catalog, install a rapplication by id, or uninstall "
                "one. Call this whenever the user wants to add, remove, or discover "
                "rapplications, agents, or services."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "catalog", "install", "uninstall"],
                        "description": "What to do.",
                    },
                    "id": {
                        "type": "string",
                        "description": "Rapplication id (for install/uninstall).",
                    },
                },
                "required": ["action"],
            },
        }

    def perform(self, **kwargs):
        action = kwargs.get("action")
        try:
            if action == "list":
                state = _read()
                return json.dumps(state)
            if action == "catalog":
                cat = _fetch_catalog()
                # Trim each entry so the LLM sees the useful fields, not the whole metadata dump.
                trimmed = [
                    {
                        "id": r.get("id"),
                        "name": r.get("name"),
                        "version": r.get("version"),
                        "summary": r.get("summary", "")[:200],
                        "category": r.get("category"),
                        "has_agent": bool(r.get("singleton_url")),
                        "has_service": bool(r.get("service_url")),
                    }
                    for r in cat.get("rapplications", [])
                ]
                return json.dumps({"rapplications": trimmed})
            if action == "install":
                rapp_id = kwargs.get("id", "")
                if not rapp_id:
                    return json.dumps({"error": "id required for install"})
                return json.dumps(_install_id(rapp_id))
            if action == "uninstall":
                rapp_id = kwargs.get("id", "")
                if not rapp_id:
                    return json.dumps({"error": "id required for uninstall"})
                return json.dumps(_uninstall_id(rapp_id))
            return json.dumps({"error": f"unknown action: {action}"})
        except Exception as e:
            return json.dumps({"error": str(e)})
