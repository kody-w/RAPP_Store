"""Tests for the @rapp/publish-to-rapp-store agent.

Mocks the network (catalog + GitHub API) so the tests don't reach out and
so the agent's local validation is exercised end-to-end against the same
fixtures as scripts/lib_rapp.py."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import publish_to_rapp_store_agent as agent_mod


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Stop tests from accidentally hitting GitHub or reading real tokens."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_ACTOR", raising=False)
    monkeypatch.setattr(agent_mod, "_fetch_catalog",
                        lambda *_a, **_kw: {"rapplications": []})


@pytest.fixture
def agent():
    return agent_mod.PublishToRappStoreAgent()


# ── validate_local ────────────────────────────────────────────────────────

class TestValidateLocal:
    def test_validate_local_zip_passes(self, agent, spine_dag_zip_bytes, tmp_path):
        z = tmp_path / "spine_dag-1.0.0.zip"
        z.write_bytes(spine_dag_zip_bytes)
        out = json.loads(agent.perform(action="validate_local", path=str(z)))
        assert out["ok"] is True, out
        assert "spine_dag" in out["summary"]

    def test_validate_local_dir_passes(self, agent, spine_dag_extracted):
        out = json.loads(agent.perform(action="validate_local",
                                        path=str(spine_dag_extracted)))
        assert out["ok"] is True, out

    def test_validate_local_missing_path(self, agent):
        out = json.loads(agent.perform(action="validate_local",
                                        path="/no/such/path"))
        assert out["ok"] is False
        assert any("E_PATH_NOT_FOUND" in e for e in out["errors"])

    def test_validate_local_rejects_bad_singleton(self, agent, make_rapp_dir):
        rapp = make_rapp_dir()
        agent_file = rapp / "singleton" / "my_thing_agent.py"
        agent_file.write_text(
            "class MyThingAgent:\n"
            "    def perform(self, **kw): return 'ok'\n"
        )
        out = json.loads(agent.perform(action="validate_local", path=str(rapp)))
        assert out["ok"] is False
        assert any("E_NO_BASIC_AGENT_IMPORT" in e for e in out["errors"])

    def test_validate_local_publisher_check_via_submitter(self, agent, make_rapp_dir):
        rapp = make_rapp_dir(publisher="@alice")
        out = json.loads(agent.perform(action="validate_local",
                                        path=str(rapp), submitter="bob"))
        assert out["ok"] is False
        assert any("E_PUBLISHER_MISMATCH" in e for e in out["errors"])


# ── bundle ────────────────────────────────────────────────────────────────

class TestBundle:
    def test_bundle_produces_round_trippable_zip(self, agent, make_rapp_dir, tmp_path):
        rapp = make_rapp_dir()
        out = json.loads(agent.perform(action="bundle", path=str(rapp)))
        assert out["ok"]
        bundle = Path(out["bundle_path"])
        assert bundle.exists()
        revalidate = json.loads(agent.perform(action="validate_local",
                                                path=str(bundle)))
        assert revalidate["ok"], revalidate


# ── validate_repo (federation) ───────────────────────────────────────────

class TestValidateRepo:
    def test_validate_repo_uses_fetcher_routes(self, agent, monkeypatch,
                                                spine_dag_extracted):
        manifest = (spine_dag_extracted / "manifest.json").read_bytes()
        sing = (spine_dag_extracted / "singleton" / "spine_dag_agent.py").read_bytes()
        commit = json.dumps({"sha": "deadbeef" + "0" * 32}).encode()
        routes = {
            "https://raw.githubusercontent.com/alice/cool/main/spine_dag/manifest.json": manifest,
            "https://raw.githubusercontent.com/alice/cool/main/spine_dag/singleton/spine_dag_agent.py": sing,
            "https://raw.githubusercontent.com/alice/cool/main/spine_dag/ui/index.html": b"<html></html>",
            "https://api.github.com/repos/alice/cool/commits/main": commit,
        }

        def fake_fetch(url, headers=None, timeout=30):
            if url in routes:
                return routes[url]
            raise RuntimeError(f"404 for {url}")

        monkeypatch.setattr(agent_mod, "_http_get", fake_fetch)
        out = json.loads(agent.perform(action="validate_repo",
                                         repo_url="https://github.com/alice/cool/tree/main/spine_dag"))
        assert out["ok"] is True, out
        assert out["source"]["type"] == "federation"
        assert out["source"]["commit_sha"] == "deadbeef" + "0" * 32

    def test_validate_repo_404_on_manifest(self, agent, monkeypatch):
        def fake_fetch(url, headers=None, timeout=30):
            raise RuntimeError(f"404 for {url}")
        monkeypatch.setattr(agent_mod, "_http_get", fake_fetch)
        out = json.loads(agent.perform(action="validate_repo",
                                         repo_url="https://github.com/ghost/repo"))
        assert out["ok"] is False
        assert any("E_FETCH_MANIFEST" in e for e in out["errors"])

    def test_validate_repo_bad_url(self, agent):
        out = json.loads(agent.perform(action="validate_repo",
                                         repo_url="not a url"))
        assert "error" in out


# ── submit_bundle / submit_repo (issue construction) ─────────────────────

class TestSubmit:
    def test_submit_bundle_dry_run_prints_payload(self, agent, make_rapp_dir):
        rapp = make_rapp_dir()
        out = json.loads(agent.perform(action="submit_bundle",
                                         path=str(rapp), dry_run=True))
        assert out["ok"] is True
        assert out["dry_run"] is True
        assert out["title"].startswith("[RAPP] @alice/my_thing v0.1.0")
        assert "mode:bundle" in out["labels"]
        assert "rapplication-submission" in out["labels"]
        assert "Mode:** bundle" in out["body_preview"]

    def test_submit_bundle_no_token_falls_back_to_dry(self, agent, make_rapp_dir):
        rapp = make_rapp_dir()
        out = json.loads(agent.perform(action="submit_bundle",
                                         path=str(rapp)))
        assert out["dry_run"] is True
        assert "no GH_TOKEN" in out["reason"]

    def test_submit_bundle_invalid_returns_errors(self, agent, make_rapp_dir):
        rapp = make_rapp_dir(version="not-semver")
        out = json.loads(agent.perform(action="submit_bundle",
                                         path=str(rapp), dry_run=True))
        assert out["ok"] is False
        assert any("E_BAD_VERSION" in e for e in out["errors"])

    def test_submit_repo_dry_run(self, agent, monkeypatch, spine_dag_extracted):
        manifest = (spine_dag_extracted / "manifest.json").read_bytes()
        sing = (spine_dag_extracted / "singleton" / "spine_dag_agent.py").read_bytes()
        routes = {
            "https://raw.githubusercontent.com/alice/cool/main/spine_dag/manifest.json": manifest,
            "https://raw.githubusercontent.com/alice/cool/main/spine_dag/singleton/spine_dag_agent.py": sing,
            "https://raw.githubusercontent.com/alice/cool/main/spine_dag/ui/index.html": b"<html></html>",
            "https://api.github.com/repos/alice/cool/commits/main": json.dumps({"sha": "a" * 40}).encode(),
        }
        monkeypatch.setattr(agent_mod, "_http_get",
                            lambda url, **kw: routes.get(url) or (_ for _ in ()).throw(RuntimeError("404")))
        out = json.loads(agent.perform(action="submit_repo",
                                         repo_url="https://github.com/alice/cool/tree/main/spine_dag",
                                         dry_run=True))
        assert out["ok"] is True
        assert "mode:federation" in out["labels"]
        assert "Mode:** federation" in out["body_preview"]

    def test_submit_bundle_posts_when_token_set(self, agent, make_rapp_dir,
                                                  monkeypatch):
        rapp = make_rapp_dir()
        monkeypatch.setenv("GH_TOKEN", "ghp_fake")
        captured = {}

        def fake_post(url, payload, token):
            captured["url"] = url
            captured["payload"] = payload
            captured["token"] = token
            return {"number": 42, "html_url": "https://github.com/kody-w/rapp_store/issues/42"}

        monkeypatch.setattr(agent_mod, "_http_post", fake_post)
        out = json.loads(agent.perform(action="submit_bundle", path=str(rapp)))
        assert out["ok"] is True
        assert out["issue"] == 42
        assert captured["token"] == "ghp_fake"
        assert captured["url"].endswith("/repos/kody-w/rapp_store/issues")
        assert captured["payload"]["title"].startswith("[RAPP]")
        assert "mode:bundle" in captured["payload"]["labels"]


# ── status ────────────────────────────────────────────────────────────────

class TestStatus:
    def test_status_parses_labels(self, agent, monkeypatch):
        def fake_get(url, **kw):
            return json.dumps({
                "title": "[RAPP] @alice/foo v0.1.0",
                "state": "closed",
                "labels": [{"name": "approved"}, {"name": "rapplication-submission"}],
                "html_url": "https://github.com/kody-w/rapp_store/issues/42",
            }).encode()
        monkeypatch.setattr(agent_mod, "_http_get", fake_get)
        out = json.loads(agent.perform(action="status", issue_number=42))
        assert out["approved"] is True
        assert out["rejected"] is False
        assert "approved" in out["labels"]


# ── unknown action / spec ────────────────────────────────────────────────

class TestMisc:
    def test_unknown_action(self, agent):
        out = json.loads(agent.perform(action="nope"))
        assert "error" in out

    def test_spec(self, agent):
        out = agent.perform(action="spec")
        assert "SPEC.md" in out
