"""Pytest fixtures for rapplication validator tests."""
import json
import hashlib
import shutil
import sys
import types
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "publish_to_rapp_store" / "singleton"))


# Stub the host-provided BasicAgent so we can import the agent module under
# test without the brainstem on sys.path. Mirrors the `super().__init__(...)`
# signature the agent's __init__ uses.
def _install_basic_agent_stub():
    class _StubBasicAgent:
        def __init__(self, name=None, metadata=None, *args, **kwargs):
            self.name = name
            self.metadata = metadata or {}

        def perform(self, **kwargs):  # pragma: no cover - subclass overrides
            raise NotImplementedError

    for modname in ("basic_agent", "agents.basic_agent",
                    "openrappter.agents.basic_agent"):
        mod = types.ModuleType(modname)
        mod.BasicAgent = _StubBasicAgent
        sys.modules[modname] = mod
    # Make sure 'agents' and 'openrappter.agents' resolve as packages.
    pkg = types.ModuleType("agents")
    pkg.basic_agent = sys.modules["agents.basic_agent"]
    sys.modules["agents"] = pkg
    op = types.ModuleType("openrappter")
    op_agents = types.ModuleType("openrappter.agents")
    op_agents.basic_agent = sys.modules["openrappter.agents.basic_agent"]
    op.agents = op_agents
    sys.modules["openrappter"] = op
    sys.modules["openrappter.agents"] = op_agents


_install_basic_agent_stub()

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def spine_dag_zip_bytes() -> bytes:
    return (FIXTURES / "spine_dag-1.0.0.zip").read_bytes()


@pytest.fixture
def spine_dag_extracted(tmp_path) -> Path:
    """Extract spine_dag-1.0.0.zip into tmp_path and return the rapp dir."""
    z = FIXTURES / "spine_dag-1.0.0.zip"
    with zipfile.ZipFile(z) as zf:
        zf.extractall(tmp_path)
    return tmp_path / "spine_dag"


@pytest.fixture
def make_rapp_dir(tmp_path):
    """Factory: build a minimal valid rapp dir at tmp_path/<id>/.

    Caller can override fields by passing kwargs that get merged into the
    manifest. Returns the rapp_dir Path.
    """
    def _make(rapp_id="my_thing", **overrides):
        rapp_dir = tmp_path / rapp_id
        rapp_dir.mkdir()
        (rapp_dir / "singleton").mkdir()

        manifest = {
            "schema": "rapp-application/1.0",
            "id": rapp_id,
            "name": "MyThing",
            "version": "0.1.0",
            "publisher": "@alice",
            "summary": "A test rapplication.",
            "category": "analysis",
            "tags": ["rapplication", "test"],
            "agent": f"singleton/{rapp_id}_agent.py",
            # Default to declaring a UI so the bundle test passes; tests that
            # need a bare agent override this.
            "ui": "ui/index.html",
        }
        manifest.update(overrides)
        (rapp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        agent_src = f'''"""Test rapp {rapp_id}."""
from agents.basic_agent import BasicAgent

__manifest__ = {{
    "schema": "rapp-agent/1.0",
    "name": "@alice/{rapp_id}",
    "version": "0.1.0",
    "description": "test",
}}


class {rapp_id.title().replace("_", "")}Agent(BasicAgent):
    def __init__(self):
        self.name = "{rapp_id}"
        self.metadata = {{"name": self.name, "description": "test", "parameters": {{}}}}

    def perform(self, **kwargs):
        return "ok"
'''
        (rapp_dir / "singleton" / f"{rapp_id}_agent.py").write_text(agent_src)
        (rapp_dir / "index_entry.json").write_text(json.dumps({
            "id": rapp_id, "name": manifest["name"], "version": manifest["version"],
            "summary": manifest["summary"], "category": manifest["category"],
            "tags": manifest["tags"],
            "singleton_filename": f"{rapp_id}_agent.py",
            "singleton_url": f"https://raw.githubusercontent.com/kody-w/rapp_store/main/{rapp_id}/singleton/{rapp_id}_agent.py",
        }, indent=2))
        (rapp_dir / "README.md").write_text(f"# {manifest['name']}\n\nA test rapp.\n")
        if manifest.get("ui"):
            ui_path = rapp_dir / manifest["ui"]
            ui_path.parent.mkdir(parents=True, exist_ok=True)
            ui_path.write_text("<html><body>test</body></html>")
        return rapp_dir
    return _make


@pytest.fixture
def fake_fetcher():
    """Build a fetcher that serves a dict of {url: bytes} for federation tests."""
    def _build(routes: dict):
        def fetch(url: str):
            from lib_rapp import FetchError
            if url in routes:
                v = routes[url]
                return v if isinstance(v, bytes) else v.encode("utf-8")
            raise FetchError(f"HTTP 404 for {url}")
        return fetch
    return _build


@pytest.fixture
def native_release(make_rapp_dir, fake_fetcher):
    """Tiny in-memory test doubles, never real release binaries or Apple evidence."""
    import lib_rapp

    rapp_dir = make_rapp_dir()
    manifest = json.loads((rapp_dir / "manifest.json").read_text())
    repo, ref = "alice/native-app", "main"
    commit, native_commit = "b" * 40, "a" * 40
    desktop = {
        "schema": "rapp-desktop/1.0",
        "platform": "macos",
        "minimum_os": "14.0",
        "bundle_id": "dev.example.mything",
        "source": {"repo": repo, "commit_sha": native_commit},
        "release_tag": "v0.1.0",
        "prerequisites": ["A supported Mac; no Python is needed to launch the app."],
        "privacy": "Fixture disclosure: captured data stays local; permissions are requested explicitly.",
        "setup": ["Open the DMG, move the application to Applications, then launch it."],
        "agent_integration": "Optional Python integration uses a separately installed brainstem.",
        "artifacts": [],
    }
    manifest["desktop"] = desktop
    routes, binaries, reports = {}, {}, {}
    api_release = {
        "tag_name": desktop["release_tag"], "draft": False, "prerelease": False,
        "html_url": f"https://github.com/{repo}/releases/tag/{desktop['release_tag']}",
        "assets": [],
    }
    authority = "Developer ID Application: Fixture Publisher (TESTTEAM01)"
    run = {
        "html_url": f"https://github.com/{repo}/actions/runs/123",
        "repository": {"full_name": repo},
        "head_sha": native_commit, "status": "completed", "conclusion": "success",
    }
    for arch in ("arm64", "x86_64"):
        filename = f"my_thing-0.1.0-{arch}.dmg"
        url = f"https://github.com/{repo}/releases/download/v0.1.0/{filename}"
        blob = f"NOT A DMG: {arch} unit test bytes".encode()
        binaries[url] = blob
        artifact = {
            "arch": arch, "format": "dmg", "url": url, "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "evidence": {"url": url[:-4] + ".evidence.json", "bytes": 1, "sha256": "0" * 64},
        }
        subject = {key: artifact[key] for key in ("arch", "url", "bytes", "sha256")}
        subject.update(id=manifest["id"], version=manifest["version"], bundle_id=desktop["bundle_id"])
        reports[arch] = {
            "schema": "rapp-desktop-evidence/1.0",
            "subject": subject,
            "source": dict(desktop["source"]),
            "workflow_run": run["html_url"],
            "signing": {
                "team_id": "TESTTEAM01", "authority": authority, "architectures": [arch],
                "codesign_details": (f"Identifier={desktop['bundle_id']}\nAuthority={authority}\n"
                                     "TeamIdentifier=TESTTEAM01\nCodeDirectory flags=0x10000(runtime)\n"),
                "codesign_verify": {"exit_code": 0, "output": "Fixture.app: valid on disk\nFixture.app: satisfies its Designated Requirement"},
            },
            "notarization": {
                "submission_id": "00000000-0000-4000-8000-000000000001",
                "submitted_sha256": "c" * 64,
                "log": {
                    "logFormatVersion": 1,
                    "jobId": "00000000-0000-4000-8000-000000000001",
                    "status": "Accepted", "statusCode": 0, "archiveFilename": filename,
                    "sha256": "c" * 64, "issues": None,
                },
            },
            "gatekeeper": {"exit_code": 0, "output": f"Fixture.app: accepted\nsource=Notarized Developer ID\norigin={authority}"},
            "stapler": {"exit_code": 0, "output": "The validate action worked!"},
        }
        desktop["artifacts"].append(artifact)

    def refresh():
        api_release["assets"] = []
        for artifact in desktop["artifacts"]:
            report = reports.get((artifact["arch"], artifact["format"]), reports[artifact["arch"]])
            blob = json.dumps(report, sort_keys=True).encode()
            evidence = artifact["evidence"]
            evidence["bytes"] = len(blob)
            evidence["sha256"] = hashlib.sha256(blob).hexdigest()
            routes[evidence["url"]] = blob
            for item in (artifact, evidence):
                api_release["assets"].append({
                    "name": item["url"].rsplit("/", 1)[1], "browser_download_url": item["url"],
                    "size": item["bytes"], "state": "uploaded", "digest": "sha256:" + item["sha256"],
                })
        routes[f"https://api.github.com/repos/{repo}/commits/{ref}"] = json.dumps({"sha": commit}).encode()
        routes[f"https://api.github.com/repos/{repo}/commits/{commit}"] = json.dumps({"sha": commit}).encode()
        routes[f"https://api.github.com/repos/{repo}/commits/v0.1.0"] = json.dumps({"sha": native_commit}).encode()
        routes[f"https://api.github.com/repos/{repo}/releases/tags/v0.1.0"] = json.dumps(api_release).encode()
        routes[f"https://api.github.com/repos/{repo}/actions/runs/123"] = json.dumps(run).encode()
        for source_ref in (ref, commit):
            base = f"https://raw.githubusercontent.com/{repo}/{source_ref}/my_thing"
            routes[f"{base}/manifest.json"] = json.dumps(manifest).encode()
            for key in ("agent", "ui"):
                routes[f"{base}/{manifest[key]}"] = (rapp_dir / manifest[key]).read_bytes()
        (rapp_dir / "manifest.json").write_text(json.dumps(manifest))

    stream_calls = []

    def stream(url):
        stream_calls.append(url)
        return iter([binaries[url]])

    def entry():
        return lib_rapp._rewrite_for_federation(
            lib_rapp.build_index_entry(manifest, lib_rapp.compute_integrity(rapp_dir, manifest), manifest["id"]),
            manifest, repo, ref, "my_thing", commit)

    refresh()
    return types.SimpleNamespace(
        manifest=manifest, desktop=desktop, repo=repo, ref=ref, commit=commit,
        native_commit=native_commit, routes=routes, binaries=binaries, reports=reports,
        api_release=api_release, run=run, rapp_dir=rapp_dir, refresh=refresh,
        fetch=fake_fetcher(routes), stream=stream, stream_calls=stream_calls, entry=entry,
    )


@pytest.fixture
def native_zip_release(native_release):
    """The ZIP test double has an app staple, never a fabricated archive ticket."""
    n = native_release
    app = "MyThing.app"
    n.desktop["setup"] = [
        "In Finder, double-click the ZIP, then drag MyThing.app to Applications and launch it.",
    ]
    for artifact in n.desktop["artifacts"]:
        arch = artifact["arch"]
        blob = f"NOT A REAL ZIP: {arch} metadata test double".encode()
        artifact.update(
            format="zip", url=artifact["url"][:-4] + ".zip",
            bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest(),
        )
        n.binaries[artifact["url"]] = blob
        artifact["evidence"]["url"] = artifact["url"] + ".evidence.json"
        report = n.reports[arch]
        report["subject"].update({key: artifact[key] for key in ("url", "bytes", "sha256")})
        report["notarization"] = {
            "method": "stapled-app", "app_path": app,
            "bundle_id": n.desktop["bundle_id"], "version": n.manifest["version"],
            "minimum_os": n.desktop["minimum_os"],
        }
        signing = report["signing"]
        signing["codesign_details"] = f"Executable=/fixture/{app}/Contents/MacOS/MyThing\n" + signing["codesign_details"]
        signing["codesign_verify"]["output"] = signing["codesign_verify"]["output"].replace("Fixture.app", app)
        report["gatekeeper"]["output"] = report["gatekeeper"]["output"].replace("Fixture.app", app)
        report["stapler"]["output"] = f"Processing: /fixture/{app}\nThe validate action worked!"
    n.refresh()
    return n
