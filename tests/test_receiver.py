"""End-to-end tests for the receiver scripts (process + promote).

These simulate a GitHub Actions issue event by writing an event JSON to a
tmp file and invoking the script's main(). Both bundle and federation
paths are covered, including the staging → main promotion."""
from __future__ import annotations

import base64
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

import process_rapplication as proc
import promote_rapplication as prom


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
