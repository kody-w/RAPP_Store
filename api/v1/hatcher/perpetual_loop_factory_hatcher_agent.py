"""perpetual_loop_factory — drop-in hatcher for the `perpetual_loop_factory` rapplication.

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

Published by @rapp · rapplication v1.0.0 · egg sha256 63d5391df190…
Source: https://kody-w.github.io/RAPP_Store/#rapp=perpetual_loop_factory
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
    "name": "@rapp/perpetual_loop_factory_hatcher",
    "version": "1.0.0",
    "display_name": "perpetual_loop_factory (hatcher)",
    "description": "Drop-in installer for the perpetual_loop_factory rapplication — the egg is baked in; drop the file in agents/ and it self-installs.",
    "author": "@rapp",
    "tags": ["install", "hatcher", "egg", "rapplication", "drop-in"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "example_call": {"args": {}},
}

RAPP_ID = "perpetual_loop_factory"
EGG_SHA256 = "63d5391df1904e7a7576a23c15a2755a892f30900ab02e342e4e1c803541aba5"
EGG_SCHEMA = "brainstem-egg/2.2-rapplication"

# The rapplication, baked in.
EGG_B64 = (
    "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"
    "gVwBcbde6n9ptbZeIn5TTlf5iTnxt/UyITLqby3mMH+5Km8qL+PkDn+xrLM+YUij740CEmWnAfIph3wXU/29Px6G9fT3JhI2XnFU"
    "SevrNW/NX3+22Q2HYdT6uvt9b733/ebIi4j2tNY2J5Imt7XxbPJxk9tH1rzW+tPJx3llsD7T1Z5/573o9+0CL6i8aUWtqfUNrrBh"
    "Krzwv33x3bpdYZ0qAHsaSeSNY/Cz1pQoftT1Yn9z6OMG+gZGj9E01zf8kWl+Y23ykXpAh5fsNWtchkkSjlrUoorDYdBTX6/3N148"
    "TWdjCjzDmJqyxWdmps/QWklLoDp+1pQ1cp5ak7iSmVxv4/vvNzakyK2PPJety3DYo0JEamccQ9uK8HgzB415BQRmZi/O+ov1S2rJ"
    "jA3jsOYZeb1gGrd4LZq9YDQrNKdvXzGPn/Yvv3++Ro8lLnK8dPGevjCLbY1+E/y8MZAH6wb43wFa1KQ/miR3pYsL/GwFiUfEbl55"
    "uSr4+nJVsB5oS0g8WN/6v//7X/5bQQT9j3+3HK+C9VSw8rIX3CjmxG2HJk26JCnm+gL2LZ1RlYD18z/9n5erVDRfQU9dKpkfW1lZ"
    "GsvGlo5Y1LSfet3Y4jZQx3COLWjq+W6oWMGIVqibHfopr832cEL/rp+vh+clVSovJzk4MGjbjqxMIwknracb+V1L+ONsVTgxIl+I"
    "8hIIt2UL1S9X+RFgzzm42bAhxZJw2h2oEguVrkOLO8GgJHp+q9KfjiVwHvJFEIe1GfuXVdx23+CA5Ti8JcUIGVrwk0uAZ5yIkWp1"
    "fW1tbbMCxu3GL9dqwqFIurl1NvnRC/PMjX9aq604sX7+9MVa+saNV6kYvx45K/TzG/OTSmdluAo/Hjib84oX3427Kh0+4O7WEOBJ"
    "1HuKQ1YY5s6Qrz54dbfbcw321ZogYJpP07KFw6EsmIOJkAoqUaIChm7c9pAH1PUknSl8BW5OOvmh03ZWMlCRCAI5gbi61cqQdOZ2"
    "N9ZELP7pp9PzTe3bdPGuKRGuNROfKrVGbbwjQa1JMrIOq1ktiapZ1X3dM3Wzh/JzH/0wwjXvJBBKA3KsYWkjZlPVmgFt3wjMk0dI"
    "WnbQ9XHqYqNGw5y43faWHtCFvav1+d6tl8QgxuYh1ISt/zTrNllFIMzGyy2FJ5i18Qeunr7cOl+9qn9sb31st9vOSxr03w2TTafl"
    "/N0V/anNVa5ZWPypWSB1t4koH7gxdeOyMS8khkUCZUno/emn3GCZVDpbuVMKuuKmUaxcWadrJME5tQ8LCi04L6ynvtfnGuPPCqsf"
    "bNO3almBlGZZU5y0MKrfzmOks4LmV5wiOm5asrVLUmZ4XbOjoKW1pK3xmwrodGbNJApGeUNdTS904zv4aTF+37XaX4451zbGJIwi"
    "w/ZWCW4oUEhatuEnrLtelGwhsxGZYzrzLvbObP4YJC8nEj//2z/zBS7KWUlJIRUJofAMfRDDY878Y+DxcPM87334/s0z1JSRur5e"
    "o08e5b/SAP2mVhe5wcq8IqQRWkayq21/Lp7VSd5bgxoEhi/s4OUq83pibBB6f22x3DqiO/L53o0VSd+tBv5wgnToJpxbZxVEGdcE"
    "e5vbgXHYLpYQ/oVrt/mKv/fTmO8FawTxQHdEXcnVuLOZCTQDauIMFVIcmMu+xOpiOkxtL9d1daMv/6Wum6R9jXLmFqkGy4lBedLL"
    "8Lme46PjZG9q5iJC4NlEyfE7aDUysGaziVR4crFZH3dlNG0bCS6lnl66kXM2O5udeo0/bTf+oXO+cjY/49O49B8C89JbnUN99NON"
    "Sy4oN+mB9BGD22aXmCEExz8hsSWmfIv5Rub0bOScNqgvTIRTvNxm96OnYd0uf20xnzzF4pyX9mmp/FwhPXbwrPbrQ9Ny3O3rDNhi"
    "ozIoK7/Ksg380vO8ZW3+xc7vHvP+XOVlxf1wEFXxhy+b9LjdRjeMIlEFyo7+FK7y0oGdrqRpx4miWz4TJ/dyrZS1kMn6+u4BKhZe"
    "wnbgXQY4np/Z0AV7sbVK2hG7ZoPvyklzBHFuSiS9bwRjnQuf7+eG2wMXKZc1BCN+H5dIEL/GTQzszjBnVLLDKXHId0eUNgHjNy4T"
    "RHqxiQ6l5H6RPHHMt0PgcsEod5952ZzkVpk7vuxZiGnQkwufhzpnYpa/P7wdl06H9Bhf50fn+28IfDICYjfTya/i9LOEaObOGZtE"
    "fWneROCou/36ZPdg//gRxwELx48ZeD+hjZ+A5T8Jjv8E1rT8LHSWUKlsZJ86hGv/0rtswA6jXL951VTVYIzr3hO/MQn9UZXPqcvh"
    "Zl5VHvIqRrsqo73n0Haup18+1IOx30iTazI9kAvqwr5EvpqrPID+E74yji8zWhz+8iHnsr5+kUG/5Q2WXjExmia8T93IH+qrUsJ0"
    "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"
    "4zmeO8R9kySp42e4srRJ0pNlsncergi6bkcygiwzRknOvNR9uo20vxmI7N8T+DLaehCU+QgQTCqEDyiv3vC+IVVDyvcJjK1SLJdI"
    "0TxdtLihz50Ba8APTCGltUEt417bW3Ooy6IuSSnyHBOBi5rXLWMtKY4YeM0ZPpQFrkDsy7o4wIkIgqv9UZAWWiJEjn+tdNL+eGj0"
    "0NkzYT27jvu9LkzyEpjkec18gHVx7YDlGc5mgRlOSroz2FifV5pOztr5ZV3qwj2AnA8vxxEzckJYB72nrVSwDPD/kHQEMzNPom3H"
    "+nVbPyg1OZmj7iLjkN4OMNa4HnrvQuUe0iINMd9OeZCrIJiPnwLP0elBreIojjnEx+bxDVBLAQIUAxQAAAAIAEyz71zJXNMeDwEA"
    "ALMBAAALAAAAAAAAAAAAAACAAQAAAAByYXBwaWQuanNvblBLAQIUAxQAAAAIAEyz71z/dUoiN0EAAADaAAAmAAAAAAAAAAAAAACA"
    "ATgBAABhZ2VudHMvcGVycGV0dWFsX2xvb3BfZmFjdG9yeV9hZ2VudC5weVBLAQIUAxQAAAAIAEyz71zE3LpyFxgAAEdNAAApAAAA"
    "AAAAAAAAAACAAbNCAAByYXBwX3VpL3BlcnBldHVhbF9sb29wX2ZhY3RvcnkvaW5kZXguaHRtbFBLAQIUAxQAAAAIAEyz71zxJXCl"
    "QQEAAEkCAAANAAAAAAAAAAAAAACAARFbAABtYW5pZmVzdC5qc29uUEsFBgAAAAAEAAQAHwEAAH1cAAAAAA=="
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


class PerpetualLoopFactoryHatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "PerpetualLoopFactoryHatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Installer for the perpetual_loop_factory rapplication. It self-installs when "
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
                    "summary": "perpetual_loop_factory is installed in this brainstem. "
                               "Ask me again with force=true to re-install.",
                })
            return json.dumps(_hatch())
        except Exception as e:
            return json.dumps({"status": "error",
                               "summary": "%s: %s" % (type(e).__name__, e)})
