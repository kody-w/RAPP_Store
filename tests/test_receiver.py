"""End-to-end tests for the receiver scripts (process + promote).

These simulate a GitHub Actions issue event by writing an event JSON to a
tmp file and invoking the script's main(). Both bundle and federation
paths are covered, including the staging → main promotion."""
from __future__ import annotations

import base64
import copy
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

import process_rapplication as proc
import promote_rapplication as prom
import lib_rapp
import lib_desktop


def _make_event(tmp_path: Path, issue_number: int, login: str, title: str, body: str) -> Path:
    event = {
        "action": "opened",
        "issue": {
            "number": issue_number,
            "title": title,
            "body": body,
            "user": {"login": login},
        },
    }
    p = tmp_path / "event.json"
    p.write_text(json.dumps(event))
    return p


def _bundle_payload(rapp_dir: Path, login: str) -> str:
    blob = _zip_dir(rapp_dir)
    sha = __import__("hashlib").sha256(blob).hexdigest()
    manifest = json.loads((rapp_dir / "manifest.json").read_text())
    meta = {
        "submission_type": "bundle",
        "id": manifest["id"],
        "version": manifest["version"],
        "publisher": manifest["publisher"],
        "name": manifest.get("name"),
        "category": manifest.get("category"),
        "tags": manifest.get("tags", []),
        "bundle_bytes": len(blob),
        "bundle_sha256": sha,
    }
    b64 = base64.b64encode(blob).decode()
    wrapped = "\n".join(b64[i:i+76] for i in range(0, len(b64), 76))
    return ("Hello.\n\n```json\n" + json.dumps(meta, indent=2) + "\n```\n\n"
            "```bundle\n" + wrapped + "\n```\n")


def _federation_payload(repo: str, ref: str, path: str, manifest: dict) -> str:
    meta = {
        "submission_type": "federation",
        "id": manifest["id"],
        "version": manifest["version"],
        "publisher": manifest["publisher"],
        "name": manifest.get("name"),
        "category": manifest.get("category"),
        "tags": manifest.get("tags", []),
        "source": {"type": "federation", "repo": repo, "ref": ref, "path": path},
    }
    return "Hi.\n\n```json\n" + json.dumps(meta, indent=2) + "\n```\n"


def _zip_dir(rapp_dir: Path) -> bytes:
    rid = rapp_dir.name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(rapp_dir.rglob("*")):
            if p.is_file():
                zf.write(p, f"{rid}/{p.relative_to(rapp_dir).as_posix()}")
    return buf.getvalue()


# ── process_rapplication ──────────────────────────────────────────────────

class TestProcessBundle:
    def test_valid_bundle_stages(self, tmp_path, make_rapp_dir):
        rapp = make_rapp_dir()
        body = _bundle_payload(rapp, "alice")
        event_path = _make_event(tmp_path, 1, "alice",
                                  "[RAPP] @alice/my_thing v0.1.0", body)
        staging = tmp_path / "staging"
        catalog = tmp_path / "index.json"
        catalog.write_text(json.dumps({"rapplications": []}))

        ok, report = proc.process(json.loads(event_path.read_text()),
                                    staging, catalog)
        assert ok, report
        assert "Submission validated" in report
        assert (staging / "my_thing" / "manifest.json").is_file()
        pending = json.loads((staging / "_pending.json").read_text())
        assert any(p["issue"] == 1 and p["mode"] == "bundle"
                   for p in pending["items"])

    def test_publisher_mismatch_rejected(self, tmp_path, make_rapp_dir):
        rapp = make_rapp_dir(publisher="@alice")
        body = _bundle_payload(rapp, "bob")
        event = json.loads(_make_event(tmp_path, 2, "bob",
                                         "[RAPP] @alice/my_thing v0.1.0", body).read_text())
        catalog = tmp_path / "index.json"
        catalog.write_text(json.dumps({"rapplications": []}))
        ok, report = proc.process(event, tmp_path / "staging", catalog)
        assert not ok
        assert "E_PUBLISHER_MISMATCH" in report

    def test_no_payload_rejected(self, tmp_path):
        event = json.loads(_make_event(tmp_path, 3, "bob",
                                         "[RAPP] @bob/foo v0.1.0",
                                         "no payload here").read_text())
        ok, report = proc.process(event, tmp_path / "staging", tmp_path / "index.json")
        assert not ok
        assert "E_NO_PAYLOAD" in report


class TestProcessFederation:
    def test_valid_federation_stages(self, tmp_path, monkeypatch,
                                       spine_dag_extracted):
        # spine_dag's manifest declares publisher @rapp; @kody-w may submit it.
        manifest = json.loads((spine_dag_extracted / "manifest.json").read_text())
        body = _federation_payload("kody-w/rapps", "main", "spine_dag", manifest)
        event = json.loads(_make_event(tmp_path, 4, "kody-w",
                                         f"[RAPP] @rapp/spine_dag v{manifest['version']}",
                                         body).read_text())
        catalog = tmp_path / "index.json"
        catalog.write_text(json.dumps({"rapplications": []}))

        manifest_blob = (spine_dag_extracted / "manifest.json").read_bytes()
        sing_blob = (spine_dag_extracted / "singleton" / "spine_dag_agent.py").read_bytes()
        ui_blob = (spine_dag_extracted / "ui" / "index.html").read_bytes()
        commit_blob = json.dumps({"sha": "f" * 40}).encode()
        routes = {
            "https://raw.githubusercontent.com/kody-w/rapps/main/spine_dag/manifest.json": manifest_blob,
            "https://raw.githubusercontent.com/kody-w/rapps/main/spine_dag/singleton/spine_dag_agent.py": sing_blob,
            "https://raw.githubusercontent.com/kody-w/rapps/main/spine_dag/ui/index.html": ui_blob,
            "https://api.github.com/repos/kody-w/rapps/commits/main": commit_blob,
        }
        import lib_rapp
        monkeypatch.setattr(lib_rapp, "_default_fetcher",
                              lambda: (lambda url: routes.get(url) or
                                        (_ for _ in ()).throw(lib_rapp.FetchError(f"404 for {url}"))))

        ok, report = proc.process(event, tmp_path / "staging", catalog)
        assert ok, report
        assert "federation" in report.lower()

        pending = json.loads((tmp_path / "staging" / "_pending.json").read_text())
        item = next(p for p in pending["items"] if p["issue"] == 4)
        assert item["mode"] == "federation"
        assert item["entry"]["source"]["repo"] == "kody-w/rapps"


# ── promote_rapplication ──────────────────────────────────────────────────

class TestPromoteBundle:
    def test_promote_moves_staging_to_root_and_updates_catalog(
            self, tmp_path, make_rapp_dir, monkeypatch):
        rapp = make_rapp_dir()
        body = _bundle_payload(rapp, "alice")
        catalog = tmp_path / "index.json"
        catalog.write_text(json.dumps({"schema": "rapp-store/1.0",
                                         "rapplications": []}))
        staging = tmp_path / "staging"
        # Stage first
        ok, _ = proc.process(json.loads(_make_event(tmp_path, 7, "alice",
                                                     "[RAPP] @alice/my_thing v0.1.0",
                                                     body).read_text()),
                              staging, catalog)
        assert ok

        approve_event = json.loads(_make_event(tmp_path, 7, "alice",
                                                 "[RAPP] @alice/my_thing v0.1.0",
                                                 body).read_text())
        ok2, report = prom.promote(approve_event, staging, catalog)
        assert ok2, report
        # File should now live under tmp_path/my_thing/
        assert (tmp_path / "my_thing" / "manifest.json").is_file()
        # And the catalog should have the entry
        cat = json.loads(catalog.read_text())
        ids = [r["id"] for r in cat["rapplications"]]
        assert "my_thing" in ids


class TestPromoteFederation:
    def test_promote_federation_just_updates_catalog(
            self, tmp_path, monkeypatch, spine_dag_extracted):
        # Set up a pending federation item directly
        manifest = json.loads((spine_dag_extracted / "manifest.json").read_text())
        rapp_id = manifest["id"]
        staging = tmp_path / "staging"
        staging.mkdir()
        pending = {
            "items": [{
                "issue": 99,
                "submitter": "@kody-w",
                "mode": "federation",
                "id": rapp_id,
                "version": manifest["version"],
                "entry": {"source": {"repo": "kody-w/rapps", "ref": "main", "path": "spine_dag"}},
            }]
        }
        (staging / "_pending.json").write_text(json.dumps(pending))

        # Mock raw fetches
        manifest_blob = (spine_dag_extracted / "manifest.json").read_bytes()
        sing_blob = (spine_dag_extracted / "singleton" / "spine_dag_agent.py").read_bytes()
        ui_blob = (spine_dag_extracted / "ui" / "index.html").read_bytes()
        commit_blob = json.dumps({"sha": "c" * 40}).encode()
        routes = {
            "https://raw.githubusercontent.com/kody-w/rapps/main/spine_dag/manifest.json": manifest_blob,
            "https://raw.githubusercontent.com/kody-w/rapps/main/spine_dag/singleton/spine_dag_agent.py": sing_blob,
            "https://raw.githubusercontent.com/kody-w/rapps/main/spine_dag/ui/index.html": ui_blob,
            "https://api.github.com/repos/kody-w/rapps/commits/main": commit_blob,
        }
        import lib_rapp
        monkeypatch.setattr(lib_rapp, "_default_fetcher",
                              lambda: (lambda url: routes.get(url) or
                                        (_ for _ in ()).throw(lib_rapp.FetchError(f"404 for {url}"))))

        catalog = tmp_path / "index.json"
        catalog.write_text(json.dumps({"schema": "rapp-store/1.0", "rapplications": []}))

        event = {"issue": {"number": 99, "title": "[RAPP] @rapp/spine_dag v1.0.0", "body": ""}}
        # tmp_path already contains the spine_dag fixture extraction; use a
        # separate base dir for the federation test so the "no copy" check is
        # meaningful.
        promote_base = tmp_path / "fed_root"
        promote_base.mkdir()
        staging2 = promote_base / "staging"
        staging2.mkdir()
        (staging2 / "_pending.json").write_text(json.dumps(pending))
        catalog = promote_base / "index.json"
        catalog.write_text(json.dumps({"schema": "rapp-store/1.0", "rapplications": []}))

        ok, report = prom.promote(event, staging2, catalog)
        assert ok, report
        # No copy into root (federation mode)
        assert not (promote_base / rapp_id).exists()
        # Catalog gained the entry
        cat = json.loads(catalog.read_text())
        ids = [r["id"] for r in cat["rapplications"]]
        assert rapp_id in ids
        entry = next(r for r in cat["rapplications"] if r["id"] == rapp_id)
        assert entry["source"]["type"] == "federation"


def _stage_native(tmp_path, monkeypatch, native_release):
    n = native_release
    root = tmp_path / "native-store"
    root.mkdir()
    catalog = root / "index.json"
    catalog.write_text(json.dumps({"schema": "rapp-store/1.0", "rapplications": []}))
    staging = root / "staging"
    body = _federation_payload(n.repo, n.ref, "my_thing", n.manifest)
    event = json.loads(_make_event(root, 101, "alice", "[RAPP] @alice/my_thing v0.1.0", body).read_text())
    monkeypatch.setattr(lib_rapp, "_default_fetcher", lambda: n.fetch)
    monkeypatch.setattr(lib_desktop, "anonymous_chunks", n.stream)
    ok, report = proc.process(event, staging, catalog)
    assert ok, report
    return root, catalog, staging, event


class TestNativeReceiver:
    def test_receiver_preserves_pins_and_promotes_only_native_metadata(
            self, tmp_path, monkeypatch, native_release):
        n = native_release
        root, catalog, staging, event = _stage_native(tmp_path, monkeypatch, n)
        pending = json.loads((staging / "_pending.json").read_text())["items"][0]
        assert pending["entry"]["desktop"] == n.desktop
        assert pending["entry"]["source"]["commit_sha"] == n.commit
        assert not (staging / "my_thing").exists()
        assert "publisher" not in n.desktop  # provenance comes from the validated source/manifest

        api = root / "api" / "v1"
        unrelated = {
            api / "egg" / "other.egg": b"immutable existing egg",
            api / "hatcher" / "other_hatcher_agent.py": b"existing hatcher",
            api / "sprite" / "other.svg": b"<svg>original bytes</svg>",
            api / "rapplication" / "other.json": b'{ "id": "other" }\n',
            root / "api" / "v2" / "discovery.json": b'{"untouched":"Zoo v2"}\n',
        }
        for path, blob in unrelated.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
        (api / "index.json").write_text(json.dumps({
            "schema": "rapp-pokedex-api/1.0", "generated_at": "unchanged", "count": 1,
            "rapplications": [{"id": "other", "egg": "keep-this-exact-value"}],
        }))

        ok, report = prom.promote(event, staging, catalog)
        assert ok, report
        entry = json.loads(catalog.read_text())["rapplications"][0]
        assert entry["desktop"] == n.desktop
        detail = json.loads((api / "rapplication" / "my_thing.json").read_text())
        assert detail["desktop"] == n.desktop
        assert detail["source"] == entry["source"]
        assert not {"rappid", "parent_rappid", "egg_url", "sprite_url", "hatcher_url"} & detail.keys()
        listing = json.loads((api / "index.json").read_text())
        assert listing["count"] == 2
        assert listing["generated_at"] == "unchanged"
        assert listing["rapplications"][0] == {"id": "other", "egg": "keep-this-exact-value"}
        assert not (root / "my_thing").exists()
        assert not list(root.rglob("*.dmg"))
        assert not (api / "egg" / "my_thing.egg").exists()
        assert not (api / "hatcher" / "my_thing_hatcher_agent.py").exists()
        for path, blob in unrelated.items():
            assert path.read_bytes() == blob
        assert json.loads((staging / "_pending.json").read_text())["items"] == []
        assert "not independent authentication" in report

    @pytest.mark.parametrize("current_version", ["0.1.0", "0.2.0"])
    def test_approval_rechecks_current_catalog_not_stage_time_version(
            self, tmp_path, monkeypatch, native_release, current_version):
        n = native_release
        root, catalog, staging, event = _stage_native(tmp_path, monkeypatch, n)
        catalog.write_text(json.dumps({
            "rapplications": [{"id": "my_thing", "version": current_version}],
        }))
        before = catalog.read_bytes()
        n.stream_calls.clear()
        ok, report = prom.promote(event, staging, catalog)
        assert not ok
        assert "E_VERSION_NOT_BUMPED" in report
        assert catalog.read_bytes() == before
        assert not n.stream_calls
        assert not (root / "api").exists()
        assert json.loads((staging / "_pending.json").read_text())["items"]

    def test_approval_rejects_moved_manifest_ref(self, tmp_path, monkeypatch, native_release):
        n = native_release
        root, catalog, staging, event = _stage_native(tmp_path, monkeypatch, n)
        before = catalog.read_bytes()
        n.routes[f"https://api.github.com/repos/{n.repo}/commits/main"] = json.dumps({"sha": "f" * 40}).encode()
        ok, report = prom.promote(event, staging, catalog)
        assert not ok
        assert "E_DESKTOP_STALE_SOURCE" in report
        assert catalog.read_bytes() == before
        assert not (root / "api").exists()

    def test_approval_rejects_edited_issue_payload(self, tmp_path, monkeypatch, native_release):
        _, catalog, staging, event = _stage_native(tmp_path, monkeypatch, native_release)
        before = catalog.read_bytes()
        event["issue"]["body"] = event["issue"]["body"].replace('"version": "0.1.0"', '"version": "9.0.0"')
        ok, report = prom.promote(event, staging, catalog)
        assert not ok
        assert "E_DESKTOP_STALE_ISSUE" in report
        assert catalog.read_bytes() == before

    def test_approval_rejects_changed_release_bytes(self, tmp_path, monkeypatch, native_release):
        n = native_release
        _, catalog, staging, event = _stage_native(tmp_path, monkeypatch, n)
        before = catalog.read_bytes()
        artifact = n.desktop["artifacts"][0]
        n.binaries[artifact["url"]] = b"X" * artifact["bytes"]
        ok, report = prom.promote(event, staging, catalog)
        assert not ok
        assert "E_DESKTOP_HASH_MISMATCH" in report
        assert catalog.read_bytes() == before

    def test_approval_does_not_accept_unreviewed_native_metadata(self, tmp_path, monkeypatch, native_release):
        n = native_release
        _, catalog, staging, event = _stage_native(tmp_path, monkeypatch, n)
        path = staging / "_pending.json"
        data = json.loads(path.read_text())
        data["items"][0]["entry"]["desktop"]["setup"] = ["Different unreviewed setup"]
        path.write_text(json.dumps(data))
        before = catalog.read_bytes()
        ok, report = prom.promote(event, staging, catalog)
        assert not ok
        assert "E_DESKTOP_STALE_PENDING" in report
        assert catalog.read_bytes() == before

    def test_discovery_preflight_failure_keeps_catalog_and_pending(self, tmp_path, monkeypatch, native_release):
        root, catalog, staging, event = _stage_native(tmp_path, monkeypatch, native_release)
        api = root / "api" / "v1"
        api.mkdir(parents=True)
        (api / "index.json").write_text("invalid JSON")
        before = catalog.read_bytes()
        pending = (staging / "_pending.json").read_bytes()
        ok, _ = prom.promote(event, staging, catalog)
        assert not ok
        assert catalog.read_bytes() == before
        assert (staging / "_pending.json").read_bytes() == pending

    def test_submission_payload_must_match_fetched_native_manifest(self, tmp_path, monkeypatch, native_release):
        n = native_release
        monkeypatch.setattr(lib_rapp, "_default_fetcher", lambda: n.fetch)
        monkeypatch.setattr(lib_desktop, "anonymous_chunks", n.stream)
        wrong = copy.deepcopy(n.manifest)
        wrong["version"] = "9.0.0"
        body = _federation_payload(n.repo, n.ref, "my_thing", wrong)
        event = json.loads(_make_event(tmp_path, 102, "alice", "[RAPP] native", body).read_text())
        ok, report = proc.process(event, tmp_path / "staging", tmp_path / "index.json")
        assert not ok
        assert "E_PAYLOAD_MISMATCH" in report
        assert not (tmp_path / "staging").exists()


def test_receiver_requires_rapp_issue_front_door(tmp_path):
    event = {"issue": {"number": 1, "title": "Bypass review", "body": "{}"}}
    ok, report = proc.process(event, tmp_path / "staging", tmp_path / "index.json")
    assert not ok
    assert "E_ISSUE_FRONT_DOOR" in report


def test_bundle_approval_also_rejects_stale_version(tmp_path, make_rapp_dir):
    rapp = make_rapp_dir()
    catalog = tmp_path / "index.json"
    catalog.write_text('{"rapplications":[]}')
    staging = tmp_path / "staging"
    event = json.loads(_make_event(tmp_path, 103, "alice", "[RAPP] my_thing",
                                    _bundle_payload(rapp, "alice")).read_text())
    assert proc.process(event, staging, catalog)[0]
    catalog.write_text('{"rapplications":[{"id":"my_thing","version":"0.2.0"}]}')
    before = catalog.read_bytes()
    ok, report = prom.promote(event, staging, catalog)
    assert not ok
    assert "E_VERSION_NOT_BUMPED" in report
    assert catalog.read_bytes() == before
    assert (staging / "my_thing").is_dir()
