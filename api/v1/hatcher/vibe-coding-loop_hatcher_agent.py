"""Vibe Coding Loop — drop-in hatcher for the `vibe-coding-loop` rapplication.

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

Published by @kody-w · rapplication v1.0.0 · egg sha256 0a1c5690e126…
Source: https://kody-w.github.io/RAPP_Store/#rapp=vibe-coding-loop
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
    "name": "@kody-w/vibe-coding-loop_hatcher",
    "version": "1.0.0",
    "display_name": "Vibe Coding Loop (hatcher)",
    "description": "Drop-in installer for the vibe-coding-loop rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@kody-w",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "vibe-coding-loop"
EGG_SHA256 = "0a1c5690e126b8e1cd76fa1bb83b2c0ac2ff4549b9cff081c7546762c047ed6e"
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


class VibeCodingLoopHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "VibeCodingLoopHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the vibe-coding-loop rapplication. It self-installs when "
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
                    "summary": "Vibe Coding Loop is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
