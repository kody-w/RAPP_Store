"""SpineDAG — drop-in hatcher for the `spine_dag` rapplication.

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

Published by @blazingbeard · rapplication v1.0.0 · egg sha256 3f2405cf255d…
Source: https://kody-w.github.io/RAPP_Store/#rapp=spine_dag
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
    "name": "@blazingbeard/spine_dag_hatcher",
    "version": "1.0.0",
    "display_name": "SpineDAG (hatcher)",
    "description": "Drop-in installer for the spine_dag rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@blazingbeard",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "spine_dag"
EGG_SHA256 = "3f2405cf255d49abbd70b4e27f67e092a3d9c7836570d713b08ea62b5ab30082"
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


class SpineDagHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "SpineDagHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the spine_dag rapplication. It self-installs when "
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
                    "summary": "SpineDAG is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
