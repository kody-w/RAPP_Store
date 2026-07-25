"""CSV Surgeon — drop-in hatcher for the `csv_surgeon` rapplication.

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

Published by @rapp · rapplication v1.0.0 · egg sha256 b104d69d6283…
Source: https://kody-w.github.io/RAPP_Store/#rapp=csv_surgeon
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
    "name": "@rapp/csv_surgeon_hatcher",
    "version": "1.0.0",
    "display_name": "CSV Surgeon (hatcher)",
    "description": "Drop-in installer for the csv_surgeon rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@rapp",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "csv_surgeon"
EGG_SHA256 = "b104d69d6283ae814e582ed22233ef88be4ca3c1130823839a94997f2ce69ef3"
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


class CsvSurgeonHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "CsvSurgeonHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the csv_surgeon rapplication. It self-installs when "
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
                    "summary": "CSV Surgeon is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
