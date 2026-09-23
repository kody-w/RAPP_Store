#!/usr/bin/env python3
"""Trusted-main orchestration for public issue staging and promotion PRs.

PR metadata binds a Git candidate, not an approval credential. No command merges
a PR, pushes main, executes submitted code, or grants RAPP/1 acceptance.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import configure_zoo_v2_protection as protection
import process_rapplication as receiver
import promote_rapplication as promoter

MARKER = re.compile(r"<!-- rapplication-candidate (\{[^\n]*\}) -->")
SHA = re.compile(r"[0-9a-f]{40}")
CHECKS = ("Complete store suite", "Pages checks", "Submission binding")
BOT = "github-actions[bot]"


class CandidateError(Exception):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def issue_digest(issue):
    return digest({key: issue.get(key) for key in ("number", "title", "body")}
                  | {"author": issue.get("user", {}).get("login")})


def issue_number(issue):
    number = issue.get("number")
    if type(number) is not int or number < 1 or not issue.get("title", "").startswith("[RAPP]"):
        raise CandidateError("E_ISSUE_FRONT_DOOR: expected a numbered [RAPP] issue")
    return number


def stage_path(number):
    return f"staging/issue-{number}"


def write_context(root, context):
    work = root / ".ci-work"
    work.mkdir(exist_ok=True)
    (work / "candidate.json").write_text(json.dumps(context, sort_keys=True) + "\n")


def prepare(root, event, phase):
    """Run the existing receiver/promoter without any GitHub credentials."""
    issue = event.get("issue", {})
    number = issue_number(issue)
    staging = root / stage_path(number)
    catalog = root / "index.json"
    if phase == "stage":
        ok, report = receiver.process(event, staging, catalog)
        if not ok:
            # The validator owns each schema's refusal codes and submission-lane guidance.
            return ok, report
        item = promoter.find_pending(staging, number)
        if (item["mode"] == "federation"
                and not SHA.fullmatch(item["entry"].get("source", {}).get("commit_sha", ""))):
            raise CandidateError("E_SOURCE_PIN: resolve a full federation commit before opening a staging PR")
        item["submission_sha256"] = receiver.submission_fingerprint(receiver.extract_payload(issue["body"]))
        item["issue_sha256"] = issue_digest(issue)
        if item["mode"] == "bundle":
            item["bundle_tree_sha256"] = promoter.bundle_tree_fingerprint(staging.parent / item["staged_dir"])
        # Stable across retries, including later approval-label events.
        item["prepared_at"] = issue.get("updated_at") or issue.get("created_at", "1970-01-01T00:00:00Z")
        receiver.write_pending(staging, item)
        report = report.replace(f"`staging/{item['id']}/`", f"`{stage_path(number)}/{item['id']}/`")
    else:
        item = promoter.find_pending(staging, number)
        if item.get("issue_sha256") != issue_digest(issue):
            raise CandidateError("E_STALE_ISSUE: merge a new staging PR for the current issue before approval")
        ok, report = promoter.promote(event, staging, catalog)
        if not ok:
            return ok, report
    paths = [stage_path(number)]
    if phase == "promotion":
        paths.append("index.json")
        if item["mode"] == "bundle":
            paths.append(f"apps/{item['entry']['publisher']}/{item['id']}")
        if "desktop" in item["entry"]:
            paths.extend(["api/v1/index.json", f"api/v1/rapplication/{item['id']}.json"])
    write_context(root, {
        "phase": phase, "issue": number, "issue_sha256": issue_digest(issue),
        "paths": paths, "prepared_at": item["prepared_at"],
    })
    return True, report


class Client:
    def __init__(self, root, repository):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise CandidateError("E_REPOSITORY: expected owner/repository")
        self.root, self.repository = root, repository

    def git(self, *args, env=None, check=True):
        result = subprocess.run(["git", *args], cwd=self.root, text=True,
                                capture_output=True, env=env, timeout=120)
        if check and result.returncode:
            raise CandidateError(f"E_GIT: {args[0]} failed; no publication is claimed")
        return (result.stdout if "-z" in args else result.stdout.strip()) if check else result

    def api(self, path, method="GET", payload=None):
        command = ["gh", "api", "--method", method, f"repos/{self.repository}/{path}"]
        if payload is not None:
            command += ["--input", "-"]
        result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise CandidateError(f"E_GITHUB_API: {method} {path} failed; retry without assuming success")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def pages(self, path, key=None):
        result = []
        for page in range(1, 101):
            data = self.api(path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
            rows = data[key] if key else data
            result.extend(rows)
            if len(rows) < 100:
                return result
        raise CandidateError("E_PAGINATION: refusing an incomplete GitHub result")

    def main_sha(self):
        return self.api("git/ref/heads/main")["object"]["sha"]

    def current_issue(self, event, phase):
        original = event["issue"]
        current = self.api(f"issues/{issue_number(original)}")
        if current.get("state") != "open" or issue_digest(current) != issue_digest(original):
            raise CandidateError("E_STALE_ISSUE: submission was edited or closed; reprocess it")
        if phase == "promotion" and "approved" not in {x["name"] for x in current.get("labels", [])}:
            raise CandidateError("E_APPROVAL_REQUIRED: current issue is not approved")
        return current

    def push_candidate(self, commit, branch):
        if not branch.startswith("rapplication/") or not SHA.fullmatch(commit):
            raise CandidateError("E_REF: refusing a non-candidate push")
        env = dict(os.environ)
        token = env.get("GH_TOKEN", "")
        if not token:
            raise CandidateError("E_TOKEN: candidate publication requires a workflow token")
        # Credentials live only in this subprocess, never in checkout config.
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + base64.b64encode(
                       ("x-access-token:" + token).encode()).decode())
        self.git("push", "origin", f"{commit}:refs/heads/{branch}", env=env)


def branch_for(meta):
    binding = {key: meta[key] for key in ("phase", "issue", "issue_sha256", "base", "tree")}
    return f"rapplication/{meta['phase']}/issue-{meta['issue']}-{digest(binding)}"


def parse_candidate(pr, repository):
    match = MARKER.findall(pr.get("body") or "")
    if len(match) != 1:
        raise CandidateError("E_CANDIDATE: missing or ambiguous candidate binding")
    try:
        meta = json.loads(match[0])
        valid = (meta["phase"] in ("stage", "promotion")
                 and type(meta["issue"]) is int and meta["issue"] > 0
                 and re.fullmatch(r"[0-9a-f]{64}", meta["issue_sha256"])
                 and all(SHA.fullmatch(meta[key]) for key in ("head", "base", "tree"))
                 and pr["head"]["ref"] == branch_for(meta)
                 and pr["head"]["sha"] == meta["head"]
                 and pr["head"]["repo"]["full_name"] == repository
                 and pr["base"]["ref"] == "main"
                 and pr["user"]["login"] == BOT)
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise CandidateError("E_CANDIDATE: stale head, wrong origin or invalid candidate binding")
    return meta


def retire_candidates(client, issue, keep=None):
    for pr in client.pages("pulls?state=open&base=main"):
        if not pr["head"]["ref"].startswith("rapplication/"):
            continue
        try:
            meta = parse_candidate(pr, client.repository)
        except CandidateError:
            continue
        if meta["issue"] != issue["number"] or pr["head"]["ref"] == keep:
            continue
        if keep or meta["issue_sha256"] != issue_digest(issue):
            client.api(f"pulls/{pr['number']}", "PATCH", {"state": "closed"})
            client.api(f"issues/{pr['number']}/comments", "POST", {
                "body": "Superseded candidate: the issue, source, or current-main base changed. "
                        "Revalidation and a new owner-reviewed candidate are required.",
            })


def open_pr(client, event, phase):
    client.current_issue(event, phase)
    context = json.loads((client.root / ".ci-work/candidate.json").read_text())
    if (context["phase"] != phase or context["issue_sha256"] != issue_digest(event["issue"])
            or context["issue"] != issue_number(event["issue"])):
        raise CandidateError("E_CANDIDATE: preparation does not match this event")
    client.git("fetch", "--no-tags", "origin", "main")
    base = client.git("rev-parse", "HEAD")
    if base != client.git("rev-parse", "origin/main") or base != client.main_sha():
        raise CandidateError("E_STALE_BASE: main advanced; rerun validation from current main")
    client.git("add", "-fA", "--", *context["paths"])
    changed = client.git("diff", "--cached", "--name-only", "-z").rstrip("\0").split("\0")
    if not changed or changed == [""]:
        raise CandidateError("E_NO_CHANGES: no new candidate; inspect the already merged staging or catalog")
    if any(not any(p == path or p.startswith(path + "/") for path in context["paths"]) for p in changed):
        raise CandidateError("E_CANDIDATE_PATH: refusing unrelated staged changes")
    meta = {key: context[key] for key in ("phase", "issue", "issue_sha256")}
    meta.update(base=base, tree=client.git("write-tree"))
    branch = branch_for(meta)
    env = dict(os.environ, GIT_AUTHOR_NAME="rapp-store-bot",
               GIT_AUTHOR_EMAIL="rapp-store-bot@users.noreply.github.com",
               GIT_COMMITTER_NAME="rapp-store-bot",
               GIT_COMMITTER_EMAIL="rapp-store-bot@users.noreply.github.com",
               GIT_AUTHOR_DATE=context["prepared_at"], GIT_COMMITTER_DATE=context["prepared_at"])
    meta["head"] = client.git("commit-tree", meta["tree"], "-p", base, "-m",
                             f"{phase}: rapplication issue #{meta['issue']}", env=env)
    remote = client.git("ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    if remote:
        if remote.split()[0] != meta["head"]:
            raise CandidateError("E_REF_CONFLICT: candidate branch differs; do not overwrite it")
    else:
        client.push_candidate(meta["head"], branch)

    owner = client.repository.split("/")[0]
    prs = client.pages(f"pulls?state=all&base=main&head={quote(owner + ':' + branch, safe='')}")
    if prs:
        if len(prs) != 1 or prs[0]["state"] != "open":
            raise CandidateError("E_PR_STATE: candidate PR is closed or ambiguous; review before retrying")
        pr = prs[0]
        if parse_candidate(pr, client.repository) != meta:
            raise CandidateError("E_PR_BINDING: existing PR no longer matches the prepared candidate")
    else:
        instruction = ("Merge this staging-only PR after its checks, then add `approved` to the issue."
                       if phase == "stage" else
                       "Only the repository owner may merge this exact checked head. Approval is not publication.")
        body = (f"Public {phase} candidate for submission #{meta['issue']}.\n\n"
                f"{instruction}\n\nBase: `{base}`\nHead: `{meta['head']}`\n\n"
                "Required: Complete store suite, Pages checks, Submission binding, and the "
                "dedicated-App `Zoo v2 current-main` status. Missing or failed checks block merge. "
                "No automatic merge or issue closure is requested.\n\n"
                "<!-- rapplication-candidate " + json.dumps(meta, sort_keys=True) + " -->")
        pr = client.api("pulls", "POST", {
            "title": f"{phase}: rapplication submission #{meta['issue']}",
            "head": branch, "base": "main", "body": body,
        })
    retire_candidates(client, event["issue"], keep=branch)
    client.current_issue(event, phase)
    if client.main_sha() != base:
        raise CandidateError("E_STALE_BASE: main advanced before dispatch; do not merge this candidate")
    # GITHUB_TOKEN-created PRs do not trigger pull_request/pull_request_target.
    client.api("actions/workflows/store-validation.yml/dispatches", "POST", {
        "ref": branch, "inputs": {"pr_number": str(pr["number"]),
                                 "expected_head": meta["head"], "expected_base": base},
    })
    client.api("actions/workflows/zoo-v2-pr-validation.yml/dispatches", "POST", {
        "ref": "main", "inputs": {"pr_number": str(pr["number"]), "expected_head": meta["head"]},
    })
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a") as stream:
            stream.write(f"pr_url={pr['html_url']}\npr_number={pr['number']}\nhead={meta['head']}\n")
    return pr


def verify_candidate(client, pr, *, merged=False):
    meta = parse_candidate(pr, client.repository)
    issue = client.api(f"issues/{meta['issue']}")
    if issue_digest(issue) != meta["issue_sha256"]:
        raise CandidateError("E_STALE_ISSUE: issue changed since candidate preparation")
    if meta["phase"] == "promotion" and "approved" not in {x["name"] for x in issue.get("labels", [])}:
        raise CandidateError("E_APPROVAL_REQUIRED: approval was removed")
    if not merged and (pr.get("state") != "open" or issue.get("state") != "open"
                       or client.main_sha() != meta["base"]):
        raise CandidateError("E_STALE_BASE: candidate must be open and based on current main")
    client.git("fetch", "--no-tags", "origin", meta["base"], meta["head"])
    if (client.git("rev-parse", meta["head"] + "^{tree}") != meta["tree"]
            or client.git("rev-list", "--parents", "-n", "1", meta["head"]).split()
            != [meta["head"], meta["base"]]):
        raise CandidateError("E_CANDIDATE: head is not the single prepared commit")
    payload = receiver.extract_payload(issue["body"])
    rapp_id, publisher = payload.get("id", ""), payload.get("publisher", "")
    if (not re.fullmatch(r"[a-z][a-z0-9_]*", rapp_id)
            or not re.fullmatch(r"@[A-Za-z0-9][A-Za-z0-9-]*", publisher)):
        raise CandidateError("E_CANDIDATE_PATH: invalid issue ID or publisher")
    allowed = [stage_path(meta["issue"])]
    if meta["phase"] == "promotion":
        allowed += ["index.json", f"apps/{publisher}/{rapp_id}",
                    "api/v1/index.json", f"api/v1/rapplication/{rapp_id}.json"]
    changed = client.git("diff", "--name-only", "-z", meta["base"], meta["head"]).rstrip("\0").split("\0")
    if any(not any(p == path or p.startswith(path + "/") for path in allowed) for p in changed):
        raise CandidateError("E_CANDIDATE_PATH: candidate changes protected or unrelated files")
    return meta, issue


def require_checks(client, meta, number):
    head = meta["head"]
    runs = client.pages(f"commits/{head}/check-runs", "check_runs")
    for name in CHECKS:
        matching = [r for r in runs if r["name"] == name and r.get("app", {}).get("slug") == "github-actions"]
        latest = max(matching, key=lambda r: r["id"], default={})
        if (latest.get("head_sha") != head or latest.get("status") != "completed"
                or latest.get("conclusion") != "success"):
            raise CandidateError(f"E_REQUIRED_CHECK: {name} is missing, pending or failed at the exact head")
    # An unavailable App cannot revoke its previous status. Do not reuse an old
    # green status if a later explicit validation attempt failed to mint a token.
    runs = client.pages("actions/workflows/zoo-v2-pr-validation.yml/runs"
                        f"?event=workflow_dispatch&branch=main&head_sha={meta['base']}", "workflow_runs")
    title = f"Zoo v2 PR #{number} @ {head}"
    matching = [r for r in runs if r.get("display_title") == title
                and r.get("event") == "workflow_dispatch" and r.get("head_sha") == meta["base"]]
    latest = max(matching, key=lambda r: r["id"], default={})
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise CandidateError("E_VALIDATOR_UNAVAILABLE: latest exact-subject validator dispatch is missing, pending or failed")
    try:
        audit = json.loads((client.root / protection.AUDIT_PATH).read_text())
        app = protection.audit_app_identity(audit)
        protection.verify_audit(audit, client.repository, app["id"], app["slug"], app["login"], app["user_id"])
    except (OSError, ValueError, protection.ProtectionError) as exc:
        raise CandidateError("E_VALIDATOR_UNAVAILABLE: committed validator App audit is unavailable") from exc
    statuses = client.pages(f"commits/{head}/statuses")
    matching = [s for s in statuses if s["context"] == "Zoo v2 current-main"]
    latest = max(matching, key=lambda s: s["id"], default={})
    actor = latest.get("creator", {})
    if (latest.get("state") != "success" or actor.get("login") != app["login"]
            or actor.get("id") != app["user_id"]):
        raise CandidateError("E_REQUIRED_CHECK: Zoo v2 current-main lacks exact validator App success")


def complete(client, number):
    pr = client.api(f"pulls/{number}")
    if not pr.get("merged") or pr.get("merged_by", {}).get("login") != client.repository.split("/")[0]:
        raise CandidateError("E_OWNER_MERGE: only a confirmed repository-owner merge can publish")
    meta, issue = verify_candidate(client, pr, merged=True)
    require_checks(client, meta, number)
    merge = pr.get("merge_commit_sha", "")
    if not SHA.fullmatch(merge):
        raise CandidateError("E_MERGE: missing merge commit")
    client.git("fetch", "--no-tags", "origin", "main", merge)
    parents = client.git("rev-list", "--parents", "-n", "1", merge).split()
    if (len(parents) not in (2, 3) or parents[1] != meta["base"]
            or (len(parents) == 3 and parents[2] != meta["head"])
            or client.git("rev-parse", merge + "^{tree}") != meta["tree"]
            or client.git("merge-base", "--is-ancestor", merge, "origin/main", check=False).returncode):
        raise CandidateError("E_STALE_MERGE: merge is not the exact checked tree on its reviewed base")
    if meta["phase"] == "stage":
        body = (f"Reviewed staging merged in #{number}. The catalog is unchanged. "
                "A maintainer can now add `approved` to prepare the separate promotion PR.")
        client.api(f"issues/{meta['issue']}/comments", "POST", {"body": body})
    elif issue.get("state") != "closed":
        client.api(f"issues/{meta['issue']}/comments", "POST", {
            "body": f"Promotion published by the repository owner's merge of checked PR #{number} "
                    f"at `{meta['head']}`. Catalog publication, not RAPP/1 authenticated acceptance.",
        })
        client.api(f"issues/{meta['issue']}/labels", "POST", {"labels": ["promoted"]})
        client.api(f"issues/{meta['issue']}", "PATCH", {"state": "closed"})
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stage", "promotion", "open-stage", "open-promotion", "invalidate", "verify", "complete"))
    parser.add_argument("--event-path")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--expected-head")
    parser.add_argument("--expected-base")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)
    try:
        if args.command in ("stage", "promotion"):
            ok, report = prepare(args.root, json.loads(Path(args.event_path).read_text()), args.command)
            print(report)
            return 0 if ok else 1
        client = Client(args.root, args.repository)
        if args.command == "invalidate":
            event = json.loads(Path(args.event_path).read_text())
            issue = client.current_issue(event, "stage")
            retire_candidates(client, issue)
            for label in ("approved", "failed", "pending-review"):
                if label in {x["name"] for x in issue.get("labels", [])}:
                    client.api(f"issues/{issue['number']}/labels/{label}", "DELETE")
        elif args.command.startswith("open-"):
            pr = open_pr(client, json.loads(Path(args.event_path).read_text()), args.command.removeprefix("open-"))
            print(f"Candidate PR opened: {pr['html_url']}. Not published; checks and owner merge are required.")
        elif args.command == "complete":
            complete(client, args.pr_number)
        else:
            pr = client.api(f"pulls/{args.pr_number}")
            if not pr["head"]["ref"].startswith("rapplication/"):
                print("Not an issue-generated candidate; no submission publication is authorized.")
                return 0
            meta, _ = verify_candidate(client, pr)
            if args.expected_head and args.expected_head != meta["head"]:
                raise CandidateError("E_STALE_HEAD: dispatch no longer matches the candidate")
            if args.expected_base and args.expected_base != meta["base"]:
                raise CandidateError("E_STALE_BASE: dispatch no longer matches the candidate")
            print("Exact issue/head/base binding verified; approval is not publication.")
        return 0
    except (CandidateError, promoter.PromoteError, receiver.ProcessError, ValueError, OSError) as exc:
        print(f"## Candidate not published\n\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
