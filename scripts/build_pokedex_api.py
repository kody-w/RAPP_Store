#!/usr/bin/env python3
"""
build_pokedex_api.py — generate the static rapp_store Pokédex API.

Modeled on https://pokeapi.co/ — the catalog is a tree of static JSON
files at predictable URLs, served from raw.githubusercontent.com. No
backend, no auth, no database. Edit the manifests, push to main, the
API "deploys."

URL shape (relative to repo root, all under api/v1/):

    api/v1/index.json                       — paginated list + counts
    api/v1/rapplication/                    — directory listing (auto by GitHub)
    api/v1/rapplication/<id>.json           — single rapplication entry
    api/v1/rapplication/<id>.egg            — pre-built rapplication .egg cartridge
    api/v1/sprite/<id>.svg                  — deterministic generative sprite

Each <id>.json carries everything a Pokédex card needs: name, types,
description, lineage (parent_rappid), stats (skin? bytes? llm_calls?),
URLs to the egg + sprite + singleton + UI bundle.

Inputs (read from apps/@<publisher>/<id>/):
    manifest.json       — required, the source of truth for id/name/etc
    singleton/<file>.py — the bare singleton agent (always)
    ui/index.html       — optional skin (UI bundle); if present → has_skin=true
    eggs/*.egg          — optional pre-built example state cartridges
    source/             — optional source dir (for transparency, not packed)

Output (written to api/v1/):
    Atomic — old files get cleaned, new files get written together.
    Run via: python3 scripts/build_pokedex_api.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_APPS = _REPO / "apps"
_API = _REPO / "api" / "v1"


SCHEMA_API_INDEX = "rapp-pokedex-api/1.0"
SCHEMA_API_RAPP = "rapp-pokedex-rapp/1.0"

# Public URL prefix used in generated entries. Hosted on raw.githubusercontent.com
# so any HTTP client (curl, browser, fetch, the rapp-zoo Discover tab) can read.
RAW_PREFIX = "https://raw.githubusercontent.com/kody-w/RAPP_Store/main"


def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:32]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Sprite generator ───────────────────────────────────────────────────────
# Same algorithm the rapp-zoo UI uses client-side, but baked into a static
# SVG file so the catalog page can render the sprite without JS. 6×6 grid,
# left-right symmetric, deterministic from rappid hash. Pure SVG, no deps.

PALETTES = {
    "creative":   ["#b58ddf", "#a78bfa", "#8250df"],
    "work":       ["#ffa657", "#f78166", "#bc4c00"],
    "productivity": ["#79c0ff", "#58a6ff", "#0969da"],
    "reflection": ["#7df0c8", "#3fb950", "#1a7f37"],
    "default":    ["#58a6ff", "#79c0ff", "#0969da"],
}


def _sprite_svg(rappid_or_id: str, category: str = "default") -> str:
    h = abs(int(hashlib.sha256(rappid_or_id.encode()).hexdigest()[:8], 16))
    palette = PALETTES.get(category, PALETTES["default"])
    fg = palette[h % 3]
    bg = palette[(h >> 4) % 3]
    rects = []
    for y in range(6):
        for x in range(3):
            bit = (h >> ((y * 3 + x) % 28)) & 1
            if bit:
                rects.append(f'<rect x="{x*8}" y="{y*8}" width="8" height="8" fill="{fg}"/>')
                rects.append(f'<rect x="{(5-x)*8}" y="{y*8}" width="8" height="8" fill="{fg}"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="192" height="192" shape-rendering="crispEdges">\n'
        f'  <rect width="48" height="48" fill="{bg}" opacity="0.25"/>\n'
        + "  " + "\n  ".join(rects) + "\n"
        '</svg>\n'
    )


# ── Egg builder ────────────────────────────────────────────────────────────
# Pack a rapplication's singleton + UI + (optional) state into a portable
# .egg under the brainstem-egg/2.2-rapplication schema. Standalone — does
# not depend on bond.py being installed; we inline the small subset of the
# format we need (single-rapp, no soul, no per-rapp organ for v1).

def _build_egg(app_dir: Path, manifest: dict) -> bytes:
    """Build a brainstem-egg/2.2-rapplication blob from an app dir."""
    rapp_id = manifest["id"]
    publisher = manifest.get("publisher", "@anon")
    name = manifest.get("name", rapp_id)
    version = manifest.get("version", "0.0.0")
    rappid_hash = _short_hash(f"{publisher}/{rapp_id}")
    rappid = f"rappid:v2:rapplication:{publisher}/{rapp_id}:{rappid_hash}"

    counts = {"agent": 0, "ui": 0, "data": 0, "soul": 0, "organ": 0}
    import io
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # rappid.json
        identity = {
            "schema": "rapp-rappid/2.0",
            "rappid": rappid,
            "parent_rappid": "rappid:v2:prototype:@rapp/origin:0b635450c04249fbb4b1bdb571044dec@github.com/kody-w/RAPP",
            "kind": "rapplication",
            "name": name,
            "version": version,
            "publisher": publisher,
            "rapp_id": rapp_id,
            "born_at": _now_iso(),
        }
        z.writestr("rappid.json", json.dumps(identity, indent=2))

        # The singleton agent (one per rapp — the chat face)
        singleton_dir = app_dir / "singleton"
        agent_filename = None
        if singleton_dir.is_dir():
            for f in sorted(singleton_dir.iterdir()):
                if f.suffix == ".py":
                    z.writestr(f"agents/{f.name}", f.read_bytes())
                    agent_filename = f.name
                    counts["agent"] += 1
                    break  # one singleton per rapp

        # The organ (one per rapp — the HTTP backplane that serves the UI).
        # Lifted into the egg under organs/<file>; the brainstem unpacker
        # places it at utils/organs/<file>, which the kernel autodiscovers.
        organ_dir = app_dir / "organs"
        organ_filename = None
        if organ_dir.is_dir():
            for f in sorted(organ_dir.iterdir()):
                if f.suffix == ".py" and f.name != "__init__.py":
                    z.writestr(f"organs/{f.name}", f.read_bytes())
                    organ_filename = f.name
                    counts["organ"] += 1
                    break  # one organ per rapp (matches the agent-first contract)

        # UI bundle (skin)
        ui_dir = app_dir / "ui"
        if ui_dir.is_dir():
            for f in ui_dir.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(ui_dir).as_posix()
                    z.writestr(f"rapp_ui/{rapp_id}/{rel}", f.read_bytes())
                    counts["ui"] += 1

        # Manifest
        api_manifest = {
            "schema": "brainstem-egg/2.2-rapplication",
            "type": "rapplication",
            "exported_at": _now_iso(),
            "rappid": rappid,
            "rapp_id": rapp_id,
            "name": name,
            "version": version,
            "publisher": publisher,
            "host": "rapp_store-static-api",
            "agent_filename": agent_filename,
            "organ_filename": organ_filename,
            "has_skin": counts["ui"] > 0,
            "counts": counts,
        }
        z.writestr("manifest.json", json.dumps(api_manifest, indent=2))

    return buf.getvalue()


# ── Per-rapp Pokédex entry ─────────────────────────────────────────────────

def _build_entry(app_dir: Path, manifest: dict) -> dict:
    """Build the static-API JSON entry for one rapplication.

    Per Article XXXVII (Rapplications Are Organisms), every catalog entry
    is a rapplication — same kind of organism, same egg distribution unit.
    Some have install_one_liner because they run as their own process
    today; that's a runtime detail, not a category. The catalog treats
    them all the same.
    """
    rapp_id = manifest["id"]
    publisher = manifest.get("publisher", "@anon")
    rappid_hash = _short_hash(f"{publisher}/{rapp_id}")
    rappid = f"rappid:v2:rapplication:{publisher}/{rapp_id}:{rappid_hash}"

    has_skin = (app_dir / "ui" / "index.html").is_file()
    singleton_files = sorted((app_dir / "singleton").glob("*.py")) if (app_dir / "singleton").is_dir() else []
    singleton_filename = singleton_files[0].name if singleton_files else None
    singleton_bytes = singleton_files[0].stat().st_size if singleton_files else 0

    # Compute sha256 of singleton for verification
    singleton_sha = ""
    if singleton_files:
        singleton_sha = hashlib.sha256(singleton_files[0].read_bytes()).hexdigest()

    rel_dir = app_dir.relative_to(_REPO).as_posix()

    entry = {
        "schema": SCHEMA_API_RAPP,
        "id": rapp_id,
        "name": manifest.get("name", rapp_id),
        "rappid": rappid,
        "version": manifest.get("version", "0.0.0"),
        "publisher": publisher,
        "category": manifest.get("category"),
        "tags": manifest.get("tags", []),
        "summary": manifest.get("summary"),
        "tagline": manifest.get("tagline"),
        "description": manifest.get("description"),
        "quality_tier": manifest.get("quality_tier", "community"),
        "license": manifest.get("license"),
        "homepage": manifest.get("homepage"),
        "repo_url": manifest.get("repo_url"),
        "spec_post": manifest.get("spec_post"),

        # Lineage (organism unification — every entry has a parent rappid)
        "parent_rappid": "rappid:v2:prototype:@rapp/origin:0b635450c04249fbb4b1bdb571044dec@github.com/kody-w/RAPP",

        # Pokédex stats
        "has_skin": has_skin,
        "singleton_lines": (singleton_files[0].read_text().count("\n") if singleton_files else 0),
        "singleton_bytes": singleton_bytes,
        "singleton_sha256": singleton_sha,

        # Optional install hints — present for any rapp that needs more
        # than just dropping the singleton .py into agents/. Today only
        # rapp-zoo uses these; nothing in the consumer model special-
        # cases them. Pure metadata.
        "install_one_liner": manifest.get("install_one_liner"),
        "default_port":      manifest.get("default_port"),

        # Asset URLs (static — published at predictable URLs)
        "sprite_url":     f"{RAW_PREFIX}/api/v1/sprite/{rapp_id}.svg",
        "egg_url":        f"{RAW_PREFIX}/api/v1/egg/{rapp_id}.egg",
        "singleton_url":  f"{RAW_PREFIX}/{rel_dir}/singleton/{singleton_filename}" if singleton_filename else None,
        "ui_url":         f"{RAW_PREFIX}/{rel_dir}/ui/index.html" if has_skin else None,

        # Self-reference + browse-back
        "self_url":       f"{RAW_PREFIX}/api/v1/rapplication/{rapp_id}.json",
        "github_url":     f"https://github.com/kody-w/RAPP_Store/tree/main/{rel_dir}",
    }
    return entry


# ── Main build ─────────────────────────────────────────────────────────────

def main():
    if not _APPS.is_dir():
        print(f"err: apps/ not found at {_APPS}", file=sys.stderr)
        sys.exit(1)

    # Reset api/v1/ for atomic rebuild
    if _API.exists():
        shutil.rmtree(_API)
    (_API / "rapplication").mkdir(parents=True)
    (_API / "sprite").mkdir(parents=True)
    (_API / "egg").mkdir(parents=True)

    entries = []
    for pub_dir in sorted(_APPS.iterdir()):
        if not pub_dir.is_dir() or not pub_dir.name.startswith("@"):
            continue
        for app_dir in sorted(pub_dir.iterdir()):
            if not app_dir.is_dir():
                continue
            manifest_path = app_dir / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
            except Exception as e:
                print(f"  ! skipping {app_dir.relative_to(_REPO)}: bad manifest ({e})", file=sys.stderr)
                continue

            rapp_id = manifest.get("id")
            if not rapp_id:
                print(f"  ! skipping {app_dir.relative_to(_REPO)}: no id", file=sys.stderr)
                continue

            entry = _build_entry(app_dir, manifest)
            entries.append(entry)

            # Write per-rapp JSON
            (_API / "rapplication" / f"{rapp_id}.json").write_text(
                json.dumps(entry, indent=2) + "\n"
            )

            # Write sprite SVG
            sprite = _sprite_svg(entry["rappid"], entry.get("category") or "default")
            (_API / "sprite" / f"{rapp_id}.svg").write_text(sprite)

            # Build & write egg — every entry packs as a 2.2-rapplication
            # egg. Per Article XXXVII, every catalog entry IS a rapplication;
            # there's no separate tool/rapp distinction. Some rapps run as
            # their own process today (e.g. rapp-zoo's full local mode);
            # the install_one_liner field tells consumers how to launch
            # those, but the egg itself is the same shape as everything else.
            try:
                egg_blob = _build_egg(app_dir, manifest)
                (_API / "egg" / f"{rapp_id}.egg").write_bytes(egg_blob)
                entry["egg_bytes"] = len(egg_blob)
            except Exception as e:
                print(f"  ! egg build failed for {rapp_id}: {e}", file=sys.stderr)
                entry["egg_url"] = None
                entry["egg_bytes"] = 0

            # Re-write the per-entry JSON to capture the final egg_url state
            (_API / "rapplication" / f"{rapp_id}.json").write_text(
                json.dumps(entry, indent=2) + "\n"
            )

            print(f"  ✓ {entry['publisher']}/{rapp_id} v{entry['version']:<8}  "
                  f"skin={entry['has_skin']!s:<5}  "
                  f"egg={entry.get('egg_bytes', 0):>5} bytes")

    # Top-level index — a paginated listing modeled after PokeAPI's /pokemon/
    index = {
        "schema": SCHEMA_API_INDEX,
        "name": "RAPP_Store Pokédex API",
        "description": (
            "Static catalog API for cataloged rapplications. PokeAPI-style: "
            "predictable JSON URLs hosted via raw.githubusercontent.com, no "
            "backend. Each rapplication is browsable as an organism — sprite, "
            "lineage, stats, downloadable .egg cartridge. Updated by pushing "
            "to main; the rebuild is a static script (scripts/build_pokedex_api.py)."
        ),
        "version": "1.0.0",
        "generated_at": _now_iso(),
        "count": len(entries),
        "self_url":      f"{RAW_PREFIX}/api/v1/index.json",
        "rapplications": [
            {
                "id":        e["id"],
                "name":      e["name"],
                "kind":      e.get("kind", "rapplication"),
                "publisher": e["publisher"],
                "category":  e["category"],
                "version":   e["version"],
                "has_skin":  e["has_skin"],
                "url":       e["self_url"],
                "sprite":    e["sprite_url"],
                "egg":       e["egg_url"],
                "install_one_liner": e.get("install_one_liner"),
            }
            for e in entries
        ],
    }
    (_API / "index.json").write_text(json.dumps(index, indent=2) + "\n")

    print()
    print(f"  → wrote {len(entries)} rapplication(s) to {_API.relative_to(_REPO)}/")
    print(f"  → index: api/v1/index.json")


if __name__ == "__main__":
    main()
