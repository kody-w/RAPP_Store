"""The catalog producer must be a pure function of apps/.

Wall-clock stamps (in egg manifests or zip member headers) once made every
build rewrite every egg's bytes — which silently broke every published
egg_sha256 pin on the next push. This guards the invariant: building twice
from the same tree yields byte-identical output.
"""
import hashlib
import copy
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

import build_pokedex_api as producer

_REPO = pathlib.Path(__file__).resolve().parent.parent


def _tree_digest(root: pathlib.Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            h.update(str(path.relative_to(root)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def test_two_builds_are_byte_identical(tmp_path):
    # Isolated copy: apps/ + the producer, no .git — exercises the
    # deterministic fallback stamp as well as the zip member stamps.
    work = tmp_path / "store"
    (work / "scripts").mkdir(parents=True)
    shutil.copytree(_REPO / "apps", work / "apps", symlinks=False)
    shutil.copy(_REPO / "scripts" / "build_pokedex_api.py", work / "scripts")

    digests = []
    for _ in range(2):
        subprocess.run(
            [sys.executable, "scripts/build_pokedex_api.py"],
            cwd=work, check=True, capture_output=True, timeout=300,
        )
        digests.append(_tree_digest(work / "api" / "v1"))
        shutil.rmtree(work / "api")
    assert digests[0] == digests[1], (
        "producer output drifted between two identical runs — a wall-clock "
        "or ordering dependency crept back in"
    )


def test_scoped_native_projection_is_deterministic_and_preserves_other_bytes(tmp_path, native_release):
    api = tmp_path / "api" / "v1"
    native = native_release.entry()
    legacy = {"id": "legacy", "name": "Existing \u2192 entry", "egg": "existing.egg"}
    catalog = {"rapplications": [native, {"id": "unrequested", "desktop": {"incomplete": True}}]}
    preserved = {
        api / "rapplication" / "legacy.json": b'{ "id": "legacy", "rappid": "existing" }\n',
        api / "egg" / "legacy.egg": b"unchanged archived bytes",
        api / "hatcher" / "legacy_hatcher_agent.py": b"unchanged generated agent",
        api / "sprite" / "legacy.svg": b"unchanged generated sprite",
        tmp_path / "api" / "v2" / "discovery.json": b"protected v2 fixture",
    }
    for path, blob in preserved.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    (api / "index.json").write_text(json.dumps({
        "schema": producer.SCHEMA_API_INDEX, "count": 1, "generated_at": "preserve-this",
        "custom": {"keep": [1, 2]}, "rapplications": [legacy],
    }, indent=2) + "\n")
    original_catalog = copy.deepcopy(catalog)

    changed = producer.refresh_native_discovery(catalog, api, ["my_thing"])
    assert set(changed) == {api / "index.json", api / "rapplication" / "my_thing.json"}
    first = _tree_digest(tmp_path / "api")
    assert producer.refresh_native_discovery(catalog, api, ["my_thing"]) == []
    assert _tree_digest(tmp_path / "api") == first
    assert catalog == original_catalog
    for path, blob in preserved.items():
        assert path.read_bytes() == blob
    index = json.loads((api / "index.json").read_text())
    assert index["count"] == 2
    assert index["generated_at"] == "preserve-this"
    assert index["custom"] == {"keep": [1, 2]}
    assert index["rapplications"][0] == legacy
    detail = json.loads((api / "rapplication" / "my_thing.json").read_text())
    assert detail["desktop"] == native["desktop"]
    assert detail["source"] == native["source"]
    assert detail["singleton_sha256"] == native["singleton_sha256"]
    assert not {"rappid", "parent_rappid", "egg_url", "sprite_url", "hatcher_url", "install_one_liner"} & detail.keys()
    assert not {"egg", "sprite"} & index["rapplications"][1].keys()
    assert not list(api.rglob("my_thing*.egg"))
    assert not list(api.rglob("my_thing*.svg"))
    assert not list(api.rglob("my_thing*.py"))
    assert not list(api.rglob("*.dmg"))


def test_native_projection_replaces_only_requested_row_in_place(tmp_path, native_release):
    api = tmp_path / "api" / "v1"
    api.mkdir(parents=True)
    (api / "index.json").write_text(json.dumps({
        "schema": producer.SCHEMA_API_INDEX,
        "rapplications": [{"id": "a"}, {"id": "my_thing", "version": "old"}, {"id": "b"}],
        "count": 3,
    }))
    producer.refresh_native_discovery({"rapplications": [native_release.entry()]}, api, ["my_thing"])
    rows = json.loads((api / "index.json").read_text())["rapplications"]
    assert [row["id"] for row in rows] == ["a", "my_thing", "b"]
    assert rows[1]["version"] == "0.1.0"


def test_native_only_cli_never_runs_legacy_producers(tmp_path, native_release):
    work = tmp_path / "store"
    (work / "scripts").mkdir(parents=True)
    for name in ("build_pokedex_api.py", "lib_desktop.py"):
        shutil.copy(_REPO / "scripts" / name, work / "scripts")
    (work / "index.json").write_text(json.dumps({"rapplications": [native_release.entry()]}))
    # No apps/ exists: a legacy producer invocation would fail.
    command = [sys.executable, "scripts/build_pokedex_api.py", "--native-only", "--ids", "my_thing"]
    subprocess.run(command, cwd=work, check=True, capture_output=True, timeout=30)
    before = _tree_digest(work / "api")
    subprocess.run(command, cwd=work, check=True, capture_output=True, timeout=30)
    assert _tree_digest(work / "api") == before
    assert sorted(str(p.relative_to(work / "api")) for p in (work / "api").rglob("*") if p.is_file()) == [
        "v1/index.json", "v1/rapplication/my_thing.json",
    ]


@pytest.mark.parametrize("ids", [[], ["missing"], ["my_thing", "missing"]])
def test_native_refresh_requires_explicit_valid_ids_and_is_preflighted(tmp_path, native_release, ids):
    api = tmp_path / "api" / "v1"
    with pytest.raises(ValueError, match="E_DESKTOP_DISCOVERY"):
        producer.refresh_native_discovery({"rapplications": [native_release.entry()]}, api, ids)
    assert not api.exists()


def test_native_projection_rejects_unpinned_source(tmp_path, native_release):
    entry = native_release.entry()
    del entry["source"]["commit_sha"]
    with pytest.raises(ValueError, match="E_DESKTOP_DISCOVERY_SOURCE"):
        producer.refresh_native_discovery({"rapplications": [entry]}, tmp_path / "api" / "v1", ["my_thing"])


def test_full_producer_in_isolated_fixture_also_includes_federated_native_metadata(
        tmp_path, native_release, make_rapp_dir):
    work = tmp_path / "full-producer-fixture"
    (work / "scripts").mkdir(parents=True)
    for name in ("build_pokedex_api.py", "lib_desktop.py"):
        shutil.copy(_REPO / "scripts" / name, work / "scripts")
    shutil.copytree(make_rapp_dir(rapp_id="legacy"), work / "apps" / "@alice" / "legacy")
    (work / "index.json").write_text(json.dumps({"rapplications": [native_release.entry()]}))
    subprocess.run([sys.executable, "scripts/build_pokedex_api.py"], cwd=work,
                   check=True, capture_output=True, timeout=30)
    api = work / "api" / "v1"
    index = json.loads((api / "index.json").read_text())
    assert index["count"] == 2
    assert [row["id"] for row in index["rapplications"]] == ["legacy", "my_thing"]
    assert (api / "egg" / "legacy.egg").is_file()
    assert not (api / "egg" / "my_thing.egg").exists()
    assert not (api / "sprite" / "my_thing.svg").exists()
    assert json.loads((api / "rapplication" / "my_thing.json").read_text())["desktop"] == native_release.desktop
    before = _tree_digest(api)
    subprocess.run([sys.executable, "scripts/build_pokedex_api.py"], cwd=work,
                   check=True, capture_output=True, timeout=30)
    assert _tree_digest(api) == before


def test_zip_native_projection_is_deterministic_and_metadata_only(tmp_path, native_zip_release):
    api = tmp_path / "api" / "v1"
    catalog = {"rapplications": [native_zip_release.entry()]}
    producer.refresh_native_discovery(catalog, api, ["my_thing"])
    before = _tree_digest(api)
    assert producer.refresh_native_discovery(catalog, api, ["my_thing"]) == []
    assert _tree_digest(api) == before
    detail = json.loads((api / "rapplication" / "my_thing.json").read_text())
    assert detail["desktop"] == native_zip_release.desktop
    assert sorted(str(p.relative_to(api)) for p in api.rglob("*") if p.is_file()) == [
        "index.json", "rapplication/my_thing.json",
    ]


def test_addressed_evidence_projection_remains_deterministic(
        tmp_path, native_zip_release, address_native_evidence):
    n = native_zip_release
    address_native_evidence(n)
    api = tmp_path / "api" / "v1"
    catalog = {"rapplications": [n.entry()]}
    producer.refresh_native_discovery(catalog, api, ["my_thing"])
    before = _tree_digest(api)
    assert producer.refresh_native_discovery(catalog, api, ["my_thing"]) == []
    assert _tree_digest(api) == before
    assert json.loads((api / "rapplication" / "my_thing.json").read_text())["desktop"] == n.desktop
