#!/usr/bin/env python3
"""Prepare a staged submission's catalog changes for an owner-reviewed PR.

Triggered when a maintainer adds the `approved` label to a [RAPP] issue.
Reads staging/_pending.json for the matching issue, then:

  - bundle mode:    copies staging/<id>/ → apps/@publisher/<id>/, recomputes integrity from
                    the on-disk files, merges the index entry into index.json.
  - federation mode: re-validates the source repo (in case main moved),
                    re-resolves commit_sha, merges the entry into index.json.

In both cases, bumps `index.json.generated_at`, removes the pending record.
Success prepares local candidate bytes, not publication. Only the merge-completion
workflow may report publication or close the submission issue.

Inputs:
  --event-path   Path to GITHUB_EVENT_PATH (the labeled-issue event)
  --staging-dir  staging/ root (default)
  --catalog      Path to index.json (default)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

import lib_rapp
import lib_desktop
import build_pokedex_api
from process_rapplication import extract_payload, ProcessError, submission_fingerprint


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STAGING = REPO_ROOT / "staging"
DEFAULT_CATALOG = REPO_ROOT / "index.json"


class PromoteError(Exception):
    pass


def bundle_tree_fingerprint(root: Path) -> str:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise PromoteError("E_PROMOTION_SYMLINK: staged bundle contains a symlink")
        if path.is_file():
            files.append([path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest(),
                          bool(path.stat().st_mode & 0o111)])
    return hashlib.sha256(json.dumps(files, separators=(",", ":")).encode()).hexdigest()


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
    if (not src.is_dir() or src.is_symlink()
            or not src.resolve().is_relative_to(staging_dir.resolve())):
        raise PromoteError(f"E_STAGED_MISSING: {src}")
    if item.get("bundle_tree_sha256") and item["bundle_tree_sha256"] != bundle_tree_fingerprint(src):
        raise PromoteError("E_STALE_PENDING: staged bundle tree changed since issue validation; resubmit")
    current = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {}
    result = lib_rapp.validate_dir(src, expected_publisher=item.get("submitter"),
                                   existing_catalog=current, submission_type="bundle")
    if not result.ok:
        raise PromoteError(f"E_REVALIDATE_FAILED: {result.errors}")
    if result.manifest["id"] != item["id"] or result.manifest["version"] != item["version"]:
        raise PromoteError("E_STALE_PENDING: staged bundle ID/version changed; resubmit")
    manifest = result.manifest
    entry = lib_rapp.build_index_entry(manifest, result.integrity, rapp_id)
    if item.get("entry") != entry:
        raise PromoteError("E_STALE_PENDING: staged bundle metadata or bytes changed; resubmit")
    previous = next((r for r in current.get("rapplications", []) if r["id"] == rapp_id), None)
    if previous and previous.get("publisher", "").lower() != manifest["publisher"].lower():
        raise PromoteError("E_PUBLISHER_CONTINUITY: an existing catalog ID cannot change publisher")

    target = repo_root / "apps" / manifest["publisher"] / rapp_id
    for tree in (src, target):
        if tree.is_symlink() or any(p.is_symlink() for p in tree.rglob("*")):
            raise PromoteError("E_PROMOTION_SYMLINK: bundle trees must not contain symlinks")
    if (any(parent.is_symlink() for parent in (repo_root / "apps", target.parent))
            or not target.resolve().is_relative_to(repo_root.resolve())):
        raise PromoteError("E_PROMOTION_PATH: bundle destination escapes apps/")
    replacement = staging_dir / "_promotion" / rapp_id
    if replacement.exists():
        shutil.rmtree(replacement)
    shutil.copytree(src, replacement)
    if target.exists():
        try:
            old_v = json.loads((target / "manifest.json").read_text())["version"]
        except (OSError, KeyError, ValueError) as exc:
            raise PromoteError("E_PREVIOUS_MANIFEST: cannot preserve previous distributable") from exc
        if not isinstance(old_v, str) or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]*", old_v):
            raise PromoteError("E_PREVIOUS_VERSION: invalid snapshot path")
        # Old snapshots and eggs are immutable; a submission cannot replace them.
        _preserve_tree(target / "versions", replacement / "versions")
        _preserve_tree(target / "eggs", replacement / "eggs")
        snapshot = replacement / "versions" / old_v
        for old in sorted(target.iterdir()):
            if old.name != "versions":
                _preserve_tree(old, snapshot / old.name)
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(replacement), target)
    shutil.rmtree(src)
    return entry, manifest


def _preserve_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if source.is_dir():
        if destination.exists() and not destination.is_dir():
            raise PromoteError("E_IMMUTABLE_HISTORY: snapshot path changed type")
        destination.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir()):
            _preserve_tree(child, destination / child.name)
    elif destination.exists():
        if not destination.is_file() or source.read_bytes() != destination.read_bytes():
            raise PromoteError("E_IMMUTABLE_HISTORY: previous snapshot or egg was changed")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def promote_federation(item: dict, catalog_path: Path) -> tuple[dict, dict]:
    staged = item.get("entry", {})
    src = staged.get("source") or {}
    repo, ref, path = src.get("repo"), src.get("ref", "main"), src.get("path", "")
    if not repo:
        raise PromoteError("E_BAD_FEDERATION_SOURCE: source.repo missing in pending entry")
    current = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {}
    native = "desktop" in staged
    if native and not lib_desktop.COMMIT_RE.fullmatch(src.get("commit_sha") or ""):
        raise PromoteError("E_DESKTOP_SOURCE_PIN: native staging lacks an immutable manifest commit")
    result = lib_rapp.validate_federation(
        repo, ref=ref, path=path, existing_catalog=current,
        expected_publisher=item.get("submitter"),
        expected_commit_sha=src.get("commit_sha") if native else None)
    if not result.ok:
        raise PromoteError(f"E_REVALIDATE_FAILED: {result.errors}")
    if result.manifest["id"] != item["id"] or result.manifest["version"] != item["version"]:
        raise PromoteError("E_STALE_PENDING: federation ID/version changed since review; resubmit")
    if native or "desktop" in result.index_entry:
        if result.index_entry != staged:
            raise PromoteError("E_DESKTOP_STALE_PENDING: native metadata or provenance changed since staging; resubmit")
    elif src.get("commit_sha") and result.index_entry != staged:
        raise PromoteError("E_STALE_PENDING: federation metadata, source pin or bytes changed since staging; resubmit")
    previous = next((r for r in current.get("rapplications", [])
                     if r["id"] == result.manifest["id"]), None)
    if previous and previous.get("publisher", "").lower() != result.manifest["publisher"].lower():
        raise PromoteError("E_PUBLISHER_CONTINUITY: an existing catalog ID cannot change publisher")
    return result.index_entry, result.manifest


def update_catalog(catalog_path: Path, entry: dict, prepared_at: str | None = None) -> dict:
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
    out["generated_at"] = prepared_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    catalog_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return out


def promote(event: dict, staging_dir: Path, catalog_path: Path) -> tuple[bool, str]:
    issue = event.get("issue", {})
    issue_number = issue.get("number")
    try:
        item = find_pending(staging_dir, issue_number)
    except PromoteError as e:
        return False, f"## ❌ Promotion failed\n\n`{e}`\n"

    if "desktop" in item.get("entry", {}) or item.get("submission_sha256"):
        error = "E_DESKTOP_STALE_ISSUE" if "desktop" in item.get("entry", {}) else "E_STALE_ISSUE"
        try:
            payload = extract_payload(issue.get("body") or "")
        except ProcessError:
            return False, f"## ❌ Promotion failed\n\n`{error}: missing approved submission payload; resubmit`\n"
        if (not issue.get("title", "").startswith("[RAPP]")
                or submission_fingerprint(payload) != item.get("submission_sha256")):
            return False, f"## ❌ Promotion failed\n\n`{error}: issue payload changed since staging; resubmit`\n"

    try:
        if item["mode"] == "bundle":
            entry, manifest = promote_bundle(item, staging_dir, catalog_path.parent, catalog_path)
        elif item["mode"] == "federation":
            entry, manifest = promote_federation(item, catalog_path)
        else:
            return False, f"## ❌ Promotion failed\n\n`E_UNKNOWN_MODE: {item.get('mode')!r}`\n"
    except PromoteError as e:
        return False, f"## ❌ Promotion failed\n\n`{e}`\n"

    discovery = {}
    if "desktop" in entry:
        current = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {}
        try:
            discovery = build_pokedex_api.native_discovery_updates(
                lib_rapp.merge_index_entry(current, entry),
                catalog_path.parent / "api" / "v1", [entry["id"]])
        except ValueError as exc:
            return False, f"## ❌ Promotion failed\n\n`{exc}`\n"
    update_catalog(catalog_path, entry, item.get("prepared_at"))
    build_pokedex_api.write_native_discovery(discovery)
    remove_pending(staging_dir, issue_number)

    return True, _md_promotion(item, entry, manifest)


def _md_promotion(item, entry, manifest):
    mode = item["mode"]
    head = "## ✅ Promotion candidate prepared — not published\n\n"
    if mode == "bundle":
        head += (f"- **mode:** bundle (candidate files in "
                 f"`apps/{manifest['publisher']}/{manifest['id']}/`)\n")
    else:
        src = entry.get("source", {})
        head += (f"- **mode:** federation (catalog points at "
                 f"`{src.get('repo')}@{src.get('ref')}` "
                 f"commit `{(src.get('commit_sha') or '')[:8]}`)\n")
    head += (f"- **id:** `{manifest['id']}`\n"
             f"- **version:** `{manifest['version']}`\n"
             f"- **publisher:** `{manifest['publisher']}`\n"
             f"- **singleton_url:** {entry.get('singleton_url')}\n\n"
             "Only the local candidate catalog was updated. These URLs become "
             "available after the checked PR is merged by the repository owner. "
             "PR creation and approval labels are not publication.\n")
    if "desktop" in entry:
        head += ("\nNative downloads remain in the source repository's GitHub Release. "
                 "Only this ID's v1 discovery/detail metadata was refreshed; no eggs, "
                 "hatchers, native binaries or RAPP/1 acceptance were generated. "
                 "Release report references and byte pins were checked; this is not "
                 "independent authentication of Apple's signing/notarization reports.\n")
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
