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
    api/v1/egg/<id>.egg                    — pre-built rapplication .egg cartridge
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

import argparse
import copy
import hashlib
import json
import re
import os
import shutil
import sys
import subprocess
import datetime
import time
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


def _app_iso(app_dir) -> str:
    """Deterministic timestamp for an app: its last git commit date (UTC).

    Wall-clock stamps inside egg bytes made every producer run rewrite every
    egg — and every egg sha256 pin with it. An egg's bytes must be a pure
    function of its app directory, so identical inputs build identical eggs.
    Uses a fixed sentinel when no git commit date is available."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", str(app_dir)],
            capture_output=True, text=True, cwd=str(_REPO), timeout=20,
        ).stdout.strip()
        if out:
            return time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(datetime.datetime.fromisoformat(out).timestamp()),
            )
    except Exception:
        pass
    return "2020-01-01T00:00:00Z"   # fixed sentinel: deterministic outside git


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
# Pack locally available rapplications using the accepted RAPP/1 section 9
# container. Nested UI/organ paths follow the reference egg_repack mapping;
# only the singleton moves to the required root agent.py.

def _build_egg(app_dir: Path, manifest: dict) -> bytes:
    """Build an unsigned rapp/1-egg rapplication from an app dir."""
    _refuse_partial_application(manifest)
    from rapp_egg import pack_rapplication

    rapp_id = manifest["id"]
    publisher = manifest.get("publisher", "@anon")
    name = manifest.get("name", rapp_id)
    version = manifest.get("version", "0.0.0")
    # §6.2 canonical rappid: rappid:@<owner>/<slug>:<64hex>. The 64-hex tail
    # content-addresses the rapplication's source (its singleton agent files) via
    # Hb("rapp/1:rappid", sha256(content)) — domain-separated, DETERMINISTIC and
    # regenerable, NOT sha256(publisher/rapp_id) (the cardinal sin), and 64-hex.
    _srcs = sorted((app_dir / "singleton").glob("*.py")) if (app_dir / "singleton").is_dir() else []
    _content = b"".join(p.read_bytes() for p in _srcs) or f"{publisher}/{rapp_id}".encode()
    _owner = re.sub(r"[^a-z0-9]+", "-", publisher.lstrip("@").lower()).strip("-") or "anon"
    _slug = re.sub(r"[^a-z0-9]+", "-", rapp_id.lower()).strip("-") or "x"
    rappid_hash = hashlib.sha256(b"rapp/1:rappid\n" + hashlib.sha256(_content).digest()).hexdigest()
    rappid = f"rappid:@{_owner}/{_slug}:{rappid_hash}"

    if not _srcs:
        raise ValueError(f"E_EGG_AGENT: {rapp_id} has no local singleton for root agent.py")
    stamp = _app_iso(app_dir)
    counts = {"agent": 1, "ui": 0, "data": 0, "soul": 0, "organ": 0}
    identity = {
        "schema": "rapp/1",
        "rappid": rappid,
        "parent_rappid": "rappid:@kody-w/rapp:9a8f0a4b5a710e20f4d819a0f37d2a4c9f113b5e78fb3c29e70b54fff48a38f9",
        "kind": "rapplication",
        "name": name,
        "version": version,
        "publisher": publisher,
        "rapp_id": rapp_id,
        "born_at": stamp,
    }
    files = {
        "rappid.json": json.dumps(identity, indent=2).encode("utf-8"),
        "agent.py": _srcs[0].read_bytes(),
    }
    organ_dir = app_dir / "organs"
    organ_filename = None
    if organ_dir.is_dir():
        for f in sorted(organ_dir.iterdir()):
            if f.suffix == ".py" and f.name != "__init__.py":
                files[f"organs/{f.name}"] = f.read_bytes()
                organ_filename = f.name
                counts["organ"] += 1
                break

    ui_dir = app_dir / "ui"
    if ui_dir.is_dir():
        for f in ui_dir.rglob("*"):
            if f.is_file():
                rel = f.relative_to(ui_dir).as_posix()
                files[f"rapp_ui/{rapp_id}/{rel}"] = f.read_bytes()
                counts["ui"] += 1

    payload = {
        "rapp_id": rapp_id,
        "name": name,
        "version": version,
        "publisher": publisher,
        "host": "rapp_store-static-api",
        "agent_filename": _srcs[0].name,
        "organ_filename": organ_filename,
        "has_skin": counts["ui"] > 0,
        "counts": counts,
    }
    return pack_rapplication(rappid, stamp[:-1] + ".000Z", files, payload)


# ── Per-rapp Pokédex entry ─────────────────────────────────────────────────

def _build_entry(app_dir: Path, manifest: dict) -> dict:
    """Build the static-API JSON entry for one rapplication.

    Per Article XXXVII (Rapplications Are Organisms), every catalog entry
    is a rapplication — same kind of organism, same egg distribution unit.
    Some have install_one_liner because they run as their own process
    today; that's a runtime detail, not a category. The catalog treats
    them all the same.
    """
    _refuse_partial_application(manifest)
    rapp_id = manifest["id"]
    publisher = manifest.get("publisher", "@anon")
    # §6.2 canonical rappid: rappid:@<owner>/<slug>:<64hex>. The 64-hex tail
    # content-addresses the rapplication's source (its singleton agent files) via
    # Hb("rapp/1:rappid", sha256(content)) — domain-separated, DETERMINISTIC and
    # regenerable, NOT sha256(publisher/rapp_id) (the cardinal sin), and 64-hex.
    _srcs = sorted((app_dir / "singleton").glob("*.py")) if (app_dir / "singleton").is_dir() else []
    _content = b"".join(p.read_bytes() for p in _srcs) or f"{publisher}/{rapp_id}".encode()
    _owner = re.sub(r"[^a-z0-9]+", "-", publisher.lstrip("@").lower()).strip("-") or "anon"
    _slug = re.sub(r"[^a-z0-9]+", "-", rapp_id.lower()).strip("-") or "x"
    rappid_hash = hashlib.sha256(b"rapp/1:rappid\n" + hashlib.sha256(_content).digest()).hexdigest()
    rappid = f"rappid:@{_owner}/{_slug}:{rappid_hash}"

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
        # Per Article XXXVII the catalog defines exactly one frozen artifact
        # kind. The index listing already stamps it (via e.get('kind', ...));
        # carry it on the detail record too so both stay aligned.
        "kind": manifest.get("kind", "rapplication"),
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
        "parent_rappid": "rappid:@kody-w/rapp:9a8f0a4b5a710e20f4d819a0f37d2a4c9f113b5e78fb3c29e70b54fff48a38f9",

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

def _refuse_partial_application(manifest):
    if (manifest.get("schema") == "rapp-application/2.0"
            or "local_docker" in manifest or manifest.get("requires")):
        raise ValueError("E_APPLICATION_SCOPED: mandatory-feature applications require a complete "
                         "verified package; use scoped --application-only discovery, not legacy eggs")


def _build_application_entry(entry):
    """Project an approved complete contract without inventing install artifacts."""
    import lib_rapp

    manifest = entry.get("application")
    errors = lib_rapp._validate_manifest(manifest)
    if not lib_rapp.is_application(manifest) or errors:
        raise ValueError("E_APPLICATION_DISCOVERY: " + "; ".join(errors or ["complete manifest missing"]))
    for key in ("id", "publisher", "version", "runtime", "requires"):
        if entry.get(key) != manifest[key]:
            raise ValueError("E_APPLICATION_DISCOVERY: catalog and application disagree on " + key)
    fields = (
        "id", "name", "version", "publisher", "category", "tags", "summary", "tagline",
        "quality_tier", "license", "homepage", "source", "application_url",
        "application_schema", "application", "runtime", "requires",
    )
    projected = {key: copy.deepcopy(entry[key]) for key in fields if key in entry}
    projected.update({
        "schema": SCHEMA_API_RAPP,
        "kind": "rapplication",
        "distribution": "local-docker" if "local-docker/1" in manifest["requires"] else "application",
        "application_schema": "rapp-application/2.0",
        "has_skin": bool(manifest.get("ui")),
        "installable": False,
        "self_url": f"{RAW_PREFIX}/api/v1/rapplication/{manifest['id']}.json",
    })
    if "local_docker" in manifest:
        projected["local_docker"] = copy.deepcopy(manifest["local_docker"])
        projected["readiness"] = copy.deepcopy(manifest["local_docker"]["readiness"])
    # This is metadata-only projection. Complete artifact publication, including
    # byte verification, belongs to the package/hatcher producer.
    projected["install_blockers"] = [
        "Discovery is metadata only; complete reviewed installer publication and device checks are required."
    ]
    return projected


def application_discovery_updates(catalog, api_dir, ids):
    """Preflight every requested rich-app row before returning any scoped writes."""
    api_dir = Path(api_dir)
    requested = sorted(set(ids))
    if not requested:
        raise ValueError("E_APPLICATION_DISCOVERY_IDS: explicit application IDs are required")
    entries = {}
    for rapp_id in requested:
        matches = [entry for entry in catalog.get("rapplications", []) if entry.get("id") == rapp_id]
        if len(matches) != 1:
            raise ValueError("E_APPLICATION_DISCOVERY_ID: expected one approved catalog row")
        entries[rapp_id] = _build_application_entry(matches[0])
    index_path = api_dir / "index.json"
    if index_path.is_file():
        index = json.loads(index_path.read_text())
        if index.get("schema") != SCHEMA_API_INDEX or not isinstance(index.get("rapplications"), list):
            raise ValueError("E_APPLICATION_DISCOVERY_INDEX: unsupported existing v1 index")
    else:
        index = {"schema": SCHEMA_API_INDEX, "name": "RAPP_Store Pokédex API",
                 "version": "1.0.0", "self_url": f"{RAW_PREFIX}/api/v1/index.json",
                 "rapplications": []}
    rows = list(index["rapplications"])
    updates = {}
    for rapp_id, entry in entries.items():
        row = copy.deepcopy(entry)
        row.pop("self_url")
        row["url"] = entry["self_url"]
        positions = [i for i, old in enumerate(rows) if old.get("id") == rapp_id]
        if len(positions) > 1:
            raise ValueError("E_APPLICATION_DISCOVERY_DUPLICATE: duplicate existing v1 ID")
        if positions:
            rows[positions[0]] = row
        else:
            rows.append(row)
        updates[api_dir / "rapplication" / f"{rapp_id}.json"] = (
            json.dumps(entry, indent=2) + "\n").encode()
    index["rapplications"] = rows
    index["count"] = len(rows)
    updates[index_path] = (json.dumps(index, indent=2) + "\n").encode()
    return updates


def refresh_application_discovery(catalog, api_dir, ids):
    return write_native_discovery(application_discovery_updates(catalog, api_dir, ids))


def _build_native_entry(entry):
    """Project reviewed federation metadata, never invent an organism or archive."""
    import lib_desktop

    source = entry.get("source")
    if (not isinstance(source, dict) or source.get("type") != "federation"
            or not isinstance(source.get("repo"), str)
            or not lib_desktop.REPO_RE.fullmatch(source["repo"])
            or not isinstance(source.get("commit_sha"), str)
            or not lib_desktop.COMMIT_RE.fullmatch(source["commit_sha"])):
        raise ValueError("E_DESKTOP_DISCOVERY_SOURCE: native discovery requires commit-pinned federation")
    errors = lib_desktop.validate_metadata(entry, repo=source.get("repo"))
    if "desktop" not in entry or errors:
        raise ValueError("E_DESKTOP_DISCOVERY: " + "; ".join(errors or ["desktop metadata missing"]))
    fields = (
        "id", "name", "version", "publisher", "category", "tags", "summary",
        "tagline", "description", "quality_tier", "license", "homepage",
        "desktop", "source", "singleton_filename", "singleton_url",
        "singleton_sha256", "singleton_bytes", "singleton_lines",
        "ui_url", "ui_sha256", "ui_bytes", "service_url", "service_sha256",
    )
    projected = {key: copy.deepcopy(entry[key]) for key in fields if key in entry}
    projected.update({
        "schema": SCHEMA_API_RAPP,
        "kind": "rapplication",
        "distribution": "desktop",
        "has_skin": bool(entry.get("ui_url")),
        "self_url": f"{RAW_PREFIX}/api/v1/rapplication/{entry['id']}.json",
        "github_url": f"https://github.com/{source['repo']}/tree/{source['commit_sha']}",
    })
    return projected


def native_discovery_updates(catalog, api_dir, ids):
    """Return only scoped v1 JSON changes; no network, clocks, eggs or hatchers."""
    api_dir = Path(api_dir)
    requested = sorted(set(ids))
    if not requested:
        raise ValueError("E_DESKTOP_DISCOVERY_IDS: explicit native IDs are required")
    native_entries = {}
    for rapp_id in requested:
        matches = [e for e in catalog.get("rapplications", []) if e.get("id") == rapp_id]
        if len(matches) != 1:
            raise ValueError(f"E_DESKTOP_DISCOVERY_ID: expected exactly one catalog entry for {rapp_id!r}")
        native_entries[rapp_id] = _build_native_entry(matches[0])
    index_path = api_dir / "index.json"
    if index_path.is_file():
        index = json.loads(index_path.read_text())
        if index.get("schema") != SCHEMA_API_INDEX or not isinstance(index.get("rapplications"), list):
            raise ValueError("E_DESKTOP_DISCOVERY_INDEX: unsupported existing v1 index")
    else:
        index = {
            "schema": SCHEMA_API_INDEX,
            "name": "RAPP_Store Pokédex API",
            "version": "1.0.0",
            "self_url": f"{RAW_PREFIX}/api/v1/index.json",
            "rapplications": [],
        }
    rows = list(index["rapplications"])
    updates = {}
    for rapp_id, entry in native_entries.items():
        row = {key: copy.deepcopy(entry[key]) for key in (
            "id", "name", "kind", "publisher", "category", "version",
            "has_skin", "distribution", "desktop",
        ) if key in entry}
        row["url"] = entry["self_url"]
        positions = [i for i, old in enumerate(rows) if old.get("id") == rapp_id]
        if len(positions) > 1:
            raise ValueError("E_DESKTOP_DISCOVERY_DUPLICATE: duplicate existing v1 ID")
        if positions:
            rows[positions[0]] = row
        else:
            rows.append(row)
        updates[api_dir / "rapplication" / f"{rapp_id}.json"] = (
            json.dumps(entry, indent=2) + "\n"
        ).encode()
    index["rapplications"] = rows
    index["count"] = len(rows)
    updates[index_path] = (json.dumps(index, indent=2) + "\n").encode()
    return updates


def write_native_discovery(updates):
    changed = []
    for path, data in updates.items():
        if path.is_file() and path.read_bytes() == data:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        changed.append(path)
    return changed


def refresh_native_discovery(catalog, api_dir, ids):
    return write_native_discovery(native_discovery_updates(catalog, api_dir, ids))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-only", action="store_true",
                        help="Only project specified native IDs from the approved catalog; no legacy producers")
    parser.add_argument("--application-only", action="store_true",
                        help="Project complete application contracts only; no partial eggs or source installers")
    parser.add_argument("--ids", nargs="+", help="Explicit approved catalog IDs for scoped refresh")
    parser.add_argument("--catalog", type=Path, default=_REPO / "index.json")
    args = parser.parse_args(argv)
    if args.native_only and args.application_only:
        parser.error("choose one scoped distribution, not both")
    if args.application_only:
        if not args.ids:
            parser.error("--application-only requires --ids")
        catalog = json.loads(args.catalog.read_text())
        changed = refresh_application_discovery(catalog, _API, args.ids)
        print(f"Application metadata-only refresh: {len(changed)} v1 JSON file(s) changed")
        return
    if args.native_only:
        if not args.ids:
            parser.error("--native-only requires --ids")
        catalog = json.loads(args.catalog.read_text())
        changed = refresh_native_discovery(catalog, _API, args.ids)
        print(f"Native metadata-only refresh: {len(changed)} v1 JSON file(s) changed")
        return
    if args.ids:
        parser.error("--ids requires --native-only or --application-only (refusing an accidental full rebuild)")
    if not _APPS.is_dir():
        print(f"err: apps/ not found at {_APPS}", file=sys.stderr)
        sys.exit(1)

    # Legacy generation cannot strip mandatory features. Check before touching
    # existing discovery or immutable assets, even if a manifest is later skipped.
    for manifest_path in sorted(_APPS.glob("@*/*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text())
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(manifest, dict):
            _refuse_partial_application(manifest)
    if args.catalog.is_file():
        for entry in json.loads(args.catalog.read_text()).get("rapplications", []):
            _refuse_partial_application(entry.get("application", entry))

    # Existing full legacy rebuild behavior; rich/native updates use scoped paths.
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
            if "desktop" in manifest:
                print(f"  ! {rapp_id}: native releases are projected only from approved federation metadata",
                      file=sys.stderr)
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

            # Runtime/install hints stay in the catalog; locally available
            # singletons all use the canonical rapplication egg variant.
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
        "generated_at": _app_iso(_APPS),
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
    if args.catalog.is_file():
        catalog = json.loads(args.catalog.read_text())
        native_ids = [e["id"] for e in catalog.get("rapplications", []) if "desktop" in e]
        if native_ids:
            refresh_native_discovery(catalog, _API, native_ids)

    print()
    try:
        api_label = _API.relative_to(_REPO)
    except ValueError:
        api_label = _API
    print(f"  → wrote {len(entries)} rapplication(s) to {api_label}/")
    print(f"  → index: api/v1/index.json")


if __name__ == "__main__":
    main()
