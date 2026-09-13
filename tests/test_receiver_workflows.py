"""Execute issue workflow shell/report blocks with inert Git and GitHub doubles."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
CASES = [
    ("process-rapplication.yml", "Validate submission", "Commit staging changes", "VALIDATION_OUTCOME"),
    ("approve-rapplication.yml", "Promote to live catalog", "Commit promotion", "PROMOTION_OUTCOME"),
]


def _step(workflow, name):
    match = re.search(r"^      - name: " + re.escape(name) + r"\n.*?(?=^      - |\Z)",
                      workflow, re.MULTILINE | re.DOTALL)
    assert match, name
    return match[0]


def _script(step, field):
    match = re.search(r"^( +)" + re.escape(field) + r": \|\n", step, re.MULTILINE)
    assert match, field
    prefix = " " * (len(match[1]) + 2)
    lines = []
    for line in step[match.end():].splitlines():
        if line and not line.startswith(prefix):
            break
        lines.append(line[len(prefix):] if line else "")
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("filename,validation,persistence,outcome", CASES)
def test_issue_jobs_use_fresh_main_and_do_not_mask_failures(filename, validation, persistence, outcome):
    workflow = (WORKFLOWS / filename).read_text()
    checkout = workflow.split("- uses: actions/checkout@v4", 1)[1].split("- uses:", 1)[0]
    assert "ref: main" in checkout
    assert "fetch-depth: 0" in checkout
    assert "group: rapp-store-state" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "pull_request" not in workflow
    assert "continue-on-error" not in workflow
    assert "set +e" not in workflow
    assert "git pull" not in workflow
    assert "git rebase" not in workflow
    assert workflow.index("- name: " + persistence) < workflow.index("- name: Report outcome")
    report = _step(workflow, "Report outcome")
    assert "if: always()" in report
    assert f"{outcome}:" in report
    assert "PUBLICATION_OUTCOME: ${{ steps.persist.outcome }}" in report
    assert "set -euo pipefail" in _script(_step(workflow, validation), "run")


def _fake_git(tmp_path):
    tools = tmp_path / "bin"
    tools.mkdir()
    executable = tools / "git"
    executable.write_text(f"""#!{sys.executable}
import json
import os
from pathlib import Path
import sys
log = Path(os.environ["TEST_GIT_LOG"])
with log.open("a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
command = sys.argv[1]
if command == "diff":
    raise SystemExit(int(os.environ.get("DIFF_EXIT", "1")))
if command == "commit":
    raise SystemExit(int(os.environ.get("COMMIT_EXIT", "0")))
if command == "push":
    count = sum(json.loads(line)[0] == "push" for line in log.read_text().splitlines())
    raise SystemExit(0 if count >= int(os.environ["PUSH_SUCCEEDS_AT"]) else 1)
""")
    executable.chmod(0o755)
    sleep = tools / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    return tools


@pytest.mark.parametrize("filename,validation,persistence,outcome", CASES)
@pytest.mark.parametrize("succeeds_at,commit_exit,diff_exit,expected_code,expected_pushes", [
    (1, 0, 1, 0, 1),
    (3, 0, 1, 0, 3),
    (99, 0, 1, 1, 3),
    (1, 7, 1, 7, 0),
    (1, 0, 0, 0, 0),
])
def test_state_publication_returns_real_commit_and_push_failures(
        tmp_path, filename, validation, persistence, outcome,
        succeeds_at, commit_exit, diff_exit, expected_code, expected_pushes):
    tools = _fake_git(tmp_path)
    log = tmp_path / "git-calls.jsonl"
    environment = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                       TEST_GIT_LOG=str(log), ISSUE_NUMBER="56",
                       PUSH_SUCCEEDS_AT=str(succeeds_at), COMMIT_EXIT=str(commit_exit),
                       DIFF_EXIT=str(diff_exit))
    workflow = (WORKFLOWS / filename).read_text()
    result = subprocess.run(
        ["bash", "-c", _script(_step(workflow, persistence), "run")],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == expected_code, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert sum(call[0] == "push" for call in calls) == expected_pushes
    assert not any(call[0] in ("pull", "rebase", "reset") for call in calls)
    if expected_code:
        assert "already present" not in result.stdout


@pytest.mark.parametrize("filename,validation,persistence,outcome", CASES)
def test_validation_and_promotion_script_failures_fail_the_step(
        tmp_path, filename, validation, persistence, outcome):
    tools = tmp_path / "bin"
    tools.mkdir()
    fake_python = tools / "python3"
    fake_python.write_text("#!/bin/sh\nprintf 'E_FIXTURE_FAILURE\\n'\nexit 7\n")
    fake_python.chmod(0o755)
    environment = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                       GITHUB_EVENT_PATH=str(tmp_path / "event.json"))
    workflow = (WORKFLOWS / filename).read_text()
    result = subprocess.run(
        ["bash", "-c", _script(_step(workflow, validation), "run")],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 7
    reports = list((tmp_path / ".ci-work").glob("*-report.md"))
    assert len(reports) == 1
    assert reports[0].read_text() == "E_FIXTURE_FAILURE\n"


@pytest.mark.parametrize("filename,validation,persistence,outcome", CASES)
@pytest.mark.parametrize("operation,publication,published", [
    ("failure", "skipped", False),
    ("success", "failure", False),
    ("success", "skipped", False),
    ("success", "success", True),
])
def test_reports_labels_and_closure_require_confirmed_publication(
        tmp_path, filename, validation, persistence, outcome, operation, publication, published):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to exercise the workflow's actual github-script block")
    workflow = (WORKFLOWS / filename).read_text()
    script = _script(_step(workflow, "Report outcome"), "script")
    report_dir = tmp_path / ".ci-work"
    report_dir.mkdir()
    report = "## ✅ SUCCESS_SENTINEL\n" if operation == "success" else "## ❌ E_FIXTURE_FAILURE\n"
    for name in ("process-report.md", "promotion-report.md"):
        (report_dir / name).write_text(report)
    harness = """
const calls = [];
const record = action => async data => { calls.push({action, ...data}); };
const github = {rest:{issues:{
  createComment: record('comment'), addLabels: record('labels'), update: record('update')
}}};
const context = {repo:{owner:'fixture',repo:'store'},issue:{number:56},
                 serverUrl:'https://github.com',runId:123};
(async () => {
""" + script + """
  console.log(JSON.stringify(calls));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [node, "-e", harness], cwd=tmp_path,
        env=dict(os.environ, **{outcome: operation, "PUBLICATION_OUTCOME": publication}),
        capture_output=True, text=True, check=True, timeout=15,
    )
    calls = json.loads(result.stdout)
    body = next(call["body"] for call in calls if call["action"] == "comment")
    labels = next(call["labels"] for call in calls if call["action"] == "labels")
    closed = any(call.get("state") == "closed" for call in calls)
    assert ("SUCCESS_SENTINEL" in body) == published
    assert closed == (published and filename.startswith("approve"))
    if published:
        assert ("promoted" if filename.startswith("approve") else "pending-review") in labels
    else:
        assert "failed" in labels
        assert not {"promoted", "pending-review"} & set(labels)
        assert "E_FIXTURE_FAILURE" in body if operation == "failure" else "not published" in body
