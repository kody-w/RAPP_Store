"""Pytest fixtures for rapplication validator tests."""
import json
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
