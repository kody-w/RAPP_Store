"""Tests for scripts/lib_rapp.py — the canonical SPEC.md validator."""
import io
import copy
import json
import zipfile
from pathlib import Path

import pytest

import lib_rapp


# ── Local-bundle validation ───────────────────────────────────────────────

class TestValidateZipGoldenSpineDag:
    def test_spine_dag_zip_validates(self, spine_dag_zip_bytes, tmp_path):
        result = lib_rapp.validate_zip(spine_dag_zip_bytes, extract_to=tmp_path)
        assert result.ok, f"spine_dag should validate; errors: {result.errors}"
        assert result.manifest["id"] == "spine_dag"
        assert result.manifest["version"] == "1.0.0"
        assert result.rapp_dir is not None
        assert result.rapp_dir.name == "spine_dag"

    def test_spine_dag_integrity_computed(self, spine_dag_zip_bytes, tmp_path):
        result = lib_rapp.validate_zip(spine_dag_zip_bytes, extract_to=tmp_path)
        # spine_dag's index_entry.json declared sha 3f71c8e6...
        assert result.integrity["singleton_sha256"] == \
            "3f71c8e61bc69f8553bbdaecaf6dd5bdf78b7df29702fbd26ef0c53fc1246776"
        assert result.integrity["singleton_lines"] == 705
        assert result.integrity["singleton_bytes"] == 28216

    def test_spine_dag_index_entry_built(self, spine_dag_zip_bytes, tmp_path):
        result = lib_rapp.validate_zip(spine_dag_zip_bytes, extract_to=tmp_path)
        entry = lib_rapp.build_index_entry(result.manifest, result.integrity, "spine_dag")
        # Per Proposal 0002, URLs land under apps/@<publisher>/<id>/.
        # spine_dag's manifest declares publisher @rapp.
        assert entry["singleton_url"] == \
            "https://raw.githubusercontent.com/kody-w/rapp_store/main/apps/@rapp/spine_dag/singleton/spine_dag_agent.py"
        assert entry["singleton_sha256"] == result.integrity["singleton_sha256"]
        assert entry["ui_url"].endswith("/apps/@rapp/spine_dag/ui/index.html")


class TestValidateBadBundle:
    def test_not_a_zip_rejected(self):
        result = lib_rapp.validate_zip(b"this is not a zip file")
        assert not result.ok
        assert any("E_BAD_ZIP" in e for e in result.errors)

    def test_oversize_bundle_rejected(self):
        big = b"x" * (lib_rapp.MAX_BUNDLE_BYTES + 1)
        result = lib_rapp.validate_zip(big)
        assert not result.ok
        assert any("E_BUNDLE_TOO_LARGE" in e for e in result.errors)

    def test_zip_without_manifest_rejected(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("foo/bar.txt", "hi")
        result = lib_rapp.validate_zip(buf.getvalue(), extract_to=tmp_path)
        assert not result.ok
        assert any("E_NO_MANIFEST" in e for e in result.errors)

    def test_path_traversal_rejected(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../escape.txt", "evil")
        result = lib_rapp.validate_zip(buf.getvalue(), extract_to=tmp_path)
        assert not result.ok
        assert any("E_PATH_TRAVERSAL" in e for e in result.errors)


# ── Manifest field validation ────────────────────────────────────────────

class TestManifestRules:
    def test_minimal_manifest_passes(self, make_rapp_dir):
        rapp = make_rapp_dir()
        result = lib_rapp.validate_dir(rapp)
        assert result.ok, result.errors

    def test_dash_in_id_rejected(self, make_rapp_dir):
        rapp = make_rapp_dir(rapp_id="my_thing", id="my-thing")
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_BAD_ID" in e for e in result.errors)

    def test_uppercase_id_rejected(self, make_rapp_dir):
        rapp = make_rapp_dir(rapp_id="my_thing", id="MyThing")
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_BAD_ID" in e for e in result.errors)

    def test_bad_version_rejected(self, make_rapp_dir):
        rapp = make_rapp_dir(version="1.0")
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_BAD_VERSION" in e for e in result.errors)

    def test_missing_publisher_rejected(self, make_rapp_dir):
        rapp = make_rapp_dir(publisher="alice-no-at-sign")
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_BAD_PUBLISHER" in e for e in result.errors)

    def test_no_entrypoint_rejected(self, make_rapp_dir, tmp_path):
        rapp = make_rapp_dir()
        manifest_path = rapp / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        del manifest["agent"]
        manifest_path.write_text(json.dumps(manifest))
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_NO_ENTRYPOINT" in e for e in result.errors)

    def test_reserved_id_rejected(self, make_rapp_dir):
        # Per Proposal 0002, RESERVED_IDS no longer needs to ban specific rapp
        # ids (binder etc.) — those live under apps/@<publisher>/. Top-level
        # repo dir names (scripts, tests, apps, ...) are still reserved.
        rapp = make_rapp_dir(rapp_id="apps", id="apps",
                             agent="singleton/apps_agent.py")
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_RESERVED_ID" in e for e in result.errors)

    def test_dir_name_must_match_id(self, make_rapp_dir):
        rapp = make_rapp_dir(rapp_id="my_thing", id="other_id")
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_DIR_NAME_MISMATCH" in e for e in result.errors)

    def test_category_must_be_in_enum(self, make_rapp_dir):
        rapp = make_rapp_dir(category="creative-pipeline")  # old, no longer accepted
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_UNKNOWN_CATEGORY" in e for e in result.errors)

    @pytest.mark.parametrize("cat", [
        "productivity", "creative", "analysis", "data",
        "integration", "platform", "workspace",
    ])
    def test_locked_categories_accepted(self, make_rapp_dir, cat):
        rapp = make_rapp_dir(category=cat)
        result = lib_rapp.validate_dir(rapp)
        assert result.ok, (cat, result.errors)


class TestQualityTierDowngrade:
    @pytest.mark.parametrize("declared,expected", [
        ("featured", "community"),
        ("official", "community"),
        ("verified", "community"),
        ("community", "community"),
        ("experimental", "experimental"),
        ("deprecated", "deprecated"),
        (None, "community"),
        ("", "community"),
    ])
    def test_downgrade_caps_at_community(self, declared, expected):
        assert lib_rapp.downgrade_tier_for_submission(declared) == expected

    def test_build_index_entry_downgrades(self, make_rapp_dir):
        rapp = make_rapp_dir(quality_tier="featured")
        result = lib_rapp.validate_dir(rapp)
        entry = lib_rapp.build_index_entry(result.manifest, result.integrity, "my_thing")
        # Submitter declared 'featured' but the receiver downgrades to 'community'
        assert entry["quality_tier"] == "community"

    def test_build_index_entry_preserves_experimental(self, make_rapp_dir):
        rapp = make_rapp_dir(quality_tier="experimental")
        result = lib_rapp.validate_dir(rapp)
        entry = lib_rapp.build_index_entry(result.manifest, result.integrity, "my_thing")
        assert entry["quality_tier"] == "experimental"


# ── Singleton AST contract ────────────────────────────────────────────────

class TestSingletonContract:
    def test_singleton_without_basicagent_import_rejected(self, make_rapp_dir):
        rapp = make_rapp_dir()
        agent_file = rapp / "singleton" / "my_thing_agent.py"
        agent_file.write_text(
            'class MyThingAgent:\n'
            '    def perform(self, **kw): return "ok"\n'
            '__manifest__ = {"schema": "rapp-agent/1.0", "name": "x", "version": "0.1.0", "description": "x"}\n'
        )
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_NO_BASIC_AGENT_IMPORT" in e for e in result.errors)

    def test_singleton_without_perform_rejected(self, make_rapp_dir):
        rapp = make_rapp_dir()
        agent_file = rapp / "singleton" / "my_thing_agent.py"
        agent_file.write_text(
            'from agents.basic_agent import BasicAgent\n'
            '__manifest__ = {"schema": "rapp-agent/1.0", "name": "x", "version": "0.1.0", "description": "x"}\n'
            'class MyThingAgent(BasicAgent):\n'
            '    def __init__(self): pass\n'
        )
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_NO_PERFORM" in e for e in result.errors)

    def test_singleton_without_manifest_rejected(self, make_rapp_dir):
        rapp = make_rapp_dir()
        agent_file = rapp / "singleton" / "my_thing_agent.py"
        agent_file.write_text(
            'from agents.basic_agent import BasicAgent\n'
            'class MyThingAgent(BasicAgent):\n'
            '    def perform(self, **kw): return "ok"\n'
        )
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_NO_INTERNAL_MANIFEST" in e for e in result.errors)

    def test_singleton_with_template_placeholder_rejected(self, make_rapp_dir):
        rapp = make_rapp_dir()
        agent_file = rapp / "singleton" / "my_thing_agent.py"
        agent_file.write_text(agent_file.read_text().replace(
            '"description": "test"',
            '"description": "YOUR LOGIC GOES HERE"'
        ))
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_TEMPLATE_PLACEHOLDER" in e for e in result.errors)

    def test_singleton_syntax_error_rejected(self, make_rapp_dir):
        rapp = make_rapp_dir()
        agent_file = rapp / "singleton" / "my_thing_agent.py"
        agent_file.write_text(
            'from agents.basic_agent import BasicAgent\n'
            '__manifest__ = {"schema": "rapp-agent/1.0", "name": "x", "version": "0.1.0", "description": "x"}\n'
            'class MyThingAgent(BasicAgent):\n'
            '    def perform(self, **kw broken syntax here\n'
        )
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_SINGLETON_SYNTAX" in e for e in result.errors)

    def test_two_public_agent_classes_rejected(self, make_rapp_dir):
        rapp = make_rapp_dir()
        agent_file = rapp / "singleton" / "my_thing_agent.py"
        agent_file.write_text(
            'from agents.basic_agent import BasicAgent\n'
            '__manifest__ = {"schema": "rapp-agent/1.0", "name": "x", "version": "0.1.0", "description": "x"}\n'
            'class FirstAgent(BasicAgent):\n'
            '    def perform(self, **kw): return "a"\n'
            'class SecondAgent(BasicAgent):\n'
            '    def perform(self, **kw): return "b"\n'
        )
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_MULTIPLE_AGENT_CLASSES" in e for e in result.errors)

    def test_validator_marker_opts_out_of_placeholder_check(self, make_rapp_dir):
        rapp = make_rapp_dir()
        agent_file = rapp / "singleton" / "my_thing_agent.py"
        agent_file.write_text(
            '# rapp-validator: allow-template-placeholders\n'
            'from agents.basic_agent import BasicAgent\n'
            '__manifest__ = {"schema": "rapp-agent/1.0", "name": "x", "version": "0.1.0", "description": "x"}\n'
            'PLACEHOLDERS = ("{{PLACEHOLDER}}", "YOUR LOGIC GOES HERE")\n'
            'class MyThingAgent(BasicAgent):\n'
            '    def perform(self, **kw): return PLACEHOLDERS[0]\n'
        )
        result = lib_rapp.validate_dir(rapp)
        assert result.ok, result.errors

    def test_internal_helper_classes_allowed(self, make_rapp_dir):
        rapp = make_rapp_dir()
        agent_file = rapp / "singleton" / "my_thing_agent.py"
        agent_file.write_text(
            'from agents.basic_agent import BasicAgent\n'
            '__manifest__ = {"schema": "rapp-agent/1.0", "name": "x", "version": "0.1.0", "description": "x"}\n'
            'class _InternalHelper(BasicAgent):\n'
            '    def perform(self, **kw): return "internal"\n'
            'class MyThingAgent(BasicAgent):\n'
            '    def perform(self, **kw): return "public"\n'
        )
        result = lib_rapp.validate_dir(rapp)
        assert result.ok, result.errors


# ── Publisher identity ────────────────────────────────────────────────────

class TestPublisherIdentity:
    def test_publisher_must_match_submitter(self, make_rapp_dir):
        rapp = make_rapp_dir(publisher="@alice")
        ok = lib_rapp.validate_dir(rapp, expected_publisher="@alice")
        assert ok.ok, ok.errors
        bad = lib_rapp.validate_dir(rapp, expected_publisher="@bob")
        assert not bad.ok
        assert any("E_PUBLISHER_MISMATCH" in e for e in bad.errors)

    def test_official_publisher_reserved(self, make_rapp_dir):
        rapp = make_rapp_dir(publisher="@rapp")
        bad = lib_rapp.validate_dir(rapp, expected_publisher="@randomperson")
        assert not bad.ok
        assert any("E_PUBLISHER_MISMATCH" in e for e in bad.errors)

    def test_kody_w_can_publish_as_rapp(self, make_rapp_dir):
        rapp = make_rapp_dir(publisher="@rapp")
        ok = lib_rapp.validate_dir(rapp, expected_publisher="@kody-w")
        assert ok.ok, ok.errors


# ── Version bump enforcement ──────────────────────────────────────────────

class TestVersionBump:
    def test_resubmit_must_bump_version(self, make_rapp_dir):
        rapp = make_rapp_dir(version="0.1.0")
        catalog = {"rapplications": [{"id": "my_thing", "version": "0.1.0"}]}
        result = lib_rapp.validate_dir(rapp, existing_catalog=catalog)
        assert not result.ok
        assert any("E_VERSION_NOT_BUMPED" in e for e in result.errors)

    def test_resubmit_with_higher_version_passes(self, make_rapp_dir):
        rapp = make_rapp_dir(version="0.2.0")
        catalog = {"rapplications": [{"id": "my_thing", "version": "0.1.0"}]}
        result = lib_rapp.validate_dir(rapp, existing_catalog=catalog)
        assert result.ok, result.errors

    def test_first_submission_passes(self, make_rapp_dir):
        rapp = make_rapp_dir(version="0.1.0")
        catalog = {"rapplications": []}
        result = lib_rapp.validate_dir(rapp, existing_catalog=catalog)
        assert result.ok, result.errors


# ── Federation (repo URL) ────────────────────────────────────────────────

class TestFederation:
    def test_parse_repo_url_simple(self):
        repo, ref, path = lib_rapp.parse_repo_url("https://github.com/alice/cool-rapps")
        assert (repo, ref, path) == ("alice/cool-rapps", "main", "")

    def test_parse_repo_url_with_tree(self):
        repo, ref, path = lib_rapp.parse_repo_url(
            "https://github.com/alice/cool-rapps/tree/develop/sub/dir")
        assert (repo, ref, path) == ("alice/cool-rapps", "develop", "sub/dir")

    def test_parse_repo_url_invalid(self):
        with pytest.raises(ValueError):
            lib_rapp.parse_repo_url("not a url")

    def test_federation_validates_via_fetcher(self, fake_fetcher, spine_dag_extracted):
        manifest = (spine_dag_extracted / "manifest.json").read_bytes()
        agent = (spine_dag_extracted / "singleton" / "spine_dag_agent.py").read_bytes()
        ui = (spine_dag_extracted / "ui" / "index.html").read_bytes()
        commit_payload = json.dumps({"sha": "abc123" + "0" * 34}).encode()
        routes = {
            "https://raw.githubusercontent.com/alice/cool-rapps/main/spine_dag/manifest.json": manifest,
            "https://raw.githubusercontent.com/alice/cool-rapps/main/spine_dag/singleton/spine_dag_agent.py": agent,
            "https://raw.githubusercontent.com/alice/cool-rapps/main/spine_dag/ui/index.html": ui,
            "https://api.github.com/repos/alice/cool-rapps/commits/main": commit_payload,
        }
        # spine_dag's manifest declares publisher @rapp; for federation we pretend
        # the submitter is @rapp (or skip the check)
        result = lib_rapp.validate_federation(
            "alice/cool-rapps", ref="main", path="spine_dag",
            fetcher=fake_fetcher(routes))
        assert result.ok, result.errors
        assert result.index_entry["source"]["type"] == "federation"
        assert result.index_entry["source"]["repo"] == "alice/cool-rapps"
        assert result.index_entry["source"]["commit_sha"] == "abc123" + "0" * 34
        assert result.index_entry["singleton_url"] == \
            "https://raw.githubusercontent.com/alice/cool-rapps/main/spine_dag/singleton/spine_dag_agent.py"
        # SHA256 must come from the actual fetched bytes
        assert result.index_entry["singleton_sha256"] == \
            "3f71c8e61bc69f8553bbdaecaf6dd5bdf78b7df29702fbd26ef0c53fc1246776"

    def test_federation_404_on_manifest_rejected(self, fake_fetcher):
        result = lib_rapp.validate_federation(
            "ghost/repo", fetcher=fake_fetcher({}))
        assert not result.ok
        assert any("E_FETCH_MANIFEST" in e for e in result.errors)

    def test_federation_bad_repo_format_rejected(self, fake_fetcher):
        result = lib_rapp.validate_federation(
            "not_a_repo", fetcher=fake_fetcher({}))
        assert not result.ok
        assert any("E_BAD_REPO" in e for e in result.errors)


# ── Bare-agent rejection (Constitution XXVII) ────────────────────────────

class TestUIRequired:
    """SPEC §6 rule 11: rapplications must ship a UI."""

    def test_no_ui_rejected(self, make_rapp_dir):
        rapp = make_rapp_dir()
        manifest_path = rapp / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        del manifest["ui"]
        manifest_path.write_text(json.dumps(manifest))
        import shutil
        shutil.rmtree(rapp / "ui", ignore_errors=True)
        result = lib_rapp.validate_dir(rapp)
        assert not result.ok
        assert any("E_NO_UI" in e for e in result.errors)

    def test_with_ui_declared_passes(self, make_rapp_dir):
        rapp = make_rapp_dir()  # default has ui
        result = lib_rapp.validate_dir(rapp)
        assert result.ok, result.errors

    def test_rejection_directs_to_RAR(self, make_rapp_dir):
        rapp = make_rapp_dir()
        manifest_path = rapp / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        del manifest["ui"]
        manifest_path.write_text(json.dumps(manifest))
        import shutil
        shutil.rmtree(rapp / "ui", ignore_errors=True)
        result = lib_rapp.validate_dir(rapp)
        no_ui_err = next((e for e in result.errors if "E_NO_UI" in e), "")
        assert "RAR" in no_ui_err

    def test_federation_no_ui_rejected(self, fake_fetcher):
        bare_manifest = json.dumps({
            "schema": "rapp-application/1.0",
            "id": "bare_thing",
            "name": "BareThing",
            "version": "0.1.0",
            "publisher": "@alice",
            "summary": "no UI",
            "category": "analysis",
            "tags": ["rapplication"],
            "agent": "singleton/bare_thing_agent.py",
        }).encode()
        bare_agent = (
            'from agents.basic_agent import BasicAgent\n'
            '__manifest__ = {"schema": "rapp-agent/1.0", "name": "x", "version": "0.1.0", "description": "x"}\n'
            'class BareThingAgent(BasicAgent):\n'
            '    def perform(self, **kw): return "ok"\n'
        ).encode()
        routes = {
            "https://raw.githubusercontent.com/alice/repo/main/manifest.json": bare_manifest,
            "https://raw.githubusercontent.com/alice/repo/main/singleton/bare_thing_agent.py": bare_agent,
            "https://api.github.com/repos/alice/repo/commits/main": json.dumps({"sha": "x" * 40}).encode(),
        }
        result = lib_rapp.validate_federation("alice/repo",
                                                fetcher=fake_fetcher(routes))
        assert not result.ok
        assert any("E_NO_UI" in e for e in result.errors)


# ── Catalog merge ─────────────────────────────────────────────────────────

class TestCatalogMerge:
    def test_merge_appends_new_entry(self):
        cat = {"rapplications": [{"id": "old", "version": "1.0.0"}]}
        new = {"id": "new", "version": "0.1.0"}
        out = lib_rapp.merge_index_entry(cat, new)
        ids = [r["id"] for r in out["rapplications"]]
        assert ids == ["old", "new"]  # appended, original order preserved

    def test_merge_replaces_in_place_preserves_order(self):
        cat = {"rapplications": [
            {"id": "a", "version": "1.0.0"},
            {"id": "b", "version": "1.0.0"},
            {"id": "c", "version": "1.0.0"},
        ]}
        new = {"id": "b", "version": "2.0.0"}
        out = lib_rapp.merge_index_entry(cat, new)
        ids = [r["id"] for r in out["rapplications"]]
        assert ids == ["a", "b", "c"]
        versions = [r["version"] for r in out["rapplications"]]
        assert versions == ["1.0.0", "2.0.0", "1.0.0"]

    def test_merge_replaces_existing_entry(self):
        cat = {"rapplications": [{"id": "thing", "version": "1.0.0", "old": True}]}
        new = {"id": "thing", "version": "1.1.0", "fresh": True}
        out = lib_rapp.merge_index_entry(cat, new)
        assert len(out["rapplications"]) == 1
        assert out["rapplications"][0] == new


# ── Bundling round-trip ───────────────────────────────────────────────────

class TestBundling:
    def test_bundle_dir_round_trips(self, make_rapp_dir, tmp_path):
        rapp = make_rapp_dir()
        blob = lib_rapp.bundle_dir(rapp)
        result = lib_rapp.validate_zip(blob, extract_to=tmp_path / "extracted")
        assert result.ok, result.errors
        assert result.manifest["id"] == "my_thing"


class TestMetadataPassThrough:
    def test_extra_metadata_survives_without_overriding_receiver_fields(self, make_rapp_dir):
        rapp = make_rapp_dir(
            runtime="twin", tool={"name": "fixture"}, homepage="https://example.com",
            custom_metadata={"nested": [1, 2]}, singleton_sha256="spoof",
            singleton_url="https://example.com/not-the-agent.py",
            source={"repo": "spoof/repo"}, ui_sha256="spoof", quality_tier="official",
        )
        result = lib_rapp.validate_dir(rapp)
        assert result.ok, result.errors
        entry = lib_rapp.build_index_entry(result.manifest, result.integrity, "my_thing")
        assert entry["runtime"] == "twin"
        assert entry["tool"] == {"name": "fixture"}
        assert entry["homepage"] == "https://example.com"
        assert entry["custom_metadata"] == {"nested": [1, 2]}
        assert entry["singleton_sha256"] == result.integrity["singleton_sha256"]
        assert entry["ui_sha256"] == result.integrity["ui_sha256"]
        assert entry["ui_bytes"] == result.integrity["ui_bytes"]
        assert entry["singleton_url"].startswith(lib_rapp.CATALOG_RAW_BASE)
        assert "source" not in entry
        assert entry["quality_tier"] == "community"
        entry["custom_metadata"]["nested"].append(3)
        assert result.manifest["custom_metadata"] == {"nested": [1, 2]}


class TestNativeFederation:
    @staticmethod
    def validate(release, **kwargs):
        return lib_rapp.validate_federation(
            release.repo, path="my_thing", fetcher=release.fetch,
            artifact_fetcher=release.stream, **kwargs)

    def test_native_release_is_verified_and_preserved(self, native_release):
        n = native_release
        result = self.validate(n, expected_publisher="@alice")
        assert result.ok, result.errors
        assert result.index_entry["desktop"] == n.desktop
        assert result.index_entry["source"]["commit_sha"] == n.commit
        assert result.index_entry["source"]["ref"] == "main"
        assert f"/{n.commit}/" in result.index_entry["singleton_url"]
        assert f"/{n.commit}/" in result.index_entry["ui_url"]
        assert result.index_entry["ui_sha256"]
        assert len(n.stream_calls) == 2
        assert not {"rappid", "parent_rappid", "egg_url", "hatcher_url"} & result.index_entry.keys()

    def test_local_preflight_uses_same_evidence_verifier(self, native_release):
        n = native_release
        result = lib_rapp.validate_dir(n.rapp_dir, fetcher=n.fetch, artifact_fetcher=n.stream)
        assert result.ok, result.errors
        assert result.index_entry["desktop"] == n.desktop
        assert len(n.stream_calls) == 2

    def test_native_bundle_submission_rejected_without_fetching(self, native_release, tmp_path, monkeypatch):
        monkeypatch.setattr(lib_rapp.lib_desktop, "verify_release",
                            lambda *a, **kw: pytest.fail("native bundles must not fetch"))
        result = lib_rapp.validate_zip(lib_rapp.bundle_dir(native_release.rapp_dir),
                                       extract_to=tmp_path / "extracted-native")
        assert not result.ok
        assert any("E_DESKTOP_FEDERATION_ONLY" in e for e in result.errors)

    def test_local_index_desktop_disagreement_rejected(self, native_release):
        n = native_release
        path = n.rapp_dir / "index_entry.json"
        entry = json.loads(path.read_text())
        entry["desktop"] = {"platform": "windows"}
        path.write_text(json.dumps(entry))
        result = lib_rapp.validate_dir(n.rapp_dir, fetcher=n.fetch, artifact_fetcher=n.stream)
        assert any("E_DESKTOP_INDEX_MISMATCH" in e for e in result.errors)
        assert not n.stream_calls

    @pytest.mark.parametrize("version", ["0.1.0", "0.2.0", "1.0.0"])
    def test_native_version_must_beat_current_catalog(self, native_release, version):
        n = native_release
        result = self.validate(n, existing_catalog={"rapplications": [{"id": "my_thing", "version": version}]})
        assert any("E_VERSION_NOT_BUMPED" in e for e in result.errors)
        assert not n.stream_calls

    @pytest.mark.parametrize("field,value,code", [
        ("bundle_id", "dev.other.mything", "E_DESKTOP_BUNDLE_ID"),
        ("repo", "other/native-app", "E_DESKTOP_REPO"),
        ("publisher", "@other", "E_DESKTOP_PUBLISHER"),
    ])
    def test_native_identity_cannot_drift(self, native_release, field, value, code):
        n = native_release
        prior = copy.deepcopy(n.entry())
        prior["version"] = "0.0.9"
        if field == "repo":
            prior["source"]["repo"] = value
        elif field == "publisher":
            prior["publisher"] = value
        else:
            prior["desktop"][field] = value
        result = self.validate(n, existing_catalog={"rapplications": [prior]})
        assert any(code in e for e in result.errors)
        assert not n.stream_calls

    def test_native_metadata_cannot_be_removed_by_update(self, native_release):
        n = native_release
        prior = n.entry()
        prior["version"] = "0.0.9"
        del n.manifest["desktop"]
        n.refresh()
        result = self.validate(n, existing_catalog={"rapplications": [prior]})
        assert any("E_DESKTOP_REQUIRED" in e for e in result.errors)

    @pytest.mark.parametrize("commit", [None, "abc123", "Z" * 40])
    def test_native_manifest_commit_pin_is_not_best_effort(self, native_release, commit):
        n = native_release
        n.routes[f"https://api.github.com/repos/{n.repo}/commits/main"] = json.dumps({"sha": commit}).encode()
        result = self.validate(n)
        assert any("E_DESKTOP_SOURCE_PIN" in e for e in result.errors)
        assert not n.stream_calls

    def test_native_manifest_moving_during_validation_rejected(self, native_release):
        n = native_release
        n.routes[f"https://raw.githubusercontent.com/{n.repo}/{n.commit}/my_thing/manifest.json"] += b" "
        result = self.validate(n)
        assert any("E_DESKTOP_STALE_SOURCE" in e for e in result.errors)
        assert not n.stream_calls

    def test_expected_manifest_commit_is_enforced(self, native_release):
        result = self.validate(native_release, expected_commit_sha="f" * 40)
        assert any("E_DESKTOP_STALE_SOURCE" in e for e in result.errors)

    def test_singleton_and_native_version_must_match(self, native_release):
        n = native_release
        path = n.rapp_dir / n.manifest["agent"]
        path.write_text(path.read_text().replace('"version": "0.1.0"', '"version": "0.0.1"'))
        n.refresh()
        result = self.validate(n)
        assert any("E_DESKTOP_AGENT_VERSION" in e for e in result.errors)
        assert not n.stream_calls

    @pytest.mark.parametrize("kind,limit,code", [
        ("agent", "MAX_SINGLETON_BYTES", "E_SINGLETON_TOO_LARGE"),
        ("ui", "MAX_UI_BYTES", "E_UI_TOO_LARGE"),
    ])
    def test_native_does_not_raise_integration_caps(self, native_release, monkeypatch, kind, limit, code):
        n = native_release
        monkeypatch.setattr(lib_rapp, limit, 8)
        result = self.validate(n)
        assert any(code in e for e in result.errors)
        assert not n.stream_calls

    def test_local_native_integration_still_has_bundle_cap(self, native_release, monkeypatch):
        n = native_release
        monkeypatch.setattr(lib_rapp, "MAX_BUNDLE_BYTES", 100)
        result = lib_rapp.validate_dir(n.rapp_dir, fetcher=n.fetch, artifact_fetcher=n.stream)
        assert any("E_BUNDLE_TOO_LARGE" in e for e in result.errors)
        assert not n.stream_calls

    def test_native_manifest_rejects_ambiguous_duplicate_keys(self, native_release):
        n = native_release
        url = f"https://raw.githubusercontent.com/{n.repo}/main/my_thing/manifest.json"
        n.routes[url] = n.routes[url].replace(b'"version": "0.1.0"', b'"version": "0.0.9", "version": "0.1.0"')
        result = self.validate(n)
        assert any("E_DESKTOP_JSON" in e for e in result.errors)
        assert not n.stream_calls

    def test_native_agent_symlink_cannot_escape_local_bundle(self, native_release, tmp_path):
        n = native_release
        agent = n.rapp_dir / n.manifest["agent"]
        outside = tmp_path / "outside_agent.py"
        outside.write_bytes(agent.read_bytes())
        agent.unlink()
        agent.symlink_to(outside)
        result = lib_rapp.validate_dir(n.rapp_dir, fetcher=n.fetch, artifact_fetcher=n.stream)
        assert any("E_PATH_TRAVERSAL" in e for e in result.errors)
        assert not n.stream_calls

    def test_local_native_missing_ui_fails_before_release_downloads(self, native_release):
        n = native_release
        manifest = copy.deepcopy(n.manifest)
        del manifest["ui"]
        (n.rapp_dir / "manifest.json").write_text(json.dumps(manifest))
        result = lib_rapp.validate_dir(n.rapp_dir, fetcher=n.fetch, artifact_fetcher=n.stream)
        assert any("E_NO_UI" in e for e in result.errors)
        assert not n.stream_calls

    def test_local_native_nonobject_index_entry_rejected(self, native_release):
        n = native_release
        (n.rapp_dir / "index_entry.json").write_text("[]")
        result = lib_rapp.validate_dir(n.rapp_dir, fetcher=n.fetch, artifact_fetcher=n.stream)
        assert any("E_BAD_INDEX_ENTRY_JSON" in e for e in result.errors)
        assert not n.stream_calls
