"""Markdown Medic — drop-in hatcher for the `markdown_medic` rapplication.

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

Published by @rapp · rapplication v1.0.0 · egg sha256 854c90e7f38d…
Source: https://kody-w.github.io/RAPP_Store/#rapp=markdown_medic
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
    "name": "@rapp/markdown_medic_hatcher",
    "version": "1.0.0",
    "display_name": "Markdown Medic (hatcher)",
    "description": "Drop-in installer for the markdown_medic rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@rapp",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "markdown_medic"
EGG_SHA256 = "854c90e7f38d0a1adbd477821b082107fbfcce52e99fc36c0324cbf8b0a7d4bd"
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


class MarkdownMedicHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "MarkdownMedicHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the markdown_medic rapplication. It self-installs when "
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
                    "summary": "Markdown Medic is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
