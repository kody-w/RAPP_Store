"""Synthetic authoring delegate: import is inert and no application job is run."""
import hashlib
import importlib.util
import json
from pathlib import Path

from agents.basic_agent import BasicAgent

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@example/dock_scotty",
    "version": "0.1.0",
    "description": "Experimental Dock authoring template; no runtime jobs or provider calls.",
}


class ScottyAgent(BasicAgent):
    def __init__(self):
        super().__init__(name="scotty", metadata={
            "name": "scotty",
            "description": "Describe the non-executing authoring template, not an installed Dock.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        })

    def perform(self, **kwargs):
        root = Path(__file__).resolve().parent
        descriptor = json.loads((root / "scotty_revision.json").read_bytes())
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != descriptor["entrypoint_sha256"]:
            raise ValueError("Template entrypoint differs from its revision descriptor.")
        support = root / ("scotty_support_" + descriptor["support_sha256"])
        lock_bytes = (support / "SCOTTY_CAPABILITY_LOCK.json").read_bytes()
        if hashlib.sha256(lock_bytes).hexdigest() != descriptor["support_sha256"]:
            raise ValueError("Template support inventory differs from its descriptor.")
        inventory = json.loads(lock_bytes)
        if len(inventory["files"]) != 1 or inventory["files"][0]["path"] != "agents/scotty_agent.py":
            raise ValueError("Unexpected template support layout.")
        item = inventory["files"][0]
        source = (support / item["path"]).read_bytes()
        if len(source) != item["bytes"] or hashlib.sha256(source).hexdigest() != item["sha256"]:
            raise ValueError("Template support source differs from its inventory.")
        spec = importlib.util.spec_from_file_location("_synthetic_dock_template", support / item["path"])
        module = importlib.util.module_from_spec(spec)
        exec(compile(source, str(support / item["path"]), "exec"), module.__dict__)
        return module.ScottyAgent().perform(**kwargs)
