#!/usr/bin/env python3
"""process_rapplication.py — receiver for [RAPP] issue submissions.

Reads the GitHub Actions issue event, parses the structured submission
payload (bundle or federation), validates against SPEC.md via
scripts/lib_rapp.py, and:

  - on bundle pass: extracts the .zip into staging/<id>/, writes a
    pending entry to staging/_pending.json, prints a markdown report.
  - on federation pass: writes the validated index entry to
    staging/_pending.json with mode='federation', prints a markdown
    report.
  - on fail: prints the errors as a markdown report and exits non-zero.

The workflow consumes stdout to comment on the issue; the wallclock
exit status decides whether to label `pending-review` or `failed`.

Inputs:
  --event-path   Path to the GITHUB_EVENT_PATH JSON file
  --staging-dir  Where to stage validated bundles (default: staging/)
  --catalog      Path to index.json for version-bump checks
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import sys
from pathlib import Path

import lib_rapp


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STAGING = REPO_ROOT / "staging"
DEFAULT_CATALOG = REPO_ROOT / "index.json"


# Issue body markers
JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
BUNDLE_BLOCK_RE = re.compile(r"```bundle\s*\n(.*?)\n```", re.DOTALL)


class ProcessError(Exception):
    pass


def parse_event(event_path: str) -> dict:
    return json.loads(Path(event_path).read_text())


def extract_payload(body: str) -> dict:
    """Extract the first JSON metadata block from the issue body."""
    m = JSON_BLOCK_RE.search(body or "")
    if not m:
        raise ProcessError("E_NO_PAYLOAD: issue body has no ```json``` block")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ProcessError(f"E_BAD_PAYLOAD_JSON: {e}")


def extract_bundle(body: str) -> bytes:
    """Decode the ```bundle``` base64 block from the issue body."""
    m = BUNDLE_BLOCK_RE.search(body or "")
    if not m:
        raise ProcessError("E_NO_BUNDLE: bundle submission has no ```bundle``` block")
    cleaned = re.sub(r"\s+", "", m.group(1))
    try:
        return base64.b64decode(cleaned)
    except Exception as e:
        raise ProcessError(f"E_BAD_BUNDLE_BASE64: {e}")


def load_catalog(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text())
    return {"rapplications": []}


def write_pending(staging_dir: Path, entry: dict) -> Path:
    staging_dir.mkdir(parents=True, exist_ok=True)
    pending_path = staging_dir / "_pending.json"
    if pending_path.is_file():
        pending = json.loads(pending_path.read_text())
    else:
        pending = {"items": []}
    pending["items"] = [p for p in pending["items"]
                        if p.get("issue") != entry.get("issue")]
    pending["items"].append(entry)
    pending_path.write_text(json.dumps(pending, indent=2))
    return pending_path


def process(event: dict, staging_dir: Path, catalog_path: Path) -> tuple[bool, str]:
    issue = event.get("issue", {})
    issue_number = issue.get("number")
    submitter = "@" + issue.get("user", {}).get("login", "")
    body = issue.get("body") or ""
    title = issue.get("title", "")

    catalog = load_catalog(catalog_path)

    try:
        payload = extract_payload(body)
    except ProcessError as e:
        return False, _md_error(issue_number, [str(e)])

    submission_type = payload.get("submission_type")
    if submission_type == "bundle":
        try:
            blob = extract_bundle(body)
        except ProcessError as e:
            return False, _md_error(issue_number, [str(e)])
        rapp_id = payload.get("id", "unknown")
        extract_to = staging_dir / "_extract" / rapp_id
        if extract_to.exists():
            shutil.rmtree(extract_to)
        result = lib_rapp.validate_zip(blob,
                                        expected_publisher=submitter,
                                        existing_catalog=catalog,
                                        extract_to=extract_to)
        if not result.ok:
            return False, _md_error(issue_number, result.errors)

        rapp_id = result.manifest["id"]
        target = staging_dir / rapp_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(result.rapp_dir, target)
        shutil.rmtree(extract_to, ignore_errors=True)

        entry = lib_rapp.build_index_entry(result.manifest, result.integrity, rapp_id)
        # staged_dir is recorded relative to staging_dir.parent, which is the
        # repo root in production and tmp_path in tests. The promoter resolves
        # it against the same parent.
        write_pending(staging_dir, {
            "issue": issue_number,
            "submitter": submitter,
            "mode": "bundle",
            "id": rapp_id,
            "version": result.manifest["version"],
            "staged_dir": str(target.relative_to(staging_dir.parent)),
            "entry": entry,
        })
        return True, _md_ok_bundle(issue_number, result, entry)

    if submission_type == "federation":
        source = payload.get("source") or {}
        repo, ref, path = source.get("repo"), source.get("ref", "main"), source.get("path", "")
        if not repo:
            return False, _md_error(issue_number, ["E_BAD_SOURCE: federation source.repo missing"])
        result = lib_rapp.validate_federation(
            repo, ref=ref, path=path,
            expected_publisher=submitter,
            existing_catalog=catalog)
        if not result.ok:
            return False, _md_error(issue_number, result.errors)
        write_pending(staging_dir, {
            "issue": issue_number,
            "submitter": submitter,
            "mode": "federation",
            "id": result.manifest["id"],
            "version": result.manifest["version"],
            "entry": result.index_entry,
        })
        return True, _md_ok_federation(issue_number, result)

    return False, _md_error(issue_number, [
        f"E_UNKNOWN_SUBMISSION_TYPE: {submission_type!r} "
        f"(expected 'bundle' or 'federation')"])


def _md_error(issue_n, errors):
    bullets = "\n".join(f"- `{e}`" for e in errors)
    return (f"## ❌ Submission rejected\n\n"
            f"The submission in issue #{issue_n} did not pass SPEC.md "
            f"validation:\n\n{bullets}\n\n"
            f"Run `@rapp/publish-to-rapp-store` with `validate_local` or "
            f"`validate_repo` locally to debug. See "
            f"[SPEC.md](https://github.com/kody-w/rapp_store/blob/main/SPEC.md) "
            f"for the full ruleset.\n")


def _md_ok_bundle(issue_n, result, entry):
    m = result.manifest
    return (f"## ✅ Submission validated (bundle mode)\n\n"
            f"- **id:** `{m['id']}`\n"
            f"- **version:** `{m['version']}`\n"
            f"- **publisher:** `{m['publisher']}`\n"
            f"- **singleton:** `{entry.get('singleton_filename')}` "
            f"(`{result.integrity.get('singleton_lines')}` lines, "
            f"`{result.integrity.get('singleton_bytes')}` bytes, "
            f"sha256 `{result.integrity.get('singleton_sha256','')[:16]}…`)\n\n"
            f"Files staged under `staging/{m['id']}/`. A maintainer will "
            f"review and add the `approved` label to promote.\n")


def _md_ok_federation(issue_n, result):
    m = result.manifest
    src = result.index_entry.get("source", {})
    return (f"## ✅ Submission validated (federation mode)\n\n"
            f"- **id:** `{m['id']}`\n"
            f"- **version:** `{m['version']}`\n"
            f"- **publisher:** `{m['publisher']}`\n"
            f"- **source:** `{src.get('repo')}@{src.get('ref')}` "
            f"(commit `{(src.get('commit_sha') or '')[:8]}`)\n"
            f"- **singleton_url:** {result.index_entry.get('singleton_url')}\n"
            f"- **singleton_sha256:** `{result.integrity.get('singleton_sha256','')[:16]}…`\n\n"
            f"On approval, the catalog entry will be added with the URL above. "
            f"Nothing is copied into `kody-w/rapp_store`.\n")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--event-path", required=True)
    p.add_argument("--staging-dir", default=str(DEFAULT_STAGING))
    p.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    args = p.parse_args(argv)

    event = parse_event(args.event_path)
    ok, report = process(event, Path(args.staging_dir), Path(args.catalog))
    sys.stdout.write(report)
    sys.stdout.flush()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
