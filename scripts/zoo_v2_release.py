#!/usr/bin/env python3
"""Idempotent Git/GitHub release plumbing for RAPP Zoo Store v2 generations."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

import configure_zoo_v2_protection as protection
import zoo_v2_store as store


BRANCH_RE = re.compile(r"^zoo-v2/issue-([1-9][0-9]*)-([0-9a-f]{64})$")
BOOTSTRAP_BRANCH = "zoo-v2/bootstrap-protection"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_CHANGED_FILES = 10_000
MAX_CHANGED_PATH_BYTES = 1_048_576
MAX_ISSUE_BRANCHES = 250
MAX_PRS_PER_BRANCH = 100
MAX_ELIGIBLE_ISSUE_PAGES = 5
MAX_STATUS_PAGES = 5
GITHUB_PAGE_SIZE = 100
RELEASE_LOCK_REF = "refs/heads/zoo-v2/release-lock"
RELEASE_LOCK_SCHEMA = "rapp-zoo-release-lock/1.0"
PROCESSED_LABEL = "zoo-v2-processed"
TOMBSTONED_LABEL = "zoo-v2-tombstoned"
ELIGIBLE_LABEL = "zoo-v2-eligible"
SUPERSEDED_LABEL = "zoo-v2-superseded"
PR_MARKER_SCHEMA = "rapp-zoo-pr/1.0"
COMPLETION_MARKER_SCHEMA = "rapp-zoo-completion/1.0"
SUPERSEDED_MARKER_SCHEMA = "rapp-zoo-superseded/1.1"
AUDIT_MARKER_RE = re.compile(
    r"<!-- (?P<kind>zoo-v2-(?:pr|completed|superseded)) "
    r"(?P<payload>\{[^\r\n]*\}) -->"
)
STORE_TITLE_RE = re.compile(r"^\[ZOO V2 (?:CREATE|UPDATE|DEPRECATE)\] ")
PROTECTED_EXACT_PATHS = frozenset({
    ".github/zoo-v2-protection-audit.json",
    "scripts/configure_zoo_v2_protection.py",
    "scripts/zoo_v2_release.py",
    "scripts/zoo_v2_store.py",
    "specs/RAPP_ZOO_STORE_V2.md",
})


class ReleaseError(store.StoreError):
    """A stable release-state refusal."""


def is_protected_path(path: str) -> bool:
    return (
        path in PROTECTED_EXACT_PATHS
        or path.startswith("api/v2/")
        or path.startswith("schemas/zoo-v2/")
        or (
            path.startswith(".github/workflows/zoo-v2-")
            and path.endswith((".yml", ".yaml"))
        )
        or (
            path.startswith(".github/ISSUE_TEMPLATE/zoo-v2-")
            and path.endswith((".yml", ".yaml"))
        )
    )


def protected_changed_files(changed_files: list[str]) -> list[str]:
    if not isinstance(changed_files, list) or any(
        not isinstance(path, str) or not path or path.startswith("/")
        for path in changed_files
    ):
        raise ReleaseError("E_CHANGED_FILES: expected repository-relative paths")
    return sorted(set(filter(is_protected_path, changed_files)))


def inspect_pr_change(
    changed_files: list[str],
    *,
    head_ref: str,
    head_repository: str,
    repository: str,
) -> str:
    """Classify every PR and fail protected changes outside authorized lanes."""
    _validate_repository(repository)
    protected = protected_changed_files(changed_files)
    if not protected:
        return "none"
    if head_repository != repository:
        raise ReleaseError(
            "E_PROTECTED_PR: protected Store paths cannot be changed from a fork"
        )
    if BRANCH_RE.fullmatch(head_ref):
        branch_match = BRANCH_RE.fullmatch(head_ref)
        assert branch_match is not None
        issue_number = branch_match.group(1)
        generation_id = head_ref.removeprefix("zoo-v2/")
        allowed = {
            "api/v2/discovery.json",
            f"api/v2/generations/{generation_id}.json",
        }
        unexpected = sorted(set(protected) - allowed)
        if unexpected:
            raise ReleaseError(
                "E_PROTECTED_PR: Zoo issue branches may change only their discovery "
                "and generation files: " + ", ".join(unexpected)
            )
        if set(protected) != allowed:
            raise ReleaseError(
                "E_PROTECTED_PR: Zoo issue branch must change discovery and its exact "
                "issue generation"
            )
        return "issue"
    if head_ref == BOOTSTRAP_BRANCH:
        if any(path.startswith("api/v2/") for path in protected):
            raise ReleaseError(
                "E_PROTECTED_PR: bootstrap branch cannot publish Store generations"
            )
        return "bootstrap"
    raise ReleaseError(
        "E_PROTECTED_PR: protected Store paths require an authorized same-repository "
        f"zoo-v2/issue-* or {BOOTSTRAP_BRANCH} branch"
    )


def _read_changed_files(path: Path) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReleaseError(f"E_CHANGED_FILES: cannot read {path}: {exc}") from exc
    if len(raw) > MAX_CHANGED_PATH_BYTES:
        raise ReleaseError("E_CHANGED_FILES: changed-path list is oversized")
    if b"\0" in raw or b"\r" in raw:
        raise ReleaseError("E_CHANGED_FILES: NUL/CR in changed-path list")
    try:
        values = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ReleaseError("E_CHANGED_FILES: paths must be valid UTF-8") from exc
    if any(not value or "\n" in value for value in values):
        raise ReleaseError("E_CHANGED_FILES: empty/newline path is forbidden")
    if len(values) > MAX_CHANGED_FILES:
        raise ReleaseError(
            f"E_CHANGED_FILES: more than {MAX_CHANGED_FILES} changed files"
        )
    return values


def complete_changed_files(root: Path, base_sha: str, head_sha: str) -> list[str]:
    """List the complete three-dot PR diff from an inert, full-history checkout."""
    if not COMMIT_SHA_RE.fullmatch(base_sha) or not COMMIT_SHA_RE.fullmatch(head_sha):
        raise ReleaseError("E_CHANGED_FILES: base/head must be full lowercase commit SHAs")
    shallow = _git(root, "rev-parse", "--is-shallow-repository")
    if shallow != "false":
        raise ReleaseError("E_CHANGED_FILES: shallow checkout is forbidden")
    for label, sha in (("base", base_sha), ("head", head_sha)):
        resolved = _run(
            ["git", "rev-parse", "--verify", f"{sha}^{{commit}}"],
            cwd=root,
            check=False,
        )
        if resolved.returncode or resolved.stdout.strip() != sha:
            raise ReleaseError(f"E_CHANGED_FILES: missing or invalid {label} commit")
    merge_base = _run(
        ["git", "merge-base", base_sha, head_sha],
        cwd=root,
        check=False,
    )
    if (
        merge_base.returncode
        or not COMMIT_SHA_RE.fullmatch(merge_base.stdout.strip())
    ):
        raise ReleaseError("E_CHANGED_FILES: no complete merge base")

    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            "-z",
            f"{base_sha}...{head_sha}",
            "--",
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ReleaseError(f"E_CHANGED_FILES: git diff failed: {detail}")
    raw = result.stdout
    if len(raw) > MAX_CHANGED_PATH_BYTES:
        raise ReleaseError("E_CHANGED_FILES: changed-path list is oversized")
    if raw and not raw.endswith(b"\0"):
        raise ReleaseError("E_CHANGED_FILES: malformed NUL-delimited git output")
    encoded_paths = raw[:-1].split(b"\0") if raw else []
    if len(encoded_paths) > MAX_CHANGED_FILES:
        raise ReleaseError(
            f"E_CHANGED_FILES: more than {MAX_CHANGED_FILES} changed files"
        )
    paths = []
    for encoded in encoded_paths:
        try:
            path = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReleaseError("E_CHANGED_FILES: paths must be valid UTF-8") from exc
        if not path or "\n" in path or "\r" in path or "\0" in path:
            raise ReleaseError("E_CHANGED_FILES: NUL/newline path is forbidden")
        paths.append(path)
    return paths


def validate_bootstrap_pr(
    root: Path,
    changed_files: list[str],
    repository: str,
) -> None:
    protected = protected_changed_files(changed_files)
    if any(path.startswith("api/v2/") for path in protected):
        raise ReleaseError("E_PROTECTED_PR: bootstrap branch cannot publish Store data")
    audit_path = protection.AUDIT_PATH.as_posix()
    if audit_path in protected:
        try:
            audit = json.loads((root / audit_path).read_text())
            validator_app = protection.audit_app_identity(audit)
            protection.verify_audit(
                audit,
                repository,
                validator_app["id"],
                validator_app["slug"],
                validator_app["login"],
                validator_app.get("user_id"),
            )
        except protection.ProtectionError as exc:
            raise ReleaseError(str(exc)) from exc


def require_protection_audit(root: Path, repository: str) -> dict:
    try:
        path = root / protection.AUDIT_PATH
        audit = json.loads(path.read_text())
        validator_app = protection.audit_app_identity(audit)
        protection.verify_audit(
            audit,
            repository,
            validator_app["id"],
            validator_app["slug"],
            validator_app["login"],
            validator_app.get("user_id"),
        )
        return audit
    except FileNotFoundError as exc:
        raise ReleaseError(
            f"E_PROTECTION_AUDIT: missing {root / protection.AUDIT_PATH}; "
            "an administrator must run configure-verify and commit its audit before release"
        ) from exc
    except (OSError, json.JSONDecodeError, protection.ProtectionError) as exc:
        raise ReleaseError(str(exc)) from exc


def _validate_repository(repository: str) -> None:
    if not REPOSITORY_RE.fullmatch(repository):
        raise ReleaseError("E_REPOSITORY: expected owner/repo")


def _run(
    command: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ReleaseError(f"E_COMMAND: {' '.join(command)}: {detail}")
    return result


def _git(root: Path, *args: str, input_text: str | None = None) -> str:
    return _run(["git", *args], cwd=root, input_text=input_text).stdout.strip()


def _gh(root: Path, *args: str) -> str:
    return _run(["gh", *args], cwd=root).stdout.strip()


def _gh_json(root: Path, *args: str) -> object:
    output = _gh(root, *args)
    try:
        return json.loads(output or "null")
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"E_GITHUB_RESPONSE: invalid JSON from gh: {exc}") from exc


def _lock_lease_key(
    repository: str,
    issue_number: int | None,
    generation_id: str,
    workflow_run_id: str,
) -> str:
    basis = "\n".join(
        (repository, str(issue_number), generation_id, workflow_run_id)
    ).encode()
    return hashlib.sha256(basis).hexdigest()


def release_lock_owner(
    repository: str,
    issue_number: int | None,
    generation_id: str,
    *,
    workflow_run_id: str | None = None,
    workflow_run_attempt: str | None = None,
    actor: str | None = None,
    workflow: str | None = None,
) -> dict:
    """Build stable workflow ownership; reruns retain the same lease key."""
    _validate_repository(repository)
    issue_owner_valid = (
        isinstance(issue_number, int)
        and not isinstance(issue_number, bool)
        and issue_number > 0
        and generation_id.startswith(f"issue-{issue_number}-")
    )
    bootstrap_owner_valid = issue_number is None and generation_id.startswith("bootstrap-")
    if not (issue_owner_valid or bootstrap_owner_valid):
        raise ReleaseError("E_RELEASE_LOCK: owner issue/generation mismatch")
    run_id = workflow_run_id or os.environ.get("GITHUB_RUN_ID") or f"local-{os.getpid()}"
    if not re.fullmatch(r"(?:[1-9][0-9]*|local-[1-9][0-9]*)", run_id):
        raise ReleaseError("E_RELEASE_LOCK: invalid workflow run id")
    run_attempt = (
        workflow_run_attempt
        or os.environ.get("GITHUB_RUN_ATTEMPT")
        or "1"
    )
    if not re.fullmatch(r"[1-9][0-9]*", run_attempt):
        raise ReleaseError("E_RELEASE_LOCK: invalid workflow run attempt")
    owner_actor = actor or os.environ.get("GITHUB_ACTOR") or "local"
    owner_workflow = workflow or os.environ.get("GITHUB_WORKFLOW") or "local"
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", owner_actor)
        or not isinstance(owner_workflow, str)
        or not owner_workflow.strip()
        or len(owner_workflow) > 200
        or any(character in owner_workflow for character in "\r\n\0")
    ):
        raise ReleaseError("E_RELEASE_LOCK: invalid owner metadata")
    return {
        "schema": RELEASE_LOCK_SCHEMA,
        "repository": repository,
        "issue_number": issue_number,
        "generation_id": generation_id,
        "workflow_run_id": run_id,
        "workflow_run_attempt": run_attempt,
        "actor": owner_actor,
        "workflow": owner_workflow,
        "lease_key": _lock_lease_key(
            repository, issue_number, generation_id, run_id
        ),
    }


def _validate_lock_owner(owner: object, repository: str | None = None) -> dict:
    if not isinstance(owner, dict) or set(owner) != {
        "schema",
        "repository",
        "issue_number",
        "generation_id",
        "workflow_run_id",
        "workflow_run_attempt",
        "actor",
        "workflow",
        "lease_key",
    }:
        raise ReleaseError("E_RELEASE_LOCK: malformed lock owner metadata")
    issue_number = owner.get("issue_number")
    if issue_number is not None and (
        not isinstance(issue_number, int)
        or isinstance(issue_number, bool)
    ):
        raise ReleaseError("E_RELEASE_LOCK: malformed lock owner metadata")
    if any(
        not isinstance(owner.get(key), str)
        for key in (
            "schema",
            "repository",
            "generation_id",
            "workflow_run_id",
            "workflow_run_attempt",
            "actor",
            "workflow",
            "lease_key",
        )
    ):
        raise ReleaseError("E_RELEASE_LOCK: malformed lock owner metadata")
    expected = release_lock_owner(
        owner["repository"],
        issue_number,
        owner["generation_id"],
        workflow_run_id=owner["workflow_run_id"],
        workflow_run_attempt=owner["workflow_run_attempt"],
        actor=owner["actor"],
        workflow=owner["workflow"],
    )
    if owner != expected or (repository is not None and owner["repository"] != repository):
        raise ReleaseError("E_RELEASE_LOCK: lock owner metadata differs")
    return expected


def _remote_ref_sha(root: Path, remote: str, ref: str) -> str | None:
    output = _git(root, "ls-remote", remote, ref)
    lines = [line for line in output.splitlines() if line]
    if not lines:
        return None
    if len(lines) != 1:
        raise ReleaseError(f"E_RELEASE_LOCK: ambiguous remote ref {ref}")
    sha, actual_ref = lines[0].split("\t", 1)
    if actual_ref != ref or not COMMIT_SHA_RE.fullmatch(sha):
        raise ReleaseError(f"E_RELEASE_LOCK: malformed remote ref {ref}")
    return sha


def _read_lock_owner(root: Path, remote: str, owner_sha: str) -> dict:
    if not COMMIT_SHA_RE.fullmatch(owner_sha):
        raise ReleaseError("E_RELEASE_LOCK: invalid lock owner commit")
    observed_ref = "refs/zoo-v2/observed-release-lock"
    _git(root, "fetch", "--force", remote, f"{RELEASE_LOCK_REF}:{observed_ref}")
    if _git(root, "rev-parse", observed_ref) != owner_sha:
        raise ReleaseError("E_RELEASE_LOCK: lock changed while it was inspected")
    if _git(root, "cat-file", "-t", owner_sha) != "commit":
        raise ReleaseError("E_RELEASE_LOCK: owner ref is not a commit")
    try:
        owner = json.loads(_git(root, "show", "-s", "--format=%B", owner_sha))
    except json.JSONDecodeError as exc:
        raise ReleaseError("E_RELEASE_LOCK: owner commit metadata is invalid") from exc
    return _validate_lock_owner(owner)


def acquire_release_lock(
    root: Path,
    remote: str,
    owner: dict,
) -> dict:
    """Atomically create the remote lock branch or resume the exact same lease."""
    owner = _validate_lock_owner(owner)
    existing_sha = _remote_ref_sha(root, remote, RELEASE_LOCK_REF)
    if existing_sha is not None:
        existing_owner = _read_lock_owner(root, remote, existing_sha)
        if existing_owner["lease_key"] != owner["lease_key"]:
            raise ReleaseError(
                "E_RELEASE_LOCKED: release lock is held by "
                f"issue #{existing_owner['issue_number']} run "
                f"{existing_owner['workflow_run_id']} at {existing_sha}"
            )
        return {"ref": RELEASE_LOCK_REF, "owner_sha": existing_sha, "owner": existing_owner}

    tree = _git(root, "hash-object", "-t", "tree", "--stdin", input_text="")
    owner_sha = _git(
        root,
        "commit-tree",
        tree,
        "-F",
        "-",
        input_text=json.dumps(owner, sort_keys=True, separators=(",", ":")) + "\n",
    )
    publication = _run(
        ["git", "push", remote, f"{owner_sha}:{RELEASE_LOCK_REF}"],
        cwd=root,
        check=False,
    )
    if publication.returncode:
        winning_sha = _remote_ref_sha(root, remote, RELEASE_LOCK_REF)
        if winning_sha is not None:
            winning_owner = _read_lock_owner(root, remote, winning_sha)
            if winning_owner["lease_key"] == owner["lease_key"]:
                return {
                    "ref": RELEASE_LOCK_REF,
                    "owner_sha": winning_sha,
                    "owner": winning_owner,
                }
            raise ReleaseError(
                "E_RELEASE_LOCKED: release lock is held by "
                f"issue #{winning_owner['issue_number']} run "
                f"{winning_owner['workflow_run_id']} at {winning_sha}"
            )
        detail = publication.stderr.strip() or publication.stdout.strip()
        raise ReleaseError(f"E_RELEASE_LOCK: atomic lock creation failed: {detail}")
    return {"ref": RELEASE_LOCK_REF, "owner_sha": owner_sha, "owner": owner}


def release_release_lock(root: Path, remote: str, lease: dict) -> None:
    """Delete only the exact owner commit; never break another owner's lease."""
    owner_sha = lease.get("owner_sha") if isinstance(lease, dict) else None
    if not isinstance(owner_sha, str) or not COMMIT_SHA_RE.fullmatch(owner_sha):
        raise ReleaseError("E_RELEASE_LOCK: invalid release lease")
    deletion = _run(
        [
            "git",
            "push",
            f"--force-with-lease={RELEASE_LOCK_REF}:{owner_sha}",
            remote,
            f":{RELEASE_LOCK_REF}",
        ],
        cwd=root,
        check=False,
    )
    if deletion.returncode:
        detail = deletion.stderr.strip() or deletion.stdout.strip()
        raise ReleaseError(f"E_RELEASE_LOCK_LEASE: exact lock cleanup failed: {detail}")
    if _remote_ref_sha(root, remote, RELEASE_LOCK_REF) is not None:
        raise ReleaseError("E_RELEASE_LOCK_LEASE: lock still exists after cleanup")


def recover_stale_release_lock(
    root: Path,
    repository: str,
    expected_owner_sha: str,
    reason: str,
    admin_actor: str,
    *,
    remote: str = "origin",
) -> dict:
    """Explicit admin-only recovery after proving the owner run and PR inactive."""
    _validate_repository(repository)
    if (
        not COMMIT_SHA_RE.fullmatch(expected_owner_sha)
        or not reason.strip()
        or len(reason) > 500
        or any(character in reason for character in "\r\n\0")
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", admin_actor)
    ):
        raise ReleaseError("E_LOCK_RECOVERY: invalid expected owner, actor, or reason")
    if os.environ.get("GITHUB_ACTOR") != admin_actor:
        raise ReleaseError("E_LOCK_RECOVERY: authenticated actor does not match admin actor")
    authenticated = _gh_json(root, "api", "user")
    if (
        not isinstance(authenticated, dict)
        or authenticated.get("login") != admin_actor
    ):
        raise ReleaseError(
            "E_LOCK_RECOVERY: recovery requires the administrator's user token"
        )
    current_sha = _remote_ref_sha(root, remote, RELEASE_LOCK_REF)
    if current_sha != expected_owner_sha:
        raise ReleaseError("E_LOCK_RECOVERY: lock owner changed or no longer exists")
    owner = _read_lock_owner(root, remote, current_sha)
    if owner["repository"] != repository:
        raise ReleaseError("E_LOCK_RECOVERY: lock belongs to another repository")

    permission = _gh_json(
        root,
        "api",
        f"repos/{repository}/collaborators/{admin_actor}/permission",
    )
    if (
        not isinstance(permission, dict)
        or permission.get("permission") != "admin"
        or not isinstance(permission.get("user"), dict)
        or permission["user"].get("login") != admin_actor
    ):
        raise ReleaseError("E_LOCK_RECOVERY: repository admin permission is required")

    run_id = owner["workflow_run_id"]
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ReleaseError(
            "E_LOCK_RECOVERY: owner workflow cannot be proven inactive"
        )
    def assert_owner_inactive() -> None:
        workflow_run = _gh_json(
            root,
            "api",
            f"repos/{repository}/actions/runs/{run_id}",
        )
        if (
            not isinstance(workflow_run, dict)
            or workflow_run.get("id") != int(run_id)
            or workflow_run.get("status") != "completed"
            or not isinstance(workflow_run.get("conclusion"), str)
        ):
            raise ReleaseError(
                "E_LOCK_RECOVERY: owner workflow may still be active or is unverifiable"
            )
        issue_branches = {
            branch
            for branch in _remote_issue_branches(root, remote)
            if _issue_number_from_branch(branch) == owner["issue_number"]
        }
        prs = list_catalog_prs(root, repository, issue_branches)
        if any(pr.get("state") == "OPEN" for pr in prs):
            raise ReleaseError("E_LOCK_RECOVERY: owner PR may still be active")

    assert_owner_inactive()

    marker = f"<!-- zoo-v2-lock-recovery:{expected_owner_sha} -->"
    audit_body = "\n".join([
        marker,
        f"Administrator `{admin_actor}` authorized stale release-lock recovery.",
        f"Owner workflow run: `{run_id}` (verified completed).",
        f"Reason: {reason}",
    ])
    if owner["issue_number"] is None:
        _gh(
            root,
            "issue",
            "create",
            "--repo",
            repository,
            "--title",
            f"[ZOO V2 LOCK RECOVERY] {expected_owner_sha[:12]}",
            "--body",
            audit_body,
        )
    else:
        _gh(
            root,
            "issue",
            "comment",
            str(owner["issue_number"]),
            "--repo",
            repository,
            "--body",
            audit_body,
        )
    if _remote_ref_sha(root, remote, RELEASE_LOCK_REF) != expected_owner_sha:
        raise ReleaseError("E_LOCK_RECOVERY: lock changed during recovery audit")
    assert_owner_inactive()
    release_release_lock(
        root,
        remote,
        {"owner_sha": expected_owner_sha, "owner": owner},
    )
    return {
        "recovered": expected_owner_sha,
        "issue_number": owner["issue_number"],
        "workflow_run_id": run_id,
        "admin_actor": admin_actor,
    }


def _remote_issue_branches(root: Path, remote: str) -> set[str]:
    output = _git(root, "ls-remote", "--heads", remote, "refs/heads/zoo-v2/issue-*")
    branches = set()
    for line in output.splitlines():
        if not line:
            continue
        ref = line.split("\t", 1)[-1]
        branch = ref.removeprefix("refs/heads/")
        if BRANCH_RE.fullmatch(branch):
            branches.add(branch)
    if len(branches) > MAX_ISSUE_BRANCHES:
        raise ReleaseError(
            f"E_QUEUE_INCOMPLETE: more than {MAX_ISSUE_BRANCHES} retained issue branches"
        )
    return branches


def _normalize_catalog_pr(value: object, repository: str, branch: str) -> dict:
    if not isinstance(value, dict):
        raise ReleaseError("E_GITHUB_RESPONSE: expected pull request objects")
    head = value.get("head")
    base = value.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise ReleaseError("E_GITHUB_RESPONSE: pull request refs are incomplete")
    head_repo = head.get("repo")
    head_repo_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    if head.get("ref") != branch or head_repo_name != repository:
        raise ReleaseError("E_GITHUB_RESPONSE: exact branch query returned another head")
    required = {
        "number": value.get("number"),
        "url": value.get("html_url"),
        "state": value.get("state"),
        "mergedAt": value.get("merged_at"),
        "headRefName": head.get("ref"),
        "headRefOid": head.get("sha"),
        "headRepository": head_repo_name,
        "baseRefName": base.get("ref"),
        "title": value.get("title"),
    }
    if (
        not isinstance(required["number"], int)
        or not isinstance(required["url"], str)
        or required["state"] not in {"open", "closed"}
        or not isinstance(required["headRefOid"], str)
        or not isinstance(required["baseRefName"], str)
    ):
        raise ReleaseError("E_GITHUB_RESPONSE: pull request fields are incomplete")
    required["state"] = str(required["state"]).upper()
    return required


def list_catalog_prs(
    root: Path,
    repository: str,
    branches: set[str] | None = None,
) -> list[dict]:
    """Query every retained issue branch exactly; never scan a truncated PR window."""
    _validate_repository(repository)
    retained = sorted(
        _remote_issue_branches(root, "origin") if branches is None else branches
    )
    if len(retained) > MAX_ISSUE_BRANCHES or any(
        not BRANCH_RE.fullmatch(branch) for branch in retained
    ):
        raise ReleaseError("E_QUEUE_INCOMPLETE: invalid or oversized retained branch set")
    owner = repository.split("/", 1)[0]
    result = []
    for branch in retained:
        value = _gh_json(
            root,
            "api",
            "--method",
            "GET",
            f"repos/{repository}/pulls",
            "-f",
            "state=all",
            "-f",
            f"head={owner}:{branch}",
            "-f",
            f"per_page={MAX_PRS_PER_BRANCH}",
        )
        if not isinstance(value, list):
            raise ReleaseError("E_GITHUB_RESPONSE: expected a pull request array")
        if len(value) >= MAX_PRS_PER_BRANCH:
            raise ReleaseError(
                f"E_QUEUE_INCOMPLETE: at least {MAX_PRS_PER_BRANCH} PRs exist for {branch}"
            )
        result.extend(_normalize_catalog_pr(item, repository, branch) for item in value)
    return result


def _issue_number_from_branch(branch: object) -> int | None:
    match = BRANCH_RE.fullmatch(branch) if isinstance(branch, str) else None
    return int(match.group(1)) if match is not None else None


def _eligible_issue_pages(root: Path, repository: str) -> list[dict]:
    """Enumerate the complete bounded open eligible issue set."""
    issues: list[dict] = []
    seen: set[int] = set()
    for page in range(1, MAX_ELIGIBLE_ISSUE_PAGES + 2):
        value = _gh_json(
            root,
            "api",
            "--method",
            "GET",
            f"repos/{repository}/issues",
            "-f",
            "state=open",
            "-f",
            f"labels={ELIGIBLE_LABEL}",
            "-f",
            "sort=created",
            "-f",
            "direction=asc",
            "-f",
            f"per_page={GITHUB_PAGE_SIZE}",
            "-f",
            f"page={page}",
        )
        if not isinstance(value, list) or len(value) > GITHUB_PAGE_SIZE:
            raise ReleaseError("E_RECONCILE_INCOMPLETE: malformed issue page")
        if page > MAX_ELIGIBLE_ISSUE_PAGES:
            if value:
                raise ReleaseError(
                    "E_RECONCILE_INCOMPLETE: eligible issue scan exceeded "
                    f"{MAX_ELIGIBLE_ISSUE_PAGES * GITHUB_PAGE_SIZE}"
                )
            break
        for item in value:
            if not isinstance(item, dict):
                raise ReleaseError("E_RECONCILE_INCOMPLETE: malformed issue object")
            if "pull_request" in item:
                continue
            number = item.get("number")
            title = item.get("title")
            state = item.get("state")
            created_at = item.get("created_at")
            updated_at = item.get("updated_at")
            body = item.get("body")
            user = item.get("user")
            labels = item.get("labels")
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or number <= 0
                or number in seen
                or not isinstance(title, str)
                or state != "open"
                or not isinstance(created_at, str)
                or not isinstance(updated_at, str)
                or not isinstance(body, str)
                or not isinstance(user, dict)
                or not isinstance(user.get("login"), str)
                or not isinstance(labels, list)
            ):
                raise ReleaseError("E_RECONCILE_INCOMPLETE: issue fields are incomplete")
            label_names = set()
            for label in labels:
                name = label.get("name") if isinstance(label, dict) else None
                if not isinstance(name, str):
                    raise ReleaseError(
                        "E_RECONCILE_INCOMPLETE: issue labels are incomplete"
                    )
                label_names.add(name)
            if ELIGIBLE_LABEL not in label_names:
                raise ReleaseError(
                    "E_RECONCILE_INCOMPLETE: API returned an ineligible issue"
                )
            seen.add(number)
            normalized = dict(item)
            normalized["_label_names"] = sorted(label_names)
            issues.append(normalized)
        if len(value) < GITHUB_PAGE_SIZE:
            break
    else:
        raise ReleaseError("E_RECONCILE_INCOMPLETE: issue pagination did not terminate")
    return sorted(issues, key=lambda issue: (issue["created_at"], issue["number"]))


def _issue_comments(root: Path, repository: str, issue_number: int) -> list[dict]:
    pages = _gh_json(
        root,
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repository}/issues/{issue_number}/comments",
    )
    if not isinstance(pages, list) or len(pages) > MAX_ELIGIBLE_ISSUE_PAGES:
        raise ReleaseError("E_GITHUB_RESPONSE: incomplete issue comment pagination")
    comments = []
    for page in pages:
        if not isinstance(page, list) or len(page) > GITHUB_PAGE_SIZE:
            raise ReleaseError("E_GITHUB_RESPONSE: malformed issue comments page")
        for comment in page:
            if not isinstance(comment, dict) or not isinstance(comment.get("body"), str):
                raise ReleaseError("E_GITHUB_RESPONSE: malformed issue comment")
            comments.append(comment)
    return comments


def _audit_marker(kind: str, payload: dict) -> str:
    return (
        f"<!-- zoo-v2-{kind} "
        f"{json.dumps(payload, sort_keys=True, separators=(',', ':'))} -->"
    )


def _trusted_actor(actor: object, validator_app: dict) -> bool:
    if not isinstance(actor, dict):
        return False
    if (
        actor.get("type") != "Bot"
        or actor.get("login") != validator_app["login"]
    ):
        return False
    return actor.get("id") == validator_app["user_id"]


def _trusted_comment(comment: dict, validator_app: dict) -> bool:
    user = comment.get("user")
    app = comment.get("performed_via_github_app")
    return (
        _trusted_actor(user, validator_app)
        and isinstance(app, dict)
        and app.get("id") == validator_app["id"]
        and app.get("slug") == validator_app["slug"]
    )


def _marker_payloads(
    root: Path,
    comments: list[dict],
    kind: str,
    schema: str,
    repository: str,
) -> list[dict]:
    audit = require_protection_audit(root, repository)
    validator_app = protection.audit_app_identity(audit)
    payloads = []
    expected_kind = f"zoo-v2-{kind}"
    for comment in comments:
        for match in AUDIT_MARKER_RE.finditer(comment["body"]):
            if match.group("kind") != expected_kind:
                continue
            if not _trusted_comment(comment, validator_app):
                continue
            try:
                payload = json.loads(match.group("payload"))
            except json.JSONDecodeError as exc:
                raise ReleaseError(
                    f"E_AUDIT_MARKER: malformed {expected_kind} marker"
                ) from exc
            if not isinstance(payload, dict) or payload.get("schema") != schema:
                raise ReleaseError(
                    f"E_AUDIT_MARKER: invalid {expected_kind} schema"
                )
            payloads.append(payload)
    return payloads


def _stale_status_description(attempt: str, base_sha: str) -> str:
    match = re.fullmatch(r"issue-[1-9][0-9]*-([0-9a-f]{64})", attempt)
    if match is None or not COMMIT_SHA_RE.fullmatch(base_sha):
        raise ReleaseError("E_SUPERSEDE_STATUS: invalid attempt/base binding")
    return f"Stale attempt {match.group(1)} at main {base_sha}"


def _failed_stale_status(
    root: Path,
    repository: str,
    candidate_head: str,
    attempt: str,
    base_sha: str,
    *,
    status_id: int | None = None,
) -> dict:
    if not COMMIT_SHA_RE.fullmatch(candidate_head):
        raise ReleaseError("E_SUPERSEDE_STATUS: invalid candidate head")
    audit = require_protection_audit(root, repository)
    validator_app = protection.audit_app_identity(audit)
    pages = _gh_json(
        root,
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repository}/commits/{candidate_head}/statuses?per_page=100",
    )
    if not isinstance(pages, list) or len(pages) > MAX_STATUS_PAGES:
        raise ReleaseError("E_SUPERSEDE_STATUS: incomplete commit status pagination")
    expected_description = _stale_status_description(attempt, base_sha)
    matches = []
    for page in pages:
        if not isinstance(page, list) or len(page) > GITHUB_PAGE_SIZE:
            raise ReleaseError("E_SUPERSEDE_STATUS: malformed commit status page")
        for item in page:
            if not isinstance(item, dict):
                raise ReleaseError("E_SUPERSEDE_STATUS: malformed commit status")
            if (
                item.get("state") == "failure"
                and item.get("context") == protection.STATUS_CONTEXT
                and item.get("description") == expected_description
                and _trusted_actor(item.get("creator"), validator_app)
                and isinstance(item.get("id"), int)
                and not isinstance(item.get("id"), bool)
                and item["id"] > 0
                and (status_id is None or item["id"] == status_id)
            ):
                matches.append(item)
    if not matches:
        raise ReleaseError(
            "E_SUPERSEDE_STATUS: exact App-authored failed status is absent"
        )
    if status_id is not None and len(matches) != 1:
        raise ReleaseError(
            "E_SUPERSEDE_STATUS: failed status identity is not unique"
        )
    return max(matches, key=lambda item: item["id"])


def _require_main_commit(
    root: Path,
    sha: str,
    *,
    remote: str = "origin",
) -> None:
    if not COMMIT_SHA_RE.fullmatch(sha):
        raise ReleaseError("E_SUPERSEDED_MARKER: invalidating base is malformed")
    resolved = _run(
        ["git", "rev-parse", "--verify", f"{sha}^{{commit}}"],
        cwd=root,
        check=False,
    )
    if resolved.returncode or resolved.stdout.strip() != sha:
        raise ReleaseError("E_SUPERSEDED_MARKER: invalidating base is not a commit")
    reachable = _run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            sha,
            f"refs/remotes/{remote}/main",
        ],
        cwd=root,
        check=False,
    )
    if reachable.returncode:
        raise ReleaseError(
            "E_SUPERSEDED_MARKER: invalidating base is not reachable from origin/main"
        )


def _exact_pr(root: Path, repository: str, pr_number: int) -> dict:
    if (
        not isinstance(pr_number, int)
        or isinstance(pr_number, bool)
        or pr_number <= 0
    ):
        raise ReleaseError("E_PR_STATE: invalid pull request number")
    value = _gh_json(root, "api", f"repos/{repository}/pulls/{pr_number}")
    if not isinstance(value, dict):
        raise ReleaseError("E_GITHUB_RESPONSE: expected pull request object")
    head = value.get("head")
    branch = head.get("ref") if isinstance(head, dict) else None
    if not isinstance(branch, str):
        raise ReleaseError("E_GITHUB_RESPONSE: pull request head is incomplete")
    return _normalize_catalog_pr(value, repository, branch)


def _normalize_issue(value: object, issue_number: int) -> dict:
    if not isinstance(value, dict) or value.get("number") != issue_number:
        raise ReleaseError("E_ISSUE_SNAPSHOT: exact issue response is malformed")
    user = value.get("user")
    labels = value.get("labels")
    required_strings = ("title", "state", "created_at", "updated_at", "body")
    if (
        any(not isinstance(value.get(key), str) for key in required_strings)
        or not isinstance(user, dict)
        or not isinstance(user.get("login"), str)
        or not isinstance(labels, list)
        or "pull_request" in value
    ):
        raise ReleaseError("E_ISSUE_SNAPSHOT: exact issue fields are incomplete")
    label_names = []
    for label in labels:
        name = label.get("name") if isinstance(label, dict) else None
        if not isinstance(name, str):
            raise ReleaseError("E_ISSUE_SNAPSHOT: exact issue labels are incomplete")
        label_names.append(name)
    normalized = dict(value)
    normalized["_label_names"] = sorted(set(label_names))
    return normalized


def _selected_snapshot(snapshot: object, issue_number: int) -> dict:
    issue = snapshot.get("issue") if isinstance(snapshot, dict) else None
    return _normalize_issue(issue, issue_number)


def validate_selected_issue(
    root: Path,
    repository: str,
    issue_number: int,
    snapshot: dict,
    allowlist: set[str],
    generation: dict,
    expected_generation_bytes: bytes,
    *,
    remote: str = "origin",
    base_generation_bytes: bytes | None = None,
) -> dict:
    """Bind an acquired release lease to one unchanged, still-eligible issue."""
    reconciled = _selected_snapshot(snapshot, issue_number)
    fresh = _normalize_issue(
        _gh_json(root, "api", f"repos/{repository}/issues/{issue_number}"),
        issue_number,
    )
    labels = set(fresh["_label_names"])
    if fresh["state"] != "open":
        raise ReleaseError("E_ISSUE_MUTATED: selected issue is no longer open")
    if ELIGIBLE_LABEL not in labels:
        raise ReleaseError("E_ISSUE_MUTATED: selected issue lost its eligible label")
    forbidden = labels & {PROCESSED_LABEL, TOMBSTONED_LABEL}
    if forbidden:
        raise ReleaseError(
            "E_ISSUE_MUTATED: selected issue has terminal label(s): "
            + ", ".join(sorted(forbidden))
        )
    try:
        store.validate_actor(fresh["user"]["login"], allowlist)
    except store.StoreError as exc:
        raise ReleaseError(str(exc)) from exc
    for field in ("title", "body", "updated_at", "_label_names"):
        if fresh[field] != reconciled[field]:
            raise ReleaseError(
                f"E_ISSUE_MUTATED: selected issue {field} changed after reconciliation"
            )

    discovery_bytes = _show(
        root, f"refs/remotes/{remote}/main", "api/v2/discovery.json"
    )
    if discovery_bytes is None:
        raise ReleaseError("E_BASE: origin/main has no Zoo v2 discovery")
    current_url = store.validate_discovery(json.loads(discovery_bytes))
    current_bytes = (
        base_generation_bytes
        if base_generation_bytes is not None
        else store.fetch_bytes(current_url)
    )
    try:
        current = json.loads(current_bytes)
    except json.JSONDecodeError as exc:
        raise ReleaseError("E_BASE: current generation is invalid JSON") from exc
    store.validate_generation(current, network=False)
    if store.canonical_json(current) != current_bytes:
        raise ReleaseError("E_BASE: current generation is not canonical")
    command = store.validate_command(
        store.parse_issue_command(fresh["body"]),
        fresh["title"],
    )
    regenerated = store.apply_command(
        current,
        current_url,
        command,
        issue_number=issue_number,
        timestamp=fresh["updated_at"],
        network=False,
    )
    regenerated_bytes = store.canonical_json(regenerated)
    if regenerated_bytes != expected_generation_bytes or regenerated != generation:
        raise ReleaseError(
            "E_ISSUE_MUTATED: regenerated issue generation bytes differ"
        )
    return fresh


def _completion_payload(
    issue_number: int,
    pr: dict,
    generation_commit: str,
) -> dict:
    branch = pr.get("headRefName")
    match = BRANCH_RE.fullmatch(branch) if isinstance(branch, str) else None
    if match is None or int(match.group(1)) != issue_number:
        raise ReleaseError("E_PROCESSED_MARKER: PR attempt does not match issue")
    attempt = branch.removeprefix("zoo-v2/")
    return {
        "schema": COMPLETION_MARKER_SCHEMA,
        "issue": issue_number,
        "pr": pr["number"],
        "attempt": attempt,
        "generation": f"api/v2/generations/{attempt}.json",
        "generation_commit": generation_commit,
        "tag": store.generation_tag_name(attempt),
        "merged_at": pr["mergedAt"],
    }


def _validate_completion_payload(
    root: Path,
    repository: str,
    issue_number: int,
    payload: dict,
    *,
    remote: str = "origin",
) -> dict:
    required = {
        "schema", "issue", "pr", "attempt", "generation",
        "generation_commit", "tag", "merged_at",
    }
    if set(payload) != required or payload.get("issue") != issue_number:
        raise ReleaseError("E_PROCESSED_MARKER: completion marker fields differ")
    pr = _exact_pr(root, repository, payload.get("pr"))
    expected = _completion_payload(
        issue_number,
        pr,
        payload.get("generation_commit"),
    )
    if pr.get("state") != "CLOSED" or not pr.get("mergedAt") or payload != expected:
        raise ReleaseError("E_PROCESSED_MARKER: completion marker/merged PR differ")
    generation_path = payload["generation"]
    generation_bytes = _show(
        root, f"refs/remotes/{remote}/main", generation_path
    )
    if generation_bytes is None:
        raise ReleaseError("E_PROCESSED_MARKER: merged generation is absent from main")
    committed_bytes = _show(
        root, payload["generation_commit"], generation_path
    )
    if committed_bytes != generation_bytes:
        raise ReleaseError("E_PROCESSED_MARKER: generation commit bytes differ")
    generation = json.loads(generation_bytes)
    if (
        generation.get("generation_id") != payload["attempt"]
        or generation.get("source_issue") != issue_number
        or store.canonical_json(generation) != generation_bytes
    ):
        raise ReleaseError("E_PROCESSED_MARKER: merged generation provenance differs")
    if _tag_target(root, payload["tag"]) != payload["generation_commit"]:
        raise ReleaseError("E_PROCESSED_MARKER: permanent tag differs")
    return pr


def _ensure_issue_label(
    root: Path,
    repository: str,
    issue_number: int,
    label: str,
) -> None:
    label_metadata = {
        PROCESSED_LABEL: (
            "0e8a16",
            "Zoo v2 command completed by a verified merged PR",
        ),
        SUPERSEDED_LABEL: (
            "d4c5f9",
            "Zoo v2 attempt superseded by a newer main generation",
        ),
    }
    if label not in label_metadata:
        raise ReleaseError("E_AUDIT_LABEL: unsupported lifecycle label")
    color, description = label_metadata[label]
    _gh(
        root,
        "label",
        "create",
        label,
        "--repo",
        repository,
        "--color",
        color,
        "--description",
        description,
        "--force",
    )
    _gh(
        root,
        "api",
        "--method",
        "POST",
        f"repos/{repository}/issues/{issue_number}/labels",
        "-f",
        f"labels[]={label}",
    )


def _ensure_audit_comment(
    root: Path,
    repository: str,
    issue_number: int,
    marker: str,
    text: str,
) -> None:
    comments = _issue_comments(root, repository, issue_number)
    validator_app = protection.audit_app_identity(
        require_protection_audit(root, repository)
    )
    if not any(
        marker in comment["body"] and _trusted_comment(comment, validator_app)
        for comment in comments
    ):
        _gh(
            root,
            "issue",
            "comment",
            str(issue_number),
            "--repo",
            repository,
            "--body",
            f"{marker}\n{text}",
        )


def finalize_merged_pr(
    root: Path,
    repository: str,
    pr_number: int,
    *,
    remote: str = "origin",
) -> dict:
    """Persist a merged command independently of its retained head branch."""
    _validate_repository(repository)
    require_protection_audit(root, repository)
    _git(root, "fetch", "--prune", remote, "main")
    _git(root, "fetch", "--tags", remote)
    pr = _exact_pr(root, repository, pr_number)
    issue_number = _issue_number_from_branch(pr.get("headRefName"))
    if (
        issue_number is None
        or pr.get("state") != "CLOSED"
        or not pr.get("mergedAt")
        or pr.get("baseRefName") != "main"
    ):
        raise ReleaseError("E_COMPLETE_MERGE: exact merged Zoo v2 PR is required")
    attempt = pr["headRefName"].removeprefix("zoo-v2/")
    generation_path = f"api/v2/generations/{attempt}.json"
    main_revision = f"refs/remotes/{remote}/main"
    generation_bytes = _show(root, main_revision, generation_path)
    if generation_bytes is None:
        raise ReleaseError("E_COMPLETE_MERGE: merged generation is absent from main")
    generation = json.loads(generation_bytes)
    store.validate_generation(generation, network=False)
    if (
        generation.get("generation_id") != attempt
        or generation.get("source_issue") != issue_number
        or store.canonical_json(generation) != generation_bytes
    ):
        raise ReleaseError("E_COMPLETE_MERGE: merged generation provenance differs")
    discovery_bytes = _show(root, main_revision, "api/v2/discovery.json")
    if discovery_bytes is None:
        raise ReleaseError("E_COMPLETE_MERGE: merged discovery is absent")
    discovery_url = store.validate_discovery(json.loads(discovery_bytes))
    discovery_match = store.validate_generation_raw_url(
        discovery_url, "discovery.generation_url"
    )
    if (
        discovery_match.group("owner") + "/" + discovery_match.group("repo")
        != repository
        or discovery_match.group("path") != generation_path
    ):
        raise ReleaseError("E_COMPLETE_MERGE: main discovery does not select merged attempt")
    generation_commit = discovery_match.group("commit")
    if _show(root, generation_commit, generation_path) != generation_bytes:
        raise ReleaseError("E_COMPLETE_MERGE: pinned generation commit bytes differ")
    tag = store.generation_tag_name(attempt)
    if _tag_target(root, tag) != generation_commit:
        raise ReleaseError("E_COMPLETE_MERGE: permanent generation tag differs")

    payload = _completion_payload(issue_number, pr, generation_commit)
    marker = _audit_marker("completed", payload)
    _ensure_audit_comment(
        root,
        repository,
        issue_number,
        marker,
        (
            f"Merged PR {pr['url']} completed attempt `{attempt}` with "
            f"generation `{generation_path}` and permanent tag `{tag}`."
        ),
    )
    _ensure_issue_label(root, repository, issue_number, PROCESSED_LABEL)
    _gh(
        root,
        "api",
        "--method",
        "PATCH",
        f"repos/{repository}/issues/{issue_number}",
        "-f",
        "state=closed",
    )
    return payload


def _superseded_payload(
    issue_number: int,
    pr: dict,
    base_sha: str,
    generation_commit: str,
    status_id: int,
) -> dict:
    branch = pr.get("headRefName")
    match = BRANCH_RE.fullmatch(branch) if isinstance(branch, str) else None
    if (
        match is None
        or int(match.group(1)) != issue_number
        or not COMMIT_SHA_RE.fullmatch(base_sha)
        or not COMMIT_SHA_RE.fullmatch(generation_commit)
        or not COMMIT_SHA_RE.fullmatch(pr.get("headRefOid", ""))
        or not isinstance(status_id, int)
        or isinstance(status_id, bool)
        or status_id < 1
    ):
        raise ReleaseError("E_SUPERSEDED_MARKER: invalid attempt provenance")
    attempt = branch.removeprefix("zoo-v2/")
    return {
        "schema": SUPERSEDED_MARKER_SCHEMA,
        "issue": issue_number,
        "pr": pr["number"],
        "attempt": attempt,
        "candidate_head": pr["headRefOid"],
        "invalidating_base": base_sha,
        "invalidating_status_id": status_id,
        "generation": f"api/v2/generations/{attempt}.json",
        "generation_commit": generation_commit,
        "tag": store.generation_tag_name(attempt),
    }


def _validate_superseded_payload(
    root: Path,
    repository: str,
    issue_number: int,
    payload: dict,
    *,
    allow_open: bool = False,
    remote: str = "origin",
) -> dict:
    required = {
        "schema", "issue", "pr", "attempt", "candidate_head",
        "invalidating_base", "invalidating_status_id", "generation",
        "generation_commit", "tag",
    }
    if set(payload) != required or payload.get("issue") != issue_number:
        raise ReleaseError("E_SUPERSEDED_MARKER: marker fields differ")
    pr = _exact_pr(root, repository, payload.get("pr"))
    expected = _superseded_payload(
        issue_number,
        pr,
        payload.get("invalidating_base"),
        payload.get("generation_commit"),
        payload.get("invalidating_status_id"),
    )
    allowed_states = {"CLOSED", "OPEN"} if allow_open else {"CLOSED"}
    if (
        pr.get("state") not in allowed_states
        or pr.get("mergedAt")
        or payload != expected
    ):
        raise ReleaseError("E_SUPERSEDED_MARKER: marker/closed PR differ")
    _git(root, "fetch", "--prune", remote, "main")
    _git(root, "fetch", "--tags", remote)
    _require_main_commit(
        root,
        payload["invalidating_base"],
        remote=remote,
    )
    _failed_stale_status(
        root,
        repository,
        payload["candidate_head"],
        payload["attempt"],
        payload["invalidating_base"],
        status_id=payload["invalidating_status_id"],
    )
    generation_bytes = _show(
        root, payload["generation_commit"], payload["generation"]
    )
    if generation_bytes is None:
        raise ReleaseError("E_SUPERSEDED_MARKER: immutable generation is missing")
    generation = json.loads(generation_bytes)
    if (
        generation.get("generation_id") != payload["attempt"]
        or generation.get("source_issue") != issue_number
        or store.canonical_json(generation) != generation_bytes
    ):
        raise ReleaseError("E_SUPERSEDED_MARKER: generation provenance differs")
    if _tag_target(root, payload["tag"]) != payload["generation_commit"]:
        raise ReleaseError("E_SUPERSEDED_MARKER: permanent tag differs")
    base_discovery = _show(
        root, payload["invalidating_base"], "api/v2/discovery.json"
    )
    if base_discovery is None:
        raise ReleaseError("E_SUPERSEDED_MARKER: invalidating base is unavailable")
    current_url = store.validate_discovery(json.loads(base_discovery))
    current_match = store.validate_generation_raw_url(
        current_url, "invalidating-base discovery"
    )
    if (
        current_match.group("owner") + "/" + current_match.group("repo")
        != repository
    ):
        raise ReleaseError(
            "E_SUPERSEDED_MARKER: invalidating discovery repository differs"
        )
    current_bytes = _show(
        root,
        current_match.group("commit"),
        current_match.group("path"),
    )
    if current_bytes is None:
        raise ReleaseError(
            "E_SUPERSEDED_MARKER: invalidating discovery generation is unavailable"
        )
    current_generation = json.loads(current_bytes)
    store.validate_generation(current_generation, network=False)
    if store.canonical_json(current_generation) != current_bytes:
        raise ReleaseError(
            "E_SUPERSEDED_MARKER: invalidating discovery generation is not canonical"
        )
    if generation.get("previous_generation_url") == current_url:
        raise ReleaseError("E_SUPERSEDED_MARKER: attempt is not stale at recorded base")
    return pr


def supersede_pr(
    root: Path,
    repository: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
    status_id: int,
    *,
    remote: str = "origin",
) -> dict:
    """Audit and close exactly one stale, unmerged attempt without deleting evidence."""
    _validate_repository(repository)
    require_protection_audit(root, repository)
    if not COMMIT_SHA_RE.fullmatch(base_sha) or not COMMIT_SHA_RE.fullmatch(head_sha):
        raise ReleaseError("E_SUPERSEDE: base/head must be full commit SHAs")
    _git(root, "fetch", "--prune", remote, "main")
    _git(root, "fetch", "--tags", remote)
    _require_main_commit(root, base_sha, remote=remote)
    pr = _exact_pr(root, repository, pr_number)
    issue_number = _issue_number_from_branch(pr.get("headRefName"))
    if (
        issue_number is None
        or pr.get("state") != "OPEN"
        or pr.get("mergedAt")
        or pr.get("baseRefName") != "main"
        or pr.get("headRefOid") != head_sha
    ):
        raise ReleaseError("E_SUPERSEDE: exact open unmerged Zoo v2 PR is required")
    attempt = pr["headRefName"].removeprefix("zoo-v2/")
    failed_status = _failed_stale_status(
        root,
        repository,
        head_sha,
        attempt,
        base_sha,
        status_id=status_id,
    )
    generation_path = f"api/v2/generations/{attempt}.json"
    generation_bytes = _show(root, head_sha, generation_path)
    if generation_bytes is None:
        raise ReleaseError("E_SUPERSEDE: candidate generation is missing")
    generation = json.loads(generation_bytes)
    store.validate_generation(generation, network=False)
    if (
        generation.get("generation_id") != attempt
        or generation.get("source_issue") != issue_number
        or store.canonical_json(generation) != generation_bytes
    ):
        raise ReleaseError("E_SUPERSEDE: candidate generation provenance differs")
    base_discovery = _show(root, base_sha, "api/v2/discovery.json")
    if base_discovery is None:
        raise ReleaseError("E_SUPERSEDE: current-main discovery is missing")
    current_url = store.validate_discovery(json.loads(base_discovery))
    if generation.get("previous_generation_url") == current_url:
        raise ReleaseError("E_SUPERSEDE: candidate is not stale against current main")
    generation_commit = _generation_commit(root, head_sha, generation_path)
    tag = store.generation_tag_name(attempt)
    if _tag_target(root, tag) != generation_commit:
        raise ReleaseError("E_SUPERSEDE: candidate permanent tag differs")
    generation_parent = _git(root, "rev-parse", f"{generation_commit}^")
    if (
        _git(root, "rev-parse", f"{head_sha}^") != generation_commit
        or set(complete_changed_files(root, generation_parent, head_sha))
        != {generation_path, "api/v2/discovery.json"}
    ):
        raise ReleaseError("E_SUPERSEDE: candidate attempt history/diff is not exact")
    candidate_discovery_bytes = _show(
        root, head_sha, "api/v2/discovery.json"
    )
    if candidate_discovery_bytes is None:
        raise ReleaseError("E_SUPERSEDE: candidate discovery is missing")
    candidate_url = store.validate_discovery(
        json.loads(candidate_discovery_bytes)
    )
    candidate_match = store.validate_generation_raw_url(
        candidate_url, "candidate discovery"
    )
    if (
        candidate_match.group("owner") + "/" + candidate_match.group("repo")
        != repository
        or candidate_match.group("commit") != generation_commit
        or candidate_match.group("path") != generation_path
    ):
        raise ReleaseError("E_SUPERSEDE: candidate discovery provenance differs")

    current = _exact_pr(root, repository, pr_number)
    if (
        current.get("state") != "OPEN"
        or current.get("mergedAt")
        or current.get("headRefOid") != head_sha
    ):
        raise ReleaseError("E_SUPERSEDE_RACE: PR changed before retirement")
    payload = _superseded_payload(
        issue_number,
        current,
        base_sha,
        generation_commit,
        failed_status["id"],
    )
    marker = _audit_marker("superseded", payload)
    _gh(
        root,
        "api",
        "--method",
        "PATCH",
        f"repos/{repository}/issues/{issue_number}",
        "-f",
        "state=open",
    )
    _ensure_audit_comment(
        root,
        repository,
        issue_number,
        marker,
        (
            f"Superseded PR {current['url']} at current base `{base_sha}`. "
            f"Attempt `{attempt}`, generation `{generation_path}`, and permanent "
            f"tag `{tag}` remain immutable evidence. Scheduled reconciliation may retry."
        ),
    )
    _ensure_issue_label(root, repository, issue_number, SUPERSEDED_LABEL)
    _gh(
        root,
        "api",
        "--method",
        "PATCH",
        f"repos/{repository}/pulls/{pr_number}",
        "-f",
        "state=closed",
    )
    return payload


def reconcile_eligible_issues(
    root: Path,
    repository: str,
    *,
    remote: str = "origin",
) -> dict:
    """Reconcile durable issue/PR markers and select the oldest pending command."""
    _validate_repository(repository)
    require_protection_audit(root, repository)
    issues = _eligible_issue_pages(root, repository)
    branches = _remote_issue_branches(root, remote)
    prs = list_catalog_prs(root, repository, branches)
    by_issue: dict[int, list[dict]] = {}
    for pr in prs:
        issue_number = _issue_number_from_branch(pr.get("headRefName"))
        if issue_number is None:
            raise ReleaseError("E_RECONCILE_INCOMPLETE: catalog PR branch is malformed")
        by_issue.setdefault(issue_number, []).append(pr)

    candidates = []
    open_prs = []
    states = []
    for issue in issues:
        number = issue["number"]
        labels = set(issue["_label_names"])
        comments = _issue_comments(root, repository, number)
        issue_prs = list(by_issue.get(number, []))
        pr_markers = _marker_payloads(
            root, comments, "pr", PR_MARKER_SCHEMA, repository
        )
        for payload in pr_markers:
            if set(payload) != {"schema", "issue", "pr", "attempt"}:
                raise ReleaseError("E_PR_MARKER: marker fields differ")
            if payload.get("issue") != number:
                raise ReleaseError("E_PR_MARKER: marker issue differs")
            pr = _exact_pr(root, repository, payload.get("pr"))
            expected_branch = f"zoo-v2/{payload.get('attempt')}"
            if (
                pr.get("headRefName") != expected_branch
                or _issue_number_from_branch(expected_branch) != number
            ):
                raise ReleaseError("E_PR_MARKER: marker/PR attempt differs")
            if not any(existing.get("number") == pr["number"] for existing in issue_prs):
                issue_prs.append(pr)

        superseded_markers = _marker_payloads(
            root,
            comments,
            "superseded",
            SUPERSEDED_MARKER_SCHEMA,
            repository,
        )
        superseded = {}
        for payload in superseded_markers:
            superseded_pr = _validate_superseded_payload(
                root,
                repository,
                number,
                payload,
                allow_open=True,
            )
            superseded[superseded_pr["number"]] = superseded_pr
            if superseded_pr["state"] == "OPEN":
                _gh(
                    root,
                    "api",
                    "--method",
                    "PATCH",
                    f"repos/{repository}/pulls/{superseded_pr['number']}",
                    "-f",
                    "state=closed",
                )
                _ensure_issue_label(
                    root, repository, number, SUPERSEDED_LABEL
                )
                _gh(
                    root,
                    "api",
                    "--method",
                    "PATCH",
                    f"repos/{repository}/issues/{number}",
                    "-f",
                    "state=open",
                )
                for existing in issue_prs:
                    if existing.get("number") == superseded_pr["number"]:
                        existing["state"] = "CLOSED"

        active = [pr for pr in issue_prs if pr.get("state") == "OPEN"]
        merged = [
            pr for pr in issue_prs
            if pr.get("state") == "CLOSED" and pr.get("mergedAt")
        ]
        closed_unmerged = [
            pr for pr in issue_prs
            if pr.get("state") == "CLOSED" and not pr.get("mergedAt")
        ]
        if len(active) > 1:
            raise ReleaseError(
                f"E_RECONCILE_INCOMPLETE: issue #{number} has multiple open PRs"
            )
        completion_markers = _marker_payloads(
            root, comments, "completed", COMPLETION_MARKER_SCHEMA, repository
        )
        completed_prs = [
            _validate_completion_payload(
                root, repository, number, payload, remote=remote
            )
            for payload in completion_markers
        ]
        if len({pr["number"] for pr in completed_prs}) > 1:
            raise ReleaseError(
                f"E_PROCESSED_MARKER: issue #{number} has conflicting completions"
            )
        if PROCESSED_LABEL in labels:
            if not completed_prs:
                raise ReleaseError(
                    f"E_PROCESSED_MARKER: issue #{number} lacks a valid completion marker"
                )
            _gh(
                root,
                "api",
                "--method",
                "PATCH",
                f"repos/{repository}/issues/{number}",
                "-f",
                "state=closed",
            )
            states.append({"number": number, "state": "processed"})
            continue
        if TOMBSTONED_LABEL in labels:
            if active:
                raise ReleaseError(
                    f"E_RECONCILE_INCOMPLETE: tombstoned issue #{number} has an open PR"
                )
            states.append({"number": number, "state": "tombstoned"})
            continue
        if completed_prs:
            _ensure_issue_label(root, repository, number, PROCESSED_LABEL)
            _gh(
                root,
                "api",
                "--method",
                "PATCH",
                f"repos/{repository}/issues/{number}",
                "-f",
                "state=closed",
            )
            states.append({"number": number, "state": "processed"})
            continue
        if merged:
            if len(merged) > 1:
                raise ReleaseError(
                    f"E_RECONCILE_INCOMPLETE: issue #{number} has multiple merged PRs"
                )
            finalize_merged_pr(
                root, repository, merged[0]["number"], remote=remote
            )
            states.append({"number": number, "state": "processed"})
            continue
        if active:
            states.append({"number": number, "state": "open-pr"})
            open_prs.extend(active)
            continue
        if closed_unmerged:
            untrusted_closures = [
                pr["number"] for pr in closed_unmerged
                if pr["number"] not in superseded
            ]
            if untrusted_closures:
                raise ReleaseError(
                    f"E_RECONCILE_BLOCKED: issue #{number} has arbitrary closed "
                    "unmerged PR(s): "
                    + ", ".join(f"#{pr}" for pr in untrusted_closures)
                )
        if not STORE_TITLE_RE.match(issue["title"]):
            raise ReleaseError(
                f"E_RECONCILE_INCOMPLETE: eligible issue #{number} has an invalid title"
            )
        states.append({
            "number": number,
            "state": "retryable" if closed_unmerged else "pending",
        })
        candidates.append(issue)

    if open_prs:
        blocked = sorted({pr["number"] for pr in open_prs})
        return {
            "selected": None,
            "blocked_by_prs": blocked,
            "scanned": len(issues),
            "states": states,
        }
    selected = candidates[0] if candidates else None
    event = None
    if selected is not None:
        event_issue = {
            key: value for key, value in selected.items() if not key.startswith("_")
        }
        event = {
            "action": "reconciled",
            "issue": event_issue,
            "repository": {"full_name": repository},
        }
    return {
        "selected": selected["number"] if selected is not None else None,
        "event": event,
        "blocked_by_prs": [],
        "scanned": len(issues),
        "states": states,
    }


def validate_queue(
    issue_number: int,
    remote_branches: set[str],
    pull_requests: list[dict],
) -> None:
    """Permit one issue lane; merged branches are durable history, not open lanes."""
    def belongs_to_issue(candidate: str) -> bool:
        match = BRANCH_RE.fullmatch(candidate)
        return match is not None and int(match.group(1)) == issue_number

    open_prs = [
        pr for pr in pull_requests
        if pr.get("state") == "OPEN"
        and (
            not isinstance(pr.get("headRefName"), str)
            or not belongs_to_issue(pr["headRefName"])
        )
    ]
    if open_prs:
        blocked = ", ".join(f"#{pr.get('number')}" for pr in open_prs)
        raise ReleaseError(f"E_QUEUE_BUSY: open Zoo v2 catalog PR(s): {blocked}")

    by_branch = {pr.get("headRefName"): pr for pr in pull_requests}
    incomplete = []
    for sibling in sorted(
        candidate for candidate in remote_branches if not belongs_to_issue(candidate)
    ):
        prior = by_branch.get(sibling)
        if prior is None or not prior.get("mergedAt"):
            incomplete.append(sibling)
    if incomplete:
        raise ReleaseError(
            "E_QUEUE_BUSY: unfinished Zoo v2 issue branch(es): " + ", ".join(incomplete)
        )


def _show(root: Path, revision: str, path: str) -> bytes | None:
    result = _run(
        ["git", "show", f"{revision}:{path}"],
        cwd=root,
        check=False,
    )
    if result.returncode:
        return None
    return result.stdout.encode()


def _generation_commit(root: Path, revision: str, generation_path: str) -> str:
    commits = _git(
        root,
        "log",
        "--format=%H",
        "--diff-filter=A",
        revision,
        "--",
        generation_path,
    ).splitlines()
    if len(commits) != 1:
        raise ReleaseError(
            f"E_GENERATION_COMMIT: expected one introducing commit for {generation_path}"
        )
    commit = commits[0]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ReleaseError("E_GENERATION_COMMIT: Git did not return a full commit SHA")
    return commit


def _tag_target(root: Path, tag: str) -> str | None:
    result = _run(
        ["git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
        cwd=root,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def ensure_permanent_tag(
    root: Path,
    remote: str,
    generation: dict,
    generation_path: str,
    generation_commit: str,
    *,
    create: bool = True,
    expected_main: str | None = None,
    publish_branch: str | None = None,
    branch_head: str | None = None,
    expected_branch: str | None = None,
) -> str:
    tag = store.generation_tag_name(generation["generation_id"])
    message = store.generation_tag_message(generation, generation_path)
    remote_refs = _git(
        root,
        "ls-remote",
        remote,
        f"refs/tags/{tag}",
        f"refs/tags/{tag}^{{}}",
    )
    remote_exists = bool(remote_refs)
    if remote_exists:
        _git(
            root,
            "fetch",
            remote,
            f"refs/tags/{tag}:refs/tags/{tag}",
        )
    elif not create:
        raise ReleaseError(f"E_PERMANENT_REF: missing durable annotated tag {tag}")
    elif _tag_target(root, tag) is None:
        _git(root, "tag", "-a", tag, generation_commit, "-F", "-", input_text=message)

    if _git(root, "cat-file", "-t", f"refs/tags/{tag}") != "tag":
        raise ReleaseError(f"E_REF_COLLISION: {tag} is not an annotated tag")
    if _tag_target(root, tag) != generation_commit:
        raise ReleaseError(f"E_REF_COLLISION: {tag} points to another commit")
    actual_message = _git(root, "for-each-ref", "--format=%(contents)", f"refs/tags/{tag}")
    if actual_message.rstrip("\n") != message.rstrip("\n"):
        raise ReleaseError(f"E_REF_COLLISION: {tag} annotation content/provenance differs")
    if publish_branch is not None:
        if (
            not BRANCH_RE.fullmatch(publish_branch)
            or branch_head is None
            or not COMMIT_SHA_RE.fullmatch(branch_head)
            or (
                expected_branch is not None
                and not COMMIT_SHA_RE.fullmatch(expected_branch)
            )
        ):
            raise ReleaseError("E_REF_PUBLICATION: invalid branch publication lease")
    if not remote_exists or publish_branch is not None:
        if expected_main is None and publish_branch is None:
            _git(root, "push", remote, f"refs/tags/{tag}:refs/tags/{tag}")
        else:
            if expected_main is None or not COMMIT_SHA_RE.fullmatch(expected_main):
                raise ReleaseError("E_BASE: expected current main must be a full commit SHA")
            command = [
                "git",
                "push",
                "--atomic",
                f"--force-with-lease=refs/heads/main:{expected_main}",
            ]
            if publish_branch is not None:
                lease_value = expected_branch or ""
                command.append(
                    f"--force-with-lease=refs/heads/{publish_branch}:{lease_value}"
                )
            command.append(remote)
            if not remote_exists:
                command.append(f"refs/tags/{tag}:refs/tags/{tag}")
            if publish_branch is not None:
                command.append(f"{branch_head}:refs/heads/{publish_branch}")
            command.append(f"{expected_main}:refs/heads/main")
            publication = _run(
                command,
                cwd=root,
                check=False,
            )
            if publication.returncode:
                detail = publication.stderr.strip() or publication.stdout.strip()
                raise ReleaseError(
                    "E_STALE_PREDECESSOR: current main or attempt branch changed "
                    f"before atomic ref/tag publication: {detail}"
                )
    return tag


def _validate_expected_predecessor(
    root: Path,
    generation: dict,
    *,
    remote: str,
    base_generation_bytes: bytes | None = None,
) -> bytes:
    base_discovery_bytes = _show(
        root, f"refs/remotes/{remote}/main", "api/v2/discovery.json"
    )
    if base_discovery_bytes is None:
        raise ReleaseError("E_BASE: origin/main has no Zoo v2 discovery")
    base_discovery = json.loads(base_discovery_bytes)
    base_url = store.validate_discovery(base_discovery)
    if generation.get("previous_generation_url") != base_url:
        raise ReleaseError(
            "E_STALE_PREDECESSOR: issue generation was not derived from current origin/main"
        )
    exact_base = base_generation_bytes if base_generation_bytes is not None else store.fetch_bytes(base_url)
    if generation.get("previous_generation_sha256") != store.sha256_bytes(exact_base):
        raise ReleaseError(
            "E_STALE_PREDECESSOR: issue generation predecessor digest is not current origin/main"
        )
    return base_discovery_bytes


def _ensure_pr(root: Path, repository: str, issue_number: int, branch: str) -> dict:
    prs = [
        pr for pr in list_catalog_prs(root, repository, {branch})
        if pr.get("headRefName") == branch
    ]
    if len(prs) > 1:
        raise ReleaseError(f"E_PR_STATE: multiple pull requests exist for {branch}")
    if prs:
        pr = prs[0]
        if pr.get("baseRefName") != "main":
            raise ReleaseError("E_PR_STATE: existing pull request does not target main")
        if pr.get("state") != "OPEN":
            if pr.get("mergedAt"):
                return pr
            raise ReleaseError("E_PR_STATE: existing pull request was closed without merge")
    else:
        title = f"catalog(v2): issue #{issue_number}"
        body = "\n".join([
            f"Validated Zoo v2 catalog CRUD for #{issue_number}.",
            "",
            "The generation is protected by its permanent annotated tag before discovery is published.",
            "No auto-merge is configured; maintainer review and the required current-main check remain mandatory.",
            f"Tracks #{issue_number}; trusted automation records completion after merge.",
        ])
        url = _gh(
            root,
            "pr",
            "create",
            "--repo",
            repository,
            "--base",
            "main",
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        )
        number = int(url.rstrip("/").rsplit("/", 1)[-1])
        pr = {
            "number": number,
            "url": url,
            "state": "OPEN",
            "mergedAt": None,
            "headRefName": branch,
            "baseRefName": "main",
            "title": title,
        }

    attempt = branch.removeprefix("zoo-v2/")
    marker = _audit_marker("pr", {
        "schema": PR_MARKER_SCHEMA,
        "issue": issue_number,
        "pr": pr["number"],
        "attempt": attempt,
    })
    comments = _issue_comments(root, repository, issue_number)
    validator_app = protection.audit_app_identity(
        require_protection_audit(root, repository)
    )
    if not any(
        marker in item["body"] and _trusted_comment(item, validator_app)
        for item in comments
    ):
        _gh(
            root,
            "issue",
            "comment",
            str(issue_number),
            "--repo",
            repository,
            "--body",
            (
                f"{marker}\nValidated catalog PR: {pr['url']}. "
                "Opening this PR does not complete the command."
            ),
        )
    return pr


def _archive_prior_issue_attempts(
    root: Path,
    remote: str,
    issue_number: int,
    current_branch: str,
    remote_branches: set[str],
    before_publication: Callable[[], None] | None = None,
) -> list[str]:
    """Verify and permanently tag retained attempts before permitting a retry."""
    archived = []
    for branch in sorted(remote_branches - {current_branch}):
        match = BRANCH_RE.fullmatch(branch)
        if match is None or int(match.group(1)) != issue_number:
            continue
        generation_id = branch.removeprefix("zoo-v2/")
        generation_path = f"api/v2/generations/{generation_id}.json"
        remote_revision = f"refs/remotes/{remote}/{branch}"
        _git(
            root,
            "fetch",
            remote,
            f"refs/heads/{branch}:{remote_revision}",
        )
        generation_bytes = _show(root, remote_revision, generation_path)
        if generation_bytes is None:
            raise ReleaseError(
                f"E_ARCHIVE_ATTEMPT: {branch} has no exact generation path"
            )
        try:
            generation = json.loads(generation_bytes)
        except json.JSONDecodeError as exc:
            raise ReleaseError(
                f"E_ARCHIVE_ATTEMPT: {branch} generation is invalid JSON"
            ) from exc
        store.validate_generation(generation, network=False)
        if (
            generation.get("source_issue") != issue_number
            or generation.get("generation_id") != generation_id
            or store.canonical_json(generation) != generation_bytes
        ):
            raise ReleaseError(
                f"E_ARCHIVE_ATTEMPT: {branch} generation provenance differs"
            )
        generation_commit = _generation_commit(
            root, remote_revision, generation_path
        )
        if before_publication:
            before_publication()
        archived.append(
            ensure_permanent_tag(
                root,
                remote,
                generation,
                generation_path,
                generation_commit,
            )
        )
    return archived


def _refresh_release_validation(
    root: Path,
    repository: str,
    issue_number: int,
    generation: dict,
    *,
    remote: str,
    create_pr: bool,
    pull_requests: list[dict] | None,
    base_generation_bytes: bytes | None,
) -> tuple[set[str], list[dict], bytes]:
    """Refresh authoritative main/queue state immediately before publication."""
    _git(root, "fetch", "--prune", remote, "main")
    remote_branches = _remote_issue_branches(root, remote)
    prs = (
        list_catalog_prs(root, repository, remote_branches)
        if pull_requests is None and create_pr
        else list(pull_requests or [])
    )
    validate_queue(issue_number, remote_branches, prs)
    base_discovery = _validate_expected_predecessor(
        root,
        generation,
        remote=remote,
        base_generation_bytes=base_generation_bytes,
    )
    return remote_branches, prs, base_discovery


def resume_release(
    root: Path,
    generation_path: str,
    repository: str,
    issue_number: int,
    *,
    remote: str = "origin",
    pull_requests: list[dict] | None = None,
    create_pr: bool = True,
    stop_after: str | None = None,
    base_generation_bytes: bytes | None = None,
    stage_hook: Callable[[str], None] | None = None,
    pr_ensurer: Callable[[Path, str, int, str], dict] | None = None,
    lock_owner: dict | None = None,
    issue_snapshot: dict | None = None,
    allowed_actors: set[str] | None = None,
    verify_issue: bool | None = None,
) -> dict:
    """Resume a release without rewriting any existing branch, tag, or PR state."""
    root = root.resolve()
    _validate_repository(repository)
    require_protection_audit(root, repository)
    path = Path(generation_path)
    expected_bytes = (root / path).read_bytes()
    generation = json.loads(expected_bytes)
    store.validate_generation(generation, network=False)
    if store.canonical_json(generation) != expected_bytes:
        raise ReleaseError("E_NON_CANONICAL_JSON: expected issue generation is not canonical")
    if generation.get("source_issue") != issue_number:
        raise ReleaseError("E_ISSUE_MISMATCH: generation source_issue differs")
    generation_id = generation.get("generation_id")
    if (
        not isinstance(generation_id, str)
        or not generation_id.startswith(f"issue-{issue_number}-")
        or path.as_posix() != f"api/v2/generations/{generation_id}.json"
    ):
        raise ReleaseError("E_ISSUE_MISMATCH: generation id/path differs from issue")

    branch = f"zoo-v2/{generation_id}"
    tag = store.generation_tag_name(generation["generation_id"])
    owner = lock_owner or release_lock_owner(
        repository,
        issue_number,
        generation_id,
    )
    must_verify_issue = create_pr if verify_issue is None else verify_issue
    if must_verify_issue and (
        issue_snapshot is None or not allowed_actors
    ):
        raise ReleaseError(
            "E_ISSUE_SNAPSHOT: release requires a reconciled issue snapshot "
            "and non-empty actor allowlist"
        )
    lease = acquire_release_lock(root, remote, owner)
    try:
        if stage_hook:
            stage_hook("lock-acquired")
        def revalidate() -> None:
            _refresh_release_validation(
                root,
                repository,
                issue_number,
                generation,
                remote=remote,
                create_pr=create_pr,
                pull_requests=pull_requests,
                base_generation_bytes=base_generation_bytes,
            )
            if must_verify_issue:
                assert issue_snapshot is not None
                assert allowed_actors is not None
                validate_selected_issue(
                    root,
                    repository,
                    issue_number,
                    issue_snapshot,
                    allowed_actors,
                    generation,
                    expected_bytes,
                    remote=remote,
                    base_generation_bytes=base_generation_bytes,
                )

        remote_branches, _, base_discovery_bytes = _refresh_release_validation(
            root,
            repository,
            issue_number,
            generation,
            remote=remote,
            create_pr=create_pr,
            pull_requests=pull_requests,
            base_generation_bytes=base_generation_bytes,
        )
        if must_verify_issue:
            assert issue_snapshot is not None
            assert allowed_actors is not None
            validate_selected_issue(
                root,
                repository,
                issue_number,
                issue_snapshot,
                allowed_actors,
                generation,
                expected_bytes,
                remote=remote,
                base_generation_bytes=base_generation_bytes,
            )

        archived_tags = _archive_prior_issue_attempts(
            root,
            remote,
            issue_number,
            branch,
            remote_branches,
            before_publication=revalidate,
        )

        branch_exists = branch in remote_branches
        branch_expected_sha = None
        local_expected = root / path
        if branch_exists:
            tracked = _run(
                ["git", "ls-files", "--error-unmatch", path.as_posix()],
                cwd=root,
                check=False,
            ).returncode == 0
            if not tracked:
                local_expected.unlink()
            _git(
                root,
                "fetch",
                remote,
                f"refs/heads/{branch}:refs/remotes/{remote}/{branch}",
            )
            remote_revision = f"refs/remotes/{remote}/{branch}"
            branch_expected_sha = _git(root, "rev-parse", remote_revision)
            branch_bytes = _show(root, remote_revision, path.as_posix())
            if branch_bytes != expected_bytes:
                raise ReleaseError(
                    "E_IMMUTABLE_GENERATION: existing issue branch has mismatched "
                    "generation bytes"
                )
            _git(root, "switch", "--discard-changes", "-C", branch, remote_revision)
            generation_commit = _generation_commit(
                root, remote_revision, path.as_posix()
            )
        else:
            _git(root, "switch", "-C", branch, f"refs/remotes/{remote}/main")
            local_expected.parent.mkdir(parents=True, exist_ok=True)
            local_expected.write_bytes(expected_bytes)
            _git(root, "add", path.as_posix())
            _git(
                root,
                "commit",
                "-m",
                f"catalog(v2): generation for issue #{issue_number}",
            )
            generation_commit = _git(root, "rev-parse", "HEAD")
        if _show(root, generation_commit, path.as_posix()) != expected_bytes:
            raise ReleaseError("E_GENERATION_COMMIT: generation commit content differs")

        _, _, base_discovery_bytes = _refresh_release_validation(
            root,
            repository,
            issue_number,
            generation,
            remote=remote,
            create_pr=create_pr,
            pull_requests=pull_requests,
            base_generation_bytes=base_generation_bytes,
        )
        expected_discovery = store.canonical_json({
            "schema": store.DISCOVERY_SCHEMA,
            "generation_url": (
                f"https://raw.githubusercontent.com/{repository}/{generation_commit}/"
                f"{path.as_posix()}"
            ),
        })
        current_discovery = (root / "api/v2/discovery.json").read_bytes()
        if current_discovery == base_discovery_bytes:
            (root / "api/v2/discovery.json").write_bytes(expected_discovery)
            _git(root, "add", "api/v2/discovery.json")
            _git(
                root,
                "commit",
                "-m",
                f"catalog(v2): pin discovery for issue #{issue_number}",
            )
        elif current_discovery != expected_discovery:
            raise ReleaseError(
                "E_DISCOVERY_COLLISION: issue branch has a different discovery pointer"
            )
        branch_head = _git(root, "rev-parse", "HEAD")

        for publication_stage in (
            "before-generation-push",
            "before-tag-push",
            "before-discovery-push",
        ):
            if stage_hook:
                stage_hook(publication_stage)
            revalidate()
        current_main = _git(root, "rev-parse", f"refs/remotes/{remote}/main")
        ensure_permanent_tag(
            root,
            remote,
            generation,
            path.as_posix(),
            generation_commit,
            expected_main=current_main,
            publish_branch=branch,
            branch_head=branch_head,
            expected_branch=branch_expected_sha,
        )
        _git(root, "branch", "--set-upstream-to", f"{remote}/{branch}", branch)
        if _tag_target(root, tag) != generation_commit:
            raise ReleaseError(
                "E_PERMANENT_REF: discovery cannot publish before permanent tag"
            )
        for completed_stage in (
            "generation-push",
            "tag-push",
            "discovery-push",
        ):
            if stage_hook:
                stage_hook(completed_stage)
            if stop_after == completed_stage:
                raise RuntimeError(f"simulated failure after {completed_stage}")

        revalidate()
        ensure_pr = pr_ensurer or _ensure_pr
        pr = ensure_pr(root, repository, issue_number, branch) if create_pr else None
        if stage_hook:
            stage_hook("pr")
        if stop_after == "pr":
            raise RuntimeError("simulated failure after PR")
        return {
            "branch": branch,
            "tag": tag,
            "generation_commit": generation_commit,
            "archived_tags": archived_tags,
            "pr": pr,
            "lock_owner_sha": lease["owner_sha"],
        }
    finally:
        try:
            if stage_hook:
                stage_hook("before-lock-release")
        finally:
            release_release_lock(root, remote, lease)


def validate_pr(root: Path, repository: str, remote: str = "origin") -> None:
    """Reject stale or unprotected candidates against freshly fetched origin/main."""
    _validate_repository(repository)
    _git(root, "fetch", "--prune", remote, "main")
    base_bytes = _show(root, f"refs/remotes/{remote}/main", "api/v2/discovery.json")
    if base_bytes is None:
        raise ReleaseError("E_BASE: current origin/main discovery is missing")
    base_sha = _git(root, "rev-parse", f"refs/remotes/{remote}/main")
    head_sha = _git(root, "rev-parse", "HEAD")
    base_path = root / ".zoo-v2-main-discovery.json"
    base_path.write_bytes(base_bytes)
    try:
        discovery = json.loads((root / "api/v2/discovery.json").read_text())
        candidate_url = store.validate_discovery(discovery)
        match = store.validate_generation_raw_url(
            candidate_url, "discovery.generation_url"
        )
        if f"{match.group('owner')}/{match.group('repo')}" != repository:
            raise ReleaseError("E_REPOSITORY: discovery points outside this repository")
        commit = match.group("commit")
        generation_path = match.group("path")
        candidate_path = root / generation_path
        if not candidate_path.is_file():
            raise ReleaseError("E_DISCOVERY_TARGET: candidate generation is absent")
        if _show(root, commit, generation_path) != candidate_path.read_bytes():
            raise ReleaseError(
                "E_DISCOVERY_TARGET: pinned commit does not contain exact generation"
            )
        _git(root, "merge-base", "--is-ancestor", commit, "HEAD")
        generation = json.loads(candidate_path.read_text())
        generation_id = generation.get("generation_id")
        source_issue = generation.get("source_issue")
        if (
            not isinstance(source_issue, int)
            or not isinstance(generation_id, str)
            or generation_path
            != f"api/v2/generations/{generation_id}.json"
            or not generation_id.startswith(f"issue-{source_issue}-")
        ):
            raise ReleaseError(
                "E_PROTECTED_PR: candidate must use its issue's exact generation path"
            )
        changed = set(complete_changed_files(root, base_sha, head_sha))
        expected_changed = {
            "api/v2/discovery.json",
            generation_path,
        }
        if changed != expected_changed:
            raise ReleaseError(
                "E_PROTECTED_PR: candidate changed-file set must be exactly "
                + ", ".join(sorted(expected_changed))
            )
        if _generation_commit(root, "HEAD", generation_path) != commit:
            raise ReleaseError(
                "E_GENERATION_COMMIT: discovery must pin the introducing commit"
            )
        ensure_permanent_tag(
            root,
            remote,
            generation,
            generation_path,
            commit,
            create=False,
        )
        store.validate_candidate(
            base_path,
            root / "api/v2/discovery.json",
            candidate_path,
        )
    finally:
        base_path.unlink(missing_ok=True)


def protect_generation(root: Path, repository: str, generation_path: str, remote: str) -> dict:
    root = root.resolve()
    _validate_repository(repository)
    require_protection_audit(root, repository)
    generation = json.loads((root / generation_path).read_text())
    store.validate_generation(generation, network=False)
    owner = release_lock_owner(
        repository,
        generation.get("source_issue"),
        generation.get("generation_id"),
    )
    lease = acquire_release_lock(root, remote, owner)
    try:
        _git(root, "fetch", "--prune", remote, "main")
        current_main = _git(root, "rev-parse", f"refs/remotes/{remote}/main")
        commit = _generation_commit(
            root, f"refs/remotes/{remote}/main", generation_path
        )
        tag = ensure_permanent_tag(
            root,
            remote,
            generation,
            generation_path,
            commit,
            expected_main=current_main,
        )
        return {"tag": tag, "commit": commit}
    finally:
        release_release_lock(root, remote, lease)


def audit_refs(
    root: Path,
    repository: str,
    remote: str = "origin",
    *,
    network: bool = False,
    fetcher: store.Fetch = store.fetch_bytes,
) -> list[dict]:
    _validate_repository(repository)
    _git(root, "fetch", "--prune", remote, "main")
    records = []
    generations: dict[str, dict] = {}
    main_ref = f"refs/remotes/{remote}/main"
    relative_paths = [
        value
        for value in _git(
            root,
            "ls-tree",
            "-r",
            "--name-only",
            main_ref,
            "api/v2/generations",
        ).splitlines()
        if value.endswith(".json")
    ]
    for relative in sorted(relative_paths):
        main_bytes = _show(root, main_ref, relative)
        if main_bytes is None:
            raise ReleaseError(f"E_GENERATION: cannot read {relative} from current main")
        generation = json.loads(main_bytes)
        if generation.get("generation_id") != Path(relative).stem:
            raise ReleaseError(
                f"E_GENERATION: filename does not match generation_id: {relative}"
            )
        store.validate_generation(generation, fetcher, network=network)
        generations[relative] = generation
        tag = store.generation_tag_name(generation["generation_id"])
        refs = _git(
            root,
            "ls-remote",
            remote,
            f"refs/tags/{tag}",
            f"refs/tags/{tag}^{{}}",
        )
        if not refs:
            raise ReleaseError(f"E_PERMANENT_REF: missing {tag}")
        _git(root, "fetch", remote, f"refs/tags/{tag}:refs/tags/{tag}")
        commit = _tag_target(root, tag)
        if commit is None:
            raise ReleaseError(f"E_PERMANENT_REF: {tag} does not resolve to a commit")
        expected_message = store.generation_tag_message(generation, relative)
        actual_message = _git(
            root,
            "for-each-ref",
            "--format=%(contents)",
            f"refs/tags/{tag}",
        )
        if actual_message.rstrip("\n") != expected_message.rstrip("\n"):
            raise ReleaseError(f"E_PERMANENT_REF: {tag} provenance annotation differs")
        committed = _show(root, commit, relative)
        if committed != main_bytes:
            raise ReleaseError(f"E_RAW_REACHABILITY: {relative} changed after introduction")
        raw_url = f"https://raw.githubusercontent.com/{repository}/{commit}/{relative}"
        if network and fetcher(raw_url) != committed:
            raise ReleaseError(f"E_RAW_REACHABILITY: raw bytes differ for {relative}")
        records.append({
            "generation_id": generation["generation_id"],
            "tag": tag,
            "commit": commit,
            "content_sha256": store.sha256_bytes(committed or b""),
            "raw_url": raw_url,
        })

    records_by_raw_url = {record["raw_url"]: record for record in records}
    for relative, generation in generations.items():
        previous_url = generation["previous_generation_url"]
        if previous_url is None:
            continue
        predecessor_record = records_by_raw_url.get(previous_url)
        if predecessor_record is None:
            raise ReleaseError(
                f"E_PERMANENT_REF: predecessor of {relative} has no exact permanent ref"
            )
        predecessor = generations.get(
            store.validate_pinned_raw_url(
                previous_url, "generation.previous_generation_url"
            ).group("path")
        )
        if predecessor is None:
            raise ReleaseError(f"E_GENERATION_CHAIN: predecessor of {relative} is absent")
        store.validate_generation(
            generation,
            fetcher,
            network=network,
            previous=predecessor,
        )

    discovery_bytes = _show(root, main_ref, "api/v2/discovery.json")
    if discovery_bytes is None:
        raise ReleaseError("E_DISCOVERY: current main discovery is missing")
    discovery = json.loads(discovery_bytes)
    current_url = store.validate_discovery(discovery)
    if current_url not in records_by_raw_url:
        raise ReleaseError(
            "E_PERMANENT_REF: discovery URL has no exact matching generation tag"
        )
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    resume = sub.add_parser("resume")
    resume.add_argument("--root", default=".")
    resume.add_argument("--generation", required=True)
    resume.add_argument("--repository", required=True)
    resume.add_argument("--issue-number", type=int, required=True)
    resume.add_argument("--remote", default="origin")
    resume.add_argument("--event-path", required=True)
    resume.add_argument("--allow-actors", required=True)

    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--root", default=".")
    reconcile.add_argument("--repository", required=True)
    reconcile.add_argument("--remote", default="origin")
    reconcile.add_argument("--event-output", required=True)
    reconcile.add_argument("--github-output")

    recover = sub.add_parser("recover-lock")
    recover.add_argument("--root", default=".")
    recover.add_argument("--repository", required=True)
    recover.add_argument("--remote", default="origin")
    recover.add_argument("--expected-owner-sha", required=True)
    recover.add_argument("--reason", required=True)
    recover.add_argument("--admin-actor", required=True)

    complete = sub.add_parser("complete-merge")
    complete.add_argument("--root", default=".")
    complete.add_argument("--repository", required=True)
    complete.add_argument("--pr-number", type=int, required=True)
    complete.add_argument("--remote", default="origin")

    supersede = sub.add_parser("supersede-pr")
    supersede.add_argument("--root", default=".")
    supersede.add_argument("--repository", required=True)
    supersede.add_argument("--pr-number", type=int, required=True)
    supersede.add_argument("--base-sha", required=True)
    supersede.add_argument("--head-sha", required=True)
    supersede.add_argument("--status-id", type=int, required=True)

    validate = sub.add_parser("validate-pr")
    validate.add_argument("--root", default=".")
    validate.add_argument("--repository", required=True)
    validate.add_argument("--remote", default="origin")

    list_prs = sub.add_parser("list-prs")
    list_prs.add_argument("--root", default=".")
    list_prs.add_argument("--repository", required=True)
    list_prs.add_argument("--remote", default="origin")
    list_prs.add_argument("--state", choices=("all", "open"), default="all")

    gate = sub.add_parser("gate-pr")
    gate.add_argument("--root", default=".")
    gate.add_argument("--base-sha", required=True)
    gate.add_argument("--head-sha", required=True)
    gate.add_argument("--head-ref", required=True)
    gate.add_argument("--head-repository", required=True)
    gate.add_argument("--repository", required=True)

    bootstrap = sub.add_parser("validate-bootstrap-pr")
    bootstrap.add_argument("--root", default=".")
    bootstrap.add_argument("--base-sha", required=True)
    bootstrap.add_argument("--head-sha", required=True)
    bootstrap.add_argument("--repository", required=True)

    protect = sub.add_parser("protect-bootstrap")
    protect.add_argument("--root", default=".")
    protect.add_argument("--repository", required=True)
    protect.add_argument(
        "--generation",
        default="api/v2/generations/bootstrap-20260822.json",
    )
    protect.add_argument("--remote", default="origin")

    audit = sub.add_parser("audit-refs")
    audit.add_argument("--root", default=".")
    audit.add_argument("--repository", required=True)
    audit.add_argument("--remote", default="origin")
    audit.add_argument("--network", action="store_true")

    args = parser.parse_args(argv)
    try:
        root = Path(args.root)
        if args.command == "resume":
            snapshot = json.loads(Path(args.event_path).read_text())
            result = resume_release(
                root,
                args.generation,
                args.repository,
                args.issue_number,
                remote=args.remote,
                issue_snapshot=snapshot,
                allowed_actors=store.parse_allowlist(args.allow_actors),
                verify_issue=True,
            )
            print(json.dumps(result, sort_keys=True))
        elif args.command == "reconcile":
            result = reconcile_eligible_issues(
                root,
                args.repository,
                remote=args.remote,
            )
            event_path = Path(args.event_output)
            selected = result["selected"]
            if selected is None:
                event_path.unlink(missing_ok=True)
            else:
                event_path.parent.mkdir(parents=True, exist_ok=True)
                event_path.write_bytes(store.canonical_json(result.pop("event")))
            if args.github_output:
                with Path(args.github_output).open("a") as output:
                    output.write(f"selected={'true' if selected is not None else 'false'}\n")
                    output.write(f"issue_number={selected or ''}\n")
                    output.write(f"event_path={event_path}\n")
            print(json.dumps(result, sort_keys=True))
        elif args.command == "recover-lock":
            result = recover_stale_release_lock(
                root,
                args.repository,
                args.expected_owner_sha,
                args.reason,
                args.admin_actor,
                remote=args.remote,
            )
            print(json.dumps(result, sort_keys=True))
        elif args.command == "complete-merge":
            result = finalize_merged_pr(
                root,
                args.repository,
                args.pr_number,
                remote=args.remote,
            )
            print(json.dumps(result, sort_keys=True))
        elif args.command == "supersede-pr":
            result = supersede_pr(
                root,
                args.repository,
                args.pr_number,
                args.base_sha,
                args.head_sha,
                args.status_id,
            )
            print(json.dumps(result, sort_keys=True))
        elif args.command == "validate-pr":
            validate_pr(root, args.repository, args.remote)
            print("Zoo v2 PR is based on current main and permanently protected.")
        elif args.command == "list-prs":
            branches = _remote_issue_branches(root, args.remote)
            prs = list_catalog_prs(root, args.repository, branches)
            if args.state == "open":
                prs = [pr for pr in prs if pr.get("state") == "OPEN"]
            print(json.dumps(prs, sort_keys=True))
        elif args.command == "gate-pr":
            mode = inspect_pr_change(
                complete_changed_files(root, args.base_sha, args.head_sha),
                head_ref=args.head_ref,
                head_repository=args.head_repository,
                repository=args.repository,
            )
            print(mode)
        elif args.command == "validate-bootstrap-pr":
            validate_bootstrap_pr(
                root,
                complete_changed_files(root, args.base_sha, args.head_sha),
                args.repository,
            )
            print("Bootstrap protected diff passed trusted-main validation.")
        elif args.command == "protect-bootstrap":
            result = protect_generation(
                root,
                args.repository,
                args.generation,
                args.remote,
            )
            print(json.dumps(result, sort_keys=True))
        else:
            records = audit_refs(
                root,
                args.repository,
                args.remote,
                network=args.network,
            )
            print(json.dumps(records, indent=2, sort_keys=True))
    except (
        ReleaseError,
        store.StoreError,
        OSError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
