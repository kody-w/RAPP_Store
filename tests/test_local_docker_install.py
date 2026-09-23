"""Source installation is not deployment: synthetic jobs, real scoped Grail loader."""

import ast
import base64
import copy
import importlib.util
import io
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import rapp_package as package
from build_hatchers import artifact_names, render_hatcher, write_artifacts

FIXTURES = Path(__file__).parent / "fixtures" / "local_docker"
AGENT = b"""from agents.basic_agent import BasicAgent
import json
__manifest__ = {
    "schema": "rapp-agent/1.0", "name": "@fixture/dock_fixture", "version": "1.0.0",
    "description": "Synthetic installation test; no application jobs or Docker effects.",
}
class ScottyAgent(BasicAgent):
    def __init__(self):
        super().__init__(name="Scotty", metadata={
            "name": "Scotty", "description": "Synthetic source-layout fixture only.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        })
    def perform(self, **kwargs):
        return json.dumps({"status": "fixture-only", "jobs_run": 0})
"""


def simple_manifest(files):
    return {
        "schema": package.APPLICATION_SCHEMA,
        "id": "dock_fixture",
        "name": "Synthetic Dock Fixture",
        "version": "1.0.0",
        "publisher": "@fixture",
        "summary": "Synthetic source-layout fixture; not deployed or job-qualified.",
        "category": "platform",
        "tags": ["rapplication", "test"],
        "agent": "singleton/scotty_agent.py",
        "agents": ["singleton/scotty_agent.py"],
        "runtime": dict(package.GRAIL),
        "files": {name: package.digest(blob) for name, blob in files.items()},
        "requires": ["portable-agents/1", "owned-files/1"],
        "profiles": [],
        "permissions": ["host-user"],
        "capabilities": ["inspect"],
        "dependencies": [],
        "services": [],
        "state": {"version": "1", "preserve": True, "seeds": {}},
        "lifecycle": dict(package.LIFECYCLE),
        "providers": {"mode": "host", "spend_limit": None, "egress_allowlist": None},
        "provenance": {
            "status": "development",
            "source": "synthetic-test-fixture",
            "deployed": False,
            "job_verified": False,
        },
    }


def declarations():
    source = b"synthetic fixture source; never fetched or materialized"
    return {
        "components.lock.json": {
            "schema": "rapp-dock-components/1",
            "profile": {
                "host": "darwin/arm64",
                "docker_context": "desktop-linux",
                "guest_platforms": ["linux/arm64", "linux/amd64"],
                "amd64_emulation_required": True,
                "assurance": "locked-public-inputs-and-local-image-observations-not-signed-builds",
                "fresh_machine_acceptance": "pending",
                "bit_identical_rebuilds_claimed": False,
            },
            "artifacts": {},
            "input_sets": {},
            "components": {
                "scrapling": {
                    "kind": "registry",
                    "platform": "linux/arm64",
                    "env": "RAPP_DOCK_IMAGE_SCRAPLING",
                    "reference": "fixture@sha256:" + package.digest(source),
                    "recipe": None,
                    "observed_image_ids": [],
                    "source": "Synthetic fixture; no registry fetch or image identity is claimed.",
                    "license": "Synthetic test data only.",
                    "blockers": [],
                }
            },
            "applications": {"scrapling": {"scrapling": "scrapling"}},
        },
        "generated/host-profiles.json": {
            "schema": "rapp-local-host-profiles/1",
            "python_minimum": "3.11",
            "grail": dict(package.GRAIL),
            "tools": {
                "git": True,
                "docker": True,
                "compose_plugin": True,
                "buildx_plugin": True,
                "local_daemon_only": True,
            },
            "profiles": [
                {
                    "id": "synthetic-arm64",
                    "host_os": "darwin",
                    "host_arch": "arm64",
                    "guest_platforms": ["linux/arm64", "linux/amd64"],
                    "emulation": True,
                    "qualification": "development-reference",
                    "fresh_install": "pending",
                    "reference_resources": {
                        "docker_vm_cpus": 1,
                        "docker_vm_memory_gib": 1,
                        "is_minimum": False,
                    },
                }
            ],
            "authentication": {
                "provider": "github-copilot",
                "custody": "adopter-owned",
                "required_for_ai_jobs": True,
                "export_credentials": False,
            },
        },
        "generated/job-contracts.json": {
            "schema": "rapp-local-jobs/1",
            "jobs": [
                {
                    "id": "scrapling.fixture",
                    "application": "scrapling",
                    "journey": "diagnostic",
                    "mode": "synthetic-only",
                    "input_schema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                    "outputs": [
                        {
                            "name": "result",
                            "kind": "native-record",
                            "media_type": "application/json",
                            "required": True,
                        }
                    ],
                    "providers": [],
                    "limitations": ["No application jobs are executed."],
                }
            ],
        },
        "generated/state-lifecycle.json": {
            "schema": "rapp-local-state-lifecycle/1",
            "owned_roots": ["synthetic-state"],
            "volumes": ["synthetic-volume"],
            "sealed_inputs": True,
            "start": "explicit-use",
            "stop": "retain-data",
            "uninstall": "drain-stop-detach-preserve",
            "upgrade": "preserve-state",
            "recovery": "reconcile-no-replay",
            "credential_export": False,
            "destructive_operations": [],
            "retention": {"dify": "stop-retain", "openshorts": "stop-retain"},
        },
        "candidate-specific-sanitized-evidence.json": {
            "schema": "rapp-readiness-evidence/1",
            "synthetic": True,
            "scope": "authoring-template",
            "candidate_digest": None,
            "acceptance_suite_revision": None,
            "observed_at": None,
            "results": [],
            "limitations": [
                "Synthetic installer evidence is not real-job qualification."
            ],
        },
    }


def local_application(bootstrap=AGENT, *, with_controller=False):
    documents = declarations()
    support = {
        "agents/scotty_agent.py": AGENT,
        "assets/synthetic.txt": b"synthetic retained source\n",
        "deploy/local/components.lock.json": package.canonical_json(
            documents["components.lock.json"]
        ),
    }
    if with_controller:
        support["agents/scotty_agent.py"] = (
            b"from local_dock import LocalDock\n" + AGENT
        )
        support["local_dock.py"] = (FIXTURES / "controller.py").read_bytes()
    lock = {
        "schema": "scotty-capability-files/1",
        "grail_commit": package.GRAIL["commit"],
        "files": [
            {"path": name, "bytes": len(blob), "sha256": package.digest(blob)}
            for name, blob in sorted(support.items())
        ],
    }
    lock_bytes = package.canonical_json(lock)
    revision = package.digest(lock_bytes)
    prefix = "singleton/scotty_support_" + revision + "/"
    files = {
        "singleton/scotty_agent.py": bootstrap,
        "singleton/scotty_revision.json": package.canonical_json(
            {
                "schema": "scotty-agent-revision/1",
                "loader_contract": package.LOADER_CONTRACT,
                "entrypoint_sha256": package.digest(bootstrap),
                "support_sha256": revision,
            }
        ),
        prefix + "SCOTTY_CAPABILITY_LOCK.json": lock_bytes,
        **{prefix + name: blob for name, blob in support.items()},
        **{name: package.canonical_json(value) for name, value in documents.items()},
        "README.md": b"Synthetic installer fixture. This is not application acceptance.\n",
    }
    manifest = simple_manifest(files)
    manifest["requires"].append("local-docker/1")
    manifest["local_docker"] = {
        "schema": package.LOCAL_DOCKER_SCHEMA,
        "component_lock": "components.lock.json",
        "loader": {
            "contract": package.LOADER_CONTRACT,
            "entrypoint": "singleton/scotty_agent.py",
            "descriptor": "singleton/scotty_revision.json",
            "support": prefix.rstrip("/"),
        },
        "requirements_file": "generated/host-profiles.json",
        "jobs_file": "generated/job-contracts.json",
        "state_lifecycle_file": "generated/state-lifecycle.json",
        "intelligence": {
            "runtime": "official-copilot-cli-in-docker",
            "version": "1.0.88",
            "model": "gpt-5-mini",
            "concurrency": 2,
            "cloud_inference": True,
            "tools": [],
            "usage": "measured-when-available",
            "monetary_cost": None,
            "hard_spend_cap": None,
            "other_paid_providers": "disabled",
        },
        "exhaust": {
            "wire": "rapp/1",
            "frame_kind": "memory.tool-call",
            "receipt_variant": "session",
            "capsule_variant": "rapplication",
            "capsule_contains": "selected-outputs-and-producing-source-not-full-app-state",
            "verification": "unsigned-structural-only",
        },
        "readiness": {
            "candidate": "experimental",
            "fresh_install": "pending",
            "recreation": {"dify": "pending", "openshorts": "pending"},
            "live_results": "candidate-specific-sanitized-evidence.json",
        },
    }
    return manifest, files


def cartridge(manifest, files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        members = [
            (
                "manifest.json",
                package.canonical_json(
                    {
                        "schema": package.PACKAGE_SCHEMA,
                        "type": "rapplication",
                        "application": manifest,
                    }
                ),
            ),
            *[
                ("application/" + name, contents)
                for name, contents in sorted(files.items())
            ],
        ]
        for name, contents in members:
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100400 << 16
            archive.writestr(info, contents)
    return out.getvalue()


def repin(manifest, files):
    manifest["files"] = {
        name: package.digest(contents) for name, contents in files.items()
    }
    return cartridge(manifest, files)


@pytest.fixture
def app():
    return local_application()


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = tmp_path / "isolated-host"
    (root / "agents").mkdir(parents=True, mode=0o700)
    owner = tmp_path / "isolated-owner"
    owner.mkdir(mode=0o700)
    for name in package.LIFECYCLE_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(owner))
    monkeypatch.setenv("RAPP_DOCK_HOME", str(tmp_path / "bound-runtime"))
    monkeypatch.setenv("RAPP_DOCK_NAMESPACE", "rapp-dock-th")
    monkeypatch.setattr(package, "verify_grail", lambda path: Path(path))
    monkeypatch.setattr(package.shutil, "which", lambda name: "/fixture/docker")
    monkeypatch.setattr(package.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(package.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        package.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=b"29.1.3\n"),
    )
    return root


def install(app, host, **kwargs):
    blob = cartridge(*app)
    return package.install_package(blob, package.digest(blob), host, **kwargs)


def app_home(host):
    return host / ".brainstem_data/rapplications/@fixture/dock_fixture"


def source_tree(host):
    return {
        path.relative_to(host).as_posix(): path.read_bytes()
        for path in host.rglob("*")
        if path.is_file()
    }


def assert_layout(host, manifest, files):
    sources = package._source_layout(manifest, files)
    for name, contents in sources.items():
        target = host / "agents" / name
        assert target.read_bytes() == contents
        assert stat.S_IMODE(target.stat().st_mode) == 0o400
    for name in package._source_directories(sources):
        assert stat.S_IMODE((host / "agents" / name).stat().st_mode) == 0o700


def test_static_contract_package_and_inspection_need_no_device(
    app, tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("static operation performed a device effect")

    monkeypatch.setattr(package.subprocess, "run", forbidden)
    monkeypatch.setattr(package.shutil, "which", forbidden)
    monkeypatch.setattr(package, "verify_grail", forbidden)
    monkeypatch.setattr(package.sys, "version_info", (3, 10, 0))
    manifest, files = app
    package.validate_contract(manifest)
    package.require_supported(manifest)
    package.verify_closure(manifest, files)
    blob = cartridge(manifest, files)
    assert package.read_package(blob, package.digest(blob)) == app
    path = tmp_path / "hatcher.py"
    path.write_bytes(render_hatcher(blob))
    before = source_tree(tmp_path)
    spec = importlib.util.spec_from_file_location("inert_fixture_hatcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "verify_grail", forbidden)
    monkeypatch.setattr(module.subprocess, "run", forbidden)
    result = json.loads(module.DockFixtureHatcherAgent().perform(action="inspect"))
    assert result["status"] == "package_verified"
    assert result["device_checked"] is False and result["installed"] is False
    assert not (tmp_path / ".brainstem_data").exists()
    assert {
        key: value
        for key, value in source_tree(tmp_path).items()
        if "__pycache__/" not in key
    } == before


@pytest.mark.parametrize("concurrency", [2, 2.0])
def test_fixed_concurrency_uses_json_numeric_equality(app, concurrency):
    app[0]["local_docker"]["intelligence"]["concurrency"] = concurrency
    package.require_supported(app[0])
    package.verify_closure(*app)
    blob = cartridge(*app)
    assert package.read_package(blob, package.digest(blob)) == app


@pytest.mark.parametrize("concurrency", [True, False, "2", 2.5, None])
def test_fixed_concurrency_does_not_coerce_booleans_or_other_values(app, concurrency):
    app[0]["local_docker"]["intelligence"]["concurrency"] = concurrency
    with pytest.raises(
        package.PackageError, match="unqualified local intelligence policy"
    ):
        package.require_supported(app[0])


def test_loader_byte_counts_remain_strict_even_for_integral_json_floats(app):
    manifest, files = app
    loader = manifest["local_docker"]["loader"]
    old_prefix = loader["support"] + "/"
    lock = json.loads(files[old_prefix + "SCOTTY_CAPABILITY_LOCK.json"])
    lock["files"][0]["bytes"] = float(lock["files"][0]["bytes"])
    encoded = package.canonical_json(lock)
    revision = package.digest(encoded)
    new_prefix = "singleton/scotty_support_" + revision + "/"
    updated = {
        new_prefix + name[len(old_prefix) :]
        if name.startswith(old_prefix)
        else name: contents
        for name, contents in files.items()
    }
    updated[new_prefix + "SCOTTY_CAPABILITY_LOCK.json"] = encoded
    descriptor = json.loads(updated[loader["descriptor"]])
    descriptor["support_sha256"] = revision
    updated[loader["descriptor"]] = package.canonical_json(descriptor)
    loader["support"] = new_prefix.rstrip("/")
    repin(manifest, updated)
    with pytest.raises(package.PackageError, match="E_LOADER_CLOSURE"):
        package.verify_closure(manifest, updated)


@pytest.mark.parametrize(
    "value",
    [0, 2, 2.0, -2, -2.0, package.MAX_SAFE_INTEGER, -package.MAX_SAFE_INTEGER],
)
def test_contract_integers_accept_safe_json_integral_numbers(value):
    assert package._integer(value)


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        "2",
        2.5,
        float("inf"),
        float("nan"),
        package.MAX_SAFE_INTEGER + 1,
        -(package.MAX_SAFE_INTEGER + 1),
        float(package.MAX_SAFE_INTEGER + 1),
    ],
)
def test_contract_integers_refuse_bool_fractional_nonfinite_and_inexact_values(value):
    assert not package._integer(value)


@pytest.mark.parametrize(
    "document,change",
    [
        (
            "generated/host-profiles.json",
            lambda value: value["profiles"][0]["reference_resources"].update(
                docker_vm_cpus=2.0
            ),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0]["input_schema"]["properties"].update(
                text={
                    "type": "string",
                    "minLength": 2.0,
                    "maxLength": 5.0,
                    "default": "ok",
                }
            ),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0]["input_schema"]["properties"].update(
                values={
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 1.0,
                    "maxItems": 2.0,
                    "default": [1.0],
                }
            ),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0]["input_schema"]["properties"].update(
                count={
                    "type": "integer",
                    "enum": [2],
                    "default": 2.0,
                }
            ),
        ),
    ],
)
def test_referenced_integer_fields_use_json_semantics(app, document, change):
    change_document(app, document, change)
    package.require_supported(app[0])
    package.verify_closure(*app)
    blob = cartridge(*app)
    assert package.read_package(blob, package.digest(blob)) == app


@pytest.mark.parametrize(
    "document,change",
    [
        (
            "components.lock.json",
            lambda value: value["artifacts"].update(
                bad={
                    "url": "https://github.com/example/fixture",
                    "sha256": "0" * 64,
                    "bytes": package.MAX_SAFE_INTEGER + 1,
                    "license": "synthetic",
                }
            ),
        ),
        (
            "generated/host-profiles.json",
            lambda value: value["profiles"][0]["reference_resources"].update(
                docker_vm_cpus=2.5
            ),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0]["input_schema"]["properties"].update(
                text={
                    "type": "string",
                    "minLength": True,
                }
            ),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0]["input_schema"]["properties"].update(
                count={
                    "type": "integer",
                    "default": package.MAX_SAFE_INTEGER + 1,
                }
            ),
        ),
    ],
)
def test_referenced_integer_fields_never_accept_unsafe_coercion(app, document, change):
    change_document(app, document, change)
    with pytest.raises(package.PackageError):
        package.verify_closure(*app)


@pytest.mark.parametrize(
    "parameter",
    [
        {
            "type": "array",
            "items": {"type": "number"},
            "uniqueItems": True,
            "default": [1, 1.0],
        },
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"n": {"type": "number"}},
                "required": ["n"],
                "additionalProperties": False,
            },
            "uniqueItems": True,
            "default": [{"n": 1}, {"n": 1.0}],
        },
        {"type": "boolean", "enum": [1], "default": True},
    ],
)
def test_numeric_equality_preserves_unique_items_and_bool_distinction(app, parameter):
    def change(value):
        value["jobs"][0]["input_schema"]["properties"]["value"] = parameter

    change_document(app, "generated/job-contracts.json", change)
    with pytest.raises(package.PackageError, match="E_JOBS"):
        package.verify_closure(*app)


@pytest.mark.parametrize(
    "field,value",
    [
        ("license", {}),
        ("license", []),
        ("quality_tier", None),
        ("homepage", None),
        ("metrics", []),
        ("tool", "true"),
        ("surfaces", ["chat", True]),
    ],
)
def test_v2_optional_metadata_keeps_its_declared_types(app, field, value):
    app[0][field] = value
    with pytest.raises(package.PackageError):
        package.require_supported(app[0])


def test_complete_flat_layout_and_receipt_written_last(app, host, monkeypatch):
    events = []
    publish, rename, unlink = (
        package._publish_file,
        package._rename_new,
        package._unlink_owned,
    )

    def record_publish(path, contents, **kwargs):
        events.append(("write", Path(path).name))
        return publish(path, contents, **kwargs)

    def record_rename(source, target):
        events.append(("rename", Path(target).name))
        return rename(source, target)

    def record_unlink(path, sha):
        events.append(("unlink", Path(path).name))
        return unlink(path, sha)

    monkeypatch.setattr(package, "_publish_file", record_publish)
    monkeypatch.setattr(package, "_rename_new", record_rename)
    monkeypatch.setattr(package, "_unlink_owned", record_unlink)
    result = install(app, host)
    assert result["status"] == "installed" and result["deployed"] is False
    assert_layout(host, *app)
    receipt = json.loads((app_home(host) / "installed.json").read_text())
    assert receipt["schema"] == "rapp-install/2.0" and receipt["status"] == "installed"
    assert receipt["sources"] == {
        name: package.digest(contents)
        for name, contents in package._source_layout(*app).items()
    }
    assert events[-1] == ("unlink", "pending.json")
    assert events[-2] == ("rename", "installed.json")
    assert events.index(("rename", "scotty_revision.json")) < events.index(
        ("rename", "scotty_agent.py")
    )
    assert install(app, host)["status"] == "already_installed"
    assert not (app_home(host) / "pending.json").exists()


def test_install_binds_private_scope_without_initializing_runtime_or_reading_custody(
    app, host
):
    selected = Path(os.environ["RAPP_DOCK_HOME"])
    assert not selected.exists()
    install(app, host)
    record = json.loads((app_home(host) / "installed.json").read_text())
    binding = record["local_docker_binding"]
    assert binding["home"] == str(selected)
    assert binding["owner_home"] == str(Path.home())
    assert binding["namespace"] == "rapp-dock-th"
    assert binding["port_base"] == 18080
    assert (
        binding["environment_sha256"]
        == package._current_binding()["environment_sha256"]
    )
    assert not selected.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("RAPP_DOCK_NAMESPACE", "rapp-dock-tg"),
        ("RAPP_DOCK_PORT_BASE", "18600"),
        ("RAPP_DOCK_AI_MODEL", "another-model"),
        ("RAPP_DOCK_NETWORK_POOL", "10.236.0.0/16"),
    ],
)
def test_runtime_configuration_drift_refuses_before_any_lifecycle_effect(
    app, host, monkeypatch, field, value
):
    install(app, host)
    before = source_tree(host)
    monkeypatch.setenv(field, value)
    monkeypatch.setattr(
        package,
        "_stop_local_docker",
        lambda *a, **kw: pytest.fail("drift reached lifecycle effects"),
    )
    with pytest.raises(package.PackageError, match="E_LIFECYCLE_SCOPE"):
        uninstall(app, host)
    with pytest.raises(package.PackageError, match="E_LIFECYCLE_SCOPE"):
        install(app, host)
    assert source_tree(host) == before


def test_other_runtime_home_is_never_initialized_or_stopped(
    app, host, tmp_path, monkeypatch
):
    install(app, host)
    other = tmp_path / "unrelated-runtime"
    monkeypatch.setenv("RAPP_DOCK_HOME", str(other))
    monkeypatch.setattr(
        package,
        "_stop_local_docker",
        lambda *a, **kw: pytest.fail("unrelated runtime reached lifecycle"),
    )
    with pytest.raises(package.PackageError, match="E_LIFECYCLE_SCOPE"):
        uninstall(app, host)
    assert not other.exists()
    assert (host / "agents/scotty_agent.py").exists()


def test_unbound_historical_receipt_never_falls_back_to_ambient_runtime(
    app, host, monkeypatch
):
    install(app, host)
    path = app_home(host) / "installed.json"
    value = json.loads(path.read_text())
    del value["local_docker_binding"]
    path.chmod(0o600)
    path.write_bytes(package.canonical_json(value))
    path.chmod(0o400)
    monkeypatch.setattr(
        package,
        "_stop_local_docker",
        lambda *a, **kw: pytest.fail("unbound receipt reached lifecycle"),
    )
    with pytest.raises(package.PackageError, match="E_LIFECYCLE_BINDING"):
        uninstall(app, host)
    assert (host / "agents/scotty_agent.py").exists()


def test_resume_requires_the_same_verified_receipt_binding(app, host):
    install(app, host)
    binding = json.loads((app_home(host) / "installed.json").read_text())[
        "local_docker_binding"
    ]
    calls = []
    key = (str(host), app[0]["publisher"], app[0]["id"])
    wrong = {**binding, "namespace": "rapp-dock-tg"}
    target = package._binding_target(binding)

    def resume():
        calls.append(target)
        return {
            "schema": "rapp-dock-installation-fence/1",
            "target": target,
            "durable": False,
            "admission_paused": False,
            "status": "reactivated",
        }

    entry = {
        "home": Path(binding["home"]),
        "binding": wrong,
        "resume": resume,
    }
    package._fences()[key] = entry
    try:
        assert package._resume_after_install(host, app[0]) == "retained-paused"
        assert calls == [] and key in package._fences()
        entry["binding"] = binding
        assert (
            package._resume_after_install(host, app[0])
            == "resumed-after-preserving-reinstall"
        )
        assert calls == [target]
        assert key not in package._fences()
    finally:
        package._fences().pop(key, None)


@pytest.mark.parametrize("selected", ["filesystem", "owner"])
def test_unsafe_runtime_root_refuses_before_source_writes(
    app, host, monkeypatch, selected
):
    monkeypatch.setenv(
        "RAPP_DOCK_HOME", "/" if selected == "filesystem" else str(Path.home())
    )
    with pytest.raises(package.PackageError, match="E_LIFECYCLE_BINDING"):
        install(app, host)
    assert not (host / ".brainstem_data").exists()


def test_failed_reactivation_retains_retry_intent_after_receipt_commit(
    app, host, monkeypatch
):
    install(app, host)
    monkeypatch.setattr(package, "_stop_local_docker", stopped_fixture)
    assert uninstall(app, host)["status"] == "detached"
    key = (str(host), app[0]["publisher"], app[0]["id"])
    entry = package._fences()[key]
    resume = entry["resume"]
    entry["resume"] = lambda: (_ for _ in ()).throw(
        OSError("synthetic durable resume failure")
    )
    result = install(app, host)
    assert result["runtime_resume"] == "retained-paused" and result["admission_paused"]
    assert (
        json.loads((app_home(host) / "installed.json").read_text())["status"]
        == "installed"
    )
    assert (
        json.loads((app_home(host) / "pending.json").read_text())["reactivate"] is True
    )
    entry["resume"] = resume
    assert install(app, host)["runtime_resume"] == "resumed-after-preserving-reinstall"
    assert not (app_home(host) / "pending.json").exists()


@pytest.mark.parametrize("stage", ["support", "descriptor", "entrypoint", "receipt"])
def test_interrupted_install_is_receipt_last_and_recovers_same_package(
    app, host, monkeypatch, stage
):
    original = package._rename_new
    stopped = False

    def interrupt(source, target):
        nonlocal stopped
        name = Path(target).name
        match = (
            stage == "support"
            and name.startswith("scotty_support_")
            or stage == "descriptor"
            and name == "scotty_revision.json"
            or stage == "entrypoint"
            and name == "scotty_agent.py"
            or stage == "receipt"
            and name == "installed.json"
        )
        if match and not stopped:
            stopped = True
            raise OSError("synthetic publication interruption")
        return original(source, target)

    monkeypatch.setattr(package, "_rename_new", interrupt)
    with pytest.raises(OSError, match="publication interruption"):
        install(app, host)
    assert not (app_home(host) / "installed.json").exists()
    assert (app_home(host) / "pending.json").is_file()
    if stage != "receipt":
        assert not (host / "agents/scotty_agent.py").exists()
    else:
        assert_layout(host, *app)
    changed = copy.deepcopy(app)
    changed[0]["version"] = "1.1.0"
    with pytest.raises(package.PackageError, match="E_RECOVERY_REQUIRED"):
        install(changed, host)
    assert install(app, host)["status"] == "installed"
    assert_layout(host, *app)


def test_recovery_refuses_tampered_partial_source(app, host, monkeypatch):
    original = package._rename_new

    def interrupt(source, target):
        if Path(target).name == "scotty_agent.py":
            raise OSError("interrupted")
        return original(source, target)

    monkeypatch.setattr(package, "_rename_new", interrupt)
    with pytest.raises(OSError):
        install(app, host)
    descriptor = host / "agents/scotty_revision.json"
    descriptor.chmod(0o600)
    descriptor.write_text("owner edit")
    before = source_tree(host)
    with pytest.raises(package.PackageError, match="E_AGENT_CONFLICT"):
        install(app, host)
    assert source_tree(host) == before


@pytest.mark.parametrize(
    "kind",
    ["entrypoint", "descriptor", "support-directory", "same-bytes", "other-scotty"],
)
def test_unowned_collisions_refuse_before_application_writes(app, host, kind):
    manifest, files = app
    sources = package._source_layout(manifest, files)
    support = manifest["local_docker"]["loader"]["support"].split("/")[1]
    if kind == "support-directory":
        (host / "agents" / support).mkdir()
    else:
        name = (
            "scotty_revision.json"
            if kind == "descriptor"
            else ("other_agent.py" if kind == "other-scotty" else "scotty_agent.py")
        )
        contents = (
            AGENT
            if kind == "other-scotty"
            else sources[name]
            if kind == "same-bytes"
            else b"unowned"
        )
        (host / "agents" / name).write_bytes(contents)
    before = source_tree(host)
    with pytest.raises(package.PackageError, match="E_(AGENT|SOURCE|SCOTTY)_CONFLICT"):
        install(app, host)
    assert source_tree(host) == before
    assert not (host / ".brainstem_data").exists()


def test_missing_owned_support_is_repaired_but_changed_support_is_refused(app, host):
    install(app, host)
    support = app[0]["local_docker"]["loader"]["support"].split("/")[1]
    asset = host / "agents" / support / "assets/synthetic.txt"
    asset.unlink()
    (host / "agents/scotty_agent.py").unlink()
    assert install(app, host)["status"] == "installed"
    assert_layout(host, *app)
    asset.chmod(0o600)
    asset.write_text("owner edit")
    with pytest.raises(package.PackageError, match="E_AGENT_CONFLICT"):
        install(app, host)
    assert asset.read_text() == "owner edit"


def test_repair_recommits_receipt_last_even_when_its_bound_bytes_are_unchanged(
    app, host, monkeypatch
):
    install(app, host)
    record = app_home(host) / "installed.json"
    old_record, old_inode = record.read_bytes(), record.stat().st_ino
    (host / "agents/scotty_agent.py").unlink()
    events = []
    original = package._publish_file

    def publish(path, contents, **kwargs):
        events.append(Path(path))
        return original(path, contents, **kwargs)

    monkeypatch.setattr(package, "_publish_file", publish)
    assert install(app, host)["status"] == "installed"
    assert events[-1] == record
    assert record.read_bytes() == old_record and record.stat().st_ino != old_inode


@pytest.mark.parametrize("link", ["symlink-file", "symlink-directory", "hardlink-file"])
def test_linked_targets_are_never_followed(app, host, tmp_path, link):
    outside = tmp_path / "unowned"
    outside.mkdir()
    owned = outside / "keep"
    owned.write_text("untouched")
    if link == "symlink-directory":
        (host / ".brainstem_data").symlink_to(outside, target_is_directory=True)
    elif link == "symlink-file":
        (host / "agents/scotty_agent.py").symlink_to(owned)
    else:
        os.link(owned, host / "agents/scotty_agent.py")
    with pytest.raises((package.PackageError, OSError)):
        install(app, host)
    assert owned.read_text() == "untouched"
    assert list(outside.iterdir()) == [owned]


@pytest.mark.parametrize(
    "name",
    [
        "assets/caf\u00e9.txt",
        "assets/stra\u00dfe.txt",
        "assets/\u0130.txt",
        "assets/file\U0001f680.txt",
        "assets/e\u0301.txt",
    ],
)
def test_v2_relative_paths_are_ascii_before_device_effects(
    app, host, monkeypatch, name
):
    app[1][name] = b"synthetic source"
    repin(*app)
    monkeypatch.setattr(
        package,
        "preflight_device",
        lambda *args, **kwargs: pytest.fail(
            "nonportable path reached device preflight"
        ),
    )
    with pytest.raises(package.PackageError, match="E_PATH:.*ASCII"):
        package.relative_path(name)
    with pytest.raises(package.PackageError, match="E_PATH:.*ASCII"):
        install(app, host)
    assert not (host / ".brainstem_data").exists()


def test_ascii_package_paths_preserve_unicode_contents_and_host_roots(app, host):
    contents = (
        "Synthetic multilingual content: caf\u00e9 \u4e16\u754c \u2713\n".encode()
    )
    app[1]["assets/unicode.txt"] = contents
    repin(*app)
    localized = host.parent / "h\u00f4te-\u4f5c\u696d"
    (localized / "agents").mkdir(mode=0o700, parents=True)
    assert install(app, localized)["status"] == "installed"
    blob = cartridge(*app)
    release = app_home(localized) / "releases" / package.digest(blob)
    assert (release / "files/assets/unicode.txt").read_bytes() == contents
    assert_layout(localized, *app)


@pytest.mark.parametrize(
    "change",
    [
        {"requires": ["portable-agents/1", "owned-files/1", "local-docker/2"]},
        {"permissions": ["docker-admin"]},
        {"profiles": ["unknown/1"]},
        {
            "requires": [
                "portable-agents/1",
                "owned-files/1",
                "local-docker/1",
                "unknown/1",
            ]
        },
        {"providers": {"mode": "host", "spend_limit": 1, "egress_allowlist": None}},
    ],
)
def test_unsupported_requirements_refuse_before_device_or_writes(
    app, host, monkeypatch, change
):
    app[0].update(change)
    monkeypatch.setattr(
        package,
        "preflight_device",
        lambda *a, **kw: pytest.fail("unsupported package reached device preflight"),
    )
    with pytest.raises(package.PackageError, match="E_UNSUPPORTED_REQUIREMENT"):
        install(app, host)
    assert not (host / ".brainstem_data").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract", "scotty-revision-loader/2"),
        ("entrypoint", "singleton/another_agent.py"),
        ("descriptor", "singleton/else.json"),
        ("support", "singleton/scotty_support_latest/"),
    ],
)
def test_closed_loader_contract(app, field, value):
    app[0]["local_docker"]["loader"][field] = value
    with pytest.raises(package.PackageError, match="E_LOADER_CONTRACT"):
        package.verify_closure(*app)


def test_nested_descriptor_and_lock_are_verified_not_just_outer_file_hashes(app):
    m, files = app
    descriptor = json.loads(files["singleton/scotty_revision.json"])
    descriptor["entrypoint_sha256"] = "0" * 64
    files["singleton/scotty_revision.json"] = package.canonical_json(descriptor)
    repin(m, files)
    with pytest.raises(package.PackageError, match="E_LOADER_BINDING"):
        package.verify_closure(m, files)


def test_unknown_support_files_are_refused_even_when_outer_package_is_repinned(app):
    m, files = app
    files[m["local_docker"]["loader"]["support"] + "/unlisted.py"] = (
        b"raise AssertionError('must not execute')"
    )
    repin(m, files)
    with pytest.raises(package.PackageError, match="E_LOADER_CLOSURE"):
        package.verify_closure(m, files)


@pytest.mark.parametrize("failed", ["python", "git", "docker", "compose", "buildx"])
def test_explicit_device_preflight_failure_has_no_application_writes(
    app, host, monkeypatch, failed
):
    if failed == "python":
        monkeypatch.setattr(package.sys, "version_info", (3, 10, 14))
    elif failed in ("git", "docker"):
        monkeypatch.setattr(
            package.shutil,
            "which",
            lambda name: None if name == failed else "/fixture/" + name,
        )
    else:

        def run(argv, **kwargs):
            return SimpleNamespace(
                returncode=1 if failed in argv else 0, stdout=b"version\n"
            )

        monkeypatch.setattr(package.subprocess, "run", run)
    with pytest.raises(
        package.PackageError, match="E_(PYTHON_UPGRADE|DOCKER|GIT)_REQUIRED"
    ):
        install(app, host)
    assert not (host / ".brainstem_data").exists()


def test_docker_preflight_only_calls_harmless_version_commands(app, host, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs["timeout"] <= 15
        return SimpleNamespace(returncode=0, stdout=b"v2.40.3\n")

    monkeypatch.setattr(package.subprocess, "run", run)
    install(app, host)
    assert calls == [
        ["/fixture/docker", "--version"],
        ["/fixture/docker", "compose", "version", "--short"],
        ["/fixture/docker", "buildx", "version"],
    ]


def test_simple_application_has_no_docker_requirement(host, monkeypatch):
    files = {"singleton/scotty_agent.py": AGENT}
    manifest = simple_manifest(files)
    monkeypatch.setattr(
        package.shutil, "which", lambda name: pytest.fail("simple app probed Docker")
    )
    monkeypatch.setattr(
        package.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("simple app ran a process"),
    )
    assert install((manifest, files), host)["status"] == "installed"
    assert install((manifest, files), host)["status"] == "already_installed"


def test_immutable_artifacts_and_deterministic_hatcher(app, tmp_path):
    manifest, _ = app
    blob = cartridge(*app)
    first, second = render_hatcher(blob), render_hatcher(blob)
    assert first == second
    names = artifact_names(manifest, blob, first)
    assert write_artifacts(tmp_path, manifest, blob) == names
    before = source_tree(tmp_path)
    assert write_artifacts(tmp_path, manifest, blob) == names
    assert source_tree(tmp_path) == before
    assert package.digest(first) in names[1] and package.digest(blob) in names[0]


def test_success_retires_only_the_exact_owned_hatcher(app, host):
    source = render_hatcher(cartridge(*app))
    path = host / "agents/dock_fixture_hatcher_agent.py"
    path.write_bytes(source)
    other = host / "agents/unrelated_hatcher_agent.py"
    other.write_text("# unrelated installer; never remove\n")
    result = install(
        app, host, retire_hatcher={"name": path.name, "sha256": package.digest(source)}
    )
    assert result["retired_hatcher"] == path.name
    assert not path.exists() and other.exists()
    retained = app_home(host) / "installers" / (package.digest(source) + ".py")
    assert retained.read_bytes() == source


def test_changed_hatcher_is_never_removed_or_used_as_force_bypass(app, host):
    path = host / "agents/dock_fixture_hatcher_agent.py"
    path.write_text("owner-modified installer")
    with pytest.raises(package.PackageError, match="E_HATCHER"):
        install(app, host, retire_hatcher={"name": path.name, "sha256": "0" * 64})
    assert path.read_text() == "owner-modified installer"
    assert not (host / ".brainstem_data").exists()


def test_retired_hatcher_and_receipt_interruption_recover_together(
    app, host, monkeypatch
):
    source = render_hatcher(cartridge(*app))
    path = host / "agents/dock_fixture_hatcher_agent.py"
    path.write_bytes(source)
    retirement = {"name": path.name, "sha256": package.digest(source)}
    original = package._rename_new
    interrupted = False

    def fail(source, target):
        nonlocal interrupted
        if Path(target).name == "installed.json" and not interrupted:
            interrupted = True
            raise OSError("synthetic receipt interruption")
        return original(source, target)

    monkeypatch.setattr(package, "_rename_new", fail)
    with pytest.raises(OSError, match="receipt interruption"):
        install(app, host, retire_hatcher=retirement)
    assert not path.exists()
    assert not (app_home(host) / "installed.json").exists()
    assert (app_home(host) / "pending.json").exists()
    assert install(app, host, retire_hatcher=retirement)["status"] == "installed"
    assert not (app_home(host) / "pending.json").exists()
    assert not path.exists()


def test_install_and_validation_never_execute_application_import_code(
    app, host, tmp_path
):
    manifest, files = app
    sentinel = tmp_path / "application-import-must-not-run"
    source = f"open({str(sentinel)!r}, 'w').write('unexpected')\n".encode() + AGENT
    files["singleton/scotty_agent.py"] = source
    descriptor = json.loads(files["singleton/scotty_revision.json"])
    descriptor["entrypoint_sha256"] = package.digest(source)
    files["singleton/scotty_revision.json"] = package.canonical_json(descriptor)
    repin(manifest, files)
    package.verify_closure(manifest, files)
    assert not sentinel.exists()
    assert install(app, host)["status"] == "installed"
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "source",
    [
        b"",
        AGENT.replace(b"from agents.basic_agent import BasicAgent", b""),
        AGENT.replace(b"__manifest__ = {", b"not_a_manifest = {"),
        AGENT.replace(b"def perform(self, **kwargs):", b"def other(self, **kwargs):"),
        AGENT.replace(
            b"def perform(self, **kwargs):", b"async def perform(self, **kwargs):"
        ),
        AGENT + b"\nclass DuplicateAgent(ScottyAgent):\n    pass\n",
        AGENT
        + b"\nclass HiddenSecondTool:\n    def perform(self, **kwargs):\n        return 'wrong'\n",
        AGENT + b"\n#" + b"x" * package.MAX_SUPPORT_FILE_BYTES,
        AGENT
        + b"".join(
            f"\nclass _Internal{number}:\n    pass\n".encode() for number in range(256)
        ),
    ],
)
def test_nonportable_or_duplicate_entrypoints_refuse_before_device_effects(
    app, host, monkeypatch, source
):
    manifest, files = app
    files["singleton/scotty_agent.py"] = source
    descriptor = json.loads(files["singleton/scotty_revision.json"])
    descriptor["entrypoint_sha256"] = package.digest(source)
    files["singleton/scotty_revision.json"] = package.canonical_json(descriptor)
    repin(manifest, files)
    monkeypatch.setattr(
        package,
        "preflight_device",
        lambda *a, **kw: pytest.fail("nonportable entrypoint reached device preflight"),
    )
    with pytest.raises(package.PackageError, match="E_AGENT"):
        install(app, host)
    assert not (host / ".brainstem_data").exists()


def change_document(app, name, transform):
    value = json.loads(app[1][name])
    transform(value)
    app[1][name] = package.canonical_json(value)
    if name == app[0]["local_docker"]["component_lock"]:
        rebind_support(app, {"deploy/local/components.lock.json": app[1][name]})
    repin(*app)


def rebind_support(app, changed):
    manifest, files = app
    loader = manifest["local_docker"]["loader"]
    prefix = loader["support"] + "/"
    support = {
        name[len(prefix) :]: contents
        for name, contents in files.items()
        if name.startswith(prefix) and name != prefix + "SCOTTY_CAPABILITY_LOCK.json"
    }
    for name, contents in changed.items():
        if contents is None:
            support.pop(name, None)
        else:
            support[name] = contents
    inventory = {
        "schema": "scotty-capability-files/1",
        "grail_commit": package.GRAIL["commit"],
        "files": [
            {"path": name, "bytes": len(contents), "sha256": package.digest(contents)}
            for name, contents in sorted(support.items())
        ],
    }
    lock = package.canonical_json(inventory)
    revision = package.digest(lock)
    new_prefix = "singleton/scotty_support_" + revision + "/"
    updated = {
        name: contents
        for name, contents in files.items()
        if not name.startswith(prefix)
    }
    updated.update({new_prefix + name: contents for name, contents in support.items()})
    updated[new_prefix + "SCOTTY_CAPABILITY_LOCK.json"] = lock
    descriptor = json.loads(updated[loader["descriptor"]])
    descriptor["support_sha256"] = revision
    updated[loader["descriptor"]] = package.canonical_json(descriptor)
    loader["support"] = new_prefix.rstrip("/")
    files.clear()
    files.update(updated)
    repin(manifest, files)


def dockerfile_component(app):
    base = "python@sha256:" + "0" * 64
    content = ("FROM " + base + "\nRUN true\n").encode()
    path = "deploy/local/fixture/Dockerfile"
    rebind_support(app, {path: content})

    def change(value):
        value["components"]["scrapling"].update(
            kind="dockerfile",
            reference=None,
            observed_image_ids=["sha256:" + "1" * 64],
            recipe={
                "files": [
                    {
                        "path": path,
                        "target": "Dockerfile",
                        "bytes": len(content),
                        "sha256": package.digest(content),
                    }
                ],
                "bases": [base],
                "artifacts": [],
            },
        )

    change_document(app, "components.lock.json", change)
    return path, content


def test_native_lock_uses_scoped_files_not_outer_lookalikes(app):
    path, content = dockerfile_component(app)
    package.verify_closure(*app)
    app[1][path] = content
    rebind_support(app, {path: None})
    with pytest.raises(package.PackageError, match="E_COMPONENTS"):
        package.verify_closure(*app)


def test_native_outer_lock_must_equal_actual_runtime_lock(app):
    value = json.loads(app[1]["components.lock.json"])
    value["components"]["scrapling"]["source"] = "changed outer description"
    app[1]["components.lock.json"] = package.canonical_json(value)
    repin(*app)
    with pytest.raises(
        package.PackageError, match="outer component declaration differs"
    ):
        package.verify_closure(*app)


@pytest.mark.parametrize(
    "mutation", ["digest", "missing", "float-bytes", "base", "add", "duplicate-target"]
)
def test_native_recipe_closes_file_and_base_inputs(app, mutation):
    path, content = dockerfile_component(app)

    def change(value):
        recipe = value["components"]["scrapling"]["recipe"]
        if mutation == "digest":
            recipe["files"][0]["sha256"] = "f" * 64
        elif mutation == "missing":
            recipe["files"][0]["path"] = "missing/Dockerfile"
        elif mutation == "float-bytes":
            recipe["files"][0]["bytes"] = float(recipe["files"][0]["bytes"])
        elif mutation == "base":
            recipe["bases"] = ["python:latest"]
        elif mutation == "duplicate-target":
            recipe["files"].append(dict(recipe["files"][0]))
        else:
            altered = content + b"ADD https://example.invalid/unlocked /app\n"
            rebind_support(app, {path: altered})
            recipe["files"][0].update(
                bytes=len(altered), sha256=package.digest(altered)
            )

    change_document(app, "components.lock.json", change)
    with pytest.raises(package.PackageError, match="E_COMPONENTS"):
        package.verify_closure(*app)


@pytest.mark.parametrize("kind", ["wheels", "npm"])
def test_native_dependency_lengths_may_be_absent_but_digest_is_required(kind):
    if kind == "wheels":
        row = {
            "filename": "fixture.whl",
            "package": "fixture",
            "version": "1.0",
            "url": "https://files.pythonhosted.org/fixture.whl",
            "sha256": "0" * 64,
        }
    else:
        row = {
            "package_path": "node_modules/fixture",
            "version": "1.0",
            "url": "https://registry.npmjs.org/fixture/-/fixture.tgz",
            "sha512_hex": "0" * 128,
            "integrity": "sha512-" + base64.b64encode(bytes(64)).decode(),
        }
    package._native_dependencies(package.canonical_json({"artifacts": [row]}), kind)
    row["requires"] = ["unqualified-fetcher"]
    with pytest.raises(package.PackageError, match="E_UNSUPPORTED_REQUIREMENT"):
        package._native_dependencies(package.canonical_json({"artifacts": [row]}), kind)


def test_real_public_native_component_lock_is_inertly_verifiable():
    value = os.environ.get("RAPP_DOCK_PUBLIC_TEMPLATE_ROOT")
    if not value:
        pytest.skip("set RAPP_DOCK_PUBLIC_TEMPLATE_ROOT to the public-only T artifact")
    root = Path(value)
    files = package.application_files(root)
    layout = package._json(files["generated/source-layout.json"])
    prefix = layout["loader"]["support"].rstrip("/") + "/"
    assert (
        files["components.lock.json"]
        == files[prefix + "deploy/local/components.lock.json"]
    )
    package._component_lock(package._json(files["components.lock.json"]), files, prefix)


@pytest.mark.parametrize(
    "document,change",
    [
        (
            "components.lock.json",
            lambda value: value.update(requires=["unqualified-runtime/1"]),
        ),
        ("components.lock.json", lambda value: value.update(mode="mutable")),
        (
            "components.lock.json",
            lambda value: value["components"]["scrapling"].update(kind="unqualified"),
        ),
        (
            "components.lock.json",
            lambda value: value["components"]["scrapling"].update(env="DOCKER_HOST"),
        ),
        (
            "components.lock.json",
            lambda value: value["components"]["scrapling"].update(
                reference="private.invalid/app@sha256:" + "0" * 64
            ),
        ),
        (
            "components.lock.json",
            lambda value: value["profile"].update(docker_context="remote"),
        ),
        (
            "components.lock.json",
            lambda value: value["artifacts"].update(
                bad={
                    "url": "https://127.0.0.1/source",
                    "sha256": "0" * 64,
                    "bytes": 1,
                    "license": "synthetic",
                }
            ),
        ),
        (
            "components.lock.json",
            lambda value: value["profile"].update(required_authority="unsupported"),
        ),
        (
            "components.lock.json",
            lambda value: value["components"]["scrapling"].update(
                reference="fixture:latest"
            ),
        ),
        (
            "components.lock.json",
            lambda value: value["components"]["scrapling"].update(reference=None),
        ),
        (
            "components.lock.json",
            lambda value: value["components"]["scrapling"].update(
                recipe={"unlocked": "Dockerfile"}
            ),
        ),
        (
            "components.lock.json",
            lambda value: value["applications"]["scrapling"].update(
                scrapling="missing"
            ),
        ),
        (
            "components.lock.json",
            lambda value: value["components"].update(
                other=copy.deepcopy(value["components"]["scrapling"])
            ),
        ),
        (
            "components.lock.json",
            lambda value: value["components"]["scrapling"].update(license={}),
        ),
        (
            "generated/host-profiles.json",
            lambda value: value.update(python_minimum="3.10"),
        ),
        (
            "generated/host-profiles.json",
            lambda value: value["grail"].update(commit="main"),
        ),
        (
            "generated/host-profiles.json",
            lambda value: value["tools"].update(local_daemon_only=False),
        ),
        ("generated/host-profiles.json", lambda value: value["tools"].update(git=1)),
        (
            "generated/host-profiles.json",
            lambda value: value["authentication"].update(export_credentials=True),
        ),
        (
            "generated/host-profiles.json",
            lambda value: value["profiles"][0].update(host_arch="x86_64"),
        ),
        (
            "generated/host-profiles.json",
            lambda value: value["profiles"][0]["reference_resources"].update(
                is_minimum=True
            ),
        ),
        (
            "generated/host-profiles.json",
            lambda value: value["profiles"].append(copy.deepcopy(value["profiles"][0])),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0].update(providers=["paid-provider"]),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0].update(providers=["copilot"]),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0].update(application="dify"),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0]["input_schema"].update(
                additionalProperties=True
            ),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0]["input_schema"].update(required=["missing"]),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0]["input_schema"].update(
                requires=["hidden-runtime/1"]
            ),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"].append(copy.deepcopy(value["jobs"][0])),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0]["outputs"][0].update(required="yes"),
        ),
        (
            "generated/state-lifecycle.json",
            lambda value: value.update(credential_export=True),
        ),
        (
            "generated/state-lifecycle.json",
            lambda value: value.update(destructive_operations=["docker-volume-rm"]),
        ),
        (
            "generated/state-lifecycle.json",
            lambda value: value.update(uninstall="remove-all"),
        ),
        (
            "generated/state-lifecycle.json",
            lambda value: value.update(owned_roots=["../outside"]),
        ),
        (
            "generated/state-lifecycle.json",
            lambda value: value["retention"].update(dify="volume-backed"),
        ),
        (
            "candidate-specific-sanitized-evidence.json",
            lambda value: value.update(observed_at="synthetic false timestamp"),
        ),
        (
            "candidate-specific-sanitized-evidence.json",
            lambda value: value.update(candidate_digest="0" * 64),
        ),
        (
            "candidate-specific-sanitized-evidence.json",
            lambda value: value.update(
                results=[
                    {
                        "job": "scrapling.fixture",
                        "mode": "wrong-mode",
                        "status": "pending",
                    }
                ]
            ),
        ),
        (
            "candidate-specific-sanitized-evidence.json",
            lambda value: value.update(
                results=[
                    {
                        "job": "scrapling.fixture",
                        "mode": "synthetic-only",
                        "status": "passed",
                    }
                ]
            ),
        ),
    ],
)
def test_referenced_requirements_are_closed_and_typechecked(
    app, host, monkeypatch, document, change
):
    change_document(app, document, change)
    monkeypatch.setattr(
        package,
        "preflight_device",
        lambda *a, **kw: pytest.fail("invalid declaration reached device effects"),
    )
    with pytest.raises(package.PackageError):
        install(app, host)
    assert not (host / ".brainstem_data").exists()


@pytest.mark.parametrize(
    "parameter",
    [
        {"type": "array", "default": []},
        {"type": "object", "properties": {}, "required": [], "default": {}},
        {"type": "integer", "default": True},
        {"type": "string", "maxLength": 2, "default": "too-long"},
        {"type": "array", "items": {"type": "integer"}, "default": [1, "wrong"]},
        {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
            "default": {"extra": 1},
        },
    ],
)
def test_nested_job_parameters_do_not_hide_unsupported_or_unbounded_defaults(
    app, parameter
):
    def change(value):
        value["jobs"][0]["input_schema"]["properties"]["argument"] = parameter

    change_document(app, "generated/job-contracts.json", change)
    with pytest.raises(package.PackageError, match="E_JOBS"):
        package.verify_closure(*app)


@pytest.mark.parametrize("pattern", ["^safe$", "^(a+)+$", "["])
@pytest.mark.parametrize("with_default", [False, True])
def test_publisher_parameter_patterns_refuse_before_evaluation_or_device_effects(
    app,
    host,
    monkeypatch,
    pattern,
    with_default,
):
    parameter = {"type": "string", "pattern": pattern}
    if with_default:
        parameter["default"] = "a" * 40 + "X"

    def change(value):
        value["jobs"][0]["input_schema"]["properties"]["argument"] = parameter

    change_document(app, "generated/job-contracts.json", change)

    def forbidden(*args, **kwargs):
        raise AssertionError("publisher pattern/default or device was evaluated")

    monkeypatch.setattr(package, "_parameter_value", forbidden)
    monkeypatch.setattr(package, "preflight_device", forbidden)
    with pytest.raises(
        package.PackageError, match="E_UNSUPPORTED_REQUIREMENT:.*pattern"
    ):
        install(app, host)
    assert not (host / ".brainstem_data").exists()


def test_template_declarations_are_inspectable_but_cannot_install_or_publish_hatchers(
    app, host, tmp_path
):
    def template(value):
        value["components"]["scrapling"].update(
            kind="blocked-build",
            reference=None,
            recipe=None,
            observed_image_ids=[],
            blockers=["Synthetic authoring fixture; no public build is claimed."],
        )

    change_document(app, "components.lock.json", template)
    package.verify_closure(*app)
    package.require_supported(app[0])
    blob = cartridge(*app)
    assert render_hatcher(blob)
    with pytest.raises(package.PackageError, match="E_COMPONENTS_TEMPLATE"):
        install(app, host)
    with pytest.raises(package.PackageError, match="E_COMPONENTS_TEMPLATE"):
        write_artifacts(tmp_path / "artifacts", app[0], blob)
    assert not (host / ".brainstem_data").exists()
    assert not (tmp_path / "artifacts").exists()


def test_undeclared_host_profile_is_not_implicitly_supported(app, host, monkeypatch):
    monkeypatch.setattr(package.platform, "machine", lambda: "x86_64")
    with pytest.raises(package.PackageError, match="E_UNSUPPORTED_DEVICE"):
        install(app, host)
    assert not (host / ".brainstem_data").exists()


@pytest.mark.parametrize(
    "body",
    [
        b'{"schema":"rapp-local-components/1","schema":"other"}',
        b'{"schema":"rapp-local-components/1","mode":NaN,"components":[]}',
        b'{"schema":"rapp-local-components/1","mode":1e9999,"components":[]}',
        b"[" + b" " * (256 * 1024) + b"]",
    ],
)
def test_ambiguous_nonfinite_or_oversized_referenced_json_is_refused(app, body):
    app[1]["components.lock.json"] = body
    repin(*app)
    with pytest.raises(package.PackageError, match="E_(JSON|LOCAL_DOCKER)"):
        package.verify_closure(*app)


def test_case_collision_and_extra_support_content_cannot_be_adopted(app, host):
    (host / "agents/Scotty_agent.py").write_text("# preexisting owner source")
    with pytest.raises(package.PackageError, match="E_COLLISION"):
        install(app, host)
    (host / "agents/Scotty_agent.py").unlink()
    install(app, host)
    support = next((host / "agents").glob("scotty_support_*"))
    (support / "owner-file.txt").write_text("unowned addition")
    before = source_tree(host)
    with pytest.raises(package.PackageError, match="E_SOURCE_CONFLICT"):
        install(app, host)
    assert source_tree(host) == before


def test_exclusive_publication_refuses_a_directory_collision_at_commit(
    app, host, monkeypatch
):
    original = package._rename_new
    collision = None

    def collide(source, target):
        nonlocal collision
        if Path(target).name.startswith("scotty_support_"):
            collision = Path(target)
            collision.mkdir(mode=0o700)
            (collision / "owner-file.txt").write_text("do not replace")
        return original(source, target)

    monkeypatch.setattr(package, "_rename_new", collide)
    with pytest.raises(package.PackageError, match="E_COLLISION"):
        install(app, host)
    assert (
        collision is not None
        and (collision / "owner-file.txt").read_text() == "do not replace"
    )
    assert not (host / "agents/scotty_agent.py").exists()
    assert not (app_home(host) / "installed.json").exists()


def test_staging_nonce_collision_never_reuses_or_removes_an_unowned_directory(
    tmp_path, monkeypatch
):
    parent = tmp_path / "owned-parent"
    existing = parent / ".rapp-stage-fixed"
    existing.mkdir(mode=0o700, parents=True)
    retained = existing / "owner-file.txt"
    retained.write_text("keep")
    monkeypatch.setattr(package.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed"))
    with pytest.raises(package.PackageError, match="E_COLLISION"):
        package._stage_tree(parent, {"source.txt": b"new"})
    assert retained.read_text() == "keep"
    assert list(existing.iterdir()) == [retained]


def test_source_replacement_during_hash_check_is_retained(tmp_path, monkeypatch):
    path = tmp_path / "source.py"
    path.write_bytes(b"owned")
    original = package._read_regular

    def changed(target, **kwargs):
        result = original(target, **kwargs)
        if kwargs.get("with_stat") and Path(target) == path:
            path.unlink()
            path.write_bytes(b"unowned replacement")
        return result

    monkeypatch.setattr(package, "_read_regular", changed)
    with pytest.raises(package.PackageError, match="E_SOURCE_DRIFT"):
        package._unlink_owned(path, package.digest(b"owned"))
    assert path.read_bytes() == b"unowned replacement"


def test_concurrent_install_cannot_bypass_the_runtime_lock(app, host):
    with package._install_lock(host):
        before = source_tree(host)
        with pytest.raises(package.PackageError, match="E_INSTALL_BUSY"):
            install(app, host)
        assert source_tree(host) == before
    assert install(app, host)["status"] == "installed"


def test_process_loss_releases_lock_without_trusting_or_killing_a_pid(
    app, host, tmp_path
):
    with package._install_lock(host):
        pass
    code = (
        "import fcntl,os,sys;"
        "fd=os.open(sys.argv[1],os.O_RDWR);"
        "fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);"
        "os._exit(73)"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            str(host / ".brainstem_data/rapplication-install.lock"),
        ],
        cwd=host,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _, error = process.communicate(timeout=15)
    assert process.returncode == 73, error
    assert install(app, host)["status"] == "installed"


def test_unsupported_atomic_rename_and_unsafe_discovery_directory_fail_before_writes(
    app, host, monkeypatch
):
    with monkeypatch.context() as context:
        context.setattr(package.ctypes, "CDLL", lambda *a, **kw: SimpleNamespace())
        with pytest.raises(package.PackageError, match="E_UNSUPPORTED_DEVICE"):
            install(app, host)
        assert not (host / ".brainstem_data").exists()
    (host / "agents").chmod(0o777)
    with pytest.raises(package.PackageError, match="E_PATH"):
        install(app, host)
    assert not (host / ".brainstem_data").exists()
    (host / "agents").chmod(0o700)


def test_versions_round_trip_without_unbounded_integer_conversion(app, host):
    app[0]["version"] = "9" * 5000 + ".0.0"
    assert install(app, host)["status"] == "installed"
    assert install(app, host)["status"] == "already_installed"
    app[0]["version"] = "1.0.0"
    with pytest.raises(package.PackageError, match="E_ROLLBACK_REFUSED"):
        install(app, host)


def test_oversized_receipt_refuses_before_application_writes(app, host):
    app[0]["state"]["version"] = "x" * package.MAX_RECORD_BYTES
    with pytest.raises(package.PackageError, match="E_PACKAGE_SIZE"):
        install(app, host)
    assert not (host / ".brainstem_data").exists()


def test_git_hosts_verify_additional_tracked_runtime_bytes_not_only_head(
    tmp_path, monkeypatch
):
    top = tmp_path / "synthetic-git-checkout"
    root = top / "rapp_brainstem"
    root.mkdir(parents=True)
    (top / ".git").write_text("synthetic marker for the mocked local Git responses")
    (root / "brainstem.py").write_bytes(b"synthetic kernel fixture")
    monkeypatch.setattr(
        package,
        "GRAIL_FILES",
        {
            "brainstem.py": package.digest(b"synthetic kernel fixture"),
        },
    )
    (root / "start.sh").write_bytes(b"changed launch script")
    original = b"stock launch script"
    expected = package.hashlib.sha1(
        b"blob " + str(len(original)).encode() + b"\0" + original
    ).hexdigest()

    def git(argv, **kwargs):
        assert "--no-replace-objects" in argv
        if "ls-tree" in argv:
            return SimpleNamespace(
                stdout=b"100644 blob "
                + expected.encode()
                + b"\trapp_brainstem/start.sh\0"
            )
        return SimpleNamespace(
            stdout=package.GRAIL["commit"] if argv[-1] == "HEAD" else str(top)
        )

    monkeypatch.setattr(package.subprocess, "run", git)
    with pytest.raises(package.PackageError, match="tracked runtime bytes differ"):
        package.verify_grail(root)
    (root / "start.sh").write_bytes(original)
    assert package.verify_grail(root) == root


def test_source_collection_preserves_nested_versions_instead_of_silently_dropping_them(
    tmp_path,
):
    files = {
        "singleton/scotty_agent.py": AGENT,
        "source/versions/schema.json": b'{"synthetic":true}\n',
        "source/eggs/format.txt": b"runtime source, not a root historical archive\n",
    }
    manifest = simple_manifest(files)
    source = tmp_path / "source"
    for name, contents in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    (source / "manifest.json").write_bytes(package.canonical_json(manifest))
    (source / "versions").mkdir()
    (source / "versions/historical.txt").write_text("retained separately")
    blob = package.build_package(source)
    assert package.read_package(blob, package.digest(blob)) == (manifest, files)


def test_unowned_scotty_bytecode_is_refused_not_deleted(app, host):
    cache = host / "agents/__pycache__"
    cache.mkdir()
    old = cache / "scotty_agent.cpython-fixture.pyc"
    old.write_bytes(b"synthetic unknown cache; not executable bytecode")
    with pytest.raises(package.PackageError, match="E_AGENT_CONFLICT"):
        install(app, host)
    assert old.read_bytes() == b"synthetic unknown cache; not executable bytecode"
    assert not (host / ".brainstem_data").exists()


def test_same_loader_contract_cannot_change_stable_bootstrap_after_detachment(
    app, host, monkeypatch
):
    install(app, host)
    monkeypatch.setattr(package, "_stop_local_docker", stopped_fixture)
    assert uninstall(app, host)["status"] == "detached"
    manifest, files = app
    manifest["version"] = "1.1.0"
    files["singleton/scotty_agent.py"] += b"\n"
    descriptor = json.loads(files["singleton/scotty_revision.json"])
    descriptor["entrypoint_sha256"] = package.digest(files["singleton/scotty_agent.py"])
    files["singleton/scotty_revision.json"] = package.canonical_json(descriptor)
    repin(manifest, files)
    with pytest.raises(package.PackageError, match="E_LOADER_CONTRACT"):
        install(app, host)
    assert not (host / "agents/scotty_agent.py").exists()


def test_python_and_integrating_browser_agree_on_closed_local_declarations(
    app, tmp_path
):
    contract_root = os.environ.get("RAPP_STORE_CONTRACT_ROOT")
    if not contract_root:
        pytest.skip(
            "set RAPP_STORE_CONTRACT_ROOT to the integrating Store contract checkout"
        )
    contract_root = str(Path(contract_root).resolve())
    cases = []
    mutations = [
        None,
        (
            "generated/host-profiles.json",
            lambda value: value.update(python_minimum="3.10"),
        ),
        (
            "generated/host-profiles.json",
            lambda value: value["profiles"][0].update(host_arch="x86_64"),
        ),
        (
            "components.lock.json",
            lambda value: value["components"]["scrapling"].update(reference=None),
        ),
        (
            "components.lock.json",
            lambda value: value["applications"]["scrapling"].update(
                scrapling="missing"
            ),
        ),
        (
            "components.lock.json",
            lambda value: value["artifacts"].update(
                bad={
                    "url": "https://127.0.0.1/source",
                    "sha256": "0" * 64,
                    "bytes": 1,
                    "license": "synthetic",
                }
            ),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0]["input_schema"].update(
                additionalProperties=True
            ),
        ),
        (
            "generated/job-contracts.json",
            lambda value: value["jobs"][0].update(providers=["paid-provider"]),
        ),
        (
            "generated/state-lifecycle.json",
            lambda value: value.update(credential_export=True),
        ),
        (
            "generated/state-lifecycle.json",
            lambda value: value["retention"].update(dify="volume-backed"),
        ),
        (
            "candidate-specific-sanitized-evidence.json",
            lambda value: value.update(observed_at="synthetic false timestamp"),
        ),
    ]
    expected = []
    for mutation in mutations:
        candidate = copy.deepcopy(app)
        if mutation is not None:
            change_document(candidate, *mutation)
        manifest, files = candidate
        try:
            package.require_supported(manifest)
            package.verify_closure(manifest, files)
            expected.append(True)
        except package.PackageError:
            expected.append(False)
        cases.append(
            {
                "manifest": manifest,
                "files": {
                    name: base64.b64encode(contents).decode()
                    for name, contents in files.items()
                },
            }
        )
    code = """
const fs = require('node:fs');
globalThis.crypto = require('node:crypto').webcrypto;
const contract = require(require('node:path').resolve(process.argv[1], 'store-contract.js'));
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
(async () => {
  await contract.ready();
  const answers = [];
  for (const item of cases) {
    const files = Object.fromEntries(Object.entries(item.files).map(([name, data]) =>
      [name, new Uint8Array(Buffer.from(data, 'base64'))]));
    const errors = await contract.validateFiles(item.manifest, name => files[name], Object.keys(files));
    answers.push({accepted: errors.length === 0, errors});
  }
  console.log(JSON.stringify(answers));
})().catch(error => { console.error(error); process.exit(1); });
"""
    result = subprocess.run(
        ["node", "-e", code, contract_root],
        input=json.dumps(cases),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    answers = json.loads(result.stdout)
    assert [row["accepted"] for row in answers] == expected, answers


def stopped_fixture(*args, **kwargs):
    if args:
        root, home, manifest = args[:3]
        binding = json.loads((home / "installed.json").read_text())[
            "local_docker_binding"
        ]
        package._fences()[(str(root), manifest["publisher"], manifest["id"])] = {
            "home": Path(binding["home"]),
            "binding": binding,
            "resume": lambda: {
                "schema": "rapp-dock-installation-fence/1",
                "target": package._binding_target(binding),
                "status": "reactivated",
                "durable": False,
                "admission_paused": False,
            },
        }
    return {
        "schema": "rapp-preserving-stop/1",
        "stopped": True,
        "drained": True,
        "admission_paused": True,
        "data_deleted": False,
        "retained": list(package.RETAINED),
        "operation_id": "synthetic-stop",
    }


def test_real_controller_preserves_targeted_durable_detach_and_reactivation(
    host, monkeypatch
):
    public_root = os.environ.get("RAPP_DOCK_PUBLIC_TEMPLATE_ROOT")
    controller_root = os.environ.get("RAPP_DOCK_CONTROLLER_TEST_ROOT")
    if not public_root or not controller_root:
        pytest.skip(
            "set public-template and controller-test roots for real controller qualification"
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("real controller fixture attempted an external effect")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    public_files = package.application_files(Path(public_root))
    layout = package._json(public_files["generated/source-layout.json"])
    source_prefix = layout["loader"]["support"].rstrip("/") + "/"
    support = {
        name[len(source_prefix) :]: contents
        for name, contents in public_files.items()
        if name.startswith(source_prefix)
        and name != source_prefix + "SCOTTY_CAPABILITY_LOCK.json"
    }
    for name in ("local_dock.py", "scotty_contract.py"):
        support[name] = (Path(controller_root) / name).read_bytes()
    support["agents/scotty_agent.py"] = b"from local_dock import LocalDock\n" + AGENT
    candidate = local_application(real_bootstrap_fixture())
    candidate[1]["components.lock.json"] = public_files["components.lock.json"]
    rebind_support(candidate, support)
    monkeypatch.setenv("RAPP_DOCK_DOCKER", "/fixture/never-executed-docker")
    result = install(candidate, host)
    assert result["status"] == "installed" and result["runtime_resume"] == "not-needed"
    home = app_home(host)
    receipt = package._receipt(home / "installed.json")
    binding = receipt["local_docker_binding"]
    blob = cartridge(*candidate)
    sha = package.digest(blob)
    bootstrap = home / "releases" / sha / "files" / candidate[0]["agent"]
    module = ModuleType("s2_real_controller_installed_fixture")
    module.__file__, module.__package__ = str(bootstrap), ""
    exec(  # noqa: S102 - verified fixture bootstrap, with all external effects denied.
        compile(candidate[1][candidate[0]["agent"]], str(bootstrap), "exec"),
        module.__dict__,
    )
    controller_type = module._entry().LocalDock
    controller = sys.modules[controller_type.__module__]
    assert Path(controller.__file__).read_bytes() == support["local_dock.py"]
    calls = []
    running = {"value": True}
    container_id = "a" * 64
    project = binding["namespace"] + "-scrapling"

    def fake_docker(args, **kwargs):
        calls.append(list(args))
        if args[:2] == ["--context", "desktop-linux"]:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    "unix://" + binding["owner_home"] + "/fixture.sock"
                ).encode(),
                b"",
            )
        assert args[:2] == [
            "--host",
            "unix://" + binding["owner_home"] + "/fixture.sock",
        ]
        selected = args[2:]
        if selected[0] == "ps":
            query = selected[selected.index("--filter") + 1]
            rows = []
            if query == "label=com.docker.compose.project" or query.endswith(
                "=" + project
            ):
                rows.append(
                    {
                        "ID": container_id,
                        "State": "running" if running["value"] else "exited",
                        "Status": "running" if running["value"] else "Exited (0)",
                        "Labels": {
                            "com.docker.compose.project": project,
                            "com.docker.compose.service": "scrapling",
                        },
                    }
                )
            if query == "label=com.docker.compose.project":
                rows.append(
                    {
                        "ID": "b" * 64,
                        "State": "running",
                        "Status": "running",
                        "Labels": {
                            "com.docker.compose.project": "rapp-dock-tg-scrapling",
                            "com.docker.compose.service": "scrapling",
                        },
                    }
                )
            return subprocess.CompletedProcess(args, 0, json.dumps(rows).encode(), b"")
        if selected[0] == "stop":
            assert selected == ["stop", "--time", "30", container_id]
            running["value"] = False
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if selected[:2] == ["network", "ls"]:
            return subprocess.CompletedProcess(args, 0, b"[]", b"")
        if selected[:2] == ["network", "inspect"] or selected[0] == "inspect":
            return subprocess.CompletedProcess(args, 1, b"", b"synthetic not found")
        raise AssertionError("Unexpected fake Docker operation: " + repr(selected))

    monkeypatch.setattr(
        controller, "docker_cli", lambda override=None: "/fixture/never-executed-docker"
    )
    monkeypatch.setattr(controller, "run_docker", fake_docker)
    dock = controller_type.for_installation(
        home=Path(binding["home"]),
        namespace=binding["namespace"],
        port_base=binding["port_base"],
    )
    other_home = host.parent / "unrelated-controller-home"
    other = controller_type.for_installation(
        home=other_home, namespace="rapp-dock-tg", port_base=18600
    )
    other.pause_for_detach()
    other.quiesce(timeout=0)
    sentinel = Path(binding["home"]) / "owned-output.bin"
    sentinel.write_bytes(b"synthetic owner output")
    detached = uninstall(candidate, host)
    assert detached["status"] == "detached", detached
    assert not running["value"] and any(call[2:3] == ["stop"] for call in calls)
    assert dock.detach_status()["durable"] and dock.detach_status()["quiesced"]
    assert other.detach_status()["durable"] and other.runtime.quiescing
    assert sentinel.read_bytes() == b"synthetic owner output"
    assert not (host / "agents/scotty_agent.py").exists()
    # Lose the installer-only in-memory fence: reactivation must use its durable
    # transaction intent and exact verified receipt, not a global resume.
    package._fences().pop(
        (str(host), candidate[0]["publisher"], candidate[0]["id"]), None
    )
    before = len(calls)
    reinstalled = install(candidate, host)
    assert reinstalled["runtime_resume"] == "resumed-after-preserving-reinstall", (
        reinstalled
    )
    assert len(calls) == before
    assert dock.detach_status()["durable"] is False
    assert other.detach_status()["durable"] and other.runtime.quiescing
    assert sentinel.read_bytes() == b"synthetic owner output"
    assert not any(
        "--volumes" in call or "prune" in call or call[2:4] == ["volume", "rm"]
        for call in calls
    )
    dock.quiesce(timeout=2)


def uninstall(app, host):
    blob = cartridge(*app)
    return package.uninstall_package(blob, package.digest(blob), host)


def test_preserving_detach_and_reinstall_keep_state_receipts_and_unrelated_sources(
    app, host, monkeypatch
):
    m, files = app
    files["seeds/settings.json"] = b'{"synthetic":"initial"}\n'
    m["state"]["seeds"] = {"settings.json": "seeds/settings.json"}
    repin(m, files)
    install(app, host)
    data = app_home(host) / "state/settings.json"
    data.write_text('{"owner":"changed"}')
    history = app_home(host) / "state/operation-receipt.json"
    history.write_text('{"synthetic":"preserved"}')
    unrelated = host / "agents/another_agent.py"
    unrelated.write_text("# unrelated source\n")
    preserve = {path: path.read_bytes() for path in (data, history, unrelated)}
    release = next((app_home(host) / "releases").iterdir())
    release_before = source_tree(release)
    monkeypatch.setattr(package, "_stop_local_docker", stopped_fixture)
    result = uninstall(app, host)
    assert result["status"] == "detached" and result["data_deleted"] is False
    assert result["retained"] == package.RETAINED
    assert not (host / "agents/scotty_agent.py").exists()
    assert not list((host / "agents").glob("scotty_support_*"))
    assert source_tree(release) == release_before
    assert {path: path.read_bytes() for path in preserve} == preserve
    assert uninstall(app, host)["status"] == "already_detached"
    assert install(app, host)["status"] == "installed"
    assert_layout(host, m, files)
    assert {path: path.read_bytes() for path in preserve} == preserve
    assert source_tree(release) == release_before


@pytest.mark.parametrize(
    "failure", ["exception", "partial", "no-drain", "deleted-data"]
)
def test_failed_stop_retains_all_sources_and_reports_partial_failure(
    app, host, monkeypatch, failure
):
    install(app, host)
    original = source_tree(host / "agents")

    def fail(*args, **kwargs):
        if failure == "exception":
            raise package.PackageError("E_DRAIN_STOP: synthetic stop failure")
        result = stopped_fixture()
        result[
            {
                "partial": "stopped",
                "no-drain": "drained",
                "deleted-data": "data_deleted",
            }[failure]
        ] = failure == "deleted-data"
        return result

    monkeypatch.setattr(package, "_stop_local_docker", fail)
    result = uninstall(app, host)
    assert result["status"] == "retained" and result["detached"] is False
    assert result["source_removed"] == [] and result["retained"] == package.RETAINED
    assert source_tree(host / "agents") == original
    assert (
        json.loads((app_home(host) / "installed.json").read_text())["status"]
        == "installed"
    )
    monkeypatch.setattr(package, "_stop_local_docker", stopped_fixture)
    assert uninstall(app, host)["status"] == "detached"


@pytest.mark.parametrize("failure_after", [0, 1, 2, 3])
def test_interrupted_detach_recovers_without_removing_state(
    app, host, monkeypatch, failure_after
):
    install(app, host)
    data = app_home(host) / "state/owner.bin"
    data.parent.mkdir(exist_ok=True)
    data.write_bytes(b"owner state remains byte-identical")
    monkeypatch.setattr(package, "_stop_local_docker", stopped_fixture)
    original = package._unlink_owned
    counter = 0

    def interrupt(path, sha):
        nonlocal counter
        if host / "agents" in Path(path).parents:
            counter += 1
            if counter == failure_after + 1:
                raise OSError("synthetic detach interruption")
        return original(path, sha)

    monkeypatch.setattr(package, "_unlink_owned", interrupt)
    partial = uninstall(app, host)
    assert partial["status"] == "partial" and partial["data_deleted"] is False
    assert partial["retained"] == package.RETAINED
    assert len(partial["source_removed"]) == failure_after
    assert (
        json.loads((app_home(host) / "installed.json").read_text())["status"]
        == "installed"
    )
    assert data.read_bytes() == b"owner state remains byte-identical"
    assert uninstall(app, host)["status"] == "detached"
    assert data.read_bytes() == b"owner state remains byte-identical"
    assert install(app, host)["status"] == "installed"


def test_detach_refuses_changed_or_extra_owned_sources_before_stop(
    app, host, monkeypatch
):
    install(app, host)
    monkeypatch.setattr(
        package,
        "_stop_local_docker",
        lambda *a, **kw: pytest.fail("tampered source reached lifecycle effects"),
    )
    descriptor = host / "agents/scotty_revision.json"
    descriptor.chmod(0o600)
    descriptor.write_text("owner edited")
    before = source_tree(host)
    with pytest.raises(package.PackageError, match="E_AGENT_CONFLICT"):
        uninstall(app, host)
    assert source_tree(host) == before


def real_bootstrap_fixture():
    store_entrypoint = os.environ.get("RAPP_SCOTTY_STORE_ENTRYPOINT")
    if store_entrypoint:
        path = Path(store_entrypoint)
        if ".brainstem" in path.parts:
            pytest.fail("never use a live installed entrypoint as fixture input")
        source = package._read_regular(path)
        assert (
            package.digest(source)
            == "586627ce417774dd06cb487e012729e6cd68a988733391960cac1b44c98f878d"
        )
        package._portable_agent(ast.parse(source), path.name)
        return source
    value = os.environ.get("RAPP_SCOTTY_TEST_BOOTSTRAP")
    if not value:
        pytest.skip(
            "set RAPP_SCOTTY_TEST_BOOTSTRAP to the reviewed scotty-revision-loader/1 source"
        )
    path = Path(value)
    if ".brainstem" in path.parts:
        pytest.fail("the live Grail may never be used as a loader source")
    original = path.read_bytes()
    assert (
        package.digest(original)
        == "9f252ebae8d53dcc71f19020d04fd841d1438c58811908b4ba20fd3c97ae1d34"
    )
    tree = ast.parse(original)
    agent_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ScottyAgent"
    )
    # The real scoped bootstrap is unchanged. Only the Store-admissible delegate
    # tail is synthetic, with the same direct BasicAgent/perform admission shape.
    prefix = b"".join(original.splitlines(keepends=True)[: agent_class.lineno - 1])
    return (
        prefix
        + b"""
from agents.basic_agent import BasicAgent
__manifest__ = {
    "schema": "rapp-agent/1.0", "name": "@fixture/dock_fixture", "version": "1.0.0",
    "description": "Synthetic source-installation fixture; no deployment or real jobs.",
}
class ScottyAgent(BasicAgent):
    def __init__(self):
        self._delegate = _implementation.ScottyAgent()
        super().__init__(name=self._delegate.name, metadata=self._delegate.metadata)
    def perform(self, **kwargs):
        return self._delegate.perform(**kwargs)
    def system_context(self):
        return self._delegate.system_context()
"""
    )


def test_generated_hatcher_in_isolated_exact_grail_loads_one_scotty_and_reinstalls(
    tmp_path,
):
    reference = os.environ.get("RAPP_GRAIL_TEST_ROOT")
    if not reference:
        pytest.skip(
            "set RAPP_GRAIL_TEST_ROOT to an isolated, pinned Grail distribution"
        )
    reference = Path(reference)
    if ".brainstem" in reference.parts:
        pytest.fail("never qualify against the live Grail")
    package.verify_grail(reference)
    app = local_application(real_bootstrap_fixture(), with_controller=True)
    root = tmp_path / "exact-grail"
    root.mkdir(mode=0o700)
    for name in package.GRAIL_FILES:
        target = root / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes((reference / name).read_bytes())
        target.chmod(0o600)
    package.verify_grail(root)
    state = tmp_path / "synthetic-retained-state"
    state.mkdir(mode=0o700)
    for name in (
        "application-state.bin",
        "volume-state.bin",
        "identity.bin",
        "output.bin",
    ):
        (state / name).write_bytes(("synthetic retained fixture: " + name).encode())
    isolated_home = tmp_path / "isolated-home"
    isolated_home.mkdir(mode=0o700)
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    hatcher_name = "dock_fixture_hatcher_agent.py"
    (root / "agents" / hatcher_name).write_bytes(render_hatcher(cartridge(*app)))
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(isolated_home),
        "TMPDIR": str(scratch),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "RAPP_INSTALL_TEST_STATE": str(state),
        "RAPP_DOCK_HOME": str(state),
        "RAPP_DOCK_NAMESPACE": "rapp-dock-th",
        "S2_BOOTSTRAP_MODE": "actual-first-store-delegate-586627ce"
        if os.environ.get("RAPP_SCOTTY_STORE_ENTRYPOINT")
        else "real-loader-body-with-fixture-delegate",
    }
    docker = shutil.which("docker")
    if docker:
        plugins = Path(docker).resolve().parent.parent / "cli-plugins"
        if plugins.is_dir():
            docker_config = tmp_path / "isolated-docker-config"
            docker_config.mkdir(mode=0o700)
            (docker_config / "config.json").write_text(
                json.dumps({"cliPluginsExtraDirs": [str(plugins)]})
            )
            env["DOCKER_CONFIG"] = str(docker_config)
    result = subprocess.run(
        [
            os.environ.get("RAPP_GRAIL_TEST_PYTHON", sys.executable),
            str(FIXTURES / "grail_loader_probe.py"),
            str(root),
            hatcher_name,
            str(state),
        ],
        cwd=root,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    marker = next(
        line
        for line in result.stdout.splitlines()
        if line.startswith("STORE_GRAIL_PROOF=")
    )
    proof = json.loads(marker.split("=", 1)[1])
    assert proof["agents"] == ["Scotty"] and proof["jobs_verified"] is False
    assert (
        proof["import_effects"] is False
        and proof["preserving_detach_reinstall"] is True
    )
    assert proof["support_tamper_refused"] is True
    assert all(
        call
        in (["--version"], ["compose", "version", "--short"], ["buildx", "version"])
        for call in proof["docker_commands"]
    )
    assert proof["buildx_probe"] == "fixture-only-not-live"
    assert proof["bootstrap"] == env["S2_BOOTSTRAP_MODE"]
