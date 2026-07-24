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

Published by @rapp · rapplication v0.3.0 · egg sha256 54bc9c745d33…
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
    "version": "0.3.0",
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
EGG_SHA256 = "54bc9c745d3310d99f3b4cbfa5becaaa45534b3622e6ff21f12972b4c6c5bcf1"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "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"
    "eI+gnWSfifpNLDbDNY5DzGiYuqwkrHlGouhKeaaOR2Usb1TMEi6i0S0WeEzVKJVMAqyrR0kqjmWrN+yJ1IEiY7GQqAFUh9bWdf1P"
    "BP6Nky1t0eW3qnyzPnXXBx3AtFNFHoplJaZO57eVC83WZHNmSKdToGkQoaetfpsEP0CGW6VoyM8qNZ31ShPoNEmSqQ9NIVGhgFqe"
    "hXKLUZ22KLNZIbVZFtGa0ZUx9bJdJ0bZmrGTg49ZjsAXNNd51DSoBnqc1Veiae4ElcPadlSqeeEWvKP4tU4Oumwb+8pHddguSUKx"
    "2uBECC2EJD0JRDMSwDv0Cc9NxaAVX2fMuXZ8+jbjKrqkRo8MwMXFxyuRBYxlJtHVKcBtQUCIqunJ7y2JrWvQLPaHYDN3ySyutU8u"
    "eEy5s6VhRE0UaOreK36rvOxu69ZDeNFfl9KiLkyRrG1hTaZu6+khREsxp1AIU1foQrYpR/yVsesO8VnGmnqMoQ8iBLcfFI0Lf7Hu"
    "KYyQ+oy772feH5J3XJh5h/gKyA/Z/TeakNtUFDd0u6k62s+QnYYLdbwd2YOrnb7W07+KA6ezQhL8lfe6UjrbINX7iu5yrZT8T1pz"
    "+zrn1ksx2Rt23gOT0Ua4MyapPTjjYcGwVB8JLHRIFtDblIi+GdsSaHRuTAvoJqYhxW7ruUr1b9bEoKK808K5+nAsYyara26rJjxV"
    "MFxX2Re/WXYsd2tXNc/QUPEho9Gi+T+ShxT/N05ySXc+ctcPKyLoI5Biq1fUwDwTXx5VOTVvpsw7AgDehU2JmGpLsVXoXPkLJ4sS"
    "8O3Hs8hJPFs0Wp8Dn2TKRlAPVZhWdeejKPZxBKgvo8t2ByG4NnmjD0lXoDU/Ub8l+3A+VKkdRDNyGfyafY5H6wVhe9llxUUMvfdX"
    "6szaKiCry5OE8rPvvv1aNc6ezP7I3QzvFmE1AJ0tTTZH6pFjLxM+BxyQynfNMcas9+8qqKyi3RExG4WWuMe3+i9+cHo/DnonLx/0"
    "Fz5k3SPLib6OrnnyCPWMJTI/eyW7EY4t7iilqyA+E07JS8kniG24UylvDmWyw6w/PGF9J/b7M/oWJunvilxQfqxsXJjp24dOpa9V"
    "6oBKnZxkkcrzl8meOLynSbTyQT+FmSi44tRCJyrX6iufBNoGql5ZUiDljCA4CELFqr1DGBtY55b+wl0uXgIy4JTzmneF5XztvrBI"
    "UD06E09eHH5UXBxKfsYyMLYlCMgjAN+rVx3qzjDhq+iKb7zCVAQW9YCnPn99qMRhkaxktFVTnQ4bMyU0jKkorWoo+XOHq9Pqvne9"
    "35QCwHLf6zI61vKKU/dAq5r13A9vmDbGv4HuZ/06oPD9SoFFK0SqXCo9U6c01U/6C0jjE2cVn5rDEzkcZJXRqRxd0OipwpyW0xcX"
    "F9b59W7nPLRenKfnz17uPuxgjBZZr1Zd8Z+pd8X3mUKrLyZxwqfiWlbHb4Lo3X9DP7fUFac5fVM76RP4RePG1osfLl4+6Iit2uqi"
    "d6jWNZL6wz1m2Q869/uLFa1YDgU8fjZA18BHEny0EbwGvyfh95rhz3fPd8HBLjigR8lEmiVRuBDr1OOGtbTyPBRr5Uq+Equoe9i4"
    "IjwPH0jIfjydxAZUm96o3Cf/TLPthvWAsc7T3Yn1cLx8MewdvvwJ59J58cP05e60I/DeHzZubE3O+9VF0w4hOsdGlXXK46bV4Cxu"
    "SKjJrKYLlT6TyThd3ohrHUNhX3wymbZeEnKXNM560/6kPVba3m1P6JlUvNue0uNCPLbo8R/zCC+3L9yXHfFBRUGFTCZWKVBewgHV"
    "P4fYHENpnWQvq2WRQHbKagme/HRVfL1JB2LRXsp2i0JFt5Xk55mvqNLQj7KXUe07qR3IsSoHb7VpA0qURvuiXhOfcKqvdvAov96E"
    "3or/1cT/AlBLAwQUAAAACABMs+9cOGEdIywBAAAZAgAADQAAAG1hbmlmZXN0Lmpzb25lkcFugzAQRO/5iohzINgGJ3CqeugX9NQL"
    "MvZCrBDbsk3VKMq/18ZBReoJvZlhZxceu/0+c/wCN5a1+6y3TCrn4ZbDOB5xgXPLjJkkZ15qlR1i2t8NxOx/B36Mth5Ex3wM4BLT"
    "vDzliH6WpMW0xfVXCsZXpViHSNG+xeex1/o6MO61vbcgODkj0VBEMGkwlKRqqKgEO3EEvGnQgOuqp6SpKZCGnCtEcS8C9ae6Og/o"
    "r6hLTZvhyVPsttzxHoyPrfEN1sWbglcWpCiTauZ+ku4CNurLvkm/aOfXSzoXpkDufPgoPGdGpggbQflukBOsnZtlusUtzKtc25Gp"
    "bVbN05SKmOvcVca9vJ1h0bielXdBeQRamwKiQ+JZbkAwH39y+UKn52mDS3HkgM/d8xdQSwECFAMUAAAACABMs+9coMnHKf0AAACO"
    "AQAACwAAAAAAAAAAAAAAgAEAAAAAcmFwcGlkLmpzb25QSwECFAMUAAAACABMs+9cJYE4H0sZAACiWwAAGwAAAAAAAAAAAAAAgAEm"
    "AQAAYWdlbnRzL2Jvb2tmYWN0b3J5X2FnZW50LnB5UEsBAhQDFAAAAAgATLPvXEFdGlziFAAAe0IAAB4AAAAAAAAAAAAAAIABqhoA"
    "AHJhcHBfdWkvYm9va2ZhY3RvcnkvaW5kZXguaHRtbFBLAQIUAxQAAAAIAEyz71w4YR0jLAEAABkCAAANAAAAAAAAAAAAAACAAcgv"
    "AABtYW5pZmVzdC5qc29uUEsFBgAAAAAEAAQACQEAAB8xAAAAAA=="
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
