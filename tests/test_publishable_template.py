"""Public template qualification uses synthetic bytes, never owner runtime evidence."""
import ast
import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import zipfile

import pytest

import lib_rapp
from test_store_browser import browser, render_complete, schema_validator


ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "dock_scotty"
PRIVACY_PATTERNS = (
    rb"/(?:Users|home)/[^/\s\"']+",
    rb"\.rapp[-]dock",
    rb"\bgh[o]_[A-Za-z0-9_]+",
    rb"\bgithub[_]pat_[A-Za-z0-9_]+",
    rb"\b192[.]168[.][0-9]+[.][0-9]+",
    rb"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    rb"\bop-[0-9]{10}-[0-9a-f]{8}\b",
)


def privacy_findings(blob, label="source", depth=0):
    if depth > 8:
        return [label + ": nested privacy inspection depth exceeded"]
    findings = [label + ": private material pattern" for pattern in PRIVACY_PATTERNS if re.search(pattern, blob)]
    if zipfile.is_zipfile(io.BytesIO(blob)):
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 20 * 1024 * 1024:
                return findings + [label + ": nested expanded size exceeds the bound"]
            for info in archive.infolist():
                if not info.is_dir():
                    findings.extend(privacy_findings(archive.read(info), label + "/" + info.filename, depth + 1))
    elif label.endswith(".py"):
        try:
            tree = ast.parse(blob)
        except (SyntaxError, ValueError):
            return findings
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)) and len(node.value) >= 256:
                try:
                    payload = base64.b64decode(node.value, validate=True)
                except (ValueError, base64.binascii.Error):
                    continue
                if zipfile.is_zipfile(io.BytesIO(payload)):
                    findings.extend(privacy_findings(payload, label + "/embedded-package", depth + 1))
    return findings


@pytest.fixture
def sample():
    manifest = json.loads((SAMPLE / "manifest.json").read_text())
    files = {name: (SAMPLE / name).read_bytes() for name in manifest["files"]}
    return manifest, files


def test_template_json_schema_and_browser_closure_pass(sample):
    manifest, files = sample
    assert not list(schema_validator("application.schema.json").iter_errors(manifest))
    result = browser({"mode": "files", "manifest": manifest, "root": str(SAMPLE), "paths": list(files)})
    assert result == {"errors": [], "reads": len(files)}


def test_template_python_admission_and_shared_package_agree(sample):
    import rapp_package

    manifest, files = sample
    rapp_package.require_supported(manifest)
    rapp_package.verify_closure(manifest, files)
    result = lib_rapp.validate_dir(SAMPLE)
    assert result.ok, result.errors
    package = rapp_package.build_package(SAMPLE)
    restored, restored_files = rapp_package.read_package(package, hashlib.sha256(package).hexdigest())
    assert restored == manifest
    assert restored_files == files
    assert privacy_findings(package, "synthetic-package.egg") == []


def test_template_is_unlisted_pending_and_never_runnable_in_browser(sample):
    manifest, _ = sample
    readiness = manifest["local_docker"]["readiness"]
    assert manifest["quality_tier"] == "experimental"
    assert readiness["candidate"] == "experimental"
    assert readiness["fresh_install"] == "pending"
    assert readiness["recreation"]["dify"] == readiness["recreation"]["openshorts"] == "pending"
    assert readiness["current_health"] == {"status": "unknown", "observed_at": None}
    assert not manifest["provenance"]["deployed"] and not manifest["provenance"]["job_verified"]
    entry = lib_rapp.build_index_entry(manifest, {}, manifest["id"])
    assert not browser({"mode": "install", "entry": entry})
    rendered = render_complete(entry)
    assert "No complete installer is offered" in rendered["text"]
    assert "Copilot cloud inference" in rendered["text"]
    assert "fresh install: pending" in rendered["text"]
    assert "Package verification: pending" in rendered["text"]
    assert "Observed health: unknown" in rendered["text"]
    assert "observation time: none" in rendered["text"]
    assert "Job/mode verification:" in rendered["text"]
    assert "gateway-authored-presenton-exported" in rendered["text"]
    assert "Acceptance suite: pending" in rendered["text"]
    assert "Provider blockers:" in rendered["text"]
    assert "Reported reference-profile qualification" in rendered["text"]
    assert "Dify full recreation: qualified" in rendered["text"]
    assert "15 read-only roles" in rendered["text"]
    assert "drained completed state only" in rendered["text"]
    assert "not-recoverable" in rendered["text"]
    assert "blocked on npm/PyPI retrieval" in rendered["text"]
    assert not any("hatcher" in link.get("href", "") or "vbrainstem" in link.get("href", "")
                   for link in rendered["links"])


def test_reference_qualification_is_sanitized_and_not_candidate_evidence(sample):
    manifest, files = sample
    reference = json.loads(files["generated/reference-readiness.json"])
    assert manifest["metrics"]["reference_readiness"] == reference
    assert reference["applies_to_this_candidate"] is False
    assert reference["basis"] == "owner-reported sanitized qualification summary"
    assert reference["dify"]["recreation"] == "qualified"
    assert reference["dify"]["read_only_roles"] == 15
    assert reference["dify"]["fresh_answer_after_recreation"] is True
    assert reference["openshorts"]["recreation"] == "qualified"
    assert reference["openshorts"]["scope"] == "drained completed state only"
    assert reference["openshorts"]["in_flight_renderer_memory"] == "not-recoverable"
    assert reference["fresh_machine_install"] == "pending"
    assert reference["presenton_native_generation"] == "opt-in"
    assert reference["dify"]["native_plugin"] == "not-installed"
    readiness = manifest["local_docker"]["readiness"]
    assert readiness["fresh_install"] == "pending"
    assert readiness["recreation"]["dify"] == readiness["recreation"]["openshorts"] == "pending"
    assert privacy_findings(files["generated/reference-readiness.json"], "reference-readiness.json") == []


def test_exact_seven_job_ids_cover_five_journeys_and_diagnostic(sample):
    manifest, files = sample
    jobs = json.loads(files[manifest["local_docker"]["jobs_file"]])["jobs"]
    assert {job["id"] for job in jobs} == {
        "scrapling.scrape", "presenton.deck", "open-seo.project_create",
        "dify.knowledge_build", "dify.knowledge_answer", "openshorts.clips", "intelligence.chat",
    }
    assert {job["journey"] for job in jobs if job["application"] != "intelligence"} == {
        "web-research", "editable-deck", "seo-project", "knowledge-answer", "captioned-shorts",
    }
    for job in jobs:
        assert job["input_schema"]["additionalProperties"] is False
        assert job["outputs"] and job["limitations"]
        assert set(job["providers"]) <= {"copilot"}
    by_id = {job["id"]: job for job in jobs}
    assert by_id["presenton.deck"]["mode"] == "gateway-authored-presenton-exported"
    assert by_id["openshorts.clips"]["input_schema"]["properties"]["clip_count"]["default"] == 3
    assert by_id["dify.knowledge_build"]["input_schema"]["required"] == ["input_paths"]


def test_public_materialization_declares_buildx_without_claiming_cold_replay(sample):
    manifest, files = sample
    profiles = json.loads(files[manifest["local_docker"]["requirements_file"]])
    assert profiles["tools"]["buildx_plugin"] is True
    assert manifest["local_docker"]["readiness"]["fresh_install"] == "pending"
    assert manifest["local_docker"]["readiness"]["jobs"]["openshorts.clips"]["status"] == "pending"


@pytest.mark.parametrize("declaration,change", [
    ("component_lock", lambda d: d.update(unknown_mandatory_requirement="privileged-engine/1")),
    ("component_lock", lambda d: d["components"]["intelligence"].update(docker_socket=True)),
    ("requirements_file", lambda d: d.update(hidden_host_policy={"root": True})),
    ("requirements_file", lambda d: d["profiles"][0]["reference_resources"].update(is_minimum=True)),
    ("jobs_file", lambda d: d["jobs"][0].update(shell_command="not-an-advertised-field")),
    ("jobs_file", lambda d: d["jobs"][0]["input_schema"].update(additionalProperties=True)),
    ("jobs_file", lambda d: d["jobs"][0].update(providers=["unapproved-paid-provider"])),
    ("state_lifecycle_file", lambda d: d.update(credential_export=True)),
    ("state_lifecycle_file", lambda d: d["retention"].update(dify="volume-backed")),
])
def test_rehashed_reference_cannot_hide_unsupported_requirements(sample, declaration, change):
    manifest, files = sample
    manifest = copy.deepcopy(manifest)
    files = dict(files)
    name = manifest["local_docker"][declaration]
    value = json.loads(files[name])
    change(value)
    files[name] = json.dumps(value).encode()
    manifest["files"][name] = hashlib.sha256(files[name]).hexdigest()
    result = browser({
        "mode": "files", "manifest": manifest,
        "files": {key: base64.b64encode(blob).decode() for key, blob in files.items()},
    })
    assert result["errors"]
    assert lib_rapp._application_contract_errors(manifest, files)


def test_synthetic_readiness_cannot_be_relabelled_as_live_success(sample):
    manifest, files = sample
    manifest["local_docker"]["readiness"]["fresh_install"] = "passed"
    result = browser({
        "mode": "files", "manifest": manifest,
        "files": {key: base64.b64encode(blob).decode() for key, blob in files.items()},
    })
    assert result["errors"]
    assert lib_rapp._application_contract_errors(manifest, files)


def test_support_member_digest_is_not_enough_if_inventory_differs(sample):
    manifest, files = sample
    name = manifest["local_docker"]["loader"]["support"] + "/agents/scotty_agent.py"
    files[name] += b"\n# synthetic tampering fixture\n"
    manifest["files"][name] = hashlib.sha256(files[name]).hexdigest()
    result = browser({
        "mode": "files", "manifest": manifest,
        "files": {key: base64.b64encode(blob).decode() for key, blob in files.items()},
    })
    assert any("E_LOADER" in error for error in result["errors"])
    assert lib_rapp._application_contract_errors(manifest, files)


@pytest.mark.parametrize("spelling", ["decimal", "exponent"])
def test_loader_integer_tokens_are_not_normalized_into_admissibility(sample, spelling):
    manifest, files = sample
    old_prefix = manifest["local_docker"]["loader"]["support"] + "/"
    inventory = json.loads(files[old_prefix + "SCOTTY_CAPABILITY_LOCK.json"])
    length = inventory["files"][0]["bytes"]
    inventory["files"][0]["bytes"] = float(length)
    raw = json.dumps(inventory, sort_keys=True).encode()
    if spelling == "exponent":
        raw = raw.replace(f'"bytes": {length}.0'.encode(), f'"bytes": {length}e0'.encode(), 1)
    revision = hashlib.sha256(raw).hexdigest()
    prefix = "singleton/scotty_support_" + revision + "/"
    files = {prefix + name[len(old_prefix):] if name.startswith(old_prefix) else name: blob
             for name, blob in files.items()}
    files[prefix + "SCOTTY_CAPABILITY_LOCK.json"] = raw
    descriptor = json.loads(files["singleton/scotty_revision.json"])
    descriptor["support_sha256"] = revision
    files["singleton/scotty_revision.json"] = json.dumps(descriptor).encode()
    manifest["local_docker"]["loader"]["support"] = prefix.rstrip("/")
    manifest["files"] = {name: hashlib.sha256(blob).hexdigest() for name, blob in files.items()}
    result = browser({
        "mode": "files", "manifest": manifest,
        "files": {key: base64.b64encode(blob).decode() for key, blob in files.items()},
    })
    assert result["errors"]
    assert any("E_LOADER" in error for error in lib_rapp._application_contract_errors(manifest, files))


def test_job_declarations_do_not_execute_publisher_regexes(sample):
    manifest, files = sample
    name = manifest["local_docker"]["jobs_file"]
    declaration = json.loads(files[name])
    declaration["jobs"][0]["input_schema"]["properties"]["url"]["pattern"] = "^safe$"
    files[name] = json.dumps(declaration).encode()
    manifest["files"][name] = hashlib.sha256(files[name]).hexdigest()
    result = browser({
        "mode": "files", "manifest": manifest,
        "files": {key: base64.b64encode(blob).decode() for key, blob in files.items()},
    })
    assert result["errors"]
    assert lib_rapp._application_contract_errors(manifest, files)


def test_template_agent_import_is_inert_and_response_is_honestly_blocked(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Template must not execute Docker, providers, or network operations")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    path = SAMPLE / "singleton" / "scotty_agent.py"
    spec = importlib.util.spec_from_file_location("_synthetic_scotty_entry", path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    answer = json.loads(module.ScottyAgent().perform())
    assert answer["status"] == "blocked"
    assert answer["code"] == "authoring-template-only"
    assert answer["fresh_install"] == "pending"


def test_template_builder_is_deterministic_without_network_or_docker(tmp_path):
    output = tmp_path / "dock_scotty"
    command = [sys.executable, "-B", str(SAMPLE / "tools" / "build_template.py"), "--output", str(output)]
    subprocess.run(command, check=True, capture_output=True, timeout=20)
    before = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    subprocess.run(command, check=True, capture_output=True, timeout=20)
    subprocess.run(command + ["--check"], check=True, capture_output=True, timeout=20)
    after = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    assert after == before
    assert before["manifest.json"] == (SAMPLE / "manifest.json").read_bytes()


def test_nested_privacy_scan_template_and_double_wrapped_archive(sample):
    manifest, files = sample
    payload = {**files, "manifest.json": json.dumps(manifest).encode()}
    for name, blob in payload.items():
        assert privacy_findings(blob, name) == []
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, blob in payload.items():
            archive.writestr(name, blob)
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("synthetic-inner.egg", inner.getvalue())
    assert privacy_findings(outer.getvalue(), "synthetic-outer.zip") == []


def test_nested_privacy_scan_detects_synthetic_private_path():
    data = b"/" + b"Users" + b"/synthetic-person/private-data"
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("fixture.txt", data)
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("inner.egg", inner.getvalue())
    findings = privacy_findings(outer.getvalue(), "outer.zip")
    assert findings and any("inner.egg/fixture.txt" in finding for finding in findings)
