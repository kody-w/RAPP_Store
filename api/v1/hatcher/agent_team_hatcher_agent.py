"""AgentTeam — drop-in hatcher for the `agent_team` rapplication.

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

Published by @kody-w · rapplication v0.1.0 · egg sha256 074a70850f5c…
Source: https://kody-w.github.io/RAPP_Store/#rapp=agent_team
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
    "name": "@kody-w/agent_team_hatcher",
    "version": "0.1.0",
    "display_name": "AgentTeam (hatcher)",
    "description": "Drop-in installer for the agent_team rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@kody-w",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "agent_team"
EGG_SHA256 = "074a70850f5ced5f1885e9941561779916295b6df816f5be74cab82126b45d3d"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "UEsDBBQAAAAIAEyz71w3CQe1+QAAAI4BAAALAAAAcmFwcGlkLmpzb251kMtOw0AMRff9iihr0o7nPVnBP3TFJvI8TEdtHkoCCCH+"
    "nQ6hZcXOvtfy8fXnrqrqJZxSj3Vb1TNO0wHqh6KWOsebmmP7eB7jR/N+wJc0rM2asG8xBoHSKxYDkGJJkbYRLEhtHUoVrTUoQSul"
    "KcUoDQQnvPAARno0mm2kCefrxu5fYGlbh5ZYYaEBljgjGS04ZCRM5CiDIwDhVTKWvAjcJcO8kkQkLQpLbkOd83AnXHLANY/D5gzY"
    "p+I8lXTHa7hNfkvzUmauDtvD/nbxq7/k5ZTmov+e+fe1bkvx86duva/y4zx0uBaLM64bZhrQRyZarluunuvd1zdQSwMEFAAAAAgA"
    "TLPvXPzqwq5gFgAAiz8AABoAAABhZ2VudHMvYWdlbnRfdGVhbV9hZ2VudC5wedVb63LcRnb+j6fohX54Rp4BrXU2laJFZSmJlhld"
    "yCWpeB2ZNdMD9My0iAFgXDSeVVi1v/IAqX1CP0m+c7obtwEl2tmtVFgqigAap0+f63dON3zflyuVlLNSyc2M/wyynfjlr38T5VqJ"
    "TOVFmshpnlalTlZikUudiHTJD49ptLjCi+KylHmpcvFSlxMhCyFFgeGxErnMsliHstRpEnjecSSzsuC3HclNGqlYLPN0I57qOBbf"
    "r2Wski8K7918gestX26KZXnA3E2J0Wlh5pve6HJ+PVqXZVYcHhysdLmuFkGYbg7u9erY00mZijRRIsrTbIqlGQmIKzBoBwoMFJHK"
    "4nSHdWFEVaZJukmrQhyfCiKJ5cjSC9M4los0l6WiBWJ5q7V4ocvvqoU4LYpKFRORV0mB6cTxX6pciW+rJCS54IFMIlGsdVaIR//i"
    "FZkKtYz1X1TkFFCI0VlVYmF4K5cblU/Ec/XhDOPPX+PPr//5D3St4jSjR8en3qWlUUAf5+kWyziPZblM8w0NxJA8XOtShXh8qcIq"
    "1+VOXKgPWm2JgCrDYMxS8Gj1uixUvBSa9Priu+mx4fqAVzGtVwEdgrNtmt+w+ZDUUlUkX5RiSTQgaa82i/NduYYcljpWAWm8FM/P"
    "Ti5FlualCGMlk3hH05GdPGSbe3jIF6Aib5SX6UzFGmojyYuyyhNiLZdbsUplbObyhHhI+kqt3Jg7MSqqMFRFITaqzHU4ES/PTyH/"
    "SC11omkZZNwRLGI8MQScBthe8f52rcO1KGrxFkIlK1jNBLOKLbGT5hHJcLveNTRkUapprmS0cyahySTEIsUdvEhrg6S/ALWfQbpU"
    "ZA4yI35TPNQFCAljnBgDTrKqZJstRKRzvEDyIlsGnwoSMPa6If+0zkrmznbGLNGdeaJUVEx3aTUXP8E8jRLpCRv1Nq3iSMRpmomF"
    "DG8EE19XGxIpufIV1gpeeMnEIbs6q5wWRD716tVrEco4DsTbQi2rmDwqiWRMz0Yy2fE8XhbLJKFAIMWmiks9jXQRagSNROY7keXp"
    "eyxPrFTJUaXMqxD6Js/Ae8zZmFdVmSk49kDfmUxImZ+RiBixZujSm7NGZqSRuZNlR1fko42eyM6XcbqFxGCRIv2g8jGk8hw6sW9j"
    "gRfH5+cmZmKWDd6aswqLg7lVW5rvAvEd7CImm/ygpTgIIdCJR7Ir0zRmAU5gU2J+IDONuJbAukw8m0Owp4ifFSjyu8RdiKCV62gF"
    "J8nTMkVUAlenSZFpEtpiJ+4ZVQNxXi1g4Gu8VdGc3vyPN5DNdDsPPN/3PY7Ys9myInXMZkJv2HuhzLTkcF94nr33Hg7keWW+O2Qz"
    "5jeNIIKFLHRo8o6j8JRucW7x1M+hykpxyg9O8jzND4V4AKOQq408FEkKVUPwHG/COK0icSAQAhMyRQrdSwiPTISnreevefjk5DRR"
    "ucvUodCrJM0VvzrAUJdka/bgPkvcm8XzZjP4mF7CISHVI/GRJ/CLcK020j8UPpGfMrmDR8FX/sQ8TxDd6KlV0kGT1d0I+BV8Zjdz"
    "I3n+q9YASLKA3ujZV0GLdKSKMNdZaZ6N6gX7V78NIRgn9Rs6NinY3PtCf1AJBU3n+gjpSJ3KhHki2wnpkzalTrCefDruTmqPbhGo"
    "Y+LdIbGo8qUMVWDeGlshARas07ylASe9Uq4K3H7XzNHGRHaUIVF7YvtuT8DtR1YO06XOi7L9wAChKa+16ExBKbtD3UZfe+/aMg3m"
    "1ArBidYDPUQIuvoDMIJb1E8Vkl+5m5Va8ZrBxqZKWgNy9VOFiFPMVPKBVn9d2xIcJFJJqBVLxf8jSeOg5SO+G4p7KpoZe7xXzHJz"
    "q5/lJovVjEInXv7YWn7OumjumLuhNW2fzaYlHiNM2F/H7usnTysNe5DiuSwlOY+aUrBBwDQwRTDcYojChIuWodU0wqoooUPEKlie"
    "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"
    "0qG5qPe9d0CTn9MhaQoXKR/UGPJ92m1QeWkOlu5TMKJzRz2Hn3dmooDbOW+7N1Il1Ya7a/bcaB8mTvaA3aSLwa4/Qbxr5v735gRW"
    "rJHSbDfJ7EGlboMqQEGwlFVcHrpvVRgNUNfIaXc8FDTp53b4tjv7+neRVm9BVCEP7LnZz4H4O5K600/mRCu1G5n/+itXYU/M/GPW"
    "cWY90Z3wWdN5PvC6GCg/AWBQSMJFgLK65eBE1FUfyhWVKGof/cpltnz+H73WTishou9XzHG1RRUBvUxap1cmYlMBvNMmBJ+0sdcA"
    "F3TPfGp2/3UO3HJHzSP2RDbYnlu1XrptclAF3YzGQZ3DKNMcNTlHuPx01MlWY6/OfnifNMfJbyIePrzZ0vHyboVJP67+EiMzwuA7"
    "G4kMvLOIsIPo6aep3iwY67RbupCsjaqjapMVQ6BM0ScrENTSr5KbhFpZrk7+aP74XX47FFt5p25mhpBxMRrqdoVu1K4Yjcd7wKu+"
    "5kK7JwVWVx/itpdP6+bq/bev1Xd72c5QGGUay16oehO2iTa2P0fhtW+a7fVYfz8S7QXZUNOsoeUpvaFtd22RtWc7jobbe66z1+nm"
    "NbNRB4Re3e+EmCZIa57O51D0w/tZCFNxEcTxxn2qRB9RzHDd4GXzCdQJ/8f7JChqP6ueluXRp230LZIskdCqRH5AEUrberBBdeu3"
    "JbxRRSFXqqiP0bufj/WJKCMjyqvuzNShlWAvVDSvkGy6L9Cd1vDru2VECeuolsnIMTj++0pHmS/d+uLY46YGbUdDvZS7mfrfOJM5"
    "/xPpiF3TvksQcihsgAu8g993e1F7DZ8s/sd7r7zzaY9YcqV21yc91vi7T3/rl0WtdWXZJz+241X2G2wtCTf74/Q9Z1Ie/X7s/Q9Q"
    "SwMEFAAAAAgATLPvXOMwhmvbFQAApkYAAB0AAAByYXBwX3VpL2FnZW50X3RlYW0vaW5kZXguaHRtbNU8y5LbRpL3/ooS5TFBDwk+"
    "+qEWyWZbrxlr/JDC0hwmFIpWESiSMEEABgrNpjWM8GlPG7ERG3PYiD3snuYXZs/zKfqB3U/YzKwqvAiyW7YjxuOwRaCQlZWV78wq"
    "eXzv6Ysnr//08hlbyJU/ORrjD/N5ML9oiKCBA4K78LMSkjNnweNEyIvGH1//rnPeMMMBX4mLxrUn1lEYywZzwkCKAMDWnisXF664"
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


class AgentTeamHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "AgentTeamHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the agent_team rapplication. It self-installs when "
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
                    "summary": "AgentTeam is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
