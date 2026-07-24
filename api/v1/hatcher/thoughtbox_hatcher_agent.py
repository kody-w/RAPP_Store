"""Thoughtbox — drop-in hatcher for the `thoughtbox` rapplication.

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

Published by @kody-w · rapplication v1.0.0 · egg sha256 290803fca937…
Source: https://kody-w.github.io/RAPP_Store/#rapp=thoughtbox
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
    "name": "@kody-w/thoughtbox_hatcher",
    "version": "1.0.0",
    "display_name": "Thoughtbox (hatcher)",
    "description": "Drop-in installer for the thoughtbox rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@kody-w",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "thoughtbox"
EGG_SHA256 = "290803fca9378c41eed349ce89dfd22c137276a8efc61b759956544dac1a1189"
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


class ThoughtboxHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "ThoughtboxHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the thoughtbox rapplication. It self-installs when "
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
                    "summary": "Thoughtbox is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
