"""Git-remote and workflow tests for the serialized Zoo v2 release lane."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import configure_zoo_v2_protection as protection
import zoo_v2_release as release
import zoo_v2_store as store


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


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


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
        "generation_id": "issue-42",
        "created_at": "2026-08-22T20:00:00Z",
        "source_issue": 42,
        "previous_generation_url": base_url,
        "previous_generation_sha256": store.sha256_bytes(base_bytes),
        "prototypes": [_prototype("0.2.0")],
        "tombstones": [],
    }
    issue_path = work / "api/v2/generations/issue-42.json"
    issue_path.write_bytes(store.canonical_json(issue_generation))
    return work, base_bytes, generation_commit


@pytest.mark.parametrize(
    "stop_after",
    ["generation-push", "tag-push", "discovery-push"],
)
def test_resume_after_each_git_failure_stage(tmp_path, stop_after):
    work, base_bytes, _ = _seed_remote(tmp_path)
    kwargs = {
        "root": work,
        "generation_path": "api/v2/generations/issue-42.json",
        "repository": "example/store",
        "issue_number": 42,
        "create_pr": False,
        "base_generation_bytes": base_bytes,
    }
    with pytest.raises(RuntimeError, match="simulated failure"):
        release.resume_release(**kwargs, stop_after=stop_after)

    result = release.resume_release(**kwargs)
    assert result["tag"] == "zoo-v2-generation-issue-42"
    assert len(result["generation_commit"]) == 40
    assert _git(work, "rev-parse", f"{result['tag']}^{{commit}}") == result["generation_commit"]
    remote_discovery = json.loads(
        _git(work, "show", "origin/zoo-v2/issue-42:api/v2/discovery.json")
    )
    assert f"/{result['generation_commit']}/" in remote_discovery["generation_url"]


def test_resume_after_pr_is_find_or_create_idempotent(tmp_path):
    work, base_bytes, _ = _seed_remote(tmp_path)
    calls = []
    durable_pr = {
        "number": 7,
        "url": "https://github.com/example/store/pull/7",
        "state": "OPEN",
        "headRefName": "zoo-v2/issue-42",
        "baseRefName": "main",
    }

    def ensure_pr(root, repository, issue_number, branch):
        calls.append((repository, issue_number, branch))
        return durable_pr

    kwargs = {
        "root": work,
        "generation_path": "api/v2/generations/issue-42.json",
        "repository": "example/store",
        "issue_number": 42,
        "pull_requests": [durable_pr],
        "base_generation_bytes": base_bytes,
        "pr_ensurer": ensure_pr,
    }
    with pytest.raises(RuntimeError, match="simulated failure after PR"):
        release.resume_release(**kwargs, stop_after="pr")
    result = release.resume_release(**kwargs)
    assert result["pr"] == durable_pr
    assert calls == [
        ("example/store", 42, "zoo-v2/issue-42"),
        ("example/store", 42, "zoo-v2/issue-42"),
    ]


def test_queue_rejects_open_pr_or_unfinished_sibling():
    with pytest.raises(release.ReleaseError, match="E_QUEUE_BUSY.*#9"):
        release.validate_queue(42, set(), [{
            "number": 9,
            "state": "OPEN",
            "headRefName": "zoo-v2/issue-9",
        }])
    with pytest.raises(release.ReleaseError, match="unfinished.*issue-8"):
        release.validate_queue(42, {"zoo-v2/issue-8"}, [])
    release.validate_queue(42, {"zoo-v2/issue-8"}, [{
        "number": 8,
        "state": "MERGED",
        "mergedAt": "2026-08-22T20:00:00Z",
        "headRefName": "zoo-v2/issue-8",
    }])


def test_mismatched_existing_branch_is_never_overwritten(tmp_path):
    work, base_bytes, _ = _seed_remote(tmp_path)
    release.resume_release(
        work,
        "api/v2/generations/issue-42.json",
        "example/store",
        42,
        create_pr=False,
        base_generation_bytes=base_bytes,
    )
    issue_path = work / "api/v2/generations/issue-42.json"
    changed = json.loads(issue_path.read_text())
    changed["created_at"] = "2026-08-22T20:01:00Z"
    issue_path.write_bytes(store.canonical_json(changed))
    with pytest.raises(release.ReleaseError, match="mismatched generation bytes"):
        release.resume_release(
            work,
            "api/v2/generations/issue-42.json",
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
    candidate = work / "api/v2/generations/issue-42.json"
    candidate_data = json.loads(candidate.read_text())
    candidate_commit = "b" * 40
    candidate_discovery = work / "candidate-discovery.json"
    candidate_discovery.write_bytes(store.canonical_json({
        "schema": store.DISCOVERY_SCHEMA,
        "generation_url": (
            "https://raw.githubusercontent.com/example/store/"
            f"{candidate_commit}/api/v2/generations/issue-42.json"
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
    release.resume_release(
        work,
        "api/v2/generations/issue-42.json",
        "example/store",
        42,
        create_pr=False,
        base_generation_bytes=base_bytes,
    )
    candidate = tmp_path / "candidate"
    subprocess.run(
        ["git", "clone", "--branch", "zoo-v2/issue-42", work.parent / "remote.git", candidate],
        check=True,
        capture_output=True,
    )
    _git(candidate, "config", "user.name", "Untrusted Candidate")
    _git(candidate, "config", "user.email", "candidate@example.invalid")
    scripts = candidate / "scripts"
    scripts.mkdir()
    (scripts / "zoo_v2_release.py").write_text("raise SystemExit(0)\n")
    (scripts / "zoo_v2_store.py").write_text("raise SystemExit(0)\n")
    generation_path = candidate / "api/v2/generations/issue-42.json"
    generation = json.loads(generation_path.read_text())
    generation["previous_generation_sha256"] = "f" * 64
    generation_path.write_bytes(store.canonical_json(generation))
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


def test_protection_payload_and_verification_are_exact():
    calls = []
    configured = protection.protection_payload()
    response = {
        **configured,
        "required_status_checks": {
            "strict": True,
            "contexts": [protection.STATUS_CONTEXT],
        },
        **{
            key: {"enabled": value}
            for key, value in {
                "enforce_admins": True,
                "required_conversation_resolution": True,
                "allow_force_pushes": False,
                "allow_deletions": False,
                "block_creations": False,
                "lock_branch": False,
                "allow_fork_syncing": True,
            }.items()
        },
    }

    def api_call(method, endpoint, payload):
        calls.append((method, endpoint, payload))
        return response

    protection.configure_and_verify("example/store", api_call)
    assert calls == [
        (
            "PUT",
            "repos/example/store/branches/main/protection",
            configured,
        ),
        (
            "GET",
            "repos/example/store/branches/main/protection",
            None,
        ),
    ]
    assert configured["required_status_checks"] == {
        "strict": True,
        "contexts": ["Zoo v2 current-main"],
    }
    assert configured["enforce_admins"] is True
    assert configured["allow_force_pushes"] is False
    assert configured["allow_deletions"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["required_status_checks"].update(strict=False),
        lambda value: value["required_status_checks"].update(contexts=[]),
        lambda value: value.update(enforce_admins={"enabled": False}),
        lambda value: value.update(allow_force_pushes={"enabled": True}),
        lambda value: value.update(allow_deletions={"enabled": True}),
        lambda value: value["required_pull_request_reviews"].update(
            require_code_owner_reviews=True
        ),
        lambda value: value.update(required_pull_request_reviews=None),
        lambda value: value.update(restrictions={"users": []}),
    ],
)
def test_protection_verification_fails_closed(mutation):
    settings = {
        "required_status_checks": {
            "strict": True,
            "contexts": ["Zoo v2 current-main"],
        },
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "required_approving_review_count": 1,
            "require_last_push_approval": True,
        },
        "restrictions": None,
        **{
            key: {"enabled": value}
            for key, value in {
                "enforce_admins": True,
                "required_conversation_resolution": True,
                "allow_force_pushes": False,
                "allow_deletions": False,
                "block_creations": False,
                "lock_branch": False,
                "allow_fork_syncing": True,
            }.items()
        },
    }
    mutation(settings)
    with pytest.raises(protection.ProtectionError, match="E_PROTECTION_VERIFY"):
        protection.verify_settings(settings)


def test_workflows_lock_permissions_queue_validation_and_audit():
    root = Path(__file__).resolve().parent.parent
    catalog = (root / ".github/workflows/zoo-v2-catalog-pr.yml").read_text()
    validation = (root / ".github/workflows/zoo-v2-pr-validation.yml").read_text()
    audit = (root / ".github/workflows/zoo-v2-audit.yml").read_text()
    migration = (root / ".github/workflows/zoo-v2-bootstrap-protect.yml").read_text()
    main_advance = (root / ".github/workflows/zoo-v2-main-advance.yml").read_text()
    assert "zoo-v2-catalog-integration-queue" in catalog
    protection_check = "configure_zoo_v2_protection.py verify"
    assert protection_check in catalog
    assert catalog.index(protection_check) < catalog.index("zoo_v2_release.py resume")
    assert "zoo_v2_release.py resume" in catalog
    assert "pull-requests: write" in catalog
    assert "path: trusted-main" in validation
    assert "path: candidate" in validation
    assert '"$TRUSTED_ROOT/scripts/zoo_v2_release.py" validate-pr' in validation
    assert 'PYTHONPATH="$TRUSTED_ROOT/scripts"' in validation
    assert '--root "$CANDIDATE_ROOT"' in validation
    assert "contents: read" in validation
    assert "pull-requests: read" in validation
    assert "statuses: write" in validation
    assert "cancel-in-progress: true" in validation
    assert "IS_ZOO:" in validation
    assert "Not a Zoo v2 candidate" in validation
    assert "Zoo v2 current-main" in validation
    assert "zoo_v2_release.py audit-refs" in audit
    assert "--network" in audit
    assert "contents: read" in audit
    assert "zoo_v2_release.py protect-bootstrap" in migration
    assert protection_check in migration
    assert migration.index(protection_check) < migration.index(
        "zoo_v2_release.py protect-bootstrap"
    )
    assert "contents: write" in migration
    assert "Revalidate each open Zoo v2 PR with trusted main tooling" in main_advance
    assert "statuses: write" in main_advance
    assert "Zoo v2 current-main" in main_advance
    assert "cancel-in-progress: true" in main_advance
    assert "BASE_SHA: ${{ github.sha }}" in main_advance
