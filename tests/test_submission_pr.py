"""Issue -> staging PR -> approval PR -> owner merge, using only local doubles."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
from urllib.parse import parse_qs, urlsplit

import pytest

import lib_desktop
import lib_rapp
from test_receiver import _bundle_payload, _federation_payload
from test_zoo_v2_release import _valid_audit

# Keyed on the validator's declared contracts, never on its error text: the
# complete application contract is optional in this tree.
COMPLETE_SCHEMA = getattr(lib_rapp, "SCHEMA_APPLICATION", None)
if COMPLETE_SCHEMA:
    from test_application_contract import complete_application  # noqa: F401  (fixture)
needs_complete_contract = pytest.mark.skipif(
    not COMPLETE_SCHEMA, reason="the complete application contract is not in this tree")

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("submission_pr", ROOT / ".github/workflows/rapplication_pr.py")
prflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prflow)


def git(root, *args):
    command = ["git"]
    if root.name == "origin.git":
        command += ["--git-dir", str(root)]
    return subprocess.run([*command, *args], cwd=root, check=True, capture_output=True,
                          text=True, timeout=30).stdout.strip()


class LocalGitHub(prflow.Client):
    """Real local Git plus an in-memory API; no tokens, public pushes or network."""
    def __init__(self, root, remote):
        super().__init__(root, "example/store")
        self.remote = remote
        self.issues, self.prs, self.api_calls, self.git_calls = {}, {}, [], []
        self.failure = None
        self.checks, self.statuses = {}, {}
        self.validator_runs = []

    def git(self, *args, **kwargs):
        self.git_calls.append(args)
        return super().git(*args, **kwargs)

    def push_candidate(self, commit, branch):
        if self.failure == "push":
            raise prflow.CandidateError("E_GIT: injected push failure")
        assert branch.startswith("rapplication/")
        self.git("push", "origin", f"{commit}:refs/heads/{branch}")

    def api(self, path, method="GET", payload=None):
        self.api_calls.append((path, method, copy.deepcopy(payload)))
        if self.failure == path or self.failure == (path, method):
            raise prflow.CandidateError("E_GITHUB_API: injected failure")
        parsed = urlsplit(path)
        route, query = parsed.path, parse_qs(parsed.query)
        if route == "git/ref/heads/main":
            return {"object": {"sha": git(self.remote, "rev-parse", "refs/heads/main")}}
        if route == "pulls" and method == "GET":
            matches = list(self.prs.values())
            if "head" in query:
                branch = query["head"][0].split(":", 1)[1]
                matches = [p for p in matches if p["head"]["ref"] == branch]
            if query.get("state") != ["all"]:
                matches = [p for p in matches if p["state"] == "open"]
            return copy.deepcopy(matches)
        if route == "pulls" and method == "POST":
            number = 100 + len(self.prs)
            branch = payload["head"]
            pr = {"number": number, "body": payload["body"], "title": payload["title"],
                  "state": "open", "merged": False, "user": {"login": prflow.BOT},
                  "html_url": f"https://github.com/example/store/pull/{number}",
                  "head": {"ref": branch, "sha": git(self.remote, "rev-parse", branch),
                           "repo": {"full_name": self.repository}},
                  "base": {"ref": "main"}}
            self.prs[number] = pr
            return copy.deepcopy(pr)
        if route.startswith("pulls/"):
            pr = self.prs[int(route.split("/")[1])]
            if method == "PATCH":
                pr.update(payload)
            return copy.deepcopy(pr)
        if route.startswith("issues/"):
            bits = route.split("/")
            number = int(bits[1])
            if len(bits) == 2:
                issue = self.issues[number]
                if method == "PATCH":
                    issue.update(payload)
                return copy.deepcopy(issue)
            if bits[2] == "comments":
                return {}
            if bits[2] == "labels":
                if method == "POST":
                    self.issues[number]["labels"] += [{"name": label} for label in payload["labels"]]
                elif method == "DELETE":
                    self.issues[number]["labels"] = [
                        label for label in self.issues[number]["labels"] if label["name"] != bits[3]]
                return []
        if route.startswith("actions/workflows/") and method == "POST":
            return None
        if route == "actions/workflows/zoo-v2-pr-validation.yml/runs":
            return {"workflow_runs": copy.deepcopy(self.validator_runs)}
        if route.startswith("commits/"):
            _, sha, kind = route.split("/")
            if kind == "check-runs":
                return {"check_runs": copy.deepcopy(self.checks.get(sha, []))}
            if kind == "statuses":
                return copy.deepcopy(self.statuses.get(sha, []))
        raise AssertionError((path, method, payload))

    def passing_checks(self, pr):
        sha = pr["head"]["sha"]
        self.checks[sha] = [{"id": n, "head_sha": sha, "name": name, "status": "completed",
                             "conclusion": "success", "app": {"slug": "github-actions"}}
                            for n, name in enumerate(prflow.CHECKS, 1)]
        app = _valid_audit()["validator_app"]
        self.statuses[sha] = [{"id": 1, "context": "Zoo v2 current-main", "state": "success",
                              "creator": {"login": app["login"], "id": app["user_id"]}}]
        meta = prflow.parse_candidate(pr, self.repository)
        self.validator_runs.append({
            "id": len(self.validator_runs) + 1, "display_title": f"Zoo v2 PR #{pr['number']} @ {sha}",
            "event": "workflow_dispatch", "head_sha": meta["base"],
            "status": "completed", "conclusion": "success",
        })

    def owner_merge(self, pr, *, mode="merge", different_base=False, different_tree=False):
        meta = prflow.parse_candidate(pr, self.repository)
        tree, base = meta["tree"], meta["base"]
        if different_base:
            base = git(self.root, "commit-tree", git(self.root, "rev-parse", base + "^{tree}"),
                       "-p", base, "-m", "unrelated main advance")
        if different_tree:
            tree = git(self.root, "rev-parse", base + "^{tree}")
        args = ["commit-tree", tree, "-p", base]
        if mode == "merge":
            args += ["-p", meta["head"]]
        merge = git(self.root, *args, "-m", "Owner-reviewed candidate")
        # Local remote refs simulate GitHub's merge endpoint, not publisher pushes.
        git(self.root, "push", "origin", f"{merge}:refs/heads/main")
        self.git("fetch", "origin", "main")
        self.git("reset", "--hard", "origin/main")
        self.prs[pr["number"]].update(state="closed", merged=True,
                                    merged_by={"login": "example"}, merge_commit_sha=merge)
        return self.prs[pr["number"]]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    root, remote = tmp_path / "store", tmp_path / "origin.git"
    root.mkdir()
    remote.mkdir()
    git(remote, "init", "--bare", "--initial-branch=main")
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    (root / "index.json").write_text('{"schema":"rapp-store/1.0","rapplications":[]}\n')
    (root / ".gitignore").write_text(".ci-work/\nstaging/\n")
    audit = root / ".github/zoo-v2-protection-audit.json"
    audit.parent.mkdir()
    audit.write_text(json.dumps(_valid_audit()))
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture baseline")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "origin", "main")
    return LocalGitHub(root, remote)


def event_for(client, body, *, number=32, author="alice"):
    event = {"issue": {"number": number, "title": "[RAPP] public test submission", "body": body,
                       "user": {"login": author}, "state": "open", "labels": [],
                       "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z"}}
    client.issues[number] = copy.deepcopy(event["issue"])
    return event


def reviewed_stage(client, event):
    ok, report = prflow.prepare(client.root, event, "stage")
    assert ok, report
    pr = prflow.open_pr(client, event, "stage")
    prflow.verify_candidate(client, pr)
    client.passing_checks(pr)
    client.owner_merge(pr)
    prflow.complete(client, pr["number"])
    assert client.issues[event["issue"]["number"]]["state"] == "open"
    client.issues[event["issue"]["number"]]["labels"] = [{"name": "approved"}]
    return {"issue": copy.deepcopy(client.issues[event["issue"]["number"]])}


def ready_promotion(client, event):
    approved = reviewed_stage(client, event)
    ok, report = prflow.prepare(client.root, approved, "promotion")
    assert ok, report
    assert "not published" in report
    pr = prflow.open_pr(client, approved, "promotion")
    prflow.verify_candidate(client, pr)
    client.passing_checks(pr)
    return pr


@pytest.mark.parametrize("publisher,author", [("@alice", "alice"), ("@rapp", "kody-w")])
@pytest.mark.parametrize("merge_mode", ["merge", "squash"])
def test_bundle_journey_requires_two_owner_reviewed_prs(
        client, make_rapp_dir, publisher, author, merge_mode):
    source = make_rapp_dir(publisher=publisher)
    event = event_for(client, _bundle_payload(source, author), author=author)
    baseline = client.main_sha()
    pr = ready_promotion(client, event)
    assert client.main_sha() != baseline  # staging, not the catalog, was merged
    assert json.loads(git(client.remote, "show", "main:index.json"))["rapplications"] == []
    assert client.issues[32]["state"] == "open"
    assert "promoted" not in {x["name"] for x in client.issues[32]["labels"]}
    client.owner_merge(pr, mode=merge_mode)
    prflow.complete(client, pr["number"])
    assert client.issues[32]["state"] == "closed"
    assert "promoted" in {x["name"] for x in client.issues[32]["labels"]}
    entry = json.loads((client.root / "index.json").read_text())["rapplications"][0]
    relative = entry["singleton_url"].split("/main/", 1)[1]
    installed = client.root / relative
    assert installed.is_file()
    assert lib_rapp.compute_integrity(installed.parents[1], json.loads(
        (installed.parents[1] / "manifest.json").read_text()))["singleton_sha256"] == entry["singleton_sha256"]
    assert not (client.root / "my_thing").exists()
    pushes = [c for c in client.git_calls if c[0] == "push"]
    assert len(pushes) == 2
    assert all(c[-1].split(":", 1)[1].startswith("refs/heads/rapplication/") for c in pushes)
    assert len(client.prs) == 2
    assert not any("closes #" in p["body"].lower() or "fixes #" in p["body"].lower() for p in client.prs.values())


def test_native_federation_uses_same_reviewed_path_without_mirroring(client, monkeypatch, native_release):
    n = native_release
    monkeypatch.setattr(lib_rapp, "_default_fetcher", lambda: n.fetch)
    monkeypatch.setattr(lib_desktop, "anonymous_chunks", n.stream)
    event = event_for(client, _federation_payload(n.repo, n.ref, "my_thing", n.manifest))
    pr = ready_promotion(client, event)
    client.owner_merge(pr)
    prflow.complete(client, pr["number"])
    detail = json.loads((client.root / "api/v1/rapplication/my_thing.json").read_text())
    assert detail["desktop"] == n.desktop
    assert not (client.root / "apps").exists()
    assert not list(client.root.rglob("*.dmg"))


def test_exact_retry_reuses_branch_pr_and_dispatches_exact_head(client, make_rapp_dir):
    event = event_for(client, _bundle_payload(make_rapp_dir(), "alice"))
    assert prflow.prepare(client.root, event, "stage")[0]
    first = prflow.open_pr(client, event, "stage")
    second = prflow.open_pr(client, event, "stage")
    assert first["number"] == second["number"]
    assert len(client.prs) == 1
    assert len([c for c in client.git_calls if c[0] == "push"]) == 1
    dispatches = [(path, data) for path, method, data in client.api_calls if "/dispatches" in path]
    assert len(dispatches) == 4
    for path, data in dispatches:
        assert data["inputs"]["expected_head"] == first["head"]["sha"]
        assert data["ref"] == ("main" if "zoo-" in path else first["head"]["ref"])


@pytest.mark.parametrize("failure", [
    "push", ("pulls", "POST"), "actions/workflows/store-validation.yml/dispatches",
    "actions/workflows/zoo-v2-pr-validation.yml/dispatches",
])
def test_publication_and_dispatch_failures_leave_issue_open_and_retryable(client, make_rapp_dir, failure):
    event = event_for(client, _bundle_payload(make_rapp_dir(), "alice"))
    baseline = client.main_sha()
    assert prflow.prepare(client.root, event, "stage")[0]
    client.failure = failure
    with pytest.raises(prflow.CandidateError):
        prflow.open_pr(client, event, "stage")
    assert client.issues[32]["state"] == "open"
    assert not client.issues[32]["labels"]
    assert client.main_sha() == baseline
    client.failure = None
    prflow.open_pr(client, event, "stage")
    assert len(client.prs) == 1


@pytest.mark.parametrize("mutation", ["head", "base", "issue", "unapproved"])
def test_stale_subject_or_approval_cannot_validate(client, make_rapp_dir, monkeypatch, mutation):
    event = event_for(client, _bundle_payload(make_rapp_dir(), "alice"))
    pr = ready_promotion(client, event)
    if mutation == "head":
        pr["head"]["sha"] = "f" * 40
    elif mutation == "base":
        monkeypatch.setattr(client, "main_sha", lambda: "f" * 40)
    elif mutation == "issue":
        client.issues[32]["body"] += "\nChanged content"
    else:
        client.issues[32]["labels"] = []
    with pytest.raises(prflow.CandidateError):
        prflow.verify_candidate(client, pr)
    assert client.issues[32]["state"] == "open"


@pytest.mark.parametrize("mutation", [
    "unmerged", "different-owner", "head", "issue", "missing-check", "failed-check",
    "skipped-check", "wrong-check-head", "missing-zoo", "wrong-app", "wrong-app-id",
    "failed-zoo", "no-audit", "merge-base", "merge-tree",
    "missing-dispatch", "failed-dispatch", "pending-dispatch", "wrong-dispatch-base",
])
def test_completion_refuses_every_unconfirmed_promotion(client, make_rapp_dir, mutation):
    event = event_for(client, _bundle_payload(make_rapp_dir(), "alice"))
    pr = ready_promotion(client, event)
    head = pr["head"]["sha"]
    if mutation != "unmerged":
        pr = client.owner_merge(pr, different_base=mutation == "merge-base", different_tree=mutation == "merge-tree")
    if mutation == "different-owner":
        pr["merged_by"]["login"] = "someone-else"
    elif mutation == "head":
        pr["head"]["sha"] = "f" * 40
    elif mutation == "issue":
        client.issues[32]["body"] += "\nChanged after checks"
    elif mutation == "missing-check":
        client.checks[head].pop()
    elif mutation == "failed-check":
        client.checks[head][0]["conclusion"] = "failure"
    elif mutation == "skipped-check":
        client.checks[head][0]["conclusion"] = "skipped"
    elif mutation == "wrong-check-head":
        client.checks[head][0]["head_sha"] = "f" * 40
    elif mutation == "missing-zoo":
        client.statuses[head] = []
    elif mutation == "wrong-app":
        client.statuses[head][0]["creator"]["login"] = prflow.BOT
    elif mutation == "wrong-app-id":
        client.statuses[head][0]["creator"]["id"] += 1
    elif mutation == "failed-zoo":
        client.statuses[head][0]["state"] = "failure"
    elif mutation == "no-audit":
        (client.root / ".github/zoo-v2-protection-audit.json").unlink()
    elif mutation == "missing-dispatch":
        client.validator_runs = []
    elif mutation == "failed-dispatch":
        client.validator_runs[-1]["conclusion"] = "failure"
    elif mutation == "pending-dispatch":
        client.validator_runs[-1]["status"] = "in_progress"
    elif mutation == "wrong-dispatch-base":
        client.validator_runs[-1]["head_sha"] = "f" * 40
    before = len(client.api_calls)
    with pytest.raises(prflow.CandidateError):
        prflow.complete(client, pr["number"])
    assert client.issues[32]["state"] == "open"
    assert not any(method in ("POST", "PATCH") for _, method, _ in client.api_calls[before:])


def test_later_failed_check_cannot_be_hidden_by_earlier_success(client, make_rapp_dir):
    event = event_for(client, _bundle_payload(make_rapp_dir(), "alice"))
    pr = ready_promotion(client, event)
    head = pr["head"]["sha"]
    client.checks[head].append(dict(client.checks[head][0], id=999, conclusion="failure"))
    client.owner_merge(pr)
    with pytest.raises(prflow.CandidateError, match="E_REQUIRED_CHECK"):
        prflow.complete(client, pr["number"])


def test_issue_edit_retires_old_candidate_and_staged_payload_cannot_be_reapproved(client, make_rapp_dir):
    event = event_for(client, _bundle_payload(make_rapp_dir(), "alice"))
    approved = reviewed_stage(client, event)
    assert prflow.prepare(client.root, approved, "promotion")[0]
    pr = prflow.open_pr(client, approved, "promotion")
    client.issues[32]["body"] += "\nNew payload text"
    prflow.retire_candidates(client, client.issues[32])
    assert client.prs[pr["number"]]["state"] == "closed"
    changed = {"issue": copy.deepcopy(client.issues[32])}
    client.git("reset", "--hard", "origin/main")
    with pytest.raises(prflow.CandidateError, match="E_STALE_ISSUE"):
        prflow.prepare(client.root, changed, "promotion")
    assert client.issues[32]["state"] == "open"


def test_source_pin_change_requires_new_native_staging(client, monkeypatch, native_release):
    n = native_release
    monkeypatch.setattr(lib_rapp, "_default_fetcher", lambda: n.fetch)
    monkeypatch.setattr(lib_desktop, "anonymous_chunks", n.stream)
    event = event_for(client, _federation_payload(n.repo, n.ref, "my_thing", n.manifest))
    approved = reviewed_stage(client, event)
    before = (client.root / "index.json").read_bytes()
    n.routes[f"https://api.github.com/repos/{n.repo}/commits/main"] = json.dumps({"sha": "f" * 40}).encode()
    ok, report = prflow.prepare(client.root, approved, "promotion")
    assert not ok and "E_DESKTOP_STALE_SOURCE" in report
    assert (client.root / "index.json").read_bytes() == before
    assert len(client.prs) == 1


def test_same_id_submissions_are_isolated_and_candidate_code_is_inert(client, make_rapp_dir):
    app = make_rapp_dir()
    with (app / "singleton/my_thing_agent.py").open("a") as stream:
        stream.write('\nraise RuntimeError("SUBMISSION_CODE_MUST_NOT_EXECUTE")\n')
    body = _bundle_payload(app, "alice")
    first = event_for(client, body, number=32)
    second = event_for(client, body, number=33)
    assert prflow.prepare(client.root, first, "stage")[0]
    old = (client.root / "staging/issue-32/_pending.json").read_bytes()
    assert prflow.prepare(client.root, second, "stage")[0]
    assert (client.root / "staging/issue-32/_pending.json").read_bytes() == old
    assert (client.root / "staging/issue-33/my_thing/manifest.json").is_file()


def test_catalog_base_advance_before_pr_creation_requires_revalidation(client, make_rapp_dir, monkeypatch):
    event = event_for(client, _bundle_payload(make_rapp_dir(), "alice"))
    assert prflow.prepare(client.root, event, "stage")[0]
    monkeypatch.setattr(client, "main_sha", lambda: "f" * 40)
    with pytest.raises(prflow.CandidateError, match="E_STALE_BASE"):
        prflow.open_pr(client, event, "stage")
    assert not client.prs
    assert not any(c[0] == "push" for c in client.git_calls)


def test_unreviewed_nonentrypoint_bundle_bytes_refuse_before_promotion(client, make_rapp_dir):
    event = event_for(client, _bundle_payload(make_rapp_dir(), "alice"))
    approved = reviewed_stage(client, event)
    before = (client.root / "index.json").read_bytes()
    (client.root / "staging/issue-32/my_thing/README.md").write_text("Unreviewed change")
    ok, report = prflow.prepare(client.root, approved, "promotion")
    assert not ok and "E_STALE_PENDING" in report
    assert (client.root / "index.json").read_bytes() == before
    assert not (client.root / "apps").exists()


@pytest.mark.parametrize("schema", ["rapp-application/2.0", "rapp-application/3.0"])
def test_unqualified_contract_refusal_is_the_validators_own_report(client, make_rapp_dir, schema):
    event = event_for(client, _bundle_payload(make_rapp_dir(schema=schema), "alice"))
    ok, report = prflow.prepare(client.root, event, "stage")
    assert not ok
    assert (ok, report) == prflow.receiver.process(
        event, client.root / prflow.stage_path(32), client.root / "index.json")
    if schema == COMPLETE_SCHEMA:
        assert "E_CONTRACT" in report and "E_MANIFEST_SCHEMA" not in report
    else:
        assert "E_MANIFEST_SCHEMA" in report
    assert not (client.root / "staging/issue-32/_pending.json").exists()
    assert not (client.root / ".ci-work/candidate.json").exists()
    assert not client.prs


@needs_complete_contract
def test_complete_application_source_zip_refuses_before_staging(client, complete_application):
    directory, _ = complete_application
    event = event_for(client, _bundle_payload(directory, "alice"))
    ok, report = prflow.prepare(client.root, event, "stage")
    assert not ok and "E_APPLICATION_FEDERATION_ONLY" in report
    assert not (client.root / "staging").exists()
    assert not (client.root / ".ci-work/candidate.json").exists()
    assert not client.prs


@needs_complete_contract
def test_complete_application_federation_promotes_only_the_reviewed_commit(
        client, complete_application, fake_fetcher, monkeypatch):
    directory, manifest = complete_application
    reviewed, moved = "b" * 40, "c" * 40
    raw = "https://raw.githubusercontent.com/alice/example"
    commits = "https://api.github.com/repos/alice/example/commits/"
    blob = (directory / "manifest.json").read_bytes()
    routes = {raw + "/main/my_thing/manifest.json": blob, raw + f"/{reviewed}/my_thing/manifest.json": blob,
              commits + "main": json.dumps({"sha": reviewed}), commits + reviewed: json.dumps({"sha": reviewed})}
    routes.update({raw + f"/{reviewed}/my_thing/{name}": (directory / name).read_bytes()
                   for name in manifest["files"]})
    monkeypatch.setattr(lib_rapp, "_default_fetcher", lambda: fake_fetcher(routes))
    event = event_for(client, _federation_payload("alice/example", "main", "my_thing", manifest))
    approved = reviewed_stage(client, event)
    staged = prflow.promoter.find_pending(client.root / prflow.stage_path(32), 32)["entry"]
    assert staged["source"]["ref"] == staged["source"]["commit_sha"] == reviewed
    # The publisher's branch moves after review; promotion must keep the reviewed pin.
    routes[raw + "/main/my_thing/manifest.json"] = b"changed after review"
    routes[commits + "main"] = json.dumps({"sha": moved})
    ok, report = prflow.prepare(client.root, approved, "promotion")
    assert ok, report
    pr = prflow.open_pr(client, approved, "promotion")
    prflow.verify_candidate(client, pr)
    client.passing_checks(pr)
    assert json.loads(git(client.remote, "show", "main:index.json"))["rapplications"] == []
    client.owner_merge(pr)
    prflow.complete(client, pr["number"])
    assert client.issues[32]["state"] == "closed"
    assert "promoted" in {x["name"] for x in client.issues[32]["labels"]}
    assert json.loads((client.root / "index.json").read_text())["rapplications"] == [staged]
    assert staged["application_url"] == raw + f"/{reviewed}/my_thing/manifest.json"
    assert "singleton_url" not in staged
    assert not (client.root / "apps").exists() and not (client.root / "api").exists()
    assert len(client.prs) == 2
