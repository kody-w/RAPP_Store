"""Log Detective — drop-in hatcher for the `log_detective` rapplication.

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

Published by @rapp · rapplication v1.0.0 · egg sha256 c072b78b6df3…
Source: https://kody-w.github.io/RAPP_Store/#rapp=log_detective
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
    "name": "@rapp/log_detective_hatcher",
    "version": "1.0.0",
    "display_name": "Log Detective (hatcher)",
    "description": "Drop-in installer for the log_detective rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@rapp",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "log_detective"
EGG_SHA256 = "c072b78b6df3e73324616d68f61a2fe917fd5c1bb66e0d18220f7c84a47e5837"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "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"
    "c29uUEsFBgAAAAAEAAQADQEAAPcbAAAAAA=="
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


class LogDetectiveHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "LogDetectiveHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the log_detective rapplication. It self-installs when "
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
                    "summary": "Log Detective is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
