"""chainforge — drop-in hatcher for the `chainforge` rapplication.

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

Published by @rapp · rapplication v1.0.0 · egg sha256 a088d6b7c814…
Source: https://kody-w.github.io/RAPP_Store/#rapp=chainforge
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
    "name": "@rapp/chainforge_hatcher",
    "version": "1.0.0",
    "display_name": "chainforge (hatcher)",
    "description": "Drop-in installer for the chainforge rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@rapp",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "chainforge"
EGG_SHA256 = "a088d6b7c814d166366fa159436915cb20aa91956a8077cadc85abe9aa82cf1f"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "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"
    "AAA="
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


class ChainforgeHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "ChainforgeHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the chainforge rapplication. It self-installs when "
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
                    "summary": "chainforge is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
