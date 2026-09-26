"""The active Store producer must emit the accepted rev-15 egg container.

The checked-in Dock reference below is byte-identical to rapp.py at
https://github.com/kody-w/rapp-1/blob/eb50008011447f5e69372ac22a1755f0978d15ed/rapp.py.
Load it without importing or executing any application payload.
"""

import binascii
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import struct
import zipfile

import pytest

import build_pokedex_api as producer


ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / (
    "apps/@kody-w/dock_scotty/singleton/"
    "scotty_support_3d47c4537516d094aef2bde15ee014ea0721c4cbef0321254cf3b2a6ebc2d6e3/"
    "deploy/local/rapp1/rapp.py"
)
REFERENCE_SHA256 = "1a04362b02f14c1e37b70c6b4f72d79e92df1cc9c2b5b394e8e1b141fc0b6050"
STAMP = "2026-09-25T12:34:56Z"


@pytest.fixture(scope="module")
def reference():
    assert hashlib.sha256(REFERENCE.read_bytes()).hexdigest() == REFERENCE_SHA256
    spec = importlib.util.spec_from_file_location("_producer_egg_reference", REFERENCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def app(make_rapp_dir, monkeypatch):
    directory = make_rapp_dir(name="Example \u2603")
    monkeypatch.setattr(producer, "_app_iso", lambda _: STAMP)
    monkeypatch.setattr(producer, "_REPO", directory.parent)
    files = {
        "ui/z.js": b"// last asset\n",
        "ui/assets/\u00e9.css": b"/* UTF-8 filename */\n",
        "ui/assets/a.css": b"/* first asset */\n",
        "organs/z_unused.py": b"name = 'not-selected'\n",
        "organs/a_organ.py": b"name = 'test-organ'\n",
        "organs/__init__.py": b"",
        "singleton/z_unused.py": b"# second source participates in the existing identity hash\n",
    }
    for name, data in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return directory, json.loads((directory / "manifest.json").read_text())


def _decode(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return json.loads(archive.read("manifest.json")), {
            name: archive.read(name) for name in archive.namelist() if name != "manifest.json"
        }


def test_manifest_and_payload_preserve_catalog_identity_and_file_bytes(app, reference):
    directory, app_manifest = app
    blob = producer._build_egg(directory, app_manifest)
    manifest, files = _decode(blob)
    entry = producer._build_entry(directory, app_manifest)

    assert set(manifest) == {
        "schema", "variant", "rappid", "created_utc", "contents", "payload", "sig",
    }
    assert manifest["schema"] == "rapp/1-egg"
    assert manifest["variant"] == "rapplication"
    assert manifest["created_utc"] == "2026-09-25T12:34:56.000Z"
    assert manifest["sig"] is None
    assert manifest["rappid"] == entry["rappid"]
    assert manifest["payload"] == {
        "rapp_id": "my_thing", "name": "Example \u2603", "version": "0.1.0",
        "publisher": "@alice", "host": "rapp_store-static-api",
        "agent_filename": "my_thing_agent.py", "organ_filename": "a_organ.py",
        "has_skin": True, "counts": {"agent": 1, "ui": 4, "data": 0, "soul": 0, "organ": 1},
    }
    source = b"".join(path.read_bytes() for path in sorted((directory / "singleton").glob("*.py")))
    unchanged_tail = hashlib.sha256(b"rapp/1:rappid\n" + hashlib.sha256(source).digest()).hexdigest()
    assert manifest["rappid"] == "rappid:@alice/my-thing:" + unchanged_tail
    identity = {
        "schema": "rapp/1", "rappid": entry["rappid"], "parent_rappid": entry["parent_rappid"],
        "kind": "rapplication", "name": "Example \u2603", "version": "0.1.0",
        "publisher": "@alice", "rapp_id": "my_thing", "born_at": STAMP,
    }
    expected_files = {
        "agent.py": (directory / "singleton/my_thing_agent.py").read_bytes(),
        "organs/a_organ.py": (directory / "organs/a_organ.py").read_bytes(),
        "rappid.json": json.dumps(identity, indent=2).encode(),
    }
    expected_files.update({
        "rapp_ui/my_thing/" + path.relative_to(directory / "ui").as_posix(): path.read_bytes()
        for path in (directory / "ui").rglob("*") if path.is_file()
    })
    assert files == expected_files
    assert [name for name in files if "/" not in name and name.endswith(".py")] == ["agent.py"]
    assert manifest["contents"] == [
        {"path": path, "hash": hashlib.sha256(b"rapp/1:egg\n" + files[path]).hexdigest()}
        for path in sorted(files, key=lambda path: path.encode("utf-8"))
    ]
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert archive.read("manifest.json") == reference.canonical(manifest).encode("utf-8")
    assert reference.read_egg(blob) == (manifest, files)
    assert reference.verify_egg(blob) == (True, None, "ok")
    assert blob == reference.pack_egg(
        "rapplication", manifest["rappid"], manifest["created_utc"],
        files=files, payload=manifest["payload"],
    )


def test_local_and_central_headers_are_manifest_first_stored_and_deterministic(app):
    blob = producer._build_egg(*app)
    manifest, files = _decode(blob)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        expected = ["manifest.json", *sorted(files, key=lambda name: name.encode("utf-8"))]
        assert archive.namelist() == expected
        local_cursor = 0
        central_cursor = archive.start_dir
        for info in archive.infolist():
            name = info.filename.encode("utf-8")
            data = archive.read(info)
            crc = binascii.crc32(data) & 0xFFFFFFFF
            assert info.header_offset == local_cursor
            local = struct.unpack_from("<4s5H3L2H", blob, local_cursor)
            assert local == (
                b"PK\x03\x04", 20, 0x800, 0, 0, 33,
                crc, len(data), len(data), len(name), 0,
            )
            local_cursor += 30
            assert blob[local_cursor:local_cursor + len(name)] == name
            local_cursor += len(name)
            assert blob[local_cursor:local_cursor + len(data)] == data
            local_cursor += len(data)

            central = struct.unpack_from("<4s6H3L5H2L", blob, central_cursor)
            assert central == (
                b"PK\x01\x02", (3 << 8) | 20, 20, 0x800, 0, 0, 33,
                crc, len(data), len(data), len(name), 0, 0, 0, 0,
                0o600 << 16, info.header_offset,
            )
            central_cursor += 46
            assert blob[central_cursor:central_cursor + len(name)] == name
            central_cursor += len(name)
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.extra == info.comment == b""
        assert local_cursor == archive.start_dir
        assert struct.unpack_from("<4s4H2LH", blob, central_cursor) == (
            b"PK\x05\x06", 0, 0, len(expected), len(expected),
            central_cursor - archive.start_dir, archive.start_dir, 0,
        )
        assert central_cursor + 22 == len(blob)
    assert manifest["schema"] == "rapp/1-egg"


def test_rebuild_ignores_filesystem_enumeration_and_zip_host_defaults(app, monkeypatch):
    directory, manifest = app
    before = producer._build_egg(directory, manifest)
    iterdir, rglob = Path.iterdir, Path.rglob
    monkeypatch.setattr(Path, "iterdir", lambda path: iter(reversed(list(iterdir(path)))))
    monkeypatch.setattr(Path, "rglob", lambda path, pattern: iter(reversed(list(rglob(path, pattern)))))
    monkeypatch.setattr(zipfile.sys, "platform", "win32")
    assert producer._build_egg(directory, manifest) == before


def test_minimal_agent_only_egg_uses_the_same_contract(make_rapp_dir, monkeypatch, reference):
    directory = make_rapp_dir(ui=None)
    monkeypatch.setattr(producer, "_app_iso", lambda _: "2020-01-01T00:00:00Z")
    blob = producer._build_egg(directory, json.loads((directory / "manifest.json").read_text()))
    manifest, files = _decode(blob)
    assert set(files) == {"agent.py", "rappid.json"}
    assert manifest["payload"]["has_skin"] is False
    assert manifest["payload"]["organ_filename"] is None
    assert manifest["created_utc"] == "2020-01-01T00:00:00.000Z"
    assert reference.verify_egg(blob) == (True, None, "ok")


def test_no_singleton_is_an_explicit_refusal_not_an_empty_rapplication(make_rapp_dir):
    directory = make_rapp_dir()
    (directory / "singleton/my_thing_agent.py").unlink()
    with pytest.raises(ValueError, match="E_EGG_AGENT"):
        producer._build_egg(directory, json.loads((directory / "manifest.json").read_text()))


@pytest.mark.parametrize("name", [
    "CON.txt", "trailing.", "trailing ", "bad:name", "back\\slash", "e\u0301.css",
])
def test_nonportable_or_colliding_archive_paths_are_refused(app, name):
    directory, manifest = app
    (directory / "ui" / name).write_bytes(b"invalid archive member")
    with pytest.raises(ValueError, match="E_EGG_PATH"):
        producer._build_egg(directory, manifest)


def test_case_colliding_archive_paths_are_refused_on_any_host(app, monkeypatch):
    directory, manifest = app
    ui = directory / "ui"
    lower, upper = ui / "index.html", ui / "INDEX.html"
    upper.write_bytes(lower.read_bytes())
    rglob = Path.rglob

    def members(path, pattern):
        paths = list(rglob(path, pattern))
        if path == ui:
            paths = [item for item in paths if item.name.lower() != "index.html"]
            paths.extend([lower, upper])
        return iter(paths)

    monkeypatch.setattr(Path, "rglob", members)
    with pytest.raises(ValueError, match="E_EGG_PATH"):
        producer._build_egg(directory, manifest)


@pytest.mark.parametrize("value", [
    {"\ue000": "BMP", "\U0001f600": "non-BMP", "a": [True, False, None, 0]},
    {"escaped": "\n\t\"\\", "unicode": "caf\u00e9", "limits": [-(2**53 - 1), 2**53 - 1]},
])
def test_canonical_port_matches_reference_utf16_order_and_exact_values(value, reference):
    import rapp_egg

    assert rapp_egg._canonical(value) == reference.canonical(value)


@pytest.mark.parametrize("value", [0.5, 2**53, -(2**53)])
def test_canonical_port_refuses_values_outside_the_reference_domain(value, reference):
    import rapp_egg

    with pytest.raises(ValueError):
        reference.canonical(value)
    with pytest.raises(ValueError, match="E_EGG_JSON"):
        rapp_egg._canonical(value)


def test_all_available_local_singletons_pass_the_pinned_reference(monkeypatch, reference):
    monkeypatch.setattr(producer, "_app_iso", lambda _: STAMP)
    built = []
    for path in sorted((ROOT / "apps").glob("@*/*/manifest.json")):
        manifest = json.loads(path.read_text())
        if manifest.get("schema") == "rapp-application/2.0":
            continue
        if not list((path.parent / "singleton").glob("*.py")):
            with pytest.raises(ValueError, match="E_EGG_AGENT"):
                producer._build_egg(path.parent, manifest)
            continue
        blob = producer._build_egg(path.parent, manifest)
        assert reference.verify_egg(blob) == (True, None, "ok"), manifest["id"]
        egg, files = reference.read_egg(blob)
        assert egg["rappid"] == producer._build_entry(path.parent, manifest)["rappid"]
        assert blob == reference.pack_egg(
            "rapplication", egg["rappid"], egg["created_utc"], files, egg["payload"],
        )
        built.append(manifest["id"])
    assert "rapp-zoo" in built
    assert "egg_hatcher" in built


def test_cli_writes_verified_eggs_without_changing_catalog_semantics(
        app, tmp_path, monkeypatch, reference, capsys):
    directory, manifest = app
    work = tmp_path / "producer"
    app_dir = work / "apps/@alice/my_thing"
    shutil.copytree(directory, app_dir)
    absent = work / "apps/@alice/metadata_only"
    absent.mkdir()
    (absent / "manifest.json").write_text(json.dumps({
        **manifest, "id": "metadata_only", "access": "private",
    }))
    catalog = b'{"rapplications":[]}\n'
    (work / "index.json").write_bytes(catalog)
    monkeypatch.setattr(producer, "_REPO", work)
    monkeypatch.setattr(producer, "_APPS", work / "apps")
    monkeypatch.setattr(producer, "_API", work / "api/v1")
    expected = producer._build_entry(app_dir, manifest)
    producer.main(["--catalog", str(work / "index.json")])
    blob = (work / "api/v1/egg/my_thing.egg").read_bytes()
    entry = json.loads((work / "api/v1/rapplication/my_thing.json").read_text())
    assert entry == {**expected, "egg_bytes": len(blob)}
    assert reference.verify_egg(blob) == (True, None, "ok")
    assert (work / "index.json").read_bytes() == catalog
    refused = json.loads((work / "api/v1/rapplication/metadata_only.json").read_text())
    assert refused["egg_url"] is None and refused["egg_bytes"] == 0
    assert not (work / "api/v1/egg/metadata_only.egg").exists()
    assert "E_EGG_AGENT" in capsys.readouterr().err
