"""rapp-zoo — drop-in hatcher for the `rapp-zoo` rapplication.

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

Published by @rapp · rapplication v1.0.0 · egg sha256 f5faa4cc1a97…
Source: https://kody-w.github.io/RAPP_Store/#rapp=rapp-zoo
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
    "name": "@rapp/rapp-zoo_hatcher",
    "version": "1.0.0",
    "display_name": "rapp-zoo (hatcher)",
    "description": "Drop-in installer for the rapp-zoo rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@rapp",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "rapp-zoo"
EGG_SHA256 = "f5faa4cc1a9719f740892e2f4e6909f21d39bccb59e54d85db9e50ddafa4f713"
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


class RappZooHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "RappZooHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the rapp-zoo rapplication. It self-installs when "
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
                    "summary": "rapp-zoo is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
