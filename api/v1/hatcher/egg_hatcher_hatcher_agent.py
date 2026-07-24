"""egg_hatcher — drop-in hatcher for the `egg_hatcher` rapplication.

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

Published by @rapp · rapplication v1.0.0 · egg sha256 c7ba1ffc5769…
Source: https://kody-w.github.io/RAPP_Store/#rapp=egg_hatcher
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
    "name": "@rapp/egg_hatcher_hatcher",
    "version": "1.0.0",
    "display_name": "egg_hatcher (hatcher)",
    "description": "Drop-in installer for the egg_hatcher rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@rapp",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "egg_hatcher"
EGG_SHA256 = "c7ba1ffc5769092d280018d273aa44430ee49244002c69416e40d75dcc0ab7ed"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "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"
    "FgAAAAA="
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


class EggHatcherHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "EggHatcherHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the egg_hatcher rapplication. It self-installs when "
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
                    "summary": "egg_hatcher is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
