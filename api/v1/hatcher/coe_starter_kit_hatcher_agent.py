"""CoE Starter Kit — drop-in hatcher for the `coe_starter_kit` rapplication.

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

Published by @bill · rapplication v1.0.0 · egg sha256 a712fc6b7312…
Source: https://kody-w.github.io/RAPP_Store/#rapp=coe_starter_kit
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
    "name": "@bill/coe_starter_kit_hatcher",
    "version": "1.0.0",
    "display_name": "CoE Starter Kit (hatcher)",
    "description": "Drop-in installer for the coe_starter_kit rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@bill",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "coe_starter_kit"
EGG_SHA256 = "a712fc6b7312d1d987807e57fc5351272962f62a068a6ff8e6bd19e279b85062"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "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"
    "AIkZAAAAAA=="
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


class CoeStarterKitHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "CoeStarterKitHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the coe_starter_kit rapplication. It self-installs when "
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
                    "summary": "CoE Starter Kit is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
