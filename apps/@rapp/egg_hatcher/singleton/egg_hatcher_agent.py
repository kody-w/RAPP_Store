"""
egg_hatcher_agent.py — feed an .egg to the brainstem; it self-bootstraps the rapp.

The egg is the universal install unit. This agent is the universal install
mechanism. Hand it a URL or a local path, it fetches the blob, calls the
brainstem's own bond.unpack_rapplication() to lay the rapp's files into
the right places, and the next /chat call hot-loads everything (the
brainstem reloads agents from disk every request — Article XVII).

Use cases:
  - LLM in chat: "install the workday rapp from the catalog"
    → agent fetches /api/v1/egg/workday.egg from raw.githubusercontent.com
    → unpacks into agents/ + utils/organs/ + .brainstem_data/
    → returns the rappid + counts
  - rapp-zoo Discover tab "Hot-load" button
    → POST /chat with `egg_url` arg
    → same path
  - User has a .egg on disk:
    → "hot-load /path/to/foo.egg"
    → reads the file, unpacks

The agent NEVER touches the brainstem's identity (~/.brainstem/rappid.json)
— that belongs to the host organism and survives all rapp installs. It
also refuses any schema other than 2.2-rapplication; organism-scope eggs
need bond.unpack_organism (a different mechanism, used by the install
one-liner's bond cycle, not by this agent).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from agents.basic_agent import BasicAgent
from utils import bond


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/egg_hatcher",
    "version": "0.1.0",
    "display_name": "Egg Hatcher",
    "description": "Feed me a .egg URL or path — I'll fetch and hot-load the rapplication into this brainstem.",
    "author": "RAPP",
    "tags": ["meta", "install", "egg", "hot-load", "rapplication"],
    "category": "core",
    "quality_tier": "official",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": "Hot-load this rapp: https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/egg/bookfactory.egg",
}


# Cap on egg size we'll fetch — sanity guard against a misconfigured URL
# pointing at a multi-gig file. Plenty of headroom for any real rapp egg
# (the largest current catalog entry is ~17 KB; full organism eggs run
# tens of KB to a few MB). Bump if a legitimate rapp ships big assets.
_MAX_EGG_BYTES = 50 * 1024 * 1024  # 50 MB


def _brainstem_src() -> str:
    """The brainstem's own source dir — where agents/, utils/organs/,
    and .brainstem_data/ live. Computed from this agent's location so it
    works regardless of where the brainstem was installed."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)  # one up from agents/ → rapp_brainstem/


def _fetch_egg(url: str) -> bytes:
    """Fetch an egg blob from a URL. Honors HTTP errors, caps size."""
    req = urllib.request.Request(url, headers={"User-Agent": "rapp-brainstem/egg_hatcher"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            blob = resp.read(_MAX_EGG_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise ValueError(f"HTTP {e.code} fetching egg: {url}")
    except urllib.error.URLError as e:
        raise ValueError(f"network error fetching {url}: {e.reason}")
    if len(blob) > _MAX_EGG_BYTES:
        raise ValueError(f"egg larger than {_MAX_EGG_BYTES // 1024 // 1024} MB cap — refusing to install")
    return blob


class EggHatcherAgent(BasicAgent):
    """Universal install mechanism — feed an egg, get a rapp."""

    def __init__(self):
        self.name = "egg_hatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Hot-load a brainstem-egg/2.2-rapplication into this brainstem. "
                "Use when the user wants to install a rapp from a .egg file or URL. "
                "Accepts either `egg_url` (fetched on demand) or `egg_path` "
                "(local file). Unpacks agent + UI + organ + per-rapp state into "
                "the brainstem's own dirs. The next /chat call hot-reloads the new "
                "agent automatically. Returns the rappid + per-tree file counts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "egg_url": {
                        "type": "string",
                        "description": (
                            "URL of the .egg to fetch. Typically a "
                            "raw.githubusercontent.com URL from the global "
                            "rapp_store Pokédex API (e.g. "
                            "https://raw.githubusercontent.com/kody-w/RAPP_Store"
                            "/main/api/v1/egg/bookfactory.egg)."
                        ),
                    },
                    "egg_path": {
                        "type": "string",
                        "description": "Absolute path to a local .egg file. Use when the user has the file on disk already.",
                    },
                    "overwrite_state": {
                        "type": "boolean",
                        "description": (
                            "If a per-rapp state cartridge from a previous "
                            "install already exists, replace it. Default false "
                            "(merge — preserve any local edits)."
                        ),
                    },
                },
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, egg_url: str = "", egg_path: str = "",
                overwrite_state: bool = False, **kwargs) -> str:
        # Validate inputs
        egg_url = (egg_url or "").strip()
        egg_path = (egg_path or "").strip()
        if not egg_url and not egg_path:
            return ("Need either egg_url (a URL — I'll fetch it) or egg_path "
                    "(a local file path). Got neither.")
        if egg_url and egg_path:
            return "Pass egg_url OR egg_path, not both. I'll only use one."

        # Source the blob
        try:
            if egg_url:
                blob = _fetch_egg(egg_url)
                source_label = egg_url
            else:
                if not os.path.isfile(egg_path):
                    return f"egg_path not found: {egg_path}"
                with open(egg_path, "rb") as f:
                    blob = f.read()
                source_label = egg_path
        except ValueError as e:
            return f"Could not load egg: {e}"

        # Sanity-peek the manifest before unpacking
        try:
            manifest = bond.inspect_egg(blob)
        except Exception as e:
            return f"Egg has no readable manifest — refusing to install: {e}"

        schema = manifest.get("schema", "")
        if schema != bond.SCHEMA_RAPP:
            return (
                f"Refusing to hatch — egg schema is {schema!r}, not "
                f"{bond.SCHEMA_RAPP!r}. Organism-scope eggs (kernel + identity) "
                "are installed by the brainstem install one-liner's bond cycle, "
                "not by this agent."
            )

        # Unpack into the brainstem's own src tree
        src = _brainstem_src()
        try:
            result = bond.unpack_rapplication(blob, src, overwrite_state=overwrite_state)
        except Exception as e:
            return f"Hatch raised an error: {e}"

        if not result.get("ok"):
            errs = result.get("errors", [])
            return f"Hatch reported errors: {errs}"

        restored = result.get("restored", {})
        name = manifest.get("name", manifest.get("rapp_id", "?"))
        rappid = manifest.get("rappid", "?")
        rapp_id = manifest.get("rapp_id", "?")

        # Friendly summary the LLM can quote back
        lines = [
            f"🥚 Hot-loaded **{name}** from {source_label}",
            f"   rappid: `{rappid}`",
            f"   rapp_id: `{rapp_id}`",
            f"   restored: agent={restored.get('agent', 0)}, "
            f"organ={restored.get('organ', 0)}, "
            f"ui={restored.get('ui', 0)}, "
            f"data={restored.get('data', 0)}, "
            f"soul={restored.get('soul', 0)}",
            "",
            "The next chat turn will load the new agent automatically "
            "(brainstem reloads agents/ from disk every request).",
        ]
        if restored.get("ui", 0) > 0:
            lines.append(
                f"   UI bundle landed at "
                f".brainstem_data/rapp_ui/{rapp_id}/ — "
                "the rapp-zoo will see it on next refresh."
            )
        return "\n".join(lines)
