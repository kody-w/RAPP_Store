"""Execute actual workflow shell/report blocks with inert GitHub doubles."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github/workflows"
CASES = [
    ("process-rapplication.yml", "Validate submission", "Open checked staging PR", "VALIDATION_OUTCOME"),
    ("approve-rapplication.yml", "Prepare promotion candidate", "Open checked promotion PR", "PROMOTION_OUTCOME"),
]
ZOO = ("zoo-v2-pr-validation.yml", "zoo-v2-catalog-pr.yml",
       "zoo-v2-main-advance.yml", "zoo-v2-merge-completion.yml")
SETTINGS = ("APP_ID", "PRIVATE_KEY", "APP_LOGIN", "APP_SLUG", "APP_USER_ID")


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
def test_issue_jobs_use_trusted_main_and_only_candidate_publication(filename, validation, persistence, outcome):
    workflow = (WORKFLOWS / filename).read_text()
    assert "ref: main" in workflow and "persist-credentials: false" in workflow
    assert "group: rapp-store-state" in workflow and "cancel-in-progress: false" in workflow
    assert "permissions: {}" in workflow and "actions: write" in workflow
    assert "continue-on-error" not in workflow and "set +e" not in workflow
    assert "HEAD:main" not in workflow and "git push" not in workflow
    assert "git add -A" not in workflow and "git rebase" not in workflow
    assert workflow.index("- name: " + persistence) < workflow.index("- name: Report outcome")
    report = _step(workflow, "Report outcome")
    assert "if: always()" in report and f"{outcome}:" in report
    assert "PR_OUTCOME: ${{ steps.persist.outcome }}" in report
    assert "state: 'closed'" not in report and "['promoted']" not in report
    assert "set -euo pipefail" in _script(_step(workflow, validation), "run")


def test_all_actions_are_immutable_and_checkouts_do_not_retain_tokens():
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text()
        for action in re.findall(r"^\s+-?\s*uses:\s*(\S+)", text, re.MULTILINE):
            assert re.fullmatch(r"[a-zA-Z0-9_/-]+@[0-9a-f]{40}", action), (path, action)
        assert text.count("actions/checkout@") == text.count("persist-credentials: false"), path
        assert "permissions: {}" in text
    validation = (WORKFLOWS / "store-validation.yml").read_text()
    assert "secrets." not in validation and ": write" not in validation
    assert "workflow_dispatch:" in validation
    assert 'test "$ACTUAL_HEAD" = "$EXPECTED_HEAD"' in validation
    assert "name: Complete store suite" in validation
    assert "python3 -m pytest tests -q" in validation
    assert "name: Pages checks" in validation and "name: Submission binding" in validation


@pytest.mark.parametrize("filename,validation,persistence,outcome", CASES)
def test_validation_failures_are_not_masked(tmp_path, filename, validation, persistence, outcome):
    tools = tmp_path / "bin"
    tools.mkdir()
    fake_python = tools / "python3"
    fake_python.write_text("#!/bin/sh\nprintf 'E_FIXTURE_FAILURE\\n'\nexit 7\n")
    fake_python.chmod(0o755)
    environment = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                       GITHUB_EVENT_PATH=str(tmp_path / "event.json"))
    workflow = (WORKFLOWS / filename).read_text()
    result = subprocess.run(["bash", "-c", _script(_step(workflow, validation), "run")],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode == 7
    reports = list((tmp_path / ".ci-work").glob("*-report.md"))
    assert len(reports) == 1 and reports[0].read_text() == "E_FIXTURE_FAILURE\n"


@pytest.mark.parametrize("filename,validation,persistence,outcome", CASES)
@pytest.mark.parametrize("operation,publication,url,ready", [
    ("failure", "skipped", "", False), ("success", "failure", "", False),
    ("success", "skipped", "", False), ("success", "success", "", False),
    ("success", "success", "https://github.com/example/store/pull/12", True),
])
def test_issue_reporting_never_claims_publication_or_closes_at_pr_creation(
        tmp_path, filename, validation, persistence, outcome, operation, publication, url, ready):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to execute the actual github-script block")
    script = _script(_step((WORKFLOWS / filename).read_text(), "Report outcome"), "script")
    report_dir = tmp_path / ".ci-work"
    report_dir.mkdir()
    for name in ("process-report.md", "promotion-report.md"):
        (report_dir / name).write_text("DETAIL_SENTINEL\n")
    harness = """
const calls = [];
const record = action => async data => { calls.push({action, ...data}); };
const github = {rest:{issues:{createComment:record('comment'),addLabels:record('labels'),
  update:record('update'),removeLabel:record('remove')}}};
const context = {repo:{owner:'example',repo:'store'},issue:{number:56},
                 serverUrl:'https://github.com',runId:123};
(async () => {
""" + script + """
  console.log(JSON.stringify(calls));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run([node, "-e", harness], cwd=tmp_path,
                            env=dict(os.environ, **{outcome: operation, "PR_OUTCOME": publication, "PR_URL": url}),
                            capture_output=True, text=True, check=True, timeout=15)
    calls = json.loads(result.stdout)
    body = next(c["body"] for c in calls if c["action"] == "comment")
    assert ("DETAIL_SENTINEL" in body) == (ready or operation == "failure")
    assert not any(c.get("state") == "closed" or "promoted" in c.get("labels", []) for c in calls)
    assert "not published" in body.lower()
    if filename.startswith("approve") and not ready:
        assert any(c["action"] == "remove" and c["name"] == "approved" for c in calls)


@pytest.mark.parametrize("filename", ZOO)
@pytest.mark.parametrize("missing", SETTINGS)
def test_zoo_missing_setting_fails_before_token_and_never_prints_values(tmp_path, filename, missing):
    workflow = (WORKFLOWS / filename).read_text()
    name = "Check validator App availability before minting"
    assert workflow.index(name) < workflow.index("verify-audit") < workflow.index("Mint dedicated validator App token")
    script = _script(_step(workflow, name), "run")
    env = dict(os.environ, **{"ZOO_V2_VALIDATOR_" + k: "DO_NOT_PRINT_" + k for k in SETTINGS})
    env["ZOO_V2_VALIDATOR_" + missing] = ""
    env["GITHUB_STEP_SUMMARY"] = str(tmp_path / "summary")
    result = subprocess.run(["bash", "-c", script], env=env, cwd=tmp_path,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "validator App unavailable: missing ZOO_V2_VALIDATOR_" + missing in result.stdout
    assert "DO_NOT_PRINT" not in result.stdout + result.stderr


@pytest.mark.parametrize("filename", ZOO)
def test_configured_settings_continue_to_audit_not_a_skipped_success(tmp_path, filename):
    script = _script(_step((WORKFLOWS / filename).read_text(),
                          "Check validator App availability before minting"), "run")
    env = dict(os.environ, **{"ZOO_V2_VALIDATOR_" + k: "fixture" for k in SETTINGS},
               GITHUB_STEP_SUMMARY=str(tmp_path / "summary"))
    result = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0
    assert not result.stdout


@pytest.mark.parametrize("config,inspection,validation,stale_head,stale_base,posted", [
    ("success", "success", "success", False, False, "success"),
    ("failure", "success", "success", False, False, "failure"),
    ("success", "failure", "skipped", False, False, "failure"),
    ("success", "success", "failure", False, False, "failure"),
    ("success", "success", "skipped", False, False, "failure"),
    ("success", "success", "success", True, False, None),
    ("success", "success", "success", False, True, "failure"),
])
def test_actual_zoo_status_block_cannot_publish_false_success(
        tmp_path, config, inspection, validation, stale_head, stale_base, posted):
    workflow = (WORKFLOWS / "zoo-v2-pr-validation.yml").read_text()
    step = _step(workflow, "Publish App-bound required current-main status")
    assert "if: always() && steps.validator-token.outcome == 'success'" in step
    tools = tmp_path / "bin"
    tools.mkdir()
    gh = tools / "gh"
    gh.write_text(f"""#!{sys.executable}
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
if '--method' in args:
 with Path(os.environ['TEST_LOG']).open('a') as f: f.write(json.dumps(args)+'\\n')
elif any('/pulls/' in a for a in args): print(os.environ['CURRENT_HEAD'])
else: print(os.environ['CURRENT_BASE'])
""")
    gh.chmod(0o755)
    log = tmp_path / "api.jsonl"
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
               TEST_LOG=str(log), GH_TOKEN="fixture", HEAD_SHA="a" * 40, BASE_SHA="b" * 40,
               CURRENT_HEAD=("c" if stale_head else "a") * 40,
               CURRENT_BASE=("c" if stale_base else "b") * 40,
               APP_CONFIG=config, INSPECTION=inspection, RESULT=validation, MODE="none",
               PR_NUMBER="12", GITHUB_REPOSITORY="example/store")
    result = subprocess.run(["bash", "-c", _script(step, "run")], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == (1 if posted == "failure" else 0)
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert len(calls) == (0 if posted is None else 1)
    if posted:
        assert f"state={posted}" in calls[0]
        assert "context=Zoo v2 current-main" in calls[0]


def test_privileged_zoo_execution_stays_in_trusted_main():
    text = (WORKFLOWS / "zoo-v2-pr-validation.yml").read_text()
    assert "Validator dispatch must run from trusted main" in text
    assert "pr.head.sha !== expected" in text
    assert 'PYTHONPATH="$TRUSTED_ROOT/scripts"' in text
    assert '"$TRUSTED_ROOT/scripts/zoo_v2_release.py"' in text
    assert 'python3 "$CANDIDATE_ROOT' not in text
    assert "python3 -m pytest" not in text
    assert "continue-on-error: true" in text  # status collector still converts every failure to failure
