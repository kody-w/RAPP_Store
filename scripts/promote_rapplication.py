#!/usr/bin/env python3
"""promote_rapplication.py — promote a staged submission to live catalog.

Triggered when a maintainer adds the `approved` label to a [RAPP] issue.
Reads staging/_pending.json for the matching issue, then:

  - bundle mode:    moves staging/<id>/ → <id>/, recomputes integrity from
                    the on-disk files, merges the index entry into index.json.
  - federation mode: re-validates the source repo (in case main moved),
                    re-resolves commit_sha, merges the entry into index.json.

In both cases, bumps `index.json.generated_at`, removes the pending record.
On success, prints a markdown comment with the live URLs.

Inputs:
  --event-path   Path to GITHUB_EVENT_PATH (the labeled-issue event)
  --staging-dir  staging/ root (default)
  --catalog      Path to index.json (default)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import lib_rapp


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STAGING = REPO_ROOT / "staging"
DEFAULT_CATALOG = REPO_ROOT / "index.json"


class PromoteError(Exception):
    pass


def find_pending(staging_dir: Path, issue_number: int) -> dict:
    pending_path = staging_dir / "_pending.json"
    if not pending_path.is_file():
        raise PromoteError(f"E_NO_PENDING: {pending_path} does not exist")
    pending = json.loads(pending_path.read_text())
    for item in pending.get("items", []):
        if item.get("issue") == issue_number:
            return item
    raise PromoteError(f"E_NO_PENDING_FOR_ISSUE: issue #{issue_number} not in {pending_path}")


def remove_pending(staging_dir: Path, issue_number: int) -> None:
    pending_path = staging_dir / "_pending.json"
    if not pending_path.is_file():
        return
    pending = json.loads(pending_path.read_text())
    pending["items"] = [p for p in pending.get("items", [])
                        if p.get("issue") != issue_number]
    pending_path.write_text(json.dumps(pending, indent=2))


def promote_bundle(item: dict, staging_dir: Path, repo_root: Path,
                    catalog_path: Path) -> tuple[dict, dict]:
    rapp_id = item["id"]
    # staged_dir was recorded relative to staging_dir.parent (= repo_root in
    # production). Resolve it against the same base.
    base = staging_dir.parent
    src = base / item["staged_dir"]
    if not src.is_dir():
        raise PromoteError(f"E_STAGED_MISSING: {src}")
    target = base / rapp_id
    if target.exists():
        previous_versions = repo_root / rapp_id / "versions"
        prev_manifest = (target / "manifest.json")
        if prev_manifest.is_file():
            try:
                prev = json.loads(prev_manifest.read_text())
                old_v = prev.get("version")
                if old_v:
                    snap = previous_versions / old_v
                    snap.mkdir(parents=True, exist_ok=True)
                    for keep in ("manifest.json",):
                        if (target / keep).is_file():
                            shutil.copy2(target / keep, snap / keep)
            except json.JSONDecodeError:
                pass
        shutil.rmtree(target)
    shutil.copytree(src, target)
    shutil.rmtree(src, ignore_errors=True)

    manifest = json.loads((target / "manifest.json").read_text())
    integrity = lib_rapp.compute_integrity(target, manifest)
    entry = lib_rapp.build_index_entry(manifest, integrity, rapp_id)
    return entry, manifest


def promote_federation(item: dict, catalog_path: Path) -> tuple[dict, dict]:
    src = item.get("entry", {}).get("source") or {}
    repo, ref, path = src.get("repo"), src.get("ref", "main"), src.get("path", "")
    if not repo:
        raise PromoteError("E_BAD_FEDERATION_SOURCE: source.repo missing in pending entry")
    result = lib_rapp.validate_federation(repo, ref=ref, path=path)
    if not result.ok:
        raise PromoteError(f"E_REVALIDATE_FAILED: {result.errors}")
    return result.index_entry, result.manifest


def update_catalog(catalog_path: Path, entry: dict) -> dict:
    if catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text())
    else:
        catalog = {
            "schema": "rapp-store/1.0",
            "name": "RAPPstore — official",
            "version": "1.0.0",
            "rapplications": [],
        }
    out = lib_rapp.merge_index_entry(catalog, entry)
    out["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    catalog_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return out


def promote(event: dict, staging_dir: Path, catalog_path: Path) -> tuple[bool, str]:
    issue = event.get("issue", {})
    issue_number = issue.get("number")
    try:
        item = find_pending(staging_dir, issue_number)
    except PromoteError as e:
        return False, f"## ❌ Promotion failed\n\n`{e}`\n"

    try:
        if item["mode"] == "bundle":
            entry, manifest = promote_bundle(item, staging_dir, staging_dir.parent, catalog_path)
        elif item["mode"] == "federation":
            entry, manifest = promote_federation(item, catalog_path)
        else:
            return False, f"## ❌ Promotion failed\n\n`E_UNKNOWN_MODE: {item.get('mode')!r}`\n"
    except PromoteError as e:
        return False, f"## ❌ Promotion failed\n\n`{e}`\n"

    update_catalog(catalog_path, entry)
    remove_pending(staging_dir, issue_number)

    return True, _md_promotion(item, entry, manifest)


def _md_promotion(item, entry, manifest):
    mode = item["mode"]
    head = "## ✅ Approved and promoted\n\n"
    if mode == "bundle":
        head += (f"- **mode:** bundle (files now live in `{manifest['id']}/`)\n")
    else:
        src = entry.get("source", {})
        head += (f"- **mode:** federation (catalog points at "
                 f"`{src.get('repo')}@{src.get('ref')}` "
                 f"commit `{(src.get('commit_sha') or '')[:8]}`)\n")
    head += (f"- **id:** `{manifest['id']}`\n"
             f"- **version:** `{manifest['version']}`\n"
             f"- **publisher:** `{manifest['publisher']}`\n"
             f"- **singleton_url:** {entry.get('singleton_url')}\n\n"
             f"Catalog updated. The brainstem's binder service will pick up "
             f"the new entry on next `catalog` action.\n")
    return head


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--event-path", required=True)
    p.add_argument("--staging-dir", default=str(DEFAULT_STAGING))
    p.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    args = p.parse_args(argv)

    event = json.loads(Path(args.event_path).read_text())
    ok, report = promote(event, Path(args.staging_dir), Path(args.catalog))
    sys.stdout.write(report)
    sys.stdout.flush()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
