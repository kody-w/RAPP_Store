"""JSON Doctor — drop-in hatcher for the `json_doctor` rapplication.

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

Published by @rapp · rapplication v1.0.0 · egg sha256 7aeb4c0ec4db…
Source: https://kody-w.github.io/RAPP_Store/#rapp=json_doctor
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
    "name": "@rapp/json_doctor_hatcher",
    "version": "1.0.0",
    "display_name": "JSON Doctor (hatcher)",
    "description": "Drop-in installer for the json_doctor rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@rapp",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "json_doctor"
EGG_SHA256 = "7aeb4c0ec4dbaff4bd053a77fefd188e995f0e85091e915e89146cdadc9d1477"
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


class JsonDoctorHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "JsonDoctorHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the json_doctor rapplication. It self-installs when "
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
                    "summary": "JSON Doctor is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
