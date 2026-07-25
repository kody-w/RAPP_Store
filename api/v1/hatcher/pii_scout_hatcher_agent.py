"""PII Scout — drop-in hatcher for the `pii_scout` rapplication.

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

Published by @rapp · rapplication v1.0.0 · egg sha256 187220117879…
Source: https://kody-w.github.io/RAPP_Store/#rapp=pii_scout
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
    "name": "@rapp/pii_scout_hatcher",
    "version": "1.0.0",
    "display_name": "PII Scout (hatcher)",
    "description": "Drop-in installer for the pii_scout rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@rapp",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "pii_scout"
EGG_SHA256 = "1872201178794ccf7d1149854b99cb9dce3ce8fa0b2419e300c5d4baaf3e319b"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "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"
    "D8lbRDbufAB/nDZPpmzrhKOnwmM9Z/2Kvid7xbvRh76DtmUJgWY90W88/hsAfqfqPHUVRwuOx+SuheaypE+OQ5giRJEyMNRjhE5y"
    "JkuXqpvHIe4Ky2djvEt6kdeyukwo1hiJMv2N17p1kOnDRq609YbvXs7mH4bLQXIx7226L7tx9yUvqml30J3ROre0nNNyieX2XULW"
    "2e4FNBZM+/vEVdfAk4aGZ+LKqquqXuTSrEgxtHa2etpwM/T7sj1q5jv2YqOuf9elEQwA3ODU3XZ2fm6oWjcTA2+/Ffu2kTGnaEGA"
    "MHy/a1Uu8RbA/NkVNUtDD/2Va56wDfvPv5kr44+eUR02V83NwTM6xzMnmYI5DesSzk/JZVfmWqLzYJDzmIh3c8SI56eUW7Y/O1Rm"
    "Hx1exi3XVNFaxo9bSGujloyCbP8cF4gwGpDM/f27D318epZLu+r7MG84uqlyPrMaf1fza9DPhljQhiy126TCcpn77RDUH31eoyNT"
    "u6WAyKjb7EXuMDvW6XxGI1uDOAtJEMF1h2CYOpr2liTTLY4+NoXxW+K0p6Dqdn+f+YojDC2RP1aWFClZeLtatwFDrA8At4b2ejeJ"
    "KJBuzmQ03z8wzyODv0IHhnJQG6NoyN7S9IGe64oqN8wHC62oIrhQog7vGJqamgMiggY1JIEoKrtu+3shMCH7QYwKXxuYbtBzAMCI"
    "KnxdShoEeO6LaoqqIDOJk4GrRm6aSDANqQJn4S4atk9F2K7HPqh2yGA35zYTgKfHIOPm3KH/L7v/AlBLAwQUAAAACAB2C/lcrpzx"
    "KnkAAACaAAAACwAAAHJhcHBpZC5qc29uq+ZSUFAqSiwoyExRsoKxrBxAtH5BZmZ8cXJ+aYlVWnJKUlJysqFRooFJmmmaeWJqUrKZ"
    "ZYqZoaWFpWmyUWpKmrmFuZGxqUlisoGxhZFhsoGZmWmSuYWhhZmFsamhsZIOzJp4iD1woyEyeYm5qSDhAE9PhWCwMFctAFBLAwQU"
    "AAAACAB2C/lcQthp+y8BAAAiAgAADQAAAG1hbmlmZXN0Lmpzb25lUc9vgyAUvvevMJ6rAyxqPe3a25LttAtBQEtmgQAua5r+7wOZ"
    "rckSEvL94H3v8W67LMsdO4sLzbss7y2VynlxKcQ4vqASFZYaM0lGvdQq30e3vxoRvf8V8WO09YIT6qMBAVQXoCkQ/gC4AyCcz2SM"
    "TyVfi0jevcb7xUhJHNOz7wbG+54xiCg4DHhoqOhZfeQ1PLZHzJDgQ9M2qMIHykDVIshAXeO+aWFbtxWG1TOGpJxH6aQoellmeDud"
    "svcn/S2si9MEBZagBIk1cz9JdxY28kuniT9r59cZiPPaisL58B2soEYmCx2F8mSQk1gTH42QRSvNNTm1HanaOtU8TSmGOuK+ZOzK"
    "21ksXCigvAvMLaA1J0C4T3iWG8Cpj8sFf9DpedrAJXiDH7uBAd93919QSwECFAMUAAAACAB2C/lcvRKCkt8NAACSIgAAGQAAAAAA"
    "AAAAAAAAgAEAAAAAYWdlbnRzL3BpaV9zY291dF9hZ2VudC5weVBLAQIUAxQAAAAIAHYL+VzsXCxCDwkAAMMTAAAcAAAAAAAAAAAA"
    "AACAARYOAAByYXBwX3VpL3BpaV9zY291dC9pbmRleC5odG1sUEsBAhQDFAAAAAgAdgv5XK6c8Sp5AAAAmgAAAAsAAAAAAAAAAAAA"
    "AIABXxcAAHJhcHBpZC5qc29uUEsBAhQDFAAAAAgAdgv5XELYafsvAQAAIgIAAA0AAAAAAAAAAAAAAIABARgAAG1hbmlmZXN0Lmpz"
    "b25QSwUGAAAAAAQABAAFAQAAWxkAAAAA"
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


class PiiScoutHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "PiiScoutHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the pii_scout rapplication. It self-installs when "
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
                    "summary": "PII Scout is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
