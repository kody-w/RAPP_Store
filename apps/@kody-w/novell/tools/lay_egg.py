#!/usr/bin/env python3
"""Lay `novell.rapp.egg` — Novell's personality in stasis.

The egg carries Novell's *state*, not his code. Per EGG_SPEC §"No executable
payloads", `body.content` MUST be declarative — so the egg holds the lens
catalogue, the PII policy and the calibration fixtures, and the store carries
the singleton. Hatch the egg into any brainstem that already has the agent and
you get this Novell: these lenses, these weights, this stance.

Run from the bundle root:  python3 tools/lay_egg.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent.parent
CREATED_AT = "2026-07-24T00:00:00Z"


def canonicalize(kind: str, content) -> bytes:
    """EGG_SPEC §7.3 — two engines must produce a bit-identical sha256."""
    if kind == "cartridge_xml":
        return content.encode("utf-8")
    if kind in ("state_json", "hybrid"):
        return json.dumps(content, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
    raise ValueError(f"unknown body.kind: {kind}")


def load_agent():
    """Import the singleton without a brainstem present."""
    shim = Path(tempfile.mkdtemp(prefix="novell-shim-"))
    (shim / "basic_agent.py").write_text(
        "class BasicAgent:\n"
        "    def __init__(self, name=None, metadata=None):\n"
        "        self.name = name; self.metadata = metadata\n"
    )
    sys.path.insert(0, str(shim))
    spec = importlib.util.spec_from_file_location(
        "novell_agent", BUNDLE / "singleton" / "novell_agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    mod = load_agent()
    manifest = json.loads((BUNDLE / "manifest.json").read_text())

    content = {
        "schema": "novell-state/1.0",
        "archetype": True,
        "models_real_person": False,
        "pii_policy": mod.PII_POLICY,
        "lens_count": len(mod.LENSES),
        "total_weight": sum(l["weight"] for l in mod.LENSES),
        "lenses": [
            {
                "id": l["id"],
                "name": l["name"],
                "barb": l["barb"],
                "asks": l["asks"],
                "killed_by": l["killed_by"],
                "weight": l["weight"],
                "answered": l["answered"],
                "provoked": l.get("provoked", []),
            }
            for l in mod.LENSES
        ],
        "default_threshold": 25,
        "score_bands": [
            {"min": 75, "reading": "He hasn't stopped talking. Nothing here is defended."},
            {"min": 50, "reading": "He's enjoying himself. Half your claims are undefended."},
            {"min": 25, "reading": "He got a few in. Fixable before anyone else reads this."},
            {"min": 1,  "reading": "He's bored. One or two loose threads."},
            {"min": 0,  "reading": "He has nothing. Suspicious — check you gave him a real artifact."},
        ],
        "calibration": {
            "note": "Fixtures the engine is tuned against. Contain no real "
                    "person, product claim, or customer reference.",
            "weak_expected_score": 100,
            "strong_expected_score": 8,
        },
    }

    kind = "state_json"
    blob = canonicalize(kind, content)
    egg = {
        "_format": "egg",
        "_schema_version": 1,
        "organism": {
            "slug": "novell",
            "species": "rapp",
            "instance": "novell",
            "scale": "daemon",
            "substrate": "cloud-brainstem",
            "name": "Novell",
            "tagline": "The hater you run before the real one shows up. "
                       "Twelve skeptic lenses, each with the evidence that kills it.",
            "population": "1 rapp daemon (novell) — an archetype, not a person",
        },
        "body": {
            "kind": kind,
            "filename": "novell.rapp.state.json",
            "content": content,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "size_bytes": len(blob),
        },
        "lineage": {
            "created_at": CREATED_AT,
            "created_by": "kody-w",
            "engine_version": "rapp-egg-v1",
            "parent_egg_sha256": None,
            "birth_tick": None,
        },
        "validation": {"ok": True, "issues": []},
    }

    out = BUNDLE / "eggs" / "novell.rapp.egg"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(egg, indent=2, ensure_ascii=False) + "\n")
    print(f"laid {out.relative_to(BUNDLE)}")
    print(f"  sha256     {egg['body']['sha256']}")
    print(f"  size_bytes {egg['body']['size_bytes']}")
    print(f"  lenses     {content['lens_count']}")
    print(f"  manifest   {manifest['id']} v{manifest['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
