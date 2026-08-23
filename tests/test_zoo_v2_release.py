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


def _valid_audit(repository: str = "example/store") -> dict:
    return {
        "schema": protection.AUDIT_SCHEMA,
        "repository": repository,
        "verified_at": "2026-08-22T20:00:00Z",
        "branch": "main",
        "branch_protection": {
            "strict": True,
            "required_status_contexts": [
                "Existing CI",
                protection.STATUS_CONTEXT,
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
        },
    }


def _write_audit(root: Path, repository: str = "example/store") -> None:
    path = root / protection.AUDIT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_valid_audit(repository), indent=2, sort_keys=True) + "\n")


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
            return [] if self.ruleset is None else [{
                "id": self.ruleset["id"],
                "name": self.ruleset["name"],
            }]
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
    first = protection.configure_and_verify("example/store", api)
    first_branch_put = next(
        payload
        for method, endpoint, payload in api.calls
        if method == "PUT" and endpoint.endswith("/branches/main/protection")
    )
    assert set(first_branch_put["required_status_checks"]["contexts"]) == {
        "Existing CI",
        protection.STATUS_CONTEXT,
    }
    assert first_branch_put["required_status_checks"]["checks"] == [
        {"context": "App CI", "app_id": 123}
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
        "include": ["refs/tags/release-*", protection.TAG_PATTERN],
        "exclude": ["refs/tags/release-test-*"],
    }
    assert {rule["type"] for rule in ruleset_put["rules"]} == {
        "creation",
        *protection.TAG_RULE_TYPES,
    }
    assert ruleset_put["bypass_actors"] == [{"actor_id": 1, "actor_type": "Team"}]
    assert first["tag_ruleset"]["id"] == 17

    api.calls.clear()
    second = protection.configure_and_verify("example/store", api)
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
    protection.configure_and_verify("example/store", api)
    payload = next(
        payload for method, endpoint, payload in api.calls
        if method == "POST" and endpoint.endswith("/rulesets")
    )
    assert payload["target"] == "tag"
    assert payload["enforcement"] == "active"
    assert payload["conditions"]["ref_name"]["include"] == [protection.TAG_PATTERN]
    assert {rule["type"] for rule in payload["rules"]} == protection.TAG_RULE_TYPES


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
        protection.protection_payload(settings)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["required_status_checks"].update(strict=False),
        lambda value: value["required_status_checks"].update(contexts=["Other"]),
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
    settings = _branch_response(protection.protection_payload(_branch_settings()))
    protection.verify_settings(settings)
    mutation(settings)
    with pytest.raises(protection.ProtectionError, match="E_PROTECTION_VERIFY"):
        protection.verify_settings(settings)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(enforcement="evaluate"),
        lambda value: value.update(target="branch"),
        lambda value: value["conditions"]["ref_name"].update(include=[]),
        lambda value: value["conditions"]["ref_name"].update(
            exclude=[protection.TAG_PATTERN]
        ),
        lambda value: value.update(rules=[{"type": "deletion"}]),
        lambda value: value.update(rules=None),
    ],
)
def test_tag_ruleset_verification_fails_closed(mutation):
    ruleset = {
        "id": 17,
        **protection._ruleset_payload(),
        "rules": [
            {"type": "creation"},
            *[{"type": name} for name in sorted(protection.TAG_RULE_TYPES)],
        ],
    }
    protection.verify_tag_ruleset(ruleset)
    mutation(ruleset)
    with pytest.raises(protection.ProtectionError, match="E_RULESET_VERIFY"):
        protection.verify_tag_ruleset(ruleset)


def test_protection_audit_refuses_absent_and_malformed_settings(tmp_path):
    with pytest.raises(protection.ProtectionError, match="administrator must run"):
        protection.verify_audit_file(tmp_path / "absent.json", "example/store")
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{")
    with pytest.raises(protection.ProtectionError, match="cannot read"):
        protection.verify_audit_file(malformed, "example/store")
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"schema": protection.AUDIT_SCHEMA}))
    with pytest.raises(protection.ProtectionError, match="identity fields"):
        protection.verify_audit_file(incomplete, "example/store")
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_valid_audit()))
    assert protection.verify_audit_file(valid, "example/store")["tag_ruleset"]["id"] == 17


@pytest.mark.parametrize(
    ("paths", "branch", "head_repo", "expected"),
    [
        (["README.md"], "feature/docs", "example/store", "none"),
        (
            ["api/v2/discovery.json", "api/v2/generations/issue-42.json"],
            "zoo-v2/issue-42",
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
            ["api/v2/discovery.json", "api/v2/generations/issue-42.json"],
            "feature/bypass",
            "example/store",
        ),
        (
            ["api/v2/discovery.json", "api/v2/generations/issue-42.json"],
            "zoo-v2/issue-42",
            "fork/store",
        ),
        (
            ["api/v2/discovery.json"],
            "zoo-v2/issue-42",
            "example/store",
        ),
        (
            ["api/v2/discovery.json", "api/v2/generations/issue-42.json",
             "scripts/zoo_v2_store.py"],
            "zoo-v2/issue-42",
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


def test_release_refuses_without_admin_audit_before_git_mutation(tmp_path):
    work, base_bytes, _ = _seed_remote(tmp_path)
    (work / protection.AUDIT_PATH).unlink()
    with pytest.raises(release.ReleaseError, match="E_PROTECTION_AUDIT"):
        release.resume_release(
            work,
            "api/v2/generations/issue-42.json",
            "example/store",
            42,
            create_pr=False,
            base_generation_bytes=base_bytes,
        )
    assert "zoo-v2/issue-42" not in _git(work, "branch", "--list")


def test_workflows_lock_permissions_queue_validation_and_audit():
    root = Path(__file__).resolve().parent.parent
    catalog = (root / ".github/workflows/zoo-v2-catalog-pr.yml").read_text()
    validation = (root / ".github/workflows/zoo-v2-pr-validation.yml").read_text()
    audit = (root / ".github/workflows/zoo-v2-audit.yml").read_text()
    migration = (root / ".github/workflows/zoo-v2-bootstrap-protect.yml").read_text()
    main_advance = (root / ".github/workflows/zoo-v2-main-advance.yml").read_text()
    assert "zoo-v2-catalog-integration-queue" in catalog
    protection_check = "configure_zoo_v2_protection.py verify-audit"
    assert protection_check in catalog
    assert catalog.index(protection_check) < catalog.index("zoo_v2_release.py resume")
    assert "zoo_v2_release.py resume" in catalog
    assert "pull-requests: write" in catalog
    assert "pull_request_target:" in validation
    assert "Inspect every changed path with trusted main" in validation
    assert "/files?per_page=100" in validation
    assert ".previous_filename // empty" in validation
    assert "zoo_v2_release.py\" gate-pr" in validation
    assert "path: trusted-main" in validation
    assert "path: candidate" in validation
    assert '"$TRUSTED_ROOT/scripts/zoo_v2_release.py" validate-pr' in validation
    assert 'PYTHONPATH="$TRUSTED_ROOT/scripts"' in validation
    assert '--root "$CANDIDATE_ROOT"' in validation
    assert "contents: read" in validation
    assert "pull-requests: read" in validation
    assert "statuses: write" in validation
    assert "cancel-in-progress: true" in validation
    assert "steps.inspection.outcome == 'success'" in validation
    assert "No protected Store paths changed" in validation
    assert "validate-bootstrap-pr" in validation
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
    assert "GH_TOKEN: ${{ github.token }}" not in catalog.split(
        "Require committed admin protection audit", 1
    )[1].split("Ensure bootstrap", 1)[0]
    assert "GH_TOKEN: ${{ github.token }}" not in migration
    assert "Revalidate each open Zoo v2 PR with trusted main tooling" in main_advance
    assert "statuses: write" in main_advance
    assert "Zoo v2 current-main" in main_advance
    assert "cancel-in-progress: true" in main_advance
    assert "BASE_SHA: ${{ github.sha }}" in main_advance
