"""Project Tracker — drop-in hatcher for the `project_tracker` rapplication.

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

Published by @kody-w · rapplication v1.0.0 · egg sha256 5edbf082d762…
Source: https://kody-w.github.io/RAPP_Store/#rapp=project_tracker
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
    "name": "@kody-w/project_tracker_hatcher",
    "version": "1.0.0",
    "display_name": "Project Tracker (hatcher)",
    "description": "Drop-in installer for the project_tracker rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@kody-w",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "project_tracker"
EGG_SHA256 = "5edbf082d76248affc5664e3ad8566054b07cf1fb1a65df448619e1654c55db5"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "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"
    "raZgZfN277ZJcBjOYlm2KJca0CrdbzzF+QsxRQ1HyBMwD0Vhnv27WN4RuYAwZrNicD3iPllBs6nFLg7xAIHlzBBEigBPLPj5G6dQ"
    "waYGmPipdtC5Jnusa+oSveWsq7UGbSkMWOe0Y7JdNc7PILLwaaRdiIdj2VUGShhrOGoJrXLxqwGguvRZEFGuGQ2w+YcFoeIK0wAT"
    "Xy8IUd2HqQPWN27aDpsaImGmRTWCoi38+jVuptGsxc8t1lT1HjVjQ/WIhEUZnW17G9rgUQOLQFavGDYAVqLFFoXu5iUtTmrRRkp7"
    "zNRCYbxYwOsZey1rD6P8Us616msYu3RG9ScuFBBZoMsb4kwuBCxyJm+zc3oQqhffmXXSvZwmGM5T9DC/LRRKqaV/aKlcyK7BjVh1"
    "WFQIUl0HFmcQmlwU7KofS/ixMUCfxSRv27eiKnd8yQHtsGMOYgWVdeSNO5WlYMe+qfr1F42w33yjkVo5QWf8ANQZRnOYhb2yxRUY"
    "ky7DkI66fMfEdn5SQdNg+BmuS/JzPjBzpzmHjWnjwHDHXttNEWHyObL6NOxdKEcXrFaW3W612sTc2+hlER8qVxL5dp9LB26smm3I"
    "hqp1urUdt8XRXnDMgKrqhUoOqnJ/9XmCxS2uAbxMppT9l+Imi1+Xb73pabiyppZCRmltAah3H6varUu+A+ZGo91UMxJZQwSvbhiW"
    "Krlr0k8ZnQUAJ8Gtnu5+dyAued1ZN6rIbH5xplboFxWe6BV0xf4LlphBh8lw+w4gHZ6Sw788eX1OTl+9fXnyCn4dnp++eU3O3x0e"
    "/erk3W/jOvZF3fKyqaNkFkZJTs7y+ShMSJ8U13XLo1wuQB/lHSyjXTXAofRpFP6M3+pbNwqUkqLfke5v41qDOmFOPtPhHIeciFRb"
    "1n6e/MuTo/fnp391Qs7ev3p1+O43rs5Uhoph4uj4OaaEKmiEvbdkSXH2/OMhY103nDtm0XIjwPshjq5D6wuZcV4tnfH8VuM5kO3N"
    "UduuztqltrpFNvroZiNJdHJGq8nP3ezpmFZH78/O37w6eUfevnvzy5Oj8zMnu7Xh+oXS8Kioqdl0UjrEeLnRwNCqPVNVbaxEjkNp"
    "jaySEPOlrjhTaRbcICiEGZxYRtjvyMZt5TSZuj1c3QCoDayJuE1z2UhlE6Jn4rRww3k+H6Q+Gk/sedWUYXmLRdh5NSHD2xaLVLM2"
    "YXyp+Pjq/hNX4tIKTWRFImu6jyNaUTQHeTURrCVPqV1WPBmene3KVZvi49i1IqBVNrnbzDJHPi0oovardPL4dosdsDs7IUeHZyfe"
    "/fn4x7/57+asNtYhNmB67DcIOsa/jRFn72HQqlu8VS4JhY89DFHrlHRQtejRR96j4sSeJcbSSVo7fl4TZkF2U/27vgynH8xrPYkq"
    "TuV7mUWan9e3Z85zdq27qTub76WnHimbfHuvnQty91drTVoyhY/Pf+5wScTzMLlniCMA8j7nCHPo+xJRP77Xmmv49sHSeKWRMO1u"
    "9RC+6qWZ+3z5/fL0+bumlWUbU19t4fn705fn/dPXfKXvXk40WbyW+DsP5rcwPPfl4gk8R7TOinFWqBBL37AaOuBR7ai4SlQCkJeL"
    "mlZ/OqtYl1fGCDaLJKoyKF/+2caq7XgZxky76qNBXi1/2O4wdHcdPnzazfZir25p812uWc9PX528PH19ci+re+/4Lm11r0dvLbTI"
    "f9hALXy0UCzJ2rTxUo6Ck5TlKi2u1XCljKbl/Rp+vCqrVJn8riy6EAuevD4mb16Qdydv37w7dzOVPFah+/2NXvpkdlM66S17FqVj"
    "fPHNiCq+cXAVXmK/MSx/xq46GFynYU7P8bJeAQDqT2jc61kcSzDEgLG87BR7EoIVmCekAPmI/CaZk2EQkzi5JrMgyykJ8aItKFQ6"
    "wrH7g1p86Iq8/jRNrbqRXYkKBZK0133Bsypi80BSdt1pmhrYXmBdLT4gbyOKERJ8253dvMfuMZ4GMb83DK+4wZKAvwFX9xjLYxg/"
    "wThzuBf64RZRUz3cgiDWZlEQLnCs5eKnOdJyeNpnhmVf+pP77ygjjLYhohwtGmSzKISWz7srH9Z/vB3kn/M/w4MtLzCm8Wx+MQ2z"
    "rLIR6hnliNuI7MIh3MzDfaReN0NomKMRL7muzTc6mKVMEh/TcTCP3HGLlbBEFuHZIvrPvO+Hk5KOiogXfqkVXt/ec9wMxEI5PlRC"
    "N37clREThjt4WbTJkF1ONLzg2Hh303q2EK+CLEnhfw2k6oXfbRnwWIcmE2+2jG6sA+LColU4Yx1IJUfoIoGMxg6WjqV2YYsG2usO"
    "bNcAWAMVTXArnh0nVHNMov1YanWO1Msx/4AHtSvhiXUwpcfXAcsUkGgEdezFCJYIRCPE0pfaKtbQMFbq1atqHJzRZm0XHFe5v3XX"
    "DNH/Ttf297i6jtR6Bp2H4t5KY8dNVyu74s51IB9CeV2kIl3r1axwqpfrmdcxIye5zDfnsoXLbrFfV7rrWauVxKkS849mSBUJWN/o"
    "ZPDEmaxVou1d8i7i/mU9ILK2CPLeU2akUlowDNNPRm+xBate7MzupnTQ34vuBpKSEOMZUFiwY97kOswn0E5VuspIByF8PYbBPt+y"
    "4Ipf8m681A6v2tMsonrkpGIlwu9mW7ASQvgAliBrz2ogxW4Dpzx7eVd7gkPyUiTDwkHWAE0WvIPlpR7LlGC8pbXZS8mmYUF156lx"
    "zxncdvbKmXs4GsG8VY8NFz5H1m5smauVES2LK6/9PcwLzTA1xtUyv2Adxpj6VRADhjigzZGpHA/j2t+axUKM0T+nsPhYrC7ANP4E"
    "ax7hBvFf7f/Z5LHApzpRudeKMRzvNsyrrIjri24e2WOngY1Z4lrUbRg/XfAkXuEWXQc3Gb8duM60vAJjWibzzZw7DtnxyMpFufgu"
    "A5pXu8SS9+An78w9KYvEFVz9Amq+Yy908vNig0SyilF14ZOnN+7bpqectkJdsak4C/DeSyq7ltIM9J5lU9n4Eq9+yZOUMreibIFN"
    "WWbGoEJV74BRH2RHvA+dj9x+Bb8WGOBtMhzGW96YTkB8bgnzuJIe86jadq4FJ55gGUZ3DAPDMQXpQr4jrO5gCmwJQtFCJL1T5oRD"
    "2oku44DjP4cZ81kztnL7YQ1U0DrJs0up6LW4A4eBdHm7+OD1RUnzwS7g8yI6thkUlFYuBTYKcvUyTB+QvEIDVKaSj5K521ctIApT"
    "CUvbDlhz68MXoHL03gpz1HxpkIDmc2cQzOCjIBry035MWDLDDmzmcFg97YfnGMoxlD1a/75WqDIwjnIA7FCltrnIuUbC9YbOoBe0"
    "CEuuOwDUGVCsETFaiHtew4z9aym3YryY1Fi02HUsDrHb9h2NYdgZrPfMfgb404iGfOrU/+47S9CMbQktH220rXDuskoshowb+g0D"
    "xguZum8rK2NSmoa4WtpKYVelNjFfTBxbomfY2BuT3vHjkU1xmJV5ZRs0fMxRU6aosnpJK73FksiP3LxwO2q3C1iRuOrEFlD+5Gnt"
    "M3Wk1miYPEU0R8PYyHIe0i5vGWNRGYmiMhsEljOSskALNghl3AXiSwciV0nxhf3tHB9dedyL/FKsGu2ApCY9TUt0S826CK9WLm2U"
    "epMlN1brVCyRerUKodwalt31KLWaMDFqilu8lxmimgKVdLsC71X9wx9MloQlaE5tD2Na8Lqc4gAcuyJnb14cp8ess332e5dgLlgl"
    "9TfeQm+ImfMQf0uxJfC5qz2Bj1jyZSLnmGE3w21g2OWYRmh3kue9KHQlzXbeWCyvYVnsUo4yMZXp8FeZoooFb1WOTim3P8iNivqG"
    "er055Woz0dWIjvNaRzFl/I7e16+/FCP1A+mK20lY5oOv6M54mz7r3haJsfSy20+H66Ls1s4O3RpiWY1mW8Y7Zn2ze6vtvX97fHh+"
    "wpp7ffJrr0zWba+Oq14Bhsm897JpEEXsAmrzCR1ohJXwuxQuCu3o2A5zeZlENRm0No9qqSMb5aCyJGoh6zDRiwgiyRNyOBo9jNCz"
    "2+Ou8ku2yfFZll0u0b4v29wwfh/tUpKnczHEWT9HdPpAE8bOjiMi+NgnhO0AibnGg5j8+CzJ7Jc435Ppj88ShpLnRniwgVy62BoZ"
    "bi1WQFbhCAfhgmk/kngcplPOFstxcOKJfZqyRIrowa5uFuAjsjXie+k5Z3+wnYNi/6rarLs9kM1yu4IvlvLEvIArG72vTUy+6SKQ"
    "KfMdNGxafnzFEBNe/hQmvtx9CSNatQedu5dlSlygI4NWXeRw4kqCG/YFKn+03gsN4iGNJC957k+p21ICLdvuVMm1lYY0pm3eL/B2"
    "uXvlsPGBiMOoZKpT127mZDw0SI27vzgjxZztdc8nYUauwygCZkI2w1RoZfYIFoOupuAegCqh5CaZA81T+kPXKI3rDQQFzeMkJxeU"
    "gH0Ntk4RBC9KQyMBKHMzVDboBfM5tFSRX+WD4VKNApKIYnTrEmFe7FoO1K3iZPkVpTNeEBS/yV2qP/LmDsP1FfIxXGMhn7yIN7TU"
    "vzWrHNtElI9tQspHzLdD5BQcgkmQwUBSwWi0fp6C4WLRViaG5QggiiLTjyVsIeNfXfssiGBflDNv1uAKMjOyUbea7ae7W1+j82Cs"
    "+hB1uc0gDP5ujWsqxwwN1aX1aAUgrV0rhOIcF4uwUiFoR80MddnEOoOFKNTqmSNCZMYdsgbr583HqM9ehJ/pqLe5gqeZyK+eG5RU"
    "V71Qq6upw2rmqCq3uLQKH1vNX6YhzcbYFMRSDVY4jcM8DCLoOI+9K/XnfIab+6BSUfTWGTYsKr6A0u9FYQwZqHEuHlEElgWTgoUL"
    "MOho2BQtIOrVZvBBQYrOj2QMqIHEvB7ICm+VQwB4JU4XBCq/HKFrkp0Yk8H2EIsGWS9Zf4P4htDPuLEYX9bVPT5DcaURLyMEcIQj"
    "h0EGwJs4AU9zOi2Cus95vAwWNYkF7JcKzibuxT43RkOMtNgItbZFYFUNFSb7OKhVBzWNUQqO/biyFTtMHyeFSzzbRLMVMRju10l1"
    "rFcVzlOHrlYXi5kQsV2foEwftBf7GoeztkiqRIGRjKZXNF3FzzGZJaBQIsyLloG9PQlyFXZhh4Tx71g0LMEYoolMf5uFI9Yo6B/G"
    "ysk8J4E4QAdrjHFKs8mgPm+B4Vmc3Ruw8mozVZyk9DvvMxB5Clf4opVdKjBVDD48VAEGTVaafBUpVMMMJFaav4SCb4EqTCJq2GUw"
    "zzCtLBiBvSC7iYfEdlSS7V5XOlosu5CyMaxxUgw8vLiAfwMUZhiAcQkky1ii0vrapCGOCWqiP/s6CGHFQfEcZXctmIVryHxdjAcc"
    "BsMJLm7ipJ9hbFI9EFDF/RHAGySfzGvFasvs2KRsGqvhC5sZw0QqVkCpCQOVnzFuPIuDWTZJrFno8SmnuiKIEJbDLV9vAapjHXuV"
    "JkPM4DsowqgAfbL2LUnGY9T135PwMsYosG/XdEtslWytr68buVHIsXqY9vGbV0LXvmRyBQO2DdxXChB+mFdnakd06xEGwvIsvxkR"
    "NxlyZzxhMZBFWY85WXikxJUOOpo8l3C9l6whWyw6Pkx5idA85ptikGyMo6csdq8B6+N7q5EL/91b48v+A068vUf9PnnDvABBtFuz"
    "Zyp2BlP7/T73tO9xMCL3tB6o2yHhaL8jjBy81CQQWxNlRztSQHeqiy15+FFfXnWEAYvFa/3+QjrswqNd0jmbwIribRLG+bEY6JPP"
    "7HRaknZWSUdxe2Bp8a04y8x0TwmiYJYM68r4eawIH+llynqMn/iuEn6Q1kXHtBBT8Dy+gV/hMNt6sn307v2xATd8jZmXeSsZHxFZ"
    "jUC9peP0NrmmKeu4AR2ZwpWUpdD3l8nTJzUSJcA96WKI8Cj1V8DvAKqOCv+A2lrGsmNkKowhyMps6cjIhFnndDrDkDoXbeRRyExY"
    "MaJKDR1ZrooRLG98kTmE+XqThZkBGfbp9yUuBXOjRyYNs081bAIF2ELYvAPzCSlZRwa/VMgCAwXSIk3ADNHRuE7ST+MouV4YjVcJ"
    "SJwkNWMiPpZkicIxHd4MI9pmcCpoaD6iDl+kdyruFQXz4hamssStJpT31jAkH/+d5NPo4P8DUEsDBBQAAAAIAKNl+FxGwuUjNQEA"
    "AC0CAAANAAAAbWFuaWZlc3QuanNvbmWRzXKDIBSF93kKx3WwiPF31UfoIqtunCteDY0RBrBtJpN3L4pOnXZ5zvng3AuPQxCEhl/w"
    "BmEVhI0GMRqLN4J9/8IiRjQoNQgOVsgxPM60vSuc2f8JfiupLbY12BlglGWE5oSdznFWndKK5u8enI+KdrtEtNXrVbZ38vWitPxA"
    "bonVwK+oK4zTNC1ZB00LHGPasCRv8jSDsu1YkRRJV7CibNMc8iYpadZhCV2TZywDzIHHv3W171sL6rXA5yPclo3efBic9+EnajNv"
    "6PI4ohH1rpqaQZiLg5y/Tu+TizR226w2VmokxrpH4gSU8Aj0ONq6EwNuzX/GqhciUnfPS93DuOfHaRh8GZjaXMU8ndUTLh6X02iN"
    "cx5ObW1OxkevJ7ETLdj54+kqjZyGnVyKZ+3k8/D8AVBLAQIUAxQAAAAIAKNl+FxYc4jOAQEAAJ4BAAALAAAAAAAAAAAAAACAAQAA"
    "AAByYXBwaWQuanNvblBLAQIUAxQAAAAIAKNl+FxpIsN+ohkAAMRrAAAfAAAAAAAAAAAAAACAASoBAABhZ2VudHMvcHJvamVjdF90"
    "cmFja2VyX2FnZW50LnB5UEsBAhQDFAAAAAgAo2X4XItNIjbJNQAAEDYBACIAAAAAAAAAAAAAAIABCRsAAHJhcHBfdWkvcHJvamVj"
    "dF90cmFja2VyL2luZGV4Lmh0bWxQSwECFAMUAAAACACjZfhcRsLlIzUBAAAtAgAADQAAAAAAAAAAAAAAgAESUQAAbWFuaWZlc3Qu"
    "anNvblBLBQYAAAAABAAEABEBAAByUgAAAAA="
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


class ProjectTrackerHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "ProjectTrackerHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the project_tracker rapplication. It self-installs when "
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
                    "summary": "Project Tracker is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
