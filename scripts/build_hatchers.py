#!/usr/bin/env python3
"""build_hatchers.py — mint a drop-in hatcher agent for every rapplication.

For each `api/v1/egg/<id>.egg` this writes
`api/v1/hatcher/<id>_hatcher_agent.py`: ONE self-contained Python file with
the rapplication's egg baked in as base64.

The user story is the whole point:

    Download the file → drop it in ~/.brainstem/src/rapp_brainstem/agents/
    → the next chat installs the rapplication.

No curl, no URL, no shell command, no network call at install time. The egg
travels inside the agent. On first run the hatcher unpacks itself into the
host brainstem using the canonical `utils.bond.unpack_rapplication()` when
that module is present, and an identical vendored unpacker when it isn't
(older brainstems), so the drop-in works everywhere.

Run after build_pokedex_api.py:  python3 scripts/build_hatchers.py
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EGGS = ROOT / "api" / "v1" / "egg"
OUT = ROOT / "api" / "v1" / "hatcher"
CATALOG = ROOT / "index.json"

TEMPLATE = '''"""__DISPLAY__ — drop-in hatcher for the `__RAPP_ID__` rapplication.

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

Published by __PUBLISHER__ · rapplication v__VERSION__ · egg sha256 __SHA12__…
Source: https://kody-w.github.io/RAPP_Store/#rapp=__RAPP_ID__
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
    "name": "__PUBLISHER__/__RAPP_ID___hatcher",
    "version": "__VERSION__",
    "display_name": "__DISPLAY__ (hatcher)",
    "description": "Drop-in installer for the __RAPP_ID__ rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "__PUBLISHER__",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "__RAPP_ID__"
EGG_SHA256 = "__SHA256__"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
__EGG_CHUNKS__
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
    if blob[:4] != b"PK\\x03\\x04":
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


class __CLASS__(BasicAgent):
    def __init__(self):
        self.name = "__CLASS_NAME_SHORT__"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the __RAPP_ID__ rapplication. It self-installs when "
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
                    "summary": "__DISPLAY__ is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
'''


def _class_names(rapp_id: str) -> tuple[str, str]:
    camel = "".join(p.capitalize() for p in rapp_id.replace("-", "_").split("_") if p)
    return camel + "HatcherAgent", camel + "Hatcher"


def main() -> int:
    if not EGGS.is_dir():
        print("err: no api/v1/egg — run build_pokedex_api.py first", file=sys.stderr)
        return 1
    catalog = json.loads(CATALOG.read_text()) if CATALOG.exists() else {}
    meta = {e.get("id"): e for e in catalog.get("rapplications", [])}

    OUT.mkdir(parents=True, exist_ok=True)
    built = 0
    for egg in sorted(EGGS.glob("*.egg")):
        rapp_id = egg.stem
        blob = egg.read_bytes()
        sha = hashlib.sha256(blob).hexdigest()
        b64 = base64.b64encode(blob).decode("ascii")
        chunks = "\n".join('    "%s"' % line
                           for line in textwrap.wrap(b64, 100))
        info = meta.get(rapp_id, {})
        cls, short = _class_names(rapp_id)
        src = (TEMPLATE
               .replace("__EGG_CHUNKS__", chunks)
               .replace("__RAPP_ID__", rapp_id)
               .replace("__SHA256__", sha)
               .replace("__SHA12__", sha[:12])
               .replace("__DISPLAY__", info.get("name") or rapp_id)
               .replace("__PUBLISHER__", info.get("publisher") or "@rapp")
               .replace("__VERSION__", info.get("version") or "1.0.0")
               .replace("__CLASS_NAME_SHORT__", short)
               .replace("__CLASS__", cls))
        dest = OUT / f"{rapp_id}_hatcher_agent.py"
        dest.write_text(src)
        compile(src, str(dest), "exec")  # fail the build on a broken template
        built += 1
        print(f"  ✓ {dest.relative_to(ROOT)}  ({len(src)//1024} KB, egg {len(blob)//1024} KB)")

    print(f"\n  → {built} hatcher(s) in api/v1/hatcher/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
