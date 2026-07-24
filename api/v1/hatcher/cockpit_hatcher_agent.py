"""Cockpit — drop-in hatcher for the `cockpit` rapplication.

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

Published by @wildhaven · rapplication v1.0.0 · egg sha256 ec92b33c1720…
Source: https://kody-w.github.io/RAPP_Store/#rapp=cockpit
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
    "name": "@wildhaven/cockpit_hatcher",
    "version": "1.0.0",
    "display_name": "Cockpit (hatcher)",
    "description": "Drop-in installer for the cockpit rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@wildhaven",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "cockpit"
EGG_SHA256 = "ec92b33c1720d1d3a96ec2ea772416045eda7bf3017c04fab29d16a097ea9eba"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "UEsDBBQAAAAIAEyz71x6p7/b/QAAAIwBAAALAAAAcmFwcGlkLmpzb25lkMFuwjAMhu88Bep5gOOkTdIT0l5hp12Q4zgiKrRV6UDT"
    "tHcfUbcxaTf7s+X/9/+xWq+rCx/lTFW7riYax52qngotdY4/NMd2f8uneKSr9DseuBvz3Hox1kZkD8ROK7A1JPI+IVqlmAxqLyFx"
    "tA03wVmLYhWyYDCRYoy8KI00ST8f/gt2Q3zf3HalbT25BGRCTVaBICQTnfIESd8NkGGflNKhFutS0IxeLITapJSMI+2SX6S63P8q"
    "nDLTnId+mfR0ljJ5Xl5b4FWmS9m4c7WFLXz7fQunfDnKVPgjlUdsh+UN/nsqDFN/oLlwBGw2YDeqeQHdYtNi/VqtPr8AUEsDBBQA"
    "AAAIAEyz71w9MwyLIQEAAAYCAAANAAAAbWFuaWZlc3QuanNvbm2QwW7DIBBE7/mKyOc4wSQxsU+V+gs99WKtYW2jEECA01ZR/r3G"
    "JIql9vhmhp1dbqv1OvN8wAtk9TprHUjtA15y7Psd3dLcgbVKcgjS6GwT0+HHYsz+dfDbGhdQNBBigBJa5oTlRflB9jUta3r8TMH4"
    "VIrnECnqty+pxABX1Dtu+NnKUFd4YExQXhHgp31B2JF0UFUdpawoOBzovsK244KVvGxPjFFkBeVI24MAIQR/NTWp6jE46Rou8xHv"
    "S/GKzsdjJr3Yki1Jqh1bJf2ALuqvRZM5GB+edzQ+GIe5D9OX8BysTBHoUYemkwofpXpUanaM60H/6wzgG3+WcZUOlMdZ5GbUwU/S"
    "baLn4AnJJvEoFyAgwAK9GdUC5+bIE95X919QSwECFAMUAAAACABMs+9ceqe/2/0AAACMAQAACwAAAAAAAAAAAAAAgAEAAAAAcmFw"
    "cGlkLmpzb25QSwECFAMUAAAACABMs+9cPTMMiyEBAAAGAgAADQAAAAAAAAAAAAAAgAEmAQAAbWFuaWZlc3QuanNvblBLBQYAAAAA"
    "AgACAHQAAAByAgAAAAA="
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


class CockpitHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "CockpitHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the cockpit rapplication. It self-installs when "
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
                    "summary": "Cockpit is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
