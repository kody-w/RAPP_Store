"""Lossless admission of the real materializer format; all fixture content is synthetic."""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

import lib_rapp
from test_publishable_template import sample
from test_store_browser import browser, schema_validator


ROOT = Path(__file__).resolve().parent.parent


def canonical(value, *, compact=False):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":") if compact else None) + "\n").encode()


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def materializer_fixture(original, *, change_lock=None, change_dependency=None):
    manifest, originals = original
    manifest, files = copy.deepcopy(manifest), dict(originals)
    old_prefix = manifest["local_docker"]["loader"]["support"]
    support = {name[len(old_prefix):]: blob for name, blob in files.items()
               if name.startswith(old_prefix) and not name.endswith("/SCOTTY_CAPABILITY_LOCK.json")}
    for name in list(files):
        if name.startswith(old_prefix):
            files.pop(name)
    image = "busybox@sha256:" + "a" * 64
    dockerfile = ("FROM " + image + "\n").encode()
    artifact_body = b"synthetic-public-input"
    sha512 = hashlib.sha512(artifact_body).hexdigest()
    dependency = {"artifact_count": 1, "artifacts": [{
        "package_path": "node_modules/synthetic", "version": "1.0.0",
        "url": "https://registry.npmjs.org/synthetic/-/synthetic-1.0.0.tgz",
        "sha512_hex": sha512,
        "integrity": "sha512-" + base64.b64encode(bytes.fromhex(sha512)).decode(),
    }]}
    if change_dependency:
        change_dependency(dependency)
    support.update({
        "deploy/local/example/Dockerfile": dockerfile,
        "deploy/local/example/backend.Dockerfile": dockerfile,
        "deploy/local/example/dependencies.json": canonical(dependency),
    })

    def selected(path, target):
        return {"path": path, "target": target, "bytes": len(support[path]), "sha256": digest(support[path])}

    artifact = {
        "url": "https://github.com/example/synthetic/releases/download/v1.0.0/source.tar.gz",
        "sha256": digest(artifact_body), "bytes": len(artifact_body), "license": "Synthetic test-only input.",
    }
    group = {
        "source": artifact,
        "files": [
            selected("deploy/local/example/backend.Dockerfile", "qualification/Dockerfile.backend-offline"),
            selected("deploy/local/example/dependencies.json", "qualification/dependencies.json"),
        ],
        "dependencies": [{"role": "backend", "manifest": "qualification/dependencies.json",
                          "kind": "npm", "target": "tarballs"}],
    }

    def component(kind, env, reference, recipe, platform="linux/arm64"):
        return {"kind": kind, "platform": platform, "env": env, "reference": reference,
                "recipe": recipe, "observed_image_ids": [], "source": "Synthetic test source.",
                "license": "Synthetic test license.", "blockers": []}

    lock = {
        "schema": "rapp-dock-components/1",
        "profile": {
            "host": "darwin/arm64", "docker_context": "desktop-linux",
            "guest_platforms": ["linux/arm64", "linux/amd64"], "amd64_emulation_required": True,
            "assurance": "locked-public-inputs-and-local-image-observations-not-signed-builds",
            "fresh_machine_acceptance": "pending", "bit_identical_rebuilds_claimed": False,
        },
        "artifacts": {"source-1.0.0": artifact},
        "input_sets": {"public-inputs": group},
        "components": {
            "registry": component("registry", "RAPP_DOCK_IMAGE_REGISTRY", image, None),
            "builder": component("dockerfile", "RAPP_DOCK_IMAGE_BUILDER", None, {
                "files": [selected("deploy/local/example/Dockerfile", "Dockerfile")],
                "bases": [image],
                "artifacts": [{"artifact": "source-1.0.0", "member": None, "target": "source.tar.gz"}],
            }),
            "openshorts-backend": component("openshorts-offline", "RAPP_DOCK_IMAGE_OPENSHORTS_BACKEND", None, {
                "role": "backend", "input_set": "public-inputs", "input_set_sha256": digest(canonical(group, compact=True)),
                "dockerfile_sha256": digest(dockerfile), "bases": [image],
            }, "linux/amd64"),
        },
        "applications": {app: {"service": "registry"} for app in (
            "intelligence", "scrapling", "presenton", "open-seo", "dify", "openshorts",
        )},
    }
    if change_lock:
        change_lock(lock)
    lock_bytes = canonical(lock)
    files["components.lock.json"] = lock_bytes
    support["deploy/local/components.lock.json"] = lock_bytes
    inventory = canonical({
        "schema": "scotty-capability-files/1",
        "grail_commit": manifest["runtime"]["commit"],
        "files": [{"path": name, "bytes": len(blob), "sha256": digest(blob)}
                  for name, blob in sorted(support.items())],
    })
    revision = digest(inventory)
    prefix = "singleton/scotty_support_" + revision + "/"
    files.update({prefix + name: blob for name, blob in support.items()})
    files[prefix + "SCOTTY_CAPABILITY_LOCK.json"] = inventory
    files["singleton/scotty_revision.json"] = canonical({
        "schema": "scotty-agent-revision/1", "loader_contract": "scotty-revision-loader/1",
        "entrypoint_sha256": digest(files["singleton/scotty_agent.py"]), "support_sha256": revision,
    })
    files["generated/dockerfiles/openshorts-backend.Dockerfile"] = dockerfile
    manifest["local_docker"]["loader"]["support"] = prefix
    manifest["files"] = {name: digest(blob) for name, blob in files.items()}
    return manifest, files


def both_errors(manifest, files):
    js = browser({"mode": "files", "manifest": manifest,
                  "files": {name: base64.b64encode(blob).decode() for name, blob in files.items()}})["errors"]
    return lib_rapp._application_contract_errors(manifest, files), js


def test_materializer_format_and_nested_dependencies_are_admitted_losslessly(sample):
    manifest, files = materializer_fixture(sample)
    assert not list(schema_validator("application.schema.json").iter_errors(manifest))
    py, js = both_errors(manifest, files)
    assert not py, py
    assert not js, js
    assert json.loads(files["components.lock.json"])["schema"] == "rapp-dock-components/1"


@pytest.mark.parametrize("change", [
    lambda d: d.update(required_unknown_feature="privileged/1"),
    lambda d: d["components"]["registry"].update(reference="busybox:latest"),
    lambda d: d["components"]["builder"].update(env="DOCKER_HOST"),
    lambda d: d["components"]["builder"].update(env="RAPP_DOCK_IMAGE_REGISTRY"),
    lambda d: d["artifacts"]["source-1.0.0"].update(url="https://unapproved.invalid/source.tar.gz"),
    lambda d: d["components"]["builder"]["recipe"].update(bases=["busybox@sha256:" + "b" * 64]),
    lambda d: d["components"]["openshorts-backend"]["recipe"].update(input_set_sha256="c" * 64),
    lambda d: d["applications"]["dify"].update(service="not-declared"),
])
def test_materializer_unknown_or_inconsistent_requirements_refuse(sample, change):
    py, js = both_errors(*materializer_fixture(sample, change_lock=change))
    assert py and js


@pytest.mark.parametrize("change", [
    lambda d: d.update(requires=["unknown-dependency-policy/1"]),
    lambda d: d["artifacts"][0].update(integrity="sha512-" + "A" * 86 + "=="),
    lambda d: d["artifacts"][0].update(url="https://unapproved.invalid/package.tgz"),
    lambda d: d["artifacts"][0].update(unbounded_fetch=True),
    lambda d: d.update(artifact_count=99),
])
def test_nested_dependency_manifests_are_not_opaque_metadata(sample, change):
    py, js = both_errors(*materializer_fixture(sample, change_dependency=change))
    assert py and js


def test_derived_recipe_is_mandatory_and_hash_bound(sample):
    manifest, files = materializer_fixture(sample)
    name = "generated/dockerfiles/openshorts-backend.Dockerfile"
    files[name] += b"# changed synthetic recipe\n"
    manifest["files"][name] = digest(files[name])
    py, js = both_errors(manifest, files)
    assert py and js


def test_root_copy_cannot_override_the_actual_runtime_lock(sample):
    manifest, files = materializer_fixture(sample)
    root = json.loads(files["components.lock.json"])
    root["profile"]["fresh_machine_acceptance"] = "passed"
    files["components.lock.json"] = canonical(root)
    manifest["files"]["components.lock.json"] = digest(files["components.lock.json"])
    py, js = both_errors(manifest, files)
    assert py and js


def test_candidate_assembler_refuses_coordinator_directory_before_inventory(tmp_path, monkeypatch):
    import rapp_package

    path = ROOT / "samples/dock_scotty/tools/assemble_candidate.py"
    spec = importlib.util.spec_from_file_location("_candidate_assembler", path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    monkeypatch.setattr(rapp_package, "application_files", lambda _: pytest.fail("Private parent tree must not be inventoried"))
    with pytest.raises(ValueError, match="public template directory"):
        module.candidate_files(tmp_path)


def assembler_fixture(sample, tmp_path):
    manifest, files = materializer_fixture(sample)
    for name in ("README.md", manifest["local_docker"]["requirements_file"],
                 manifest["local_docker"]["jobs_file"], manifest["local_docker"]["state_lifecycle_file"],
                 manifest["local_docker"]["readiness"]["live_results"]):
        files.pop(name)
    descriptor = json.loads(files["singleton/scotty_revision.json"])
    files["generated/source-layout.json"] = canonical({
        "schema": "scotty-store-template/1", "component_lock": "components.lock.json",
        "capability_lock_sha256": descriptor["support_sha256"],
    })
    payload = tmp_path / "public-payload"
    for name, blob in files.items():
        target = payload / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    path = ROOT / "samples/dock_scotty/tools/assemble_candidate.py"
    spec = importlib.util.spec_from_file_location("_candidate_assembler_fixture", path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module, payload


def test_candidate_assembly_is_pending_and_create_only(sample, tmp_path):
    module, payload = assembler_fixture(sample, tmp_path)
    output = tmp_path / "candidate" / "dock_scotty"
    result = module.write_candidate(payload, output)
    assert result["fresh_install"] == "pending"
    assert result["job_verified"] is False
    validated = lib_rapp.validate_dir(output)
    assert validated.ok, validated.errors
    evidence = json.loads((output / "generated/candidate-evidence.json").read_text())
    assert evidence["candidate_digest"] == result["support_sha256"]
    assert evidence["observed_at"] is None
    assert all(item["status"] == "pending" for item in evidence["results"])
    with pytest.raises(ValueError, match="new directory"):
        module.write_candidate(payload, output)


def test_candidate_refusal_occurs_before_output_writes(sample, tmp_path, monkeypatch):
    import rapp_package

    module, payload = assembler_fixture(sample, tmp_path)

    def refused(*args, **kwargs):
        raise rapp_package.PackageError("E_UNSUPPORTED_REQUIREMENT: synthetic refusal")

    monkeypatch.setattr(rapp_package, "require_installable", refused)
    output = tmp_path / "not-written" / "dock_scotty"
    with pytest.raises(rapp_package.PackageError, match="E_UNSUPPORTED_REQUIREMENT"):
        module.write_candidate(payload, output)
    assert not output.parent.exists()


def test_outer_release_version_does_not_rewrite_stable_bootstrap(sample, tmp_path):
    module, payload = assembler_fixture(sample, tmp_path)
    first, first_files = module.candidate_files(payload)
    second, second_files = module.candidate_files(payload, version="0.2.0")
    assert first["version"] == "0.1.0"
    assert second["version"] == "0.2.0"
    assert first_files["singleton/scotty_agent.py"] == second_files["singleton/scotty_agent.py"]
    assert first_files["singleton/scotty_revision.json"] == second_files["singleton/scotty_revision.json"]
    assert first["local_docker"]["loader"] == second["local_docker"]["loader"]


@pytest.mark.skipif(not os.environ.get("RAPP_STORE_PUBLIC_TEMPLATE"),
                    reason="Requires a separately reviewed public Dock export; never the live runtime.")
def test_actual_public_export_passes_static_admission_without_payload_imports():
    path = ROOT / "samples/dock_scotty/tools/assemble_candidate.py"
    spec = importlib.util.spec_from_file_location("_actual_candidate_assembler", path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    manifest, files = module.candidate_files(Path(os.environ["RAPP_STORE_PUBLIC_TEMPLATE"]))
    py, js = both_errors(manifest, files)
    assert not py, py
    assert not js, js
    assert manifest["local_docker"]["readiness"]["fresh_install"] == "pending"
    assert not manifest["provenance"]["deployed"]
    assert not manifest["provenance"]["job_verified"]
