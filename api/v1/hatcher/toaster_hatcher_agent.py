"""Toaster — drop-in hatcher for the `toaster` rapplication.

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

Published by @rapp · rapplication v1.0.0 · egg sha256 df666e84e797…
Source: https://kody-w.github.io/RAPP_Store/#rapp=toaster
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
    "name": "@rapp/toaster_hatcher",
    "version": "1.0.0",
    "display_name": "Toaster (hatcher)",
    "description": "Drop-in installer for the toaster rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@rapp",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "toaster"
EGG_SHA256 = "df666e84e7977fc2e2176f14697fd29beaf8fa6f7d38a5d040a4409ba80422c7"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "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"
    "AAAAAAQABAABAQAAE18AAAAA"
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


class ToasterHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "ToasterHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the toaster rapplication. It self-installs when "
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
                    "summary": "Toaster is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
