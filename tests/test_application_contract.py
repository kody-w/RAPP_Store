"""Complete-contract admission is additive to the public simple/native catalog."""
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

import build_pokedex_api
import lib_rapp


ROOT = Path(__file__).resolve().parent.parent
GRAIL = {
    "repo": "microsoft/aibast-agents-library",
    "commit": "c60521e2cacbcbfa585a118c1275093d7bb15b74",
    "version": "0.6.16",
}
LIFECYCLE = {
    "install": "copy-verified-files", "upgrade": "preserve-state",
    "uninstall": "preserve-state", "recovery": "reinstall-verified-package",
}


@pytest.fixture
def complete_application(make_rapp_dir):
    directory = make_rapp_dir()
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest.update({
        "schema": lib_rapp.SCHEMA_APPLICATION,
        "agents": [manifest["agent"]],
        "runtime": dict(GRAIL),
        "requires": ["portable-agents/1", "owned-files/1"],
        "profiles": [], "permissions": ["host-user"], "capabilities": ["synthetic-test"],
        "dependencies": [], "services": [],
        "state": {"version": "1", "preserve": True, "seeds": {}},
        "lifecycle": dict(LIFECYCLE),
        "providers": {"mode": "none", "spend_limit": None, "egress_allowlist": None},
        "provenance": {"status": "development", "source": "synthetic-test",
                       "deployed": False, "job_verified": False},
    })
    manifest.pop("ui")
    manifest["files"] = {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file() and path.name not in ("manifest.json", "index_entry.json")
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return directory, manifest


def test_complete_chat_app_accepts_no_separate_ui_or_index_override(complete_application):
    directory, manifest = complete_application
    (directory / "index_entry.json").unlink()
    result = lib_rapp.validate_dir(directory, expected_publisher="@alice")
    assert result.ok, result.errors
    assert result.integrity["package_sha256"]
    assert "singleton_sha256" not in result.integrity
    assert result.manifest == manifest


def test_complete_source_zip_refuses_unqualified_promotion_before_writes(complete_application, tmp_path):
    directory, _ = complete_application
    target = tmp_path / "not-extracted"
    result = lib_rapp.validate_zip(lib_rapp.bundle_dir(directory), extract_to=target)
    assert not result.ok
    assert any("E_APPLICATION_FEDERATION_ONLY" in error for error in result.errors)
    assert not target.exists()
    assert not lib_rapp.validate_dir(directory, submission_type="bundle").ok


@pytest.mark.parametrize("schema", ["rapp-application/1.0", "rapp-application/2.0"])
def test_unknown_mandatory_feature_refuses_before_extraction(complete_application, tmp_path, schema):
    directory, manifest = complete_application
    manifest["schema"] = schema
    manifest["requires"].append("future-required-device/99")
    (directory / "manifest.json").write_text(json.dumps(manifest))
    target = tmp_path / "must-not-exist"
    result = lib_rapp.validate_zip(lib_rapp.bundle_dir(directory), extract_to=target)
    assert not result.ok
    assert any("E_UNSUPPORTED_REQUIREMENT" in error for error in result.errors)
    assert not target.exists()


@pytest.mark.parametrize("duplicate_name", ["my_thing/manifest.json", "my_thing/MANIFEST.json"])
def test_ambiguous_zip_cannot_hide_mandatory_features(complete_application, tmp_path, duplicate_name):
    directory, manifest = complete_application
    archive = io.BytesIO(lib_rapp.bundle_dir(directory))
    replacement = copy.deepcopy(manifest)
    replacement["requires"].append("unsupported-hidden-feature/1")
    with zipfile.ZipFile(archive, "a") as bundle:
        if duplicate_name.endswith("/manifest.json"):
            with pytest.warns(UserWarning, match="Duplicate name"):
                bundle.writestr(duplicate_name, json.dumps(replacement))
        else:
            bundle.writestr(duplicate_name, json.dumps(replacement))
    target = tmp_path / "unwritten"
    result = lib_rapp.validate_zip(archive.getvalue(), extract_to=target)
    assert not result.ok
    assert any("E_DUPLICATE_ZIP_MEMBER" in error for error in result.errors)
    assert not target.exists()


def test_new_contract_never_bypasses_state_or_file_integrity(complete_application, tmp_path):
    directory, manifest = complete_application
    (directory / "README.md").write_text("changed")
    result = lib_rapp.validate_zip(lib_rapp.bundle_dir(directory), extract_to=tmp_path / "untouched")
    assert not result.ok
    assert any("E_FILE_DIGEST" in error for error in result.errors)
    assert not (tmp_path / "untouched").exists()
    manifest["state"]["preserve"] = False
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert not lib_rapp.validate_dir(directory).ok


def test_complete_catalog_entry_cannot_be_a_source_only_install(complete_application):
    directory, manifest = complete_application
    result = lib_rapp.validate_dir(directory)
    assert result.ok, result.errors
    entry = lib_rapp.build_index_entry(manifest, result.integrity, manifest["id"])
    assert entry["application"] == manifest
    assert entry["requires"] == manifest["requires"]
    assert entry["application_schema"] == "rapp-application/2.0"
    assert entry["installable"] is False
    assert entry["install_blockers"]
    assert "files" not in entry
    assert "agents" not in entry
    assert not any(key.startswith(("singleton_", "service_", "ui_", "egg_", "hatcher_"))
                   for key in entry)


@pytest.mark.parametrize("previous,code", [
    ({"publisher": "@another-publisher"}, "E_APPLICATION_OWNERSHIP"),
    ({"publisher": "@alice", "desktop": {"preserved": "native listing"}}, "E_APPLICATION_DISTRIBUTION"),
])
def test_rich_extension_cannot_replace_other_publisher_or_native_listing(complete_application, previous, code):
    directory, manifest = complete_application
    catalog = {"rapplications": [{"id": manifest["id"], "version": "0.0.1", **previous}]}
    original = copy.deepcopy(catalog)
    result = lib_rapp.validate_dir(directory, existing_catalog=catalog)
    assert not result.ok
    assert any(code in error for error in result.errors)
    assert catalog == original


def test_complete_federation_fetches_commit_pinned_entire_closure(complete_application, fake_fetcher):
    directory, manifest = complete_application
    commit = "b" * 40
    base = "https://raw.githubusercontent.com/alice/example"
    blob = (directory / "manifest.json").read_bytes()
    routes = {
        base + "/main/my_thing/manifest.json": blob,
        base + "/" + commit + "/my_thing/manifest.json": blob,
        "https://api.github.com/repos/alice/example/commits/main": json.dumps({"sha": commit}),
    }
    routes.update({base + "/" + commit + "/my_thing/" + name: (directory / name).read_bytes()
                   for name in manifest["files"]})
    seen = []
    fetch = fake_fetcher(routes)

    def tracked(url):
        seen.append(url)
        return fetch(url)

    result = lib_rapp.validate_federation("alice/example", path="my_thing", fetcher=tracked)
    assert result.ok, result.errors
    assert result.index_entry["source"]["commit_sha"] == commit
    assert result.index_entry["source"]["ref"] == commit
    assert result.index_entry["application_url"] == base + "/" + commit + "/my_thing/manifest.json"
    assert "singleton_url" not in result.index_entry
    assert set(url.rsplit("/my_thing/", 1)[1] for url in seen if "/" + commit + "/my_thing/" in url) == {
        "manifest.json", *manifest["files"],
    }
    routes[base + "/" + commit + "/my_thing/README.md"] = b"tampered declaration"
    assert not lib_rapp.validate_federation("alice/example", path="my_thing", fetcher=tracked).ok


def test_complete_federation_refuses_moved_source(complete_application, fake_fetcher):
    directory, manifest = complete_application
    commit = "b" * 40
    routes = {
        "https://raw.githubusercontent.com/alice/example/main/my_thing/manifest.json":
            (directory / "manifest.json").read_bytes(),
        "https://api.github.com/repos/alice/example/commits/main": json.dumps({"sha": commit}),
    }
    result = lib_rapp.validate_federation("alice/example", path="my_thing",
                                        expected_commit_sha="c" * 40, fetcher=fake_fetcher(routes))
    assert not result.ok
    assert "E_APPLICATION_STALE_SOURCE" in result.errors[0]


def test_existing_receiver_rechecks_complete_federation_at_reviewed_commit(
        complete_application, fake_fetcher, monkeypatch, tmp_path):
    import promote_rapplication

    directory, manifest = complete_application
    commit = "b" * 40
    base = "https://raw.githubusercontent.com/alice/example"
    blob = (directory / "manifest.json").read_bytes()
    routes = {
        base + "/main/my_thing/manifest.json": blob,
        base + "/" + commit + "/my_thing/manifest.json": blob,
        "https://api.github.com/repos/alice/example/commits/main": json.dumps({"sha": commit}),
        "https://api.github.com/repos/alice/example/commits/" + commit: json.dumps({"sha": commit}),
    }
    routes.update({base + "/" + commit + "/my_thing/" + name: (directory / name).read_bytes()
                   for name in manifest["files"]})
    fetch = fake_fetcher(routes)
    staged = lib_rapp.validate_federation("alice/example", path="my_thing", fetcher=fetch)
    assert staged.ok, staged.errors
    routes[base + "/main/my_thing/manifest.json"] = b"changed branch after review"
    routes["https://api.github.com/repos/alice/example/commits/main"] = json.dumps({"sha": "c" * 40})
    monkeypatch.setattr(lib_rapp, "_default_fetcher", lambda: fetch)
    entry, promoted = promote_rapplication.promote_federation({
        "id": manifest["id"], "version": manifest["version"], "submitter": "@alice",
        "entry": staged.index_entry,
    }, tmp_path / "index.json")
    assert entry["source"]["ref"] == entry["source"]["commit_sha"] == commit
    assert promoted == manifest


def test_application_scoped_projection_preserves_native_zoo_and_archived_bytes(
        complete_application, tmp_path):
    directory, manifest = complete_application
    entry = lib_rapp.build_index_entry(manifest, {}, manifest["id"])
    native = {"id": "unrelated_native", "desktop": {"preserved": "synthetic native descriptor"}}
    catalog = {"rapplications": [native, entry]}
    original = copy.deepcopy(catalog)
    api = tmp_path / "api" / "v1"
    api.mkdir(parents=True)
    (api / "index.json").write_text(json.dumps({
        "schema": build_pokedex_api.SCHEMA_API_INDEX,
        "generated_at": "existing-recorded-stamp", "custom": {"keep": True},
        "rapplications": [{"id": "unrelated_native", "desktop": native["desktop"]}], "count": 1,
    }))
    preserved = {
        api / "egg" / "existing.egg": b"historical immutable fixture",
        api / "hatcher" / "existing.py": b"historical installer fixture",
        api / "rapplication" / "unrelated_native.json": b"native descriptor fixture",
        tmp_path / "api" / "v2" / "discovery.json": b"independent Zoo fixture",
    }
    for path, blob in preserved.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    changed = build_pokedex_api.refresh_application_discovery(catalog, api, ["my_thing"])
    assert set(changed) == {api / "index.json", api / "rapplication" / "my_thing.json"}
    assert build_pokedex_api.refresh_application_discovery(catalog, api, ["my_thing"]) == []
    assert catalog == original
    for path, blob in preserved.items():
        assert path.read_bytes() == blob
    detail = json.loads((api / "rapplication" / "my_thing.json").read_text())
    assert detail["requires"] == manifest["requires"]
    assert detail["application"] == manifest
    assert detail["installable"] is False
    assert not {"rappid", "parent_rappid", "singleton_url", "service_url", "egg_url", "hatcher_url"} & detail.keys()


def test_application_projection_refuses_unknown_requirements_before_writes(complete_application, tmp_path):
    directory, manifest = complete_application
    manifest["requires"].append("unknown-mandatory/1")
    entry = lib_rapp.build_index_entry(manifest, {}, manifest["id"])
    target = tmp_path / "unwritten"
    with pytest.raises(ValueError, match="E_UNSUPPORTED_REQUIREMENT"):
        build_pokedex_api.refresh_application_discovery({"rapplications": [entry]}, target, [manifest["id"]])
    assert not target.exists()


def test_legacy_producer_refuses_rich_app_before_rewriting_any_assets(complete_application, tmp_path):
    directory, _ = complete_application
    work = tmp_path / "store"
    (work / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "build_pokedex_api.py", work / "scripts")
    shutil.copytree(directory, work / "apps" / "@alice" / "my_thing")
    archived = work / "api" / "v1" / "egg" / "historical.egg"
    archived.parent.mkdir(parents=True)
    archived.write_bytes(b"immutable existing fixture")
    result = subprocess.run([sys.executable, "scripts/build_pokedex_api.py"],
                            cwd=work, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "E_APPLICATION_SCOPED" in result.stderr
    assert archived.read_bytes() == b"immutable existing fixture"


def test_simple_apps_have_no_new_docker_or_package_import_dependency(make_rapp_dir, monkeypatch):
    directory = make_rapp_dir()
    monkeypatch.setitem(sys.modules, "rapp_package", None)
    result = lib_rapp.validate_dir(directory)
    assert result.ok, result.errors
    assert "singleton_url" in lib_rapp.build_index_entry(result.manifest, result.integrity, "my_thing")
