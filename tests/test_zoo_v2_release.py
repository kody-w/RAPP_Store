"""Git-remote and workflow tests for the serialized Zoo v2 release lane."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import configure_zoo_v2_protection as protection
import zoo_v2_release as release
import zoo_v2_store as store

VALIDATOR_APP_ID = 4242
SAMPLE_ATTEMPT_ID = f"issue-42-{'d' * 64}"
SAMPLE_ATTEMPT_PATH = f"api/v2/generations/{SAMPLE_ATTEMPT_ID}.json"
SAMPLE_ATTEMPT_BRANCH = f"zoo-v2/{SAMPLE_ATTEMPT_ID}"


def _prototype(version: str) -> dict:
    digest = "a" * 64
    commit = "b" * 40
    return {
        "id": "synthetic-example",
        "name": "Synthetic Example",
        "version": version,
        "summary": "Inert local release simulation data.",
        "status": "prototype",
        "artifact": {
            "url": f"https://raw.githubusercontent.com/example/content/{commit}/agent.py",
            "sha256": digest,
            "media_type": "text/x-python",
        },
        "license": {
            "spdx": "MIT",
            "evidence_url": f"https://raw.githubusercontent.com/example/content/{commit}/LICENSE",
            "evidence_sha256": "c" * 64,
        },
        "wire_contract": "RAPP/1",
        "identity": f"rappid:@example/synthetic-example:{digest}",
        "ecosystem_acceptance": "not-asserted",
        "external_blockers": ["Independent ecosystem admission remains incomplete."],
    }


def _git(root: Path, *args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def _valid_audit(repository: str = "example/store") -> dict:
    return {
        "schema": protection.AUDIT_SCHEMA,
        "repository": repository,
        "verified_at": "2026-08-22T20:00:00Z",
        "branch": "main",
        "validator_app_id": VALIDATOR_APP_ID,
        "branch_protection": {
            "strict": True,
            "required_status_contexts": ["Existing CI"],
            "required_status_checks": [
                {
                    "context": protection.STATUS_CONTEXT,
                    "app_id": VALIDATOR_APP_ID,
                }
            ],
            "required_approving_review_count": 2,
            "dismiss_stale_reviews": True,
            "require_last_push_approval": True,
            "enforce_admins": True,
            "required_conversation_resolution": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
        },
        "tag_ruleset": {
            "id": 17,
            "name": protection.TAG_RULESET_NAME,
            "target": "tag",
            "enforcement": "active",
            "include": protection.TAG_PATTERN,
            "required_rules": sorted(protection.TAG_RULE_TYPES),
            "bypass_actors": [],
        },
    }


def _write_audit(root: Path, repository: str = "example/store") -> None:
    path = root / protection.AUDIT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_valid_audit(repository), indent=2, sort_keys=True) + "\n")


def _issue_path(work: Path, issue_number: int = 42) -> Path:
    matches = list((work / "api/v2/generations").glob(f"issue-{issue_number}-*.json"))
    assert len(matches) == 1
    return matches[0]


def _issue_relative(work: Path, issue_number: int = 42) -> str:
    return _issue_path(work, issue_number).relative_to(work).as_posix()


def _issue_branch(work: Path, issue_number: int = 42) -> str:
    return f"zoo-v2/{_issue_path(work, issue_number).stem}"


def _seed_remote(tmp_path: Path) -> tuple[Path, bytes, str]:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True)
    subprocess.run(["git", "clone", remote, work], check=True, capture_output=True)
    _git(work, "config", "user.name", "Test Store Bot")
    _git(work, "config", "user.email", "store@example.invalid")
    _git(work, "switch", "-c", "main")

    generation = {
        "schema": store.GENERATION_SCHEMA,
        "generation_id": "bootstrap-20260822",
        "created_at": "2026-08-22T19:16:00Z",
        "source_issue": None,
        "previous_generation_url": None,
        "prototypes": [_prototype("0.1.0")],
        "tombstones": [],
    }
    base_bytes = store.canonical_json(generation)
    generation_path = work / "api/v2/generations/bootstrap-20260822.json"
    generation_path.parent.mkdir(parents=True)
    generation_path.write_bytes(base_bytes)
    _write_audit(work)
    _git(work, "add", ".")
    _git(work, "commit", "-m", "bootstrap generation")
    generation_commit = _git(work, "rev-parse", "HEAD")

    base_url = (
        "https://raw.githubusercontent.com/example/store/"
        f"{generation_commit}/api/v2/generations/bootstrap-20260822.json"
    )
    discovery = work / "api/v2/discovery.json"
    discovery.write_bytes(store.canonical_json({
        "schema": store.DISCOVERY_SCHEMA,
        "generation_url": base_url,
    }))
    _git(work, "add", ".")
    _git(work, "commit", "-m", "bootstrap discovery")
    _git(work, "push", "--set-upstream", "origin", "main")
    subprocess.run(
        ["git", "--git-dir", remote, "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
    )

    issue_generation = {
        "schema": store.GENERATION_SCHEMA,
        "created_at": "2026-08-22T20:00:00Z",
        "source_issue": 42,
        "previous_generation_url": base_url,
        "previous_generation_sha256": store.sha256_bytes(base_bytes),
        "prototypes": [_prototype("0.2.0")],
        "tombstones": [],
    }
    issue_generation["generation_id"] = store.generation_attempt_id(issue_generation)
    issue_path = work / f"api/v2/generations/{issue_generation['generation_id']}.json"
    issue_path.write_bytes(store.canonical_json(issue_generation))
    return work, base_bytes, generation_commit


def _advance_main(remote: Path, racer: Path) -> tuple[bytes, str]:
    subprocess.run(["git", "clone", remote, racer], check=True, capture_output=True)
    _git(racer, "config", "user.name", "Concurrent Store Bot")
    _git(racer, "config", "user.email", "racer@example.invalid")
    discovery = json.loads((racer / "api/v2/discovery.json").read_text())
    predecessor_url = store.validate_discovery(discovery)
    predecessor_path = racer / store.validate_generation_raw_url(
        predecessor_url, "generation_url"
    ).group("path")
    predecessor_bytes = predecessor_path.read_bytes()
    predecessor = json.loads(predecessor_bytes)
    generation = {
        "schema": store.GENERATION_SCHEMA,
        "created_at": "2026-08-22T20:01:00Z",
        "source_issue": 99,
        "previous_generation_url": predecessor_url,
        "previous_generation_sha256": store.sha256_bytes(predecessor_bytes),
        "prototypes": [_prototype("0.1.1")],
        "tombstones": [],
    }
    generation["generation_id"] = store.generation_attempt_id(generation)
    relative = f"api/v2/generations/{generation['generation_id']}.json"
    path = racer / relative
    path.write_bytes(store.canonical_json(generation))
    _git(racer, "add", relative)
    _git(racer, "commit", "-m", "concurrent generation")
    generation_commit = _git(racer, "rev-parse", "HEAD")
    tag = store.generation_tag_name(generation["generation_id"])
    _git(
        racer,
        "tag",
        "-a",
        tag,
        generation_commit,
        "-F",
        "-",
        input_text=store.generation_tag_message(generation, relative),
    )
    _git(racer, "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}")
    store.pin_discovery("example/store", generation_commit, relative, racer / "api/v2/discovery.json")
    _git(racer, "add", "api/v2/discovery.json")
    _git(racer, "commit", "-m", "advance main discovery")
    _git(racer, "push", "origin", "HEAD:refs/heads/main")
    return path.read_bytes(), (
        f"https://raw.githubusercontent.com/example/store/{generation_commit}/{relative}"
    )


def _write_issue_attempt(
    work: Path,
    issue_number: int,
    base_bytes: bytes,
    *,
    version: str,
) -> str:
    discovery = json.loads((work / "api/v2/discovery.json").read_text())
    base_url = store.validate_discovery(discovery)
    generation = {
        "schema": store.GENERATION_SCHEMA,
        "created_at": f"2026-08-22T20:{issue_number % 60:02d}:00Z",
        "source_issue": issue_number,
        "previous_generation_url": base_url,
        "previous_generation_sha256": store.sha256_bytes(base_bytes),
        "prototypes": [_prototype(version)],
        "tombstones": [],
    }
    generation["generation_id"] = store.generation_attempt_id(generation)
    relative = f"api/v2/generations/{generation['generation_id']}.json"
    path = work / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(store.canonical_json(generation))
    return relative


def _eligible_issue(number: int, *, labels: list[str] | None = None) -> dict:
    label_names = labels or [release.ELIGIBLE_LABEL]
    return {
        "number": number,
        "title": f"[ZOO V2 UPDATE] synthetic-{number}",
        "state": "open",
        "created_at": f"2026-08-22T20:{number:02d}:00Z",
        "updated_at": f"2026-08-22T20:{number:02d}:01Z",
        "body": "```json\n{}\n```",
        "user": {"login": "example"},
        "labels": [
            {"name": name}
            for name in label_names
        ],
        "_label_names": sorted(label_names),
    }


def _matching_release_issue(work: Path, issue_number: int = 42) -> dict:
    generation = json.loads(_issue_path(work, issue_number).read_text())
    command = {
        "schema": store.COMMAND_SCHEMA,
        "operation": "update",
        "id": "synthetic-example",
        "prototype": generation["prototypes"][0],
    }
    body = f"```json\n{json.dumps(command, indent=2, sort_keys=True)}\n```"
    return {
        "number": issue_number,
        "title": "[ZOO V2 UPDATE] synthetic-example",
        "state": "open",
        "created_at": generation["created_at"],
        "updated_at": generation["created_at"],
        "body": body,
        "user": {"login": "example"},
        "labels": [{"name": release.ELIGIBLE_LABEL}],
    }


def _issue_event(issue: dict, repository: str = "example/store") -> dict:
    return {
        "action": "reconciled",
        "issue": json.loads(json.dumps(issue)),
        "repository": {"full_name": repository},
    }


def _raw_pr(
    number: int,
    branch: str,
    head_sha: str,
    *,
    state: str = "open",
    merged_at: str | None = None,
) -> dict:
    return {
        "number": number,
        "html_url": f"https://github.com/example/store/pull/{number}",
        "state": state,
        "merged_at": merged_at,
        "title": f"catalog(v2): {branch}",
        "head": {
            "ref": branch,
            "sha": head_sha,
            "repo": {"full_name": "example/store"},
        },
        "base": {"ref": "main"},
    }


@pytest.mark.parametrize(
    "stop_after",
    ["generation-push", "tag-push", "discovery-push"],
)
def test_resume_after_each_git_failure_stage(tmp_path, stop_after):
    work, base_bytes, _ = _seed_remote(tmp_path)
    generation_path = _issue_relative(work)
    branch = _issue_branch(work)
    kwargs = {
        "root": work,
        "generation_path": generation_path,
        "repository": "example/store",
        "issue_number": 42,
        "create_pr": False,
        "base_generation_bytes": base_bytes,
    }
    with pytest.raises(RuntimeError, match="simulated failure"):
        release.resume_release(**kwargs, stop_after=stop_after)

    result = release.resume_release(**kwargs)
    assert result["tag"] == f"zoo-v2-generation-{Path(generation_path).stem}"
    assert len(result["generation_commit"]) == 40
    assert _git(work, "rev-parse", f"{result['tag']}^{{commit}}") == result["generation_commit"]
    remote_discovery = json.loads(
        _git(work, "show", f"origin/{branch}:api/v2/discovery.json")
    )
    assert f"/{result['generation_commit']}/" in remote_discovery["generation_url"]


def test_resume_after_pr_is_find_or_create_idempotent(tmp_path):
    work, base_bytes, _ = _seed_remote(tmp_path)
    generation_path = _issue_relative(work)
    branch = _issue_branch(work)
    calls = []
    durable_pr = {
        "number": 7,
        "url": "https://github.com/example/store/pull/7",
        "state": "OPEN",
        "headRefName": branch,
        "baseRefName": "main",
    }

    def ensure_pr(root, repository, issue_number, branch):
        calls.append((repository, issue_number, branch))
        return durable_pr

    kwargs = {
        "root": work,
        "generation_path": generation_path,
        "repository": "example/store",
        "issue_number": 42,
        "pull_requests": [durable_pr],
        "base_generation_bytes": base_bytes,
        "pr_ensurer": ensure_pr,
        "verify_issue": False,
    }
    with pytest.raises(RuntimeError, match="simulated failure after PR"):
        release.resume_release(**kwargs, stop_after="pr")
    result = release.resume_release(**kwargs)
    assert result["pr"] == durable_pr
    assert calls == [
        ("example/store", 42, branch),
        ("example/store", 42, branch),
    ]


def test_opening_pr_records_only_link_marker_not_processed(monkeypatch, tmp_path):
    branch = SAMPLE_ATTEMPT_BRANCH
    calls = []
    monkeypatch.setattr(release, "list_catalog_prs", lambda *_args: [])
    monkeypatch.setattr(release, "_issue_comments", lambda *_args: [])

    def gh(_root, *args):
        calls.append(args)
        if args[:2] == ("pr", "create"):
            return "https://github.com/example/store/pull/77"
        return ""

    monkeypatch.setattr(release, "_gh", gh)
    pr = release._ensure_pr(tmp_path, "example/store", 42, branch)
    assert pr["number"] == 77
    body = next(
        call[call.index("--body") + 1]
        for call in calls
        if call[:2] == ("issue", "comment")
    )
    assert release.PR_MARKER_SCHEMA in body
    assert release.PROCESSED_LABEL not in "\n".join(" ".join(call) for call in calls)


@pytest.mark.parametrize(
    "mutation",
    [
        "close",
        "title",
        "body",
        "updated_at",
        "eligible_removed",
        "processed",
        "tombstoned",
        "labels_changed",
        "actor",
    ],
)
def test_locked_release_refetches_and_rejects_every_issue_mutation(
    tmp_path, monkeypatch, mutation
):
    work, base_bytes, _ = _seed_remote(tmp_path)
    generation_path = _issue_relative(work)
    issue = _matching_release_issue(work)
    snapshot = _issue_event(issue)
    fresh = json.loads(json.dumps(issue))

    if mutation == "close":
        fresh["state"] = "closed"
    elif mutation == "title":
        fresh["title"] += " edited"
    elif mutation == "body":
        fresh["body"] += "\nEdited."
    elif mutation == "updated_at":
        fresh["updated_at"] = "2026-08-22T20:00:01Z"
    elif mutation == "eligible_removed":
        fresh["labels"] = []
    elif mutation == "processed":
        fresh["labels"].append({"name": release.PROCESSED_LABEL})
    elif mutation == "tombstoned":
        fresh["labels"].append({"name": release.TOMBSTONED_LABEL})
    elif mutation == "labels_changed":
        fresh["labels"].append({"name": "documentation"})
    else:
        fresh["user"]["login"] = "intruder"

    monkeypatch.setattr(
        release,
        "_gh_json",
        lambda _root, *args: json.loads(json.dumps(fresh)),
    )
    with pytest.raises(release.ReleaseError, match="E_(ISSUE_MUTATED|ACTOR_NOT_ALLOWED)"):
        release.resume_release(
            work,
            generation_path,
            "example/store",
            42,
            create_pr=False,
            pull_requests=[],
            base_generation_bytes=base_bytes,
            issue_snapshot=snapshot,
            allowed_actors={"example"},
            verify_issue=True,
        )
    branch = _issue_branch(work)
    tag = store.generation_tag_name(Path(generation_path).stem)
    assert _git(work, "ls-remote", "--heads", "origin", f"refs/heads/{branch}") == ""
    assert _git(work, "ls-remote", "--tags", "origin", f"refs/tags/{tag}") == ""


@pytest.mark.parametrize(
    "race_stage",
    ["before-generation-push", "before-tag-push", "before-discovery-push"],
)
def test_issue_edit_race_aborts_before_atomic_ref_tag_publication(
    tmp_path, monkeypatch, race_stage
):
    work, base_bytes, _ = _seed_remote(tmp_path)
    generation_path = _issue_relative(work)
    issue = _matching_release_issue(work)
    snapshot = _issue_event(issue)
    fresh = json.loads(json.dumps(issue))
    monkeypatch.setattr(
        release,
        "_gh_json",
        lambda _root, *args: json.loads(json.dumps(fresh)),
    )

    def mutate(stage):
        if stage == race_stage:
            fresh["labels"].append({"name": "race-edit"})
            fresh["updated_at"] = "2026-08-22T20:00:01Z"

    with pytest.raises(release.ReleaseError, match="E_ISSUE_MUTATED"):
        release.resume_release(
            work,
            generation_path,
            "example/store",
            42,
            create_pr=False,
            pull_requests=[],
            base_generation_bytes=base_bytes,
            issue_snapshot=snapshot,
            allowed_actors={"example"},
            verify_issue=True,
            stage_hook=mutate,
        )
    branch = _issue_branch(work)
    tag = store.generation_tag_name(Path(generation_path).stem)
    assert _git(work, "ls-remote", "--heads", "origin", f"refs/heads/{branch}") == ""
    assert _git(work, "ls-remote", "--tags", "origin", f"refs/tags/{tag}") == ""


def test_locked_release_regenerates_exact_bytes_from_reconciled_snapshot(
    tmp_path, monkeypatch
):
    work, base_bytes, _ = _seed_remote(tmp_path)
    generation_path = _issue_relative(work)
    issue = _matching_release_issue(work)
    command = json.loads(store.JSON_BLOCK_RE.findall(issue["body"])[0])
    command["prototype"]["summary"] = "Edited before locked generation."
    issue["body"] = f"```json\n{json.dumps(command, indent=2, sort_keys=True)}\n```"
    issue["updated_at"] = "2026-08-22T20:00:01Z"
    snapshot = _issue_event(issue)
    monkeypatch.setattr(release, "_gh_json", lambda *_args: issue)

    with pytest.raises(release.ReleaseError, match="regenerated.*bytes differ"):
        release.resume_release(
            work,
            generation_path,
            "example/store",
            42,
            create_pr=False,
            pull_requests=[],
            base_generation_bytes=base_bytes,
            issue_snapshot=snapshot,
            allowed_actors={"example"},
            verify_issue=True,
        )
    assert not _git(work, "ls-remote", "--heads", "origin", "refs/heads/zoo-v2/issue-*")


def test_main_advance_race_publishes_no_partial_attempt_and_retry_uses_new_predecessor(tmp_path):
    work, base_bytes, _ = _seed_remote(tmp_path)
    stale_path = _issue_relative(work)
    stale_id = Path(stale_path).stem
    remote = work.parent / "remote.git"
    raced = {}

    def advance(stage):
        if stage == "before-tag-push":
            raced["bytes"], raced["url"] = _advance_main(
                remote, tmp_path / "racer"
            )

    with pytest.raises(release.ReleaseError, match="E_STALE_PREDECESSOR"):
        release.resume_release(
            work,
            stale_path,
            "example/store",
            42,
            create_pr=False,
            base_generation_bytes=base_bytes,
            stage_hook=advance,
        )

    stale_tag = f"zoo-v2-generation-{stale_id}"
    assert _git(work, "ls-remote", "--tags", "origin", f"refs/tags/{stale_tag}") == ""

    _git(work, "fetch", "--prune", "origin", "main")
    _git(work, "switch", "--discard-changes", "-C", "main", "origin/main")
    retry = {
        "schema": store.GENERATION_SCHEMA,
        "created_at": "2026-08-22T20:00:00Z",
        "source_issue": 42,
        "previous_generation_url": raced["url"],
        "previous_generation_sha256": store.sha256_bytes(raced["bytes"]),
        "prototypes": [_prototype("0.2.0")],
        "tombstones": [],
    }
    retry["generation_id"] = store.generation_attempt_id(retry)
    retry_path = f"api/v2/generations/{retry['generation_id']}.json"
    (work / retry_path).write_bytes(store.canonical_json(retry))

    result = release.resume_release(
        work,
        retry_path,
        "example/store",
        42,
        create_pr=False,
        base_generation_bytes=raced["bytes"],
    )
    assert result["tag"] != stale_tag
    assert result["archived_tags"] == []
    assert retry["previous_generation_url"] == raced["url"]
    assert not _git(work, "ls-remote", "--tags", "origin", f"refs/tags/{stale_tag}")
    assert _git(work, "ls-remote", "--tags", "origin", f"refs/tags/{result['tag']}")
    remote_discovery = json.loads(
        _git(work, "show", f"origin/{result['branch']}:api/v2/discovery.json")
    )
    assert retry["generation_id"] in remote_discovery["generation_url"]


def test_catalog_pr_queries_are_exact_and_not_repository_windowed(
    tmp_path, monkeypatch
):
    branches = {
        f"zoo-v2/issue-7-{'7' * 64}",
        f"zoo-v2/issue-8-{'8' * 64}",
    }
    old_unrelated = [
        {"number": number, "head": {"ref": f"old-{number}"}}
        for number in range(1, 151)
    ]
    relevant = {}
    for index, branch in enumerate(sorted(branches), 200):
        relevant[f"example:{branch}"] = [{
            "number": index,
            "html_url": f"https://github.com/example/store/pull/{index}",
            "state": "open",
            "merged_at": None,
            "title": "catalog",
            "head": {
                "ref": branch,
                "sha": f"{index:040x}",
                "repo": {"full_name": "example/store"},
            },
            "base": {"ref": "main"},
        }]
    calls = []

    def exact_query(_root, *args):
        calls.append(args)
        head_filter = next(arg.removeprefix("head=") for arg in args if arg.startswith("head="))
        assert all(item["head"]["ref"] != head_filter for item in old_unrelated)
        return relevant[head_filter]

    monkeypatch.setattr(release, "_gh_json", exact_query)
    result = release.list_catalog_prs(tmp_path, "example/store", branches)
    assert {item["headRefName"] for item in result} == branches
    assert len(calls) == len(branches)
    assert all("--limit" not in call for call in calls)


def test_catalog_pr_query_fails_closed_at_exact_branch_bound(tmp_path, monkeypatch):
    branch = f"zoo-v2/issue-7-{'7' * 64}"
    monkeypatch.setattr(
        release,
        "_gh_json",
        lambda *_args: [{} for _ in range(release.MAX_PRS_PER_BRANCH)],
    )
    with pytest.raises(release.ReleaseError, match="E_QUEUE_INCOMPLETE"):
        release.list_catalog_prs(tmp_path, "example/store", {branch})

    def rate_limited(*_args):
        raise release.ReleaseError("E_COMMAND: GitHub API rate limit exceeded")

    monkeypatch.setattr(release, "_gh_json", rate_limited)
    with pytest.raises(release.ReleaseError, match="rate limit"):
        release.list_catalog_prs(tmp_path, "example/store", {branch})


def test_queue_rejects_open_pr_or_unfinished_sibling():
    with pytest.raises(release.ReleaseError, match="E_QUEUE_BUSY.*#9"):
        release.validate_queue(42, set(), [{
            "number": 9,
            "state": "OPEN",
            "headRefName": f"zoo-v2/issue-9-{'9' * 64}",
        }])
    with pytest.raises(release.ReleaseError, match="unfinished.*issue-8"):
        release.validate_queue(42, {f"zoo-v2/issue-8-{'8' * 64}"}, [])
    branch = f"zoo-v2/issue-8-{'8' * 64}"
    release.validate_queue(42, {branch}, [{
        "number": 8,
        "state": "MERGED",
        "mergedAt": "2026-08-22T20:00:00Z",
        "headRefName": branch,
    }])


def test_atomic_release_lock_resumes_exact_owner_and_cleans_exact_lease(tmp_path):
    work, _, _ = _seed_remote(tmp_path)
    generation_id = Path(_issue_relative(work)).stem
    owner = release.release_lock_owner(
        "example/store",
        42,
        generation_id,
        workflow_run_id="1001",
        actor="store-bot",
        workflow="catalog",
    )
    contender = release.release_lock_owner(
        "example/store",
        42,
        generation_id,
        workflow_run_id="1002",
        actor="store-bot",
        workflow="catalog",
    )

    lease = release.acquire_release_lock(work, "origin", owner)
    resumed = release.acquire_release_lock(work, "origin", owner)
    assert resumed["owner_sha"] == lease["owner_sha"]
    assert release._remote_ref_sha(work, "origin", release.RELEASE_LOCK_REF) == (
        lease["owner_sha"]
    )
    with pytest.raises(release.ReleaseError, match="E_RELEASE_LOCKED.*1001"):
        release.acquire_release_lock(work, "origin", contender)
    with pytest.raises(release.ReleaseError, match="E_RELEASE_LOCK_LEASE"):
        release.release_release_lock(
            work,
            "origin",
            {"owner_sha": "f" * 40},
        )
    assert release._remote_ref_sha(work, "origin", release.RELEASE_LOCK_REF) == (
        lease["owner_sha"]
    )
    release.release_release_lock(work, "origin", lease)
    assert release._remote_ref_sha(work, "origin", release.RELEASE_LOCK_REF) is None


def test_two_remote_releasers_create_exactly_one_lane_then_queue_blocks(tmp_path):
    first, base_bytes, _ = _seed_remote(tmp_path)
    first_path = _issue_relative(first)
    remote = tmp_path / "remote.git"
    second = tmp_path / "second"
    subprocess.run(["git", "clone", remote, second], check=True, capture_output=True)
    _git(second, "config", "user.name", "Second Store Bot")
    _git(second, "config", "user.email", "second@example.invalid")
    second_path = _write_issue_attempt(second, 43, base_bytes, version="0.3.0")
    acquired = threading.Event()
    finish = threading.Event()
    first_result = {}
    first_errors = []
    pr_calls = []

    def hold_after_lock(stage):
        if stage == "lock-acquired":
            acquired.set()
            assert finish.wait(timeout=10)

    def ensure_pr(_root, _repository, issue_number, branch):
        pr_calls.append((issue_number, branch))
        return {
            "number": 7,
            "url": "https://github.com/example/store/pull/7",
            "state": "OPEN",
            "mergedAt": None,
            "headRefName": branch,
            "baseRefName": "main",
        }

    def run_first():
        try:
            first_result.update(release.resume_release(
                first,
                first_path,
                "example/store",
                42,
                pull_requests=[],
                base_generation_bytes=base_bytes,
                stage_hook=hold_after_lock,
                pr_ensurer=ensure_pr,
                verify_issue=False,
                lock_owner=release.release_lock_owner(
                    "example/store",
                    42,
                    Path(first_path).stem,
                    workflow_run_id="2001",
                    actor="store-bot",
                    workflow="catalog",
                ),
            ))
        except Exception as exc:  # pragma: no cover - asserted below
            first_errors.append(exc)

    thread = threading.Thread(target=run_first)
    thread.start()
    assert acquired.wait(timeout=10)
    with pytest.raises(release.ReleaseError, match="E_RELEASE_LOCKED.*2001"):
        release.resume_release(
            second,
            second_path,
            "example/store",
            43,
            create_pr=False,
            base_generation_bytes=base_bytes,
            lock_owner=release.release_lock_owner(
                "example/store",
                43,
                Path(second_path).stem,
                workflow_run_id="2002",
                actor="store-bot",
                workflow="catalog",
            ),
        )
    finish.set()
    thread.join(timeout=20)
    assert not thread.is_alive()
    assert first_errors == []
    assert first_result["pr"]["number"] == 7
    assert pr_calls == [(42, first_result["branch"])]
    assert release._remote_ref_sha(first, "origin", release.RELEASE_LOCK_REF) is None

    with pytest.raises(release.ReleaseError, match="E_QUEUE_BUSY.*issue-42"):
        release.resume_release(
            second,
            second_path,
            "example/store",
            43,
            create_pr=False,
            base_generation_bytes=base_bytes,
            lock_owner=release.release_lock_owner(
                "example/store",
                43,
                Path(second_path).stem,
                workflow_run_id="2002",
                actor="store-bot",
                workflow="catalog",
            ),
        )
    tags = _git(first, "ls-remote", "--tags", "origin", "refs/tags/zoo-v2-generation-issue-*")
    assert len([line for line in tags.splitlines() if "^{}" not in line]) == 1
    assert release._remote_ref_sha(first, "origin", release.RELEASE_LOCK_REF) is None


def test_stale_lock_recovery_is_admin_audited_and_fails_closed(
    tmp_path, monkeypatch
):
    work, _, _ = _seed_remote(tmp_path)
    generation_id = Path(_issue_relative(work)).stem
    owner = release.release_lock_owner(
        "example/store",
        42,
        generation_id,
        workflow_run_id="3001",
        actor="store-bot",
        workflow="catalog",
    )
    lease = release.acquire_release_lock(work, "origin", owner)
    monkeypatch.setenv("GITHUB_ACTOR", "admin-user")
    audit_calls = []

    def github_json(_root, *args):
        if args[-1] == "user":
            return {"login": "admin-user"}
        target = next((arg for arg in args if arg.startswith("repos/")), "")
        if target.endswith("/collaborators/admin-user/permission"):
            return {"permission": "admin", "user": {"login": "admin-user"}}
        if target.endswith("/actions/runs/3001"):
            return {"id": 3001, "status": "completed", "conclusion": "failure"}
        if target.endswith("/pulls"):
            return []
        raise AssertionError(args)

    monkeypatch.setattr(release, "_gh_json", github_json)
    monkeypatch.setattr(
        release,
        "_gh",
        lambda _root, *args: audit_calls.append(args) or "",
    )
    monkeypatch.setattr(
        release,
        "_gh_json",
        lambda _root, *args: {"login": "different-user"}
        if args[-1] == "user"
        else github_json(_root, *args),
    )
    with pytest.raises(release.ReleaseError, match="administrator's user token"):
        release.recover_stale_release_lock(
            work,
            "example/store",
            lease["owner_sha"],
            "Runner terminated before finally cleanup.",
            "admin-user",
        )
    monkeypatch.setattr(release, "_gh_json", github_json)
    result = release.recover_stale_release_lock(
        work,
        "example/store",
        lease["owner_sha"],
        "Runner terminated before finally cleanup.",
        "admin-user",
    )
    assert result["recovered"] == lease["owner_sha"]
    assert release._remote_ref_sha(work, "origin", release.RELEASE_LOCK_REF) is None
    assert any("zoo-v2-lock-recovery" in " ".join(call) for call in audit_calls)

    active_lease = release.acquire_release_lock(work, "origin", owner)

    def active_json(_root, *args):
        if args[-1] == "user":
            return {"login": "admin-user"}
        target = next((arg for arg in args if arg.startswith("repos/")), "")
        if target.endswith("/collaborators/admin-user/permission"):
            return {"permission": "admin", "user": {"login": "admin-user"}}
        if target.endswith("/actions/runs/3001"):
            return {"id": 3001, "status": "in_progress", "conclusion": None}
        raise AssertionError(args)

    monkeypatch.setattr(release, "_gh_json", active_json)
    with pytest.raises(release.ReleaseError, match="may still be active"):
        release.recover_stale_release_lock(
            work,
            "example/store",
            active_lease["owner_sha"],
            "Unverified stale claim.",
            "admin-user",
        )
    assert release._remote_ref_sha(work, "origin", release.RELEASE_LOCK_REF) == (
        active_lease["owner_sha"]
    )
    release.release_release_lock(work, "origin", active_lease)


def test_reconciliation_drains_three_coalesced_commands_in_order(monkeypatch, tmp_path):
    issues = [_eligible_issue(number) for number in (1, 2, 3)]
    prs = []
    gh_calls = []
    finalized = []
    monkeypatch.setattr(release, "_eligible_issue_pages", lambda *_args: issues)
    monkeypatch.setattr(
        release,
        "_remote_issue_branches",
        lambda *_args: {pr["headRefName"] for pr in prs},
    )
    monkeypatch.setattr(release, "list_catalog_prs", lambda *_args: list(prs))
    monkeypatch.setattr(release, "_issue_comments", lambda *_args: [])
    monkeypatch.setattr(
        release,
        "_gh",
        lambda _root, *args: gh_calls.append(args) or "",
    )
    monkeypatch.setattr(
        release,
        "finalize_merged_pr",
        lambda _root, _repository, pr_number, **_kwargs: finalized.append(pr_number),
    )

    first = release.reconcile_eligible_issues(tmp_path, "example/store")
    assert first["selected"] == 1
    assert first["event"]["issue"]["number"] == 1
    assert "event" not in first["event"]

    prs.append({
        "number": 101,
        "url": "https://github.com/example/store/pull/101",
        "state": "OPEN",
        "mergedAt": None,
        "headRefName": f"zoo-v2/issue-1-{'1' * 64}",
    })
    blocked = release.reconcile_eligible_issues(tmp_path, "example/store")
    assert blocked["selected"] is None
    assert blocked["blocked_by_prs"] == [101]
    assert not any("zoo-v2-processed" in " ".join(call) for call in gh_calls)

    prs[0]["state"] = "CLOSED"
    prs[0]["mergedAt"] = "2026-08-22T21:00:00Z"
    second = release.reconcile_eligible_issues(tmp_path, "example/store")
    assert second["selected"] == 2
    prs.append({
        "number": 102,
        "url": "https://github.com/example/store/pull/102",
        "state": "CLOSED",
        "mergedAt": "2026-08-22T22:00:00Z",
        "headRefName": f"zoo-v2/issue-2-{'2' * 64}",
    })
    third = release.reconcile_eligible_issues(tmp_path, "example/store")
    assert third["selected"] == 3
    prs.append({
        "number": 103,
        "url": "https://github.com/example/store/pull/103",
        "state": "CLOSED",
        "mergedAt": "2026-08-22T23:00:00Z",
        "headRefName": f"zoo-v2/issue-3-{'3' * 64}",
    })
    drained = release.reconcile_eligible_issues(tmp_path, "example/store")
    assert drained["selected"] is None
    assert [state["number"] for state in drained["states"]] == [1, 2, 3]
    assert finalized == [101, 101, 102, 101, 102, 103]


def test_eligible_issue_scan_paginates_fully_and_fails_closed_at_bound(
    monkeypatch, tmp_path
):
    calls = []
    pages = {
        1: [_eligible_issue(number) for number in range(1, 101)],
        2: [_eligible_issue(number) for number in range(101, 104)],
    }

    def github_json(_root, *args):
        page = int(next(arg.removeprefix("page=") for arg in args if arg.startswith("page=")))
        calls.append(page)
        return pages.get(page, [])

    monkeypatch.setattr(release, "_gh_json", github_json)
    result = release._eligible_issue_pages(tmp_path, "example/store")
    assert len(result) == 103
    assert calls == [1, 2]

    monkeypatch.setattr(
        release,
        "_gh_json",
        lambda _root, *args: [
            _eligible_issue(
                (int(next(
                    arg.removeprefix("page=")
                    for arg in args if arg.startswith("page=")
                )) - 1) * 100 + index
            )
            for index in range(1, 101)
        ],
    )
    with pytest.raises(release.ReleaseError, match="E_RECONCILE_INCOMPLETE"):
        release._eligible_issue_pages(tmp_path, "example/store")


def test_processed_and_tombstoned_markers_fail_closed_or_skip(monkeypatch, tmp_path):
    processed = _eligible_issue(
        1, labels=[release.ELIGIBLE_LABEL, release.PROCESSED_LABEL]
    )
    tombstoned = _eligible_issue(
        2, labels=[release.ELIGIBLE_LABEL, release.TOMBSTONED_LABEL]
    )
    monkeypatch.setattr(
        release,
        "_eligible_issue_pages",
        lambda *_args: [processed, tombstoned],
    )
    monkeypatch.setattr(release, "_remote_issue_branches", lambda *_args: set())
    monkeypatch.setattr(release, "list_catalog_prs", lambda *_args: [])
    monkeypatch.setattr(release, "_issue_comments", lambda *_args: [])
    with pytest.raises(release.ReleaseError, match="lacks a valid completion marker"):
        release.reconcile_eligible_issues(tmp_path, "example/store")

    monkeypatch.setattr(
        release,
        "_eligible_issue_pages",
        lambda *_args: [tombstoned],
    )
    result = release.reconcile_eligible_issues(tmp_path, "example/store")
    assert result["selected"] is None
    assert result["states"] == [{"number": 2, "state": "tombstoned"}]


def test_merge_completion_survives_deleted_branch_and_ignores_pr_history(
    tmp_path, monkeypatch
):
    work, base_bytes, _ = _seed_remote(tmp_path)
    generation_path = _issue_relative(work)
    released = release.resume_release(
        work,
        generation_path,
        "example/store",
        42,
        create_pr=False,
        base_generation_bytes=base_bytes,
    )
    branch = released["branch"]
    head_sha = _git(work, "rev-parse", "HEAD")
    _git(work, "switch", "-C", "main", "origin/main")
    _git(work, "merge", "--squash", f"origin/{branch}")
    _git(work, "commit", "-m", "squash merged catalog attempt")
    _git(work, "push", "origin", "main")
    _git(work, "push", "origin", "--delete", branch)
    _git(work, "fetch", "--prune", "--tags", "origin", "main")

    raw_pr = _raw_pr(
        501,
        branch,
        head_sha,
        state="closed",
        merged_at="2026-08-22T22:00:00Z",
    )
    exact_calls = []

    def exact_api(_root, *args):
        exact_calls.append(args)
        assert args[-1] == "repos/example/store/pulls/501"
        return raw_pr

    gh_calls = []
    monkeypatch.setattr(release, "_gh_json", exact_api)
    monkeypatch.setattr(
        release,
        "_gh",
        lambda _root, *args: gh_calls.append(args) or "",
    )
    pr_marker = release._audit_marker("pr", {
        "schema": release.PR_MARKER_SCHEMA,
        "issue": 42,
        "pr": 501,
        "attempt": Path(generation_path).stem,
    })
    pr_comment = {
        "body": pr_marker,
        "user": {"login": "github-actions[bot]"},
    }
    pending = _matching_release_issue(work)
    pending["_label_names"] = [release.ELIGIBLE_LABEL]
    monkeypatch.setattr(release, "_eligible_issue_pages", lambda *_args: [pending])
    monkeypatch.setattr(release, "_remote_issue_branches", lambda *_args: set())
    monkeypatch.setattr(release, "list_catalog_prs", lambda *_args: [])
    monkeypatch.setattr(release, "_issue_comments", lambda *_args: [pr_comment])
    recovered = release.reconcile_eligible_issues(work, "example/store")
    assert recovered["selected"] is None
    assert recovered["states"] == [{"number": 42, "state": "processed"}]
    assert not _git(work, "ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    comment_call = next(call for call in gh_calls if call[:2] == ("issue", "comment"))
    marker_body = comment_call[comment_call.index("--body") + 1]
    assert release.COMPLETION_MARKER_SCHEMA in marker_body
    assert any(release.PROCESSED_LABEL in " ".join(call) for call in gh_calls)
    assert any(
        call[:4] == ("api", "--method", "PATCH", "repos/example/store/issues/42")
        for call in gh_calls
    )

    processed = _matching_release_issue(work)
    processed["labels"].append({"name": release.PROCESSED_LABEL})
    processed["_label_names"] = sorted(
        label["name"] for label in processed["labels"]
    )
    trusted_comment = {
        "body": marker_body,
        "user": {"login": "github-actions[bot]"},
        "author_association": "NONE",
    }
    monkeypatch.setattr(release, "_eligible_issue_pages", lambda *_args: [processed])
    monkeypatch.setattr(release, "_remote_issue_branches", lambda *_args: set())
    monkeypatch.setattr(release, "list_catalog_prs", lambda *_args: [])
    monkeypatch.setattr(
        release, "_issue_comments", lambda *_args: [trusted_comment]
    )
    reconciled = release.reconcile_eligible_issues(work, "example/store")
    assert reconciled["selected"] is None
    assert reconciled["states"] == [{"number": 42, "state": "processed"}]
    assert exact_calls == [
        ("api", "repos/example/store/pulls/501"),
        ("api", "repos/example/store/pulls/501"),
        ("api", "repos/example/store/pulls/501"),
    ]


def test_superseded_attempt_is_audited_retryable_and_uses_unique_predecessor(
    tmp_path, monkeypatch
):
    work, base_bytes, _ = _seed_remote(tmp_path)
    stale_path = _issue_relative(work)
    released = release.resume_release(
        work,
        stale_path,
        "example/store",
        42,
        create_pr=False,
        base_generation_bytes=base_bytes,
    )
    branch = released["branch"]
    head_sha = _git(work, "rev-parse", "HEAD")
    raced_bytes, raced_url = _advance_main(
        work.parent / "remote.git", tmp_path / "supersede-racer"
    )
    _git(work, "fetch", "--prune", "--tags", "origin", "main")
    base_sha = _git(work, "rev-parse", "origin/main")
    pr_state = {"state": "open", "merged_at": None}

    def exact_api(_root, *args):
        assert args[-1] == "repos/example/store/pulls/601"
        return _raw_pr(
            601,
            branch,
            head_sha,
            state=pr_state["state"],
            merged_at=pr_state["merged_at"],
        )

    gh_calls = []
    monkeypatch.setattr(release, "_gh_json", exact_api)
    monkeypatch.setattr(release, "_issue_comments", lambda *_args: [])
    monkeypatch.setattr(
        release,
        "_gh",
        lambda _root, *args: gh_calls.append(args) or "",
    )
    superseded = release.supersede_pr(
        work, "example/store", 601, base_sha, head_sha
    )
    assert superseded["attempt"] == Path(stale_path).stem
    assert superseded["invalidating_base"] == base_sha
    assert superseded["tag"] == released["tag"]
    assert _git(work, "ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    assert _git(work, "ls-remote", "--tags", "origin", f"refs/tags/{released['tag']}")
    marker_call = next(call for call in gh_calls if call[:2] == ("issue", "comment"))
    marker_body = marker_call[marker_call.index("--body") + 1]
    assert release.SUPERSEDED_MARKER_SCHEMA in marker_body
    assert any(release.SUPERSEDED_LABEL in " ".join(call) for call in gh_calls)

    normalized_open = release._normalize_catalog_pr(
        exact_api(work, "api", "repos/example/store/pulls/601"),
        "example/store",
        branch,
    )
    pending = _matching_release_issue(work)
    pending["labels"].append({"name": release.SUPERSEDED_LABEL})
    pending["_label_names"] = sorted(label["name"] for label in pending["labels"])
    trusted_comment = {
        "body": marker_body,
        "user": {"login": "github-actions[bot]"},
        "author_association": "NONE",
    }
    monkeypatch.setattr(release, "_eligible_issue_pages", lambda *_args: [pending])
    monkeypatch.setattr(
        release, "_remote_issue_branches", lambda *_args: {branch}
    )
    monkeypatch.setattr(
        release, "list_catalog_prs", lambda *_args: [normalized_open]
    )
    monkeypatch.setattr(
        release, "_issue_comments", lambda *_args: [trusted_comment]
    )
    reconciliation = release.reconcile_eligible_issues(work, "example/store")
    assert reconciliation["selected"] == 42
    assert reconciliation["states"] == [{"number": 42, "state": "retryable"}]
    assert reconciliation["event"]["issue"]["body"] == pending["body"]
    assert any(
        call[:4] == ("api", "--method", "PATCH", "repos/example/store/pulls/601")
        for call in gh_calls
    )

    _git(work, "switch", "--discard-changes", "-C", "main", "origin/main")
    retry = {
        "schema": store.GENERATION_SCHEMA,
        "created_at": "2026-08-22T20:00:00Z",
        "source_issue": 42,
        "previous_generation_url": raced_url,
        "previous_generation_sha256": store.sha256_bytes(raced_bytes),
        "prototypes": [_prototype("0.2.0")],
        "tombstones": [],
    }
    retry["generation_id"] = store.generation_attempt_id(retry)
    retry_path = f"api/v2/generations/{retry['generation_id']}.json"
    (work / retry_path).write_bytes(store.canonical_json(retry))
    retry_release = release.resume_release(
        work,
        retry_path,
        "example/store",
        42,
        create_pr=False,
        base_generation_bytes=raced_bytes,
    )
    assert retry_release["branch"] != branch
    assert retry_release["tag"] != released["tag"]
    assert retry["previous_generation_url"] == raced_url


def test_supersede_merge_race_refuses_to_close_or_mark(tmp_path, monkeypatch):
    work, base_bytes, _ = _seed_remote(tmp_path)
    stale_path = _issue_relative(work)
    released = release.resume_release(
        work,
        stale_path,
        "example/store",
        42,
        create_pr=False,
        base_generation_bytes=base_bytes,
    )
    branch = released["branch"]
    head_sha = _git(work, "rev-parse", "HEAD")
    _advance_main(work.parent / "remote.git", tmp_path / "merge-racer")
    _git(work, "fetch", "--prune", "--tags", "origin", "main")
    base_sha = _git(work, "rev-parse", "origin/main")
    responses = [
        _raw_pr(701, branch, head_sha),
        _raw_pr(
            701,
            branch,
            head_sha,
            state="closed",
            merged_at="2026-08-22T22:00:00Z",
        ),
    ]
    monkeypatch.setattr(release, "_gh_json", lambda *_args: responses.pop(0))
    gh_calls = []
    monkeypatch.setattr(release, "_issue_comments", lambda *_args: [])
    monkeypatch.setattr(
        release,
        "_gh",
        lambda _root, *args: gh_calls.append(args) or "",
    )
    with pytest.raises(release.ReleaseError, match="E_SUPERSEDE_RACE"):
        release.supersede_pr(work, "example/store", 701, base_sha, head_sha)
    assert gh_calls == []


def test_multiple_trusted_supersessions_retry_without_command_loss(
    monkeypatch, tmp_path
):
    issue = _eligible_issue(42, labels=[
        release.ELIGIBLE_LABEL,
        release.SUPERSEDED_LABEL,
    ])
    issue["body"] = "```json\n{\"command\":\"preserved\"}\n```"
    branches = [
        f"zoo-v2/issue-42-{'1' * 64}",
        f"zoo-v2/issue-42-{'2' * 64}",
    ]
    prs = [
        {
            "number": 801 + index,
            "url": f"https://github.com/example/store/pull/{801 + index}",
            "state": "CLOSED",
            "mergedAt": None,
            "headRefName": branch,
        }
        for index, branch in enumerate(branches)
    ]
    comments = []
    for pr, branch in zip(prs, branches):
        payload = {
            "schema": release.SUPERSEDED_MARKER_SCHEMA,
            "issue": 42,
            "pr": pr["number"],
            "attempt": branch.removeprefix("zoo-v2/"),
            "invalidating_base": "a" * 40,
            "generation": (
                "api/v2/generations/"
                f"{branch.removeprefix('zoo-v2/')}.json"
            ),
            "generation_commit": "b" * 40,
            "tag": store.generation_tag_name(branch.removeprefix("zoo-v2/")),
        }
        comments.append({
            "body": release._audit_marker("superseded", payload),
            "user": {"login": "github-actions[bot]"},
        })
    monkeypatch.setattr(release, "_eligible_issue_pages", lambda *_args: [issue])
    monkeypatch.setattr(
        release, "_remote_issue_branches", lambda *_args: set(branches)
    )
    monkeypatch.setattr(release, "list_catalog_prs", lambda *_args: prs)
    monkeypatch.setattr(release, "_issue_comments", lambda *_args: comments)
    monkeypatch.setattr(
        release,
        "_validate_superseded_payload",
        lambda _root, _repo, _issue, payload, **_kwargs: next(
            pr for pr in prs if pr["number"] == payload["pr"]
        ),
    )
    result = release.reconcile_eligible_issues(tmp_path, "example/store")
    assert result["selected"] == 42
    assert result["states"] == [{"number": 42, "state": "retryable"}]
    assert result["event"]["issue"]["body"] == issue["body"]


def test_arbitrary_closed_unmerged_pr_remains_blocked(monkeypatch, tmp_path):
    issue = _eligible_issue(42)
    branch = f"zoo-v2/issue-42-{'4' * 64}"
    pr = {
        "number": 901,
        "url": "https://github.com/example/store/pull/901",
        "state": "CLOSED",
        "mergedAt": None,
        "headRefName": branch,
    }
    monkeypatch.setattr(release, "_eligible_issue_pages", lambda *_args: [issue])
    monkeypatch.setattr(
        release, "_remote_issue_branches", lambda *_args: {branch}
    )
    monkeypatch.setattr(release, "list_catalog_prs", lambda *_args: [pr])
    monkeypatch.setattr(release, "_issue_comments", lambda *_args: [])
    with pytest.raises(release.ReleaseError, match="arbitrary closed unmerged"):
        release.reconcile_eligible_issues(tmp_path, "example/store")


def test_content_bound_attempt_is_never_overwritten(tmp_path):
    work, base_bytes, _ = _seed_remote(tmp_path)
    generation_path = _issue_relative(work)
    release.resume_release(
        work,
        generation_path,
        "example/store",
        42,
        create_pr=False,
        base_generation_bytes=base_bytes,
    )
    issue_path = work / generation_path
    changed = json.loads(issue_path.read_text())
    changed["created_at"] = "2026-08-22T20:01:00Z"
    issue_path.write_bytes(store.canonical_json(changed))
    with pytest.raises(store.StoreError, match="bind its exact attempt content"):
        release.resume_release(
            work,
            generation_path,
            "example/store",
            42,
            create_pr=False,
            base_generation_bytes=base_bytes,
        )


def test_bootstrap_migration_and_audit_are_idempotent(tmp_path):
    work, _, bootstrap_commit = _seed_remote(tmp_path)
    first = release.protect_generation(
        work,
        "example/store",
        "api/v2/generations/bootstrap-20260822.json",
        "origin",
    )
    second = release.protect_generation(
        work,
        "example/store",
        "api/v2/generations/bootstrap-20260822.json",
        "origin",
    )
    assert first == second == {
        "tag": "zoo-v2-generation-bootstrap-20260822",
        "commit": bootstrap_commit,
    }
    records = release.audit_refs(work, "example/store")
    assert records[0]["tag"] == first["tag"]
    assert records[0]["commit"] == bootstrap_commit


def test_bootstrap_migration_refuses_same_name_with_wrong_provenance(tmp_path):
    work, _, bootstrap_commit = _seed_remote(tmp_path)
    tag = "zoo-v2-generation-bootstrap-20260822"
    _git(work, "tag", "-a", tag, bootstrap_commit, "-m", "wrong provenance")
    _git(work, "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}")
    with pytest.raises(release.ReleaseError, match="annotation content/provenance differs"):
        release.protect_generation(
            work,
            "example/store",
            "api/v2/generations/bootstrap-20260822.json",
            "origin",
        )


def test_candidate_requires_exact_base_url_digest_and_crud_semantics(tmp_path):
    work, base_bytes, _ = _seed_remote(tmp_path)
    candidate = _issue_path(work)
    candidate_data = json.loads(candidate.read_text())
    candidate_commit = "b" * 40
    candidate_discovery = work / "candidate-discovery.json"
    candidate_discovery.write_bytes(store.canonical_json({
        "schema": store.DISCOVERY_SCHEMA,
        "generation_url": (
            "https://raw.githubusercontent.com/example/store/"
            f"{candidate_commit}/{candidate.relative_to(work).as_posix()}"
        ),
    }))
    base_discovery = work / "api/v2/discovery.json"
    fetcher = lambda url: base_bytes
    store.validate_candidate(
        base_discovery,
        candidate_discovery,
        candidate,
        fetcher=fetcher,
        network=False,
    )
    candidate_data["previous_generation_sha256"] = "f" * 64
    candidate.write_bytes(store.canonical_json(candidate_data))
    with pytest.raises(store.StoreError, match="E_STALE_PREDECESSOR"):
        store.validate_candidate(
            base_discovery,
            candidate_discovery,
            candidate,
            fetcher=fetcher,
            network=False,
        )


def test_trusted_validator_ignores_candidate_script_mutations(tmp_path):
    work, base_bytes, _ = _seed_remote(tmp_path)
    generation_path = _issue_relative(work)
    branch = _issue_branch(work)
    release.resume_release(
        work,
        generation_path,
        "example/store",
        42,
        create_pr=False,
        base_generation_bytes=base_bytes,
    )
    candidate = tmp_path / "candidate"
    subprocess.run(
        ["git", "clone", "--branch", branch, work.parent / "remote.git", candidate],
        check=True,
        capture_output=True,
    )
    _git(candidate, "config", "user.name", "Untrusted Candidate")
    _git(candidate, "config", "user.email", "candidate@example.invalid")
    scripts = candidate / "scripts"
    scripts.mkdir()
    (scripts / "zoo_v2_release.py").write_text("raise SystemExit(0)\n")
    (scripts / "zoo_v2_store.py").write_text("raise SystemExit(0)\n")
    candidate_generation_path = candidate / generation_path
    generation = json.loads(candidate_generation_path.read_text())
    generation["previous_generation_sha256"] = "f" * 64
    candidate_generation_path.write_bytes(store.canonical_json(generation))
    _git(candidate, "add", ".")
    _git(candidate, "commit", "-m", "malicious validator and stale candidate")

    trusted_root = Path(__file__).resolve().parent.parent
    env = {
        **os.environ,
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(trusted_root / "scripts"),
    }
    result = subprocess.run(
        [
            sys.executable,
            str(trusted_root / "scripts/zoo_v2_release.py"),
            "validate-pr",
            "--root",
            str(candidate),
            "--repository",
            "example/store",
        ],
        cwd=trusted_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 1
    assert "E_DISCOVERY_TARGET" in result.stderr


def test_validate_pr_rejects_shadow_and_extra_changed_paths(tmp_path):
    work, base_bytes, _ = _seed_remote(tmp_path)
    generation_path = _issue_relative(work)
    result = release.resume_release(
        work,
        generation_path,
        "example/store",
        42,
        create_pr=False,
        base_generation_bytes=base_bytes,
    )
    candidate = tmp_path / "changed-set-candidate"
    subprocess.run(
        ["git", "clone", "--branch", result["branch"], work.parent / "remote.git", candidate],
        check=True,
        capture_output=True,
    )
    _git(candidate, "config", "user.name", "Candidate")
    _git(candidate, "config", "user.email", "candidate@example.invalid")
    shadow = candidate / "api/v2/shadow" / generation_path
    shadow.parent.mkdir(parents=True)
    shadow.write_text("{}\n")
    (candidate / "README-shadow.md").write_text("unrelated\n")
    _git(candidate, "add", ".")
    _git(candidate, "commit", "-m", "add shadow and unrelated paths")
    with pytest.raises(release.ReleaseError, match="changed-file set"):
        release.validate_pr(candidate, "example/store")


def _branch_settings() -> dict:
    return {
        "required_status_checks": {
            "strict": False,
            "contexts": ["Existing CI"],
            "checks": [{"context": "App CI", "app_id": 123}],
        },
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": False,
            "require_code_owner_reviews": True,
            "required_approving_review_count": 3,
            "require_last_push_approval": False,
            "dismissal_restrictions": {
                "users": [{"login": "maintainer"}],
                "teams": [{"slug": "release"}],
                "apps": [{"slug": "release-app"}],
            },
        },
        "restrictions": {
            "users": [{"login": "publisher"}],
            "teams": [{"slug": "store"}],
            "apps": [{"slug": "store-app"}],
        },
        "enforce_admins": {"enabled": False},
        "required_conversation_resolution": {"enabled": False},
        "required_linear_history": {"enabled": True},
        "allow_force_pushes": {"enabled": True},
        "allow_deletions": {"enabled": True},
        "block_creations": {"enabled": True},
        "lock_branch": {"enabled": True},
        "allow_fork_syncing": {"enabled": False},
    }


def _branch_response(payload: dict) -> dict:
    response = json.loads(json.dumps(payload))
    for name in (
        "enforce_admins",
        "required_conversation_resolution",
        "required_linear_history",
        "allow_force_pushes",
        "allow_deletions",
        "block_creations",
        "lock_branch",
        "allow_fork_syncing",
    ):
        response[name] = {"enabled": payload[name]}
    return response


class _ProtectionApi:
    def __init__(self, *, existing_ruleset=True):
        self.branch = _branch_settings()
        self.calls = []
        self.ruleset = {
            "id": 17,
            "name": protection.TAG_RULESET_NAME,
            "target": "tag",
            "enforcement": "evaluate",
            "bypass_actors": [{"actor_id": 1, "actor_type": "Team"}],
            "conditions": {
                "ref_name": {
                    "include": ["refs/tags/release-*"],
                    "exclude": [
                        "refs/tags/release-test-*",
                        protection.TAG_PATTERN,
                    ],
                }
            },
            "rules": [{"type": "creation"}],
        } if existing_ruleset else None

    def __call__(self, method, endpoint, payload):
        self.calls.append((method, endpoint, json.loads(json.dumps(payload))))
        if endpoint.endswith("/branches/main/protection"):
            if method == "GET":
                return self.branch
            self.branch = _branch_response(payload)
            return self.branch
        if endpoint.endswith("/rulesets?includes_parents=false"):
            summaries = [{"id": 99, "name": "Existing release rules"}]
            if self.ruleset is not None:
                summaries.append({
                    "id": self.ruleset["id"],
                    "name": self.ruleset["name"],
                })
            return summaries
        if endpoint.endswith("/rulesets") and method == "POST":
            self.ruleset = {"id": 17, **payload}
            return self.ruleset
        if endpoint.endswith("/rulesets/17"):
            if method == "GET":
                return self.ruleset
            self.ruleset = {"id": 17, **payload}
            return self.ruleset
        raise AssertionError((method, endpoint, payload))


def test_protection_configuration_is_additive_and_idempotent():
    api = _ProtectionApi()
    first = protection.configure_and_verify("example/store", VALIDATOR_APP_ID, api)
    first_branch_put = next(
        payload
        for method, endpoint, payload in api.calls
        if method == "PUT" and endpoint.endswith("/branches/main/protection")
    )
    assert set(first_branch_put["required_status_checks"]["contexts"]) == {
        "Existing CI",
    }
    assert first_branch_put["required_status_checks"]["checks"] == [
        {"context": "App CI", "app_id": 123},
        {"context": protection.STATUS_CONTEXT, "app_id": VALIDATOR_APP_ID},
    ]
    reviews = first_branch_put["required_pull_request_reviews"]
    assert reviews["required_approving_review_count"] == 3
    assert reviews["require_code_owner_reviews"] is True
    assert reviews["dismissal_restrictions"] == {
        "users": ["maintainer"],
        "teams": ["release"],
        "apps": ["release-app"],
    }
    assert first_branch_put["restrictions"] == {
        "users": ["publisher"],
        "teams": ["store"],
        "apps": ["store-app"],
    }
    assert first_branch_put["required_linear_history"] is True
    assert first_branch_put["block_creations"] is True
    assert first_branch_put["lock_branch"] is True
    assert first_branch_put["allow_force_pushes"] is False
    assert first_branch_put["allow_deletions"] is False

    ruleset_put = next(
        payload
        for method, endpoint, payload in api.calls
        if method == "PUT" and endpoint.endswith("/rulesets/17")
    )
    assert ruleset_put["conditions"]["ref_name"] == {
        "include": [protection.TAG_PATTERN],
        "exclude": [],
    }
    assert {rule["type"] for rule in ruleset_put["rules"]} == protection.TAG_RULE_TYPES
    assert ruleset_put["bypass_actors"] == []
    assert first["tag_ruleset"]["id"] == 17
    assert first["tag_ruleset"]["bypass_actors"] == []
    assert not any(endpoint.endswith("/rulesets/99") for _, endpoint, _ in api.calls)

    api.calls.clear()
    second = protection.configure_and_verify("example/store", VALIDATOR_APP_ID, api)
    second_ruleset_put = next(
        payload
        for method, endpoint, payload in api.calls
        if method == "PUT" and endpoint.endswith("/rulesets/17")
    )
    assert second_ruleset_put == ruleset_put
    assert second["branch_protection"] == first["branch_protection"]
    assert not any(method == "POST" for method, _, _ in api.calls)


def test_missing_named_ruleset_is_created_with_required_payload():
    api = _ProtectionApi(existing_ruleset=False)
    protection.configure_and_verify("example/store", VALIDATOR_APP_ID, api)
    payload = next(
        payload for method, endpoint, payload in api.calls
        if method == "POST" and endpoint.endswith("/rulesets")
    )
    assert payload["target"] == "tag"
    assert payload["enforcement"] == "active"
    assert payload["conditions"]["ref_name"]["include"] == [protection.TAG_PATTERN]
    assert {rule["type"] for rule in payload["rules"]} == protection.TAG_RULE_TYPES
    assert payload["bypass_actors"] == []


@pytest.mark.parametrize(
    "settings",
    [
        None,
        {"required_status_checks": []},
        {"required_status_checks": {"checks": [{}]}},
        {"required_pull_request_reviews": []},
        {
            "required_pull_request_reviews": {
                "required_approving_review_count": "one"
            }
        },
        {"restrictions": []},
        {"required_linear_history": {"enabled": "yes"}},
    ],
)
def test_additive_payload_refuses_malformed_existing_settings(settings):
    with pytest.raises(protection.ProtectionError, match="E_PROTECTION_CONFIG"):
        protection.protection_payload(settings, VALIDATOR_APP_ID)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["required_status_checks"].update(strict=False),
        lambda value: value["required_status_checks"].update(checks=[]),
        lambda value: value.update(enforce_admins={"enabled": False}),
        lambda value: value.update(allow_force_pushes={"enabled": True}),
        lambda value: value.update(allow_deletions={"enabled": True}),
        lambda value: value["required_pull_request_reviews"].update(
            required_approving_review_count=0
        ),
        lambda value: value.update(required_pull_request_reviews=None),
    ],
)
def test_protection_verification_fails_closed_but_accepts_supersets(mutation):
    settings = _branch_response(
        protection.protection_payload(_branch_settings(), VALIDATOR_APP_ID)
    )
    protection.verify_settings(settings, VALIDATOR_APP_ID)
    mutation(settings)
    with pytest.raises(protection.ProtectionError, match="E_PROTECTION_VERIFY"):
        protection.verify_settings(settings, VALIDATOR_APP_ID)


def test_status_binding_rejects_generic_and_github_actions_app():
    generic = _branch_response(
        protection.protection_payload(_branch_settings(), VALIDATOR_APP_ID)
    )
    generic["required_status_checks"]["checks"] = []
    generic["required_status_checks"]["contexts"].append(protection.STATUS_CONTEXT)
    with pytest.raises(protection.ProtectionError, match="validator GitHub App"):
        protection.verify_settings(generic, VALIDATOR_APP_ID)

    actions = _branch_response(
        protection.protection_payload(_branch_settings(), VALIDATOR_APP_ID)
    )
    trusted = next(
        check for check in actions["required_status_checks"]["checks"]
        if check["context"] == protection.STATUS_CONTEXT
    )
    trusted["app_id"] = 15368
    with pytest.raises(protection.ProtectionError, match="validator GitHub App"):
        protection.verify_settings(actions, VALIDATOR_APP_ID)


def test_configuration_replaces_unbound_status_with_exact_app_check():
    existing = _branch_settings()
    existing["required_status_checks"]["contexts"].append(protection.STATUS_CONTEXT)
    existing["required_status_checks"]["checks"].append({
        "context": protection.STATUS_CONTEXT,
        "app_id": 15368,
    })
    payload = protection.protection_payload(existing, VALIDATOR_APP_ID)
    assert protection.STATUS_CONTEXT not in payload["required_status_checks"]["contexts"]
    assert [
        check for check in payload["required_status_checks"]["checks"]
        if check["context"] == protection.STATUS_CONTEXT
    ] == [{"context": protection.STATUS_CONTEXT, "app_id": VALIDATOR_APP_ID}]


@pytest.mark.parametrize("app_id", [None, 0, -1, False, "4242"])
def test_protection_configuration_requires_numeric_validator_app_id(app_id):
    with pytest.raises(protection.ProtectionError, match="E_VALIDATOR_APP"):
        protection.protection_payload(_branch_settings(), app_id)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(enforcement="evaluate"),
        lambda value: value.update(target="branch"),
        lambda value: value["conditions"]["ref_name"].update(include=[]),
        lambda value: value["conditions"]["ref_name"].update(exclude=["~ALL"]),
        lambda value: value["conditions"].update(repository_name={
            "include": ["example/store"],
            "exclude": [],
        }),
        lambda value: value.update(rules=[{"type": "deletion"}]),
        lambda value: value.update(rules=None),
        lambda value: value.update(bypass_actors=[{
            "actor_id": 1,
            "actor_type": "Team",
            "bypass_mode": "always",
        }]),
        lambda value: value.update(bypass_actors=None),
    ],
)
def test_tag_ruleset_verification_fails_closed(mutation):
    ruleset = {
        "id": 17,
        **protection._ruleset_payload(),
    }
    protection.verify_tag_ruleset(ruleset)
    mutation(ruleset)
    with pytest.raises(protection.ProtectionError, match="E_RULESET_VERIFY"):
        protection.verify_tag_ruleset(ruleset)


def test_protection_audit_refuses_absent_and_malformed_settings(tmp_path):
    with pytest.raises(protection.ProtectionError, match="administrator must run"):
        protection.verify_audit_file(
            tmp_path / "absent.json", "example/store", VALIDATOR_APP_ID
        )
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{")
    with pytest.raises(protection.ProtectionError, match="cannot read"):
        protection.verify_audit_file(malformed, "example/store", VALIDATOR_APP_ID)
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"schema": protection.AUDIT_SCHEMA}))
    with pytest.raises(protection.ProtectionError, match="identity fields"):
        protection.verify_audit_file(incomplete, "example/store", VALIDATOR_APP_ID)
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_valid_audit()))
    assert protection.verify_audit_file(
        valid, "example/store", VALIDATOR_APP_ID
    )["tag_ruleset"]["id"] == 17


def test_protection_audit_requires_exact_app_and_empty_ruleset_bypass():
    wrong_app = _valid_audit()
    wrong_app["validator_app_id"] = 15368
    wrong_app["branch_protection"]["required_status_checks"][0]["app_id"] = 15368
    with pytest.raises(protection.ProtectionError, match="identity fields"):
        protection.verify_audit(wrong_app, "example/store", VALIDATOR_APP_ID)

    bypass = _valid_audit()
    bypass["tag_ruleset"]["bypass_actors"] = [{
        "actor_id": 1,
        "actor_type": "Team",
        "bypass_mode": "pull_request",
    }]
    with pytest.raises(protection.ProtectionError, match="ruleset minima"):
        protection.verify_audit(bypass, "example/store", VALIDATOR_APP_ID)


@pytest.mark.parametrize(
    ("paths", "branch", "head_repo", "expected"),
    [
        (["README.md"], "feature/docs", "example/store", "none"),
        (
            ["api/v2/discovery.json", SAMPLE_ATTEMPT_PATH],
            SAMPLE_ATTEMPT_BRANCH,
            "example/store",
            "issue",
        ),
        (
            ["scripts/configure_zoo_v2_protection.py"],
            release.BOOTSTRAP_BRANCH,
            "example/store",
            "bootstrap",
        ),
    ],
)
def test_protected_diff_gate_classifies_authorized_changes(
    paths, branch, head_repo, expected
):
    assert release.inspect_pr_change(
        paths,
        head_ref=branch,
        head_repository=head_repo,
        repository="example/store",
    ) == expected


@pytest.mark.parametrize(
    ("paths", "branch", "head_repo"),
    [
        (
            ["api/v2/discovery.json", SAMPLE_ATTEMPT_PATH],
            "feature/bypass",
            "example/store",
        ),
        (
            ["api/v2/discovery.json", SAMPLE_ATTEMPT_PATH],
            SAMPLE_ATTEMPT_BRANCH,
            "fork/store",
        ),
        (
            ["api/v2/discovery.json"],
            SAMPLE_ATTEMPT_BRANCH,
            "example/store",
        ),
        (
            ["api/v2/discovery.json", SAMPLE_ATTEMPT_PATH,
             "scripts/zoo_v2_store.py"],
            SAMPLE_ATTEMPT_BRANCH,
            "example/store",
        ),
        (
            ["api/v2/discovery.json"],
            release.BOOTSTRAP_BRANCH,
            "example/store",
        ),
    ],
)
def test_protected_diff_gate_cannot_bypass_branch_with_catalog_edits(
    paths, branch, head_repo
):
    with pytest.raises(release.ReleaseError, match="E_PROTECTED_PR"):
        release.inspect_pr_change(
            paths,
            head_ref=branch,
            head_repository=head_repo,
            repository="example/store",
        )


def _seed_diff_repository(root: Path) -> tuple[str, str]:
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "Diff Test")
    _git(root, "config", "user.email", "diff@example.invalid")
    _git(root, "commit", "--allow-empty", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")
    return base, base


def test_complete_local_diff_finds_protected_path_after_3000_files(tmp_path):
    work = tmp_path / "complete-diff"
    base, _ = _seed_diff_repository(work)
    ordinary = work / "0000-ordinary"
    ordinary.mkdir()
    for index in range(3001):
        (ordinary / f"{index:04d}.txt").write_text("inert\n")
    protected = work / "api/v2/generations/late.json"
    protected.parent.mkdir(parents=True)
    protected.write_text("{}\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "large candidate")
    head = _git(work, "rev-parse", "HEAD")

    changed = release.complete_changed_files(work, base, head)
    assert len(changed) == 3002
    assert changed.index("api/v2/generations/late.json") > 3000
    with pytest.raises(release.ReleaseError, match="E_PROTECTED_PR"):
        release.inspect_pr_change(
            changed,
            head_ref="feature/large",
            head_repository="example/store",
            repository="example/store",
        )


def test_complete_local_diff_rejects_newline_path_and_shallow_checkout(
    tmp_path, monkeypatch
):
    work = tmp_path / "hostile-diff"
    base, _ = _seed_diff_repository(work)
    (work / "bad\npath.txt").write_text("inert\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "hostile path")
    head = _git(work, "rev-parse", "HEAD")
    with pytest.raises(release.ReleaseError, match="NUL/newline"):
        release.complete_changed_files(work, base, head)

    monkeypatch.setattr(release, "_git", lambda *_args, **_kwargs: "true")
    with pytest.raises(release.ReleaseError, match="shallow checkout"):
        release.complete_changed_files(work, base, head)


def test_changed_path_list_rejects_nul_oversize_and_count(tmp_path, monkeypatch):
    path = tmp_path / "changed.txt"
    path.write_bytes(b"README.md\0api/v2/discovery.json\n")
    with pytest.raises(release.ReleaseError, match="NUL"):
        release._read_changed_files(path)

    path.write_bytes(b"a\nb\nc\nd\n")
    monkeypatch.setattr(release, "MAX_CHANGED_FILES", 3)
    with pytest.raises(release.ReleaseError, match="more than 3"):
        release._read_changed_files(path)

    monkeypatch.setattr(release, "MAX_CHANGED_PATH_BYTES", 3)
    with pytest.raises(release.ReleaseError, match="oversized"):
        release._read_changed_files(path)


def test_release_refuses_without_admin_audit_before_git_mutation(tmp_path):
    work, base_bytes, _ = _seed_remote(tmp_path)
    generation_path = _issue_relative(work)
    branch = _issue_branch(work)
    (work / protection.AUDIT_PATH).unlink()
    with pytest.raises(release.ReleaseError, match="E_PROTECTION_AUDIT"):
        release.resume_release(
            work,
            generation_path,
            "example/store",
            42,
            create_pr=False,
            base_generation_bytes=base_bytes,
        )
    assert branch not in _git(work, "branch", "--list")


def test_workflows_lock_permissions_queue_validation_and_audit():
    root = Path(__file__).resolve().parent.parent
    catalog = (root / ".github/workflows/zoo-v2-catalog-pr.yml").read_text()
    validation = (root / ".github/workflows/zoo-v2-pr-validation.yml").read_text()
    audit = (root / ".github/workflows/zoo-v2-audit.yml").read_text()
    migration = (root / ".github/workflows/zoo-v2-bootstrap-protect.yml").read_text()
    main_advance = (root / ".github/workflows/zoo-v2-main-advance.yml").read_text()
    completion = (
        root / ".github/workflows/zoo-v2-merge-completion.yml"
    ).read_text()
    release_source = (root / "scripts/zoo_v2_release.py").read_text()
    assert "zoo-v2-catalog-integration-coalescing" in catalog
    assert "Contention coalescing only" in catalog
    assert "schedule:" in catalog
    assert "workflow_dispatch:" in catalog
    assert "issues:" in catalog
    assert "zoo_v2_release.py reconcile" in catalog
    assert "--github-output \"$GITHUB_OUTPUT\"" in catalog
    assert "steps.reconcile.outputs.issue_number" in catalog
    assert "github.event.issue" not in catalog
    assert "GITHUB_EVENT_PATH" not in catalog
    assert release.RELEASE_LOCK_REF in (root / "scripts/zoo_v2_release.py").read_text()
    assert "recover-lock" in (root / "scripts/zoo_v2_release.py").read_text()
    protection_check = "configure_zoo_v2_protection.py verify-audit"
    assert protection_check in catalog
    assert catalog.index(protection_check) < catalog.index("zoo_v2_release.py resume")
    assert "zoo_v2_release.py resume" in catalog
    assert '--event-path "$GITHUB_WORKSPACE/.zoo-v2-selected-issue.json"' in catalog
    assert '--allow-actors "$ALLOWED_ACTORS"' in catalog
    assert "pull-requests: write" in catalog
    assert "pull_request_target:" in validation
    assert "Inspect complete local diff with trusted main" in validation
    assert "/files?per_page=100" not in validation
    assert "git diff" not in validation
    assert "zoo_v2_release.py\" gate-pr" in validation
    assert "path: trusted-main" in validation
    assert "path: candidate" in validation
    assert "--base-sha \"$base_sha\"" in validation
    assert "--head-sha \"$HEAD_SHA\"" in validation
    assert '"$TRUSTED_ROOT/scripts/zoo_v2_release.py" validate-pr' in validation
    assert 'PYTHONPATH="$TRUSTED_ROOT/scripts"' in validation
    assert '--root "$CANDIDATE_ROOT"' in validation
    assert "contents: read" in validation
    assert "pull-requests: read" in validation
    assert "statuses: write" not in validation
    assert "actions/create-github-app-token@v2" in validation
    assert "secrets.ZOO_V2_VALIDATOR_APP_ID" in validation
    assert "secrets.ZOO_V2_VALIDATOR_PRIVATE_KEY" in validation
    assert "GH_TOKEN: ${{ github.token }}" not in validation
    assert "environment: zoo-v2-validator" in validation
    assert "cancel-in-progress: true" in validation
    assert "steps.inspection.outcome == 'success'" in validation
    assert "No protected Store paths changed" in validation
    assert "validate-bootstrap-pr" in validation
    assert "Zoo v2 current-main" in validation
    assert "complete-merge" in completion
    assert "pull_request_target:" in completion
    assert "types: [closed]" in completion
    assert "github.event.pull_request.merged == true" in completion
    assert "issues: write" in completion
    assert "fetch-depth: 0" in completion
    assert "zoo_v2_release.py audit-refs" in audit
    assert "--network" in audit
    assert "contents: read" in audit
    assert "zoo_v2_release.py protect-bootstrap" in migration
    assert protection_check in migration
    assert migration.index(protection_check) < migration.index(
        "zoo_v2_release.py protect-bootstrap"
    )
    assert "contents: write" in migration
    assert "GH_TOKEN: ${{ github.token }}" not in catalog.split(
        "Require committed admin protection audit", 1
    )[1].split("Ensure bootstrap", 1)[0]
    assert "GH_TOKEN: ${{ github.token }}" not in migration
    assert "Revalidate each open Zoo v2 PR with trusted main tooling" in main_advance
    assert "list-prs" in main_advance
    assert "gh pr list" not in main_advance
    assert "--limit 100" not in main_advance
    assert "statuses: write" not in main_advance
    assert "actions/create-github-app-token@v2" in main_advance
    assert "GH_TOKEN: ${{ github.token }}" not in main_advance
    assert "VALIDATOR_TOKEN: ${{ steps.validator-token.outputs.token }}" in main_advance
    assert "RETIRE_TOKEN: ${{ github.token }}" in main_advance
    assert "supersede-pr" in main_advance
    assert "issues: write" in main_advance
    assert "pull-requests: write" in main_advance
    assert "zoo_v2_release.py\" gate-pr" not in main_advance
    assert '"$tools" gate-pr' in main_advance
    assert "Zoo v2 current-main" in main_advance
    assert "cancel-in-progress: true" in main_advance
    assert "BASE_SHA: ${{ github.sha }}" in main_advance
    assert "--atomic" in release_source
    assert "validate_selected_issue(" in release_source
    assert release.COMPLETION_MARKER_SCHEMA in release_source
    assert release.SUPERSEDED_MARKER_SCHEMA in release_source
