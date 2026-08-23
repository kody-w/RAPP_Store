#!/usr/bin/env python3
"""Idempotent Git/GitHub release plumbing for RAPP Zoo Store v2 generations."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

import configure_zoo_v2_protection as protection
import zoo_v2_store as store


BRANCH_RE = re.compile(r"^zoo-v2/issue-([1-9]\d*)$")
BOOTSTRAP_BRANCH = "zoo-v2/bootstrap-protection"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
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
        issue_number = head_ref.removeprefix("zoo-v2/issue-")
        allowed = {
            "api/v2/discovery.json",
            f"api/v2/generations/issue-{issue_number}.json",
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
        return [line for line in path.read_text().splitlines() if line]
    except OSError as exc:
        raise ReleaseError(f"E_CHANGED_FILES: cannot read {path}: {exc}") from exc


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
            protection.verify_audit_file(root / audit_path, repository)
        except protection.ProtectionError as exc:
            raise ReleaseError(str(exc)) from exc


def require_protection_audit(root: Path, repository: str) -> dict:
    try:
        return protection.verify_audit_file(root / protection.AUDIT_PATH, repository)
    except protection.ProtectionError as exc:
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
    return branches


def list_catalog_prs(root: Path, repository: str | None = None) -> list[dict]:
    repo_args = ["--repo", repository] if repository else []
    value = _gh_json(
        root,
        "pr",
        "list",
        *repo_args,
        "--state",
        "all",
        "--limit",
        "100",
        "--json",
        "number,url,state,mergedAt,headRefName,baseRefName,title",
    )
    if not isinstance(value, list):
        raise ReleaseError("E_GITHUB_RESPONSE: expected a pull request array")
    return [
        item for item in value
        if isinstance(item, dict)
        and isinstance(item.get("headRefName"), str)
        and BRANCH_RE.fullmatch(item["headRefName"])
    ]


def validate_queue(
    issue_number: int,
    remote_branches: set[str],
    pull_requests: list[dict],
) -> None:
    """Permit one issue lane; merged branches are durable history, not open lanes."""
    branch = f"zoo-v2/issue-{issue_number}"
    open_prs = [
        pr for pr in pull_requests
        if pr.get("state") == "OPEN" and pr.get("headRefName") != branch
    ]
    if open_prs:
        blocked = ", ".join(f"#{pr.get('number')}" for pr in open_prs)
        raise ReleaseError(f"E_QUEUE_BUSY: open Zoo v2 catalog PR(s): {blocked}")

    by_branch = {pr.get("headRefName"): pr for pr in pull_requests}
    incomplete = []
    for sibling in sorted(remote_branches - {branch}):
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
            "--force",
            remote,
            f"refs/tags/{tag}:refs/tags/{tag}",
        )
    elif not create:
        raise ReleaseError(f"E_PERMANENT_REF: missing durable annotated tag {tag}")
    elif _tag_target(root, tag) is not None:
        raise ReleaseError(f"E_REF_COLLISION: local {tag} exists but durable remote ref does not")
    else:
        _git(root, "tag", "-a", tag, generation_commit, "-F", "-", input_text=message)

    if _git(root, "cat-file", "-t", f"refs/tags/{tag}") != "tag":
        raise ReleaseError(f"E_REF_COLLISION: {tag} is not an annotated tag")
    if _tag_target(root, tag) != generation_commit:
        raise ReleaseError(f"E_REF_COLLISION: {tag} points to another commit")
    actual_message = _git(root, "for-each-ref", "--format=%(contents)", f"refs/tags/{tag}")
    if actual_message.rstrip("\n") != message.rstrip("\n"):
        raise ReleaseError(f"E_REF_COLLISION: {tag} annotation content/provenance differs")
    if not remote_exists:
        _git(root, "push", remote, f"refs/tags/{tag}:refs/tags/{tag}")
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
        pr for pr in list_catalog_prs(root, repository)
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
            f"<!-- zoo-v2-pr:issue-{issue_number} -->",
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

    marker = f"<!-- zoo-v2-pr:issue-{issue_number} -->"
    comment_pages = _gh_json(
        root,
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repository}/issues/{issue_number}/comments",
    )
    if not isinstance(comment_pages, list):
        raise ReleaseError("E_GITHUB_RESPONSE: expected issue comments array")
    comments = [
        comment
        for page in comment_pages
        if isinstance(page, list)
        for comment in page
    ]
    if not any(isinstance(item, dict) and marker in str(item.get("body", "")) for item in comments):
        _gh(
            root,
            "issue",
            "comment",
            str(issue_number),
            "--repo",
            repository,
            "--body",
            f"{marker}\nValidated catalog PR: {pr['url']}",
        )
    return pr


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
    if generation.get("generation_id") != f"issue-{issue_number}" or path.stem != (
        f"issue-{issue_number}"
    ):
        raise ReleaseError("E_ISSUE_MISMATCH: generation id/path differs from issue")

    branch = f"zoo-v2/issue-{issue_number}"
    tag = store.generation_tag_name(generation["generation_id"])
    _git(root, "fetch", "--prune", remote, "main")
    prs = (
        list_catalog_prs(root, repository)
        if pull_requests is None and create_pr
        else (pull_requests or [])
    )
    validate_queue(issue_number, _remote_issue_branches(root, remote), prs)
    base_discovery_bytes = _validate_expected_predecessor(
        root,
        generation,
        remote=remote,
        base_generation_bytes=base_generation_bytes,
    )

    branch_exists = branch in _remote_issue_branches(root, remote)
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
        branch_bytes = _show(root, remote_revision, path.as_posix())
        if branch_bytes != expected_bytes:
            raise ReleaseError(
                "E_IMMUTABLE_GENERATION: existing issue branch has mismatched generation bytes"
            )
        _git(root, "switch", "--discard-changes", "-C", branch, remote_revision)
        generation_commit = _generation_commit(root, remote_revision, path.as_posix())
    else:
        _git(root, "switch", "-C", branch, f"refs/remotes/{remote}/main")
        local_expected.parent.mkdir(parents=True, exist_ok=True)
        local_expected.write_bytes(expected_bytes)
        _git(root, "add", path.as_posix())
        _git(root, "commit", "-m", f"catalog(v2): generation for issue #{issue_number}")
        generation_commit = _git(root, "rev-parse", "HEAD")
        _git(root, "push", "--set-upstream", remote, f"HEAD:refs/heads/{branch}")
    if _show(root, generation_commit, path.as_posix()) != expected_bytes:
        raise ReleaseError("E_GENERATION_COMMIT: generation commit content differs")
    if stage_hook:
        stage_hook("generation-push")
    if stop_after == "generation-push":
        raise RuntimeError("simulated failure after generation push")

    ensure_permanent_tag(root, remote, generation, path.as_posix(), generation_commit)
    if stage_hook:
        stage_hook("tag-push")
    if stop_after == "tag-push":
        raise RuntimeError("simulated failure after tag push")

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
        _git(root, "commit", "-m", f"catalog(v2): pin discovery for issue #{issue_number}")
        _git(root, "push", remote, f"HEAD:refs/heads/{branch}")
    elif current_discovery != expected_discovery:
        raise ReleaseError("E_DISCOVERY_COLLISION: issue branch has a different discovery pointer")
    if _tag_target(root, tag) != generation_commit:
        raise ReleaseError("E_PERMANENT_REF: discovery cannot publish before permanent tag")
    if stage_hook:
        stage_hook("discovery-push")
    if stop_after == "discovery-push":
        raise RuntimeError("simulated failure after discovery push")

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
        "pr": pr,
    }


def validate_pr(root: Path, repository: str, remote: str = "origin") -> None:
    """Reject stale or unprotected candidates against freshly fetched origin/main."""
    _validate_repository(repository)
    _git(root, "fetch", "--prune", remote, "main")
    base_bytes = _show(root, f"refs/remotes/{remote}/main", "api/v2/discovery.json")
    if base_bytes is None:
        raise ReleaseError("E_BASE: current origin/main discovery is missing")
    base_path = root / ".zoo-v2-main-discovery.json"
    base_path.write_bytes(base_bytes)
    try:
        discovery = json.loads((root / "api/v2/discovery.json").read_text())
        candidate_url = store.validate_discovery(discovery)
        match = store.validate_pinned_raw_url(candidate_url, "discovery.generation_url")
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
    _validate_repository(repository)
    require_protection_audit(root, repository)
    _git(root, "fetch", "--prune", remote, "main")
    generation = json.loads((root / generation_path).read_text())
    commit = _generation_commit(root, f"refs/remotes/{remote}/main", generation_path)
    tag = ensure_permanent_tag(root, remote, generation, generation_path, commit)
    return {"tag": tag, "commit": commit}


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
        _git(root, "fetch", "--force", remote, f"refs/tags/{tag}:refs/tags/{tag}")
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

    validate = sub.add_parser("validate-pr")
    validate.add_argument("--root", default=".")
    validate.add_argument("--repository", required=True)
    validate.add_argument("--remote", default="origin")

    gate = sub.add_parser("gate-pr")
    gate.add_argument("--root", default=".")
    gate.add_argument("--changed-files", type=Path, required=True)
    gate.add_argument("--head-ref", required=True)
    gate.add_argument("--head-repository", required=True)
    gate.add_argument("--repository", required=True)

    bootstrap = sub.add_parser("validate-bootstrap-pr")
    bootstrap.add_argument("--root", default=".")
    bootstrap.add_argument("--changed-files", type=Path, required=True)
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
            result = resume_release(
                root,
                args.generation,
                args.repository,
                args.issue_number,
                remote=args.remote,
            )
            print(json.dumps(result, sort_keys=True))
        elif args.command == "validate-pr":
            validate_pr(root, args.repository, args.remote)
            print("Zoo v2 PR is based on current main and permanently protected.")
        elif args.command == "gate-pr":
            mode = inspect_pr_change(
                _read_changed_files(args.changed_files),
                head_ref=args.head_ref,
                head_repository=args.head_repository,
                repository=args.repository,
            )
            print(mode)
        elif args.command == "validate-bootstrap-pr":
            validate_bootstrap_pr(
                root,
                _read_changed_files(args.changed_files),
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
