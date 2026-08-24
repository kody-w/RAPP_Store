"""BookFactory — drop-in hatcher for the `bookfactory` rapplication.

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

Published by @rapp · rapplication v0.3.1 · egg sha256 f8002b0ea585…
Source: https://kody-w.github.io/RAPP_Store/#rapp=bookfactory
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
    "name": "@rapp/bookfactory_hatcher",
    "version": "0.3.1",
    "display_name": "BookFactory (hatcher)",
    "description": "Drop-in installer for the bookfactory rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@rapp",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "bookfactory"
EGG_SHA256 = "f8002b0ea585ae8000ba181302b538c47064becb5def499a446ca86998a3d1da"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "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"
    "qAFUh9bWdf1PBP6Nky1t0eW3qnyzPnXXBx3AtFNFHoplJaZO57eVC83WZHNmSKdToGkQoaetfpsEP0CGW6VoyM8qNZ31ShPoNEmS"
    "qQ9NIVGhgFqehXKLUZ22KLNZIbVZFtGa0ZUx9bJdJ0bZmrGTg49ZjsAXNNd51DSoBnqc1Veiae4ElcPadlSqeeEWvKP4tU4Oumwb"
    "+8pHddguSUKx2uBECC2EJD0JRDMSwDv0Cc9NxaAVX2fMuXZ8+jbjKrqkRo8MwMXFxyuRBYxlJtHVKcBtQUCIqunJ7y2JrWvQLPaH"
    "YDN3ySyutU8ueEy5s6VhRE0UaOreK36rvOxu69ZDeNFfl9KiLkyRrG1hTaZu6+khREsxp1AIU1foQrYpR/yVsesO8VnGmnqMoQ8i"
    "BLcfFI0Lf7HuKYyQ+oy772feH5J3XJh5h/gKyA/Z/TeakNtUFDd0u6k62s+QnYYLdbwd2YOrnb7W07+KA6ezQhL8lfe6UjrbINX7"
    "iu5yrZT8T1pz+zrn1ksx2Rt23gOT0Ua4MyapPTjjYcGwVB8JLHRIFtDblIi+GdsSaHRuTAvoJqYhxW7ruUr1b9bEoKK808K5+nAs"
    "Yyara26rJjxVMFxX2Re/WXYsd2tXNc/QUPEho9Gi+T+ShxT/N05ySXc+ctcPKyLoI5Biq1fUwDwTXx5VOTVvpsw7AgDehU2JmGpL"
    "sVXoXPkLJ4sS8O3Hs8hJPFs0Wp8Dn2TKRlAPVZhWdeejKPZxBKgvo8t2ByG4NnmjD0lXoDU/Ub8l+3A+VKkdRDNyGfyafY5H6wVh"
    "e9llxUUMvfdX6szaKiCry5OE8rPvvv1aNc6ezP7I3QzvFmE1AJ0tTTZH6pFjLxM+BxyQynfNMcas9+8qqKyi3RExG4WWuMe3+i9+"
    "cHo/DnonLx/0Fz5k3SPLib6OrnnyCPWMJTI/eyW7EY4t7iilqyA+E07JS8kniG24UylvDmWyw6w/PGF9J/b7M/oWJunvilxQfqxs"
    "XJjp24dOpa9V6oBKnZxkkcrzl8meOLynSbTyQT+FmSi44tRCJyrX6iufBNoGql5ZUiDljCA4CELFqr1DGBtY55b+wl0uXgIy4JTz"
    "mneF5XztvrBIUD06E09eHH5UXBxKfsYyMLYlCMgjAN+rVx3qzjDhq+iKb7zCVAQW9YCnPn99qMRhkaxktFVTnQ4bMyU0jKkorWoo"
    "+XOHq9Pqvne935QCwHLf6zI61vKKU/dAq5r13A9vmDbGv4HuZ/06oPD9SoFFK0SqXCo9U6c01U/6C0jjE2cVn5rDEzkcZJXRqRxd"
    "0OipwpyW0xcXF9b59W7nPLRenKfnz17uPuxgjBZZr1Zd8Z+pd8X3mUKrLyZxwqfiWlbHb4Lo3X9DP7fUFac5fVM76RP4RePG1osf"
    "Ll4+6Iit2uqid6jWNZL6wz1m2Q869/uLFa1YDgU8fjZA18BHEny0EbwGvyfh95rhz3fPd8HBLjigR8lEmiVRuBDr1OOGtbTyPBRr"
    "5Uq+Equoe9i4IjwPH0jIfjydxAZUm96o3Cf/TLPthvWAsc7T3Yn1cLx8MewdvvwJ59J58cP05e60I/DeHzZubE3O+9VF0w4hOsdG"
    "lXXK46bV4CxuSKjJrKYLlT6TyThd3ohrHUNhX3wymbZeEnKXNM560/6kPVba3m1P6JlUvNue0uNCPLbo8R/zCC+3L9yXHfFBRUGF"
    "TCZWKVBewgHVP4fYHENpnWQvq2WRQHbKagme/HRVfL1JB2LRXsp2i0JFt5Xk55mvqNLQj7KXUe07qR3IsSoHb7VpA0qURvuiXhOf"
    "cKqvdvAov96E3or/1cT/AlBLAwQUAAAACAARuRddyDJy3SwBAAAZAgAADQAAAG1hbmlmZXN0Lmpzb25lkcFugzAQRO/5iohzIMYm"
    "xOFU9dAv6KkXtNgbYoXYyDZVoyj/XhsHFakn9GaGnV14bLbbzIkL3iBrtllnQWnn8ZZj3+9pQXML4zgoAV4Zne1i2t9HjNn/Dv6M"
    "xnqULfgYoITWOeE5rT4Ja0jZMPqVgvFVJZchSjZv8bnvjLmeQXhj7w3wqjx1jJVdKVAyVpED4YJTIankUPGSoKxEjUJyCvxAa07r"
    "AztTPPGaHPH4V9SmptXw5Gm4zXe8B+NjbXyjdfGm4JGCFWVSx6kblLugjfq8b9IvxvnlktaFKZg7Hz6KyGFUKQI9at+e1YBL52qZ"
    "dnaL8VVubA96ndXTMKQicK27qriXtxPOmjCT9i4oj0BLU8Byl3hSK5Dg408mL3RmGlY4F0cO+Nw8fwFQSwECFAMUAAAACAARuRdd"
    "dZPSsv4AAACOAQAACwAAAAAAAAAAAAAAgAEAAAAAcmFwcGlkLmpzb25QSwECFAMUAAAACAARuRdduJr3vQgZAADqWgAAGwAAAAAA"
    "AAAAAAAAgAEnAQAAYWdlbnRzL2Jvb2tmYWN0b3J5X2FnZW50LnB5UEsBAhQDFAAAAAgAEbkXXUFdGlziFAAAe0IAAB4AAAAAAAAA"
    "AAAAAIABaBoAAHJhcHBfdWkvYm9va2ZhY3RvcnkvaW5kZXguaHRtbFBLAQIUAxQAAAAIABG5F13IMnLdLAEAABkCAAANAAAAAAAA"
    "AAAAAACAAYYvAABtYW5pZmVzdC5qc29uUEsFBgAAAAAEAAQACQEAAN0wAAAAAA=="
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


class BookfactoryHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "BookfactoryHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the bookfactory rapplication. It self-installs when "
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
                    "summary": "BookFactory is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
