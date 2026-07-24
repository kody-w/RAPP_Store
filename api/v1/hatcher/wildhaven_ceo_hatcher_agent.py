"""WildhavenCEO — drop-in hatcher for the `wildhaven_ceo` rapplication.

    1. Save this file.
    2. Drop it into your brainstem's agents folder:
           ~/.brainstem/src/rapp_brainstem/agents/
    3. Say anything in chat.

That is the whole install. The rapplication's egg is baked into this file as
base64 — nothing is downloaded, no shell command is run, and it works offline.
On the first run this hatcher unpacks the egg into your brainstem (agents,
organs, UI, and per-rapp state land in their canonical places), then gets out
of the way. Re-running is safe: it fingerprints what it installed and skips
if the same egg is already hatched.

Published by @wildhaven · rapplication v0.1.0 · egg sha256 e65d63d623cc…
Source: https://kody-w.github.io/RAPP_Store/#rapp=wildhaven_ceo
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import zipfile

from agents.basic_agent import BasicAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@wildhaven/wildhaven_ceo_hatcher",
    "version": "0.1.0",
    "display_name": "WildhavenCEO (hatcher)",
    "description": "Drop-in installer for the wildhaven_ceo rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@wildhaven",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "wildhaven_ceo"
EGG_SHA256 = "e65d63d623cc120e2de2911d00a5edc8184b1c9fda69778644800e762d9129fe"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "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"
)


def _brainstem_src() -> str:
    """This file lives at <src>/agents/<name>.py → <src> is two levels up."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _egg_bytes() -> bytes:
    return base64.b64decode(EGG_B64)


def _vendored_unpack(blob: bytes, src: str) -> dict:
    """Identical mapping to utils.bond.unpack_rapplication, for brainstems
    that predate bond. Engine files are (re)written; existing per-rapp state
    is preserved."""
    if blob[:4] != b"PK\x03\x04":
        raise ValueError("baked payload is not a valid egg")
    counts = {"agent": 0, "organ": 0, "ui": 0, "data": 0, "soul": 0,
              "rappid": 0, "skipped": 0}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("schema") != EGG_SCHEMA:
            raise ValueError("unexpected egg schema %r" % manifest.get("schema"))
        rapp_id = manifest.get("rapp_id") or RAPP_ID
        data_dir = os.path.join(src, ".brainstem_data", rapp_id)

        for name in z.namelist():
            if name.endswith("/") or name == "manifest.json":
                continue
            parts = name.split("/")
            if ".." in parts or name.startswith("/"):
                continue  # path-traversal guard

            if name.startswith("agents/"):
                target, kind, is_state = os.path.join(src, "agents", name[7:]), "agent", False
            elif name.startswith("organs/"):
                target, kind, is_state = os.path.join(src, "utils", "organs", name[7:]), "organ", False
            elif name.startswith("rapp_ui/"):
                target, kind, is_state = os.path.join(src, ".brainstem_data", "rapp_ui", name[8:]), "ui", False
            elif name.startswith("data/"):
                target, kind, is_state = os.path.join(src, ".brainstem_data", name[5:]), "data", True
            elif name == "soul.md":
                target, kind, is_state = os.path.join(data_dir, "soul.md"), "soul", True
            elif name == "rappid.json":
                target, kind, is_state = os.path.join(data_dir, "rappid.json"), "rappid", True
            else:
                counts["skipped"] += 1
                continue

            if is_state and os.path.exists(target):
                counts["skipped"] += 1       # never clobber the user's state
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(name) as fsrc, open(target, "wb") as fdst:
                fdst.write(fsrc.read())
            counts[kind] += 1
    return counts


def _hatch(force: bool = False) -> dict:
    """Unpack the baked egg into this brainstem. Idempotent via a stamp file."""
    src = _brainstem_src()
    stamp = os.path.join(src, ".brainstem_data", RAPP_ID, ".hatched")
    if not force and os.path.exists(stamp):
        try:
            with open(stamp) as f:
                if (json.load(f).get("egg_sha256") or "") == EGG_SHA256:
                    return {"status": "already_installed", "rapp": RAPP_ID}
        except (ValueError, OSError):
            pass  # unreadable stamp → re-hatch

    blob = _egg_bytes()
    actual = hashlib.sha256(blob).hexdigest()
    if actual != EGG_SHA256:
        raise ValueError("baked egg failed its integrity check (%s)" % actual[:12])

    try:  # canonical path first
        from utils import bond  # type: ignore
        result = bond.unpack_rapplication(blob, src)
        counts = result if isinstance(result, dict) else {"unpacked": True}
        how = "utils.bond"
    except Exception:
        counts = _vendored_unpack(blob, src)
        how = "vendored"

    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    with open(stamp, "w") as f:
        json.dump({"rapp": RAPP_ID, "egg_sha256": EGG_SHA256, "via": how}, f, indent=2)
    return {"status": "installed", "rapp": RAPP_ID, "via": how, "counts": counts}


# Self-install on drop-in: the brainstem reloads agents/ every request, so the
# stamp above keeps this to exactly one real unpack. Never raise at import —
# a failed hatch must not take the host brainstem down.
_BOOT: dict = {}
try:
    _BOOT = _hatch()
except Exception as _e:  # pragma: no cover
    _BOOT = {"status": "error", "error": "%s: %s" % (type(_e).__name__, _e)}


class WildhavenCeoHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "WildhavenCeoHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the wildhaven_ceo rapplication. It self-installs when "
                "dropped into agents/; call it to check install status, or pass "
                "force=true to re-install the baked egg."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "force": {
                        "type": "boolean",
                        "description": "Re-unpack the baked egg even if it is already installed.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        try:
            if kwargs.get("force"):
                return json.dumps(_hatch(force=True))
            if _BOOT.get("status") in ("installed", "already_installed"):
                return json.dumps({
                    "status": _BOOT.get("status"),
                    "rapp": RAPP_ID,
                    "summary": "WildhavenCEO is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
