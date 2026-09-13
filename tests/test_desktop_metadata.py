"""Native metadata, publisher-evidence bindings and bounded transport tests."""
import copy
import json
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import lib_desktop as desktop


def _set(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


@pytest.mark.parametrize("path,value,code", [
    (("desktop",), None, "E_DESKTOP_SCHEMA"),
    (("desktop",), [], "E_DESKTOP_SCHEMA"),
    (("desktop", "schema"), "rapp-desktop/2.0", "E_DESKTOP_SCHEMA"),
    (("desktop", "platform"), "windows", "E_DESKTOP_SCHEMA"),
    (("desktop", "minimum_os"), "14", "E_DESKTOP_OS"),
    (("desktop", "minimum_os"), 14, "E_DESKTOP_OS"),
    (("desktop", "bundle_id"), "unstable", "E_DESKTOP_BUNDLE_ID"),
    (("desktop", "source"), {}, "E_DESKTOP_SOURCE"),
    (("desktop", "source", "commit_sha"), "main", "E_DESKTOP_SOURCE"),
    (("desktop", "source", "commit_sha"), "A" * 40, "E_DESKTOP_SOURCE"),
    (("desktop", "source", "repo"), "alice/repo/extra", "E_DESKTOP_SOURCE"),
    (("desktop", "source", "repo"), "../repo", "E_DESKTOP_SOURCE"),
    (("desktop", "release_tag"), "latest", "E_DESKTOP_TAG"),
    (("desktop", "release_tag"), "v9.0.0", "E_DESKTOP_TAG"),
    (("desktop", "privacy"), "", "E_DESKTOP_DISCLOSURE"),
    (("desktop", "prerequisites"), [], "E_DESKTOP_DISCLOSURE"),
    (("desktop", "setup"), [None], "E_DESKTOP_DISCLOSURE"),
    (("desktop", "agent_integration"), {}, "E_DESKTOP_DISCLOSURE"),
    (("desktop", "artifacts"), [], "E_DESKTOP_ARTIFACTS"),
    (("desktop", "artifacts", 0, "arch"), "universal", "E_DESKTOP_ARCH"),
    (("desktop", "artifacts", 1, "arch"), "arm64", "E_DESKTOP_ARCH"),
    (("desktop", "artifacts", 0, "arch"), [], "E_DESKTOP_ARCH"),
    (("desktop", "artifacts", 0, "format"), "pkg", "E_DESKTOP_FORMAT"),
    (("desktop", "artifacts", 0, "bytes"), True, "E_DESKTOP_SIZE"),
    (("desktop", "artifacts", 0, "bytes"), 0, "E_DESKTOP_SIZE"),
    (("desktop", "artifacts", 0, "bytes"), -1, "E_DESKTOP_SIZE"),
    (("desktop", "artifacts", 0, "bytes"), 1.5, "E_DESKTOP_SIZE"),
    (("desktop", "artifacts", 0, "bytes"), "100", "E_DESKTOP_SIZE"),
    (("desktop", "artifacts", 0, "bytes"), desktop.MAX_ARTIFACT_BYTES + 1, "E_DESKTOP_SIZE"),
    (("desktop", "artifacts", 0, "sha256"), "a" * 63, "E_DESKTOP_SHA256"),
    (("desktop", "artifacts", 0, "sha256"), "A" * 64, "E_DESKTOP_SHA256"),
    (("desktop", "artifacts", 0, "evidence"), None, "E_DESKTOP_EVIDENCE"),
    (("desktop", "artifacts", 0, "evidence", "bytes"), desktop.MAX_EVIDENCE_BYTES + 1, "E_DESKTOP_SIZE"),
    (("desktop", "artifacts", 0, "evidence", "sha256"), None, "E_DESKTOP_SHA256"),
    (("access",), "private", "E_DESKTOP_PUBLIC_ONLY"),
    (("version",), "00.1.0", "E_DESKTOP_VERSION"),
])
def test_incomplete_or_unsupported_metadata_fails_closed(native_release, path, value, code):
    manifest = copy.deepcopy(native_release.manifest)
    _set(manifest, path, value)
    errors = desktop.validate_metadata(manifest)
    assert any(code in error for error in errors), errors


@pytest.mark.parametrize("replacement", [
    "http://github.com/alice/native-app/releases/download/v0.1.0/my_thing-0.1.0-arm64.dmg",
    "file:///Applications/MyThing.app",
    "javascript:alert(1)",
    "https://github.com/mallory/native-app/releases/download/v0.1.0/my_thing-0.1.0-arm64.dmg",
    "https://github.com/alice/wrong-repo/releases/download/v0.1.0/my_thing-0.1.0-arm64.dmg",
    "https://github.com.evil.example/alice/native-app/releases/download/v0.1.0/my_thing-0.1.0-arm64.dmg",
    "https://token@github.com/alice/native-app/releases/download/v0.1.0/my_thing-0.1.0-arm64.dmg",
    "https://github.com:443/alice/native-app/releases/download/v0.1.0/my_thing-0.1.0-arm64.dmg",
    "https://github.com/alice/native-app/releases/download/v0.1.0/my_thing-0.1.0-x86_64.dmg",
    "https://github.com/alice/native-app/releases/download/v0.1.0/my_thing-0.2.0-arm64.dmg",
    "https://github.com/alice/native-app/releases/download/v0.1.0/my_thing-0.1.0-arm64.dmg?download=1",
    "https://github.com/alice/native-app/releases/download/v0.1.0/my_thing-0.1.0-arm64.dmg#pin",
    "https://github.com/alice/native-app/releases/download/v0.1.0/../my_thing-0.1.0-arm64.dmg",
    "https://github.com/alice/native-app/releases/download/v0.1.0/%6dy_thing-0.1.0-arm64.dmg",
])
def test_release_urls_are_exact_owner_repo_version_architecture_bound(native_release, replacement):
    native_release.desktop["artifacts"][0]["url"] = replacement
    errors = desktop.verify_release(
        native_release.manifest, fetcher=lambda url: pytest.fail("unsafe metadata must not fetch"),
        artifact_fetcher=lambda url: pytest.fail("unsafe metadata must not stream"))
    assert any("E_DESKTOP_URL" in e for e in errors)


@pytest.mark.parametrize("field", ["rappid", "parent_rappid", "ecosystem_acceptance", "egg_url", "hatcher_url", "notarized", "signed", "trust"])
def test_native_distribution_does_not_self_assert_protocol_or_legacy_artifacts(native_release, field):
    native_release.manifest[field] = "unverified-claim"
    assert any("E_DESKTOP_UNSUPPORTED_CLAIM" in e for e in desktop.validate_metadata(native_release.manifest))


def test_arbitrary_desktop_fields_and_unsigned_claims_rejected(native_release):
    native_release.desktop["notarized"] = True
    assert any("E_DESKTOP_SCHEMA" in e for e in desktop.validate_metadata(native_release.manifest))


def test_metadata_repo_matches_federation(native_release):
    errors = desktop.validate_metadata(native_release.manifest, repo="other/source")
    assert any("E_DESKTOP_REPO" in e for e in errors)


@pytest.mark.parametrize("path,value,code", [
    (("subject", "version"), "9.0.0", "E_DESKTOP_EVIDENCE_BINDING"),
    (("subject", "arch"), "x86_64", "E_DESKTOP_EVIDENCE_BINDING"),
    (("subject", "bytes"), 1, "E_DESKTOP_EVIDENCE_BINDING"),
    (("subject", "sha256"), "f" * 64, "E_DESKTOP_EVIDENCE_BINDING"),
    (("subject", "bundle_id"), "dev.other.app", "E_DESKTOP_EVIDENCE_BINDING"),
    (("source", "commit_sha"), "f" * 40, "E_DESKTOP_EVIDENCE_BINDING"),
    (("workflow_run",), "https://github.com/other/repo/actions/runs/123", "E_DESKTOP_WORKFLOW"),
    (("signing",), {"signed": True}, "E_DESKTOP_SIGNING"),
    (("signing", "authority"), "adhoc", "E_DESKTOP_SIGNING"),
    (("signing", "team_id"), "short", "E_DESKTOP_SIGNING"),
    (("signing", "architectures"), ["x86_64"], "E_DESKTOP_SIGNING"),
    (("signing", "codesign_details"), "Identifier=dev.other.app", "E_DESKTOP_SIGNING"),
    (("signing", "codesign_verify", "exit_code"), 1, "E_DESKTOP_SIGNING"),
    (("signing", "codesign_verify", "output"), "signed=true", "E_DESKTOP_SIGNING"),
    (("notarization",), {"status": "Accepted"}, "E_DESKTOP_NOTARIZATION"),
    (("notarization", "log", "status"), "In Progress", "E_DESKTOP_NOTARIZATION"),
    (("notarization", "log", "statusCode"), False, "E_DESKTOP_NOTARIZATION"),
    (("notarization", "log", "jobId"), "different", "E_DESKTOP_NOTARIZATION"),
    (("notarization", "log", "sha256"), "e" * 64, "E_DESKTOP_NOTARIZATION"),
    (("notarization", "log", "archiveFilename"), "wrong-version-arm64.dmg", "E_DESKTOP_NOTARIZATION"),
    (("notarization", "log", "issues"), [{"severity": "error"}], "E_DESKTOP_NOTARIZATION"),
    (("gatekeeper", "output"), "accepted by publisher", "E_DESKTOP_GATEKEEPER"),
    (("gatekeeper", "exit_code"), True, "E_DESKTOP_GATEKEEPER"),
    (("stapler", "output"), "not stapled", "E_DESKTOP_STAPLER"),
])
def test_publisher_reports_must_bind_real_verification_outputs(native_release, path, value, code):
    n = native_release
    _set(n.reports["arm64"], path, value)
    n.refresh()
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any(code in e for e in errors), errors
    assert not n.stream_calls


def test_pre_staple_notary_digest_may_differ_from_final_dmg(native_release):
    n = native_release
    assert n.reports["arm64"]["notarization"]["submitted_sha256"] != n.desktop["artifacts"][0]["sha256"]
    assert desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream) == []


@pytest.mark.parametrize("key,value", [
    ("head_sha", "f" * 40), ("status", "in_progress"), ("conclusion", "failure"),
    ("repository", {"full_name": "other/repo"}), ("html_url", "https://example.com/claim"),
    ("repository", "not-an-object"),
])
def test_build_run_must_be_public_success_for_same_source(native_release, key, value):
    n = native_release
    n.run[key] = value
    n.refresh()
    assert any("E_DESKTOP_WORKFLOW" in e for e in desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream))
    assert not n.stream_calls


@pytest.mark.parametrize("key,value", [
    ("tag_name", "latest"), ("draft", True), ("prerelease", True), ("html_url", "https://example.com/release"),
])
def test_only_published_stable_versioned_releases(native_release, key, value):
    n = native_release
    n.api_release[key] = value
    n.refresh()
    assert any("E_DESKTOP_RELEASE" in e for e in desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream))
    assert not n.stream_calls


def test_tag_must_resolve_to_native_build_commit(native_release):
    n = native_release
    n.routes[f"https://api.github.com/repos/{n.repo}/commits/v0.1.0"] = json.dumps({"sha": "f" * 40}).encode()
    assert any("E_DESKTOP_TAG_COMMIT" in e for e in desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream))


@pytest.mark.parametrize("key,value", [
    ("size", 1), ("size", True), ("digest", "sha256:" + "e" * 64),
    ("name", "other.dmg"), ("state", "new"),
])
def test_release_asset_inventory_must_match_pins(native_release, key, value):
    n = native_release
    n.api_release["assets"][0][key] = value
    n.routes[f"https://api.github.com/repos/{n.repo}/releases/tags/v0.1.0"] = json.dumps(n.api_release).encode()
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any("E_DESKTOP_RELEASE_ASSET" in e for e in errors)
    assert not n.stream_calls


@pytest.mark.parametrize("change,code", [
    (lambda b: b + b" ", "E_DESKTOP_BYTES_MISMATCH"),
    (lambda b: b[:-1], "E_DESKTOP_BYTES_MISMATCH"),
    (lambda b: b"X" + b[1:], "E_DESKTOP_HASH_MISMATCH"),
])
def test_final_binary_stream_must_match_exact_size_and_hash(native_release, change, code):
    n = native_release
    url = n.desktop["artifacts"][0]["url"]
    n.binaries[url] = change(n.binaries[url])
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any(code in e for e in errors)
    assert len(n.stream_calls) == 1


@pytest.mark.parametrize("change,code", [
    (lambda b: b + b" ", "E_DESKTOP_BYTES_MISMATCH"),
    (lambda b: b"X" + b[1:], "E_DESKTOP_HASH_MISMATCH"),
])
def test_evidence_bytes_are_verified_not_just_urls(native_release, change, code):
    n = native_release
    url = n.desktop["artifacts"][0]["evidence"]["url"]
    n.routes[url] = change(n.routes[url])
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any(code in e for e in errors)
    assert not n.stream_calls


def test_stream_stops_and_closes_immediately_after_exact_byte_limit():
    state = []
    def chunks(url):
        try:
            for chunk in (b"ab", b"cd", b"must-not-read"):
                state.append(chunk)
                yield chunk
        finally:
            state.append("closed")
    with pytest.raises(desktop.DesktopError, match="E_DESKTOP_BYTES_MISMATCH"):
        desktop.verify_artifact({"url": "unused", "bytes": 3, "sha256": "f" * 64}, chunks)
    assert state == [b"ab", b"cd", "closed"]


def test_stream_chunk_and_elapsed_time_are_bounded(monkeypatch):
    artifact = {"url": "unused", "bytes": 10, "sha256": "f" * 64}
    with pytest.raises(desktop.DesktopError, match="E_DESKTOP_STREAM"):
        desktop.verify_artifact(artifact, lambda url: iter([b"x" * (desktop.CHUNK_BYTES + 1)]))
    clock = iter([0, desktop.MAX_DOWNLOAD_SECONDS + 1])
    monkeypatch.setattr(desktop, "time", types.SimpleNamespace(monotonic=lambda: next(clock)))
    with pytest.raises(desktop.DesktopError, match="E_DESKTOP_TIMEOUT"):
        desktop.verify_artifact(artifact, lambda url: iter([b"x"]))


@pytest.mark.parametrize("url", ["http://github.com/file", "https://evil.example/file", "file:///etc/passwd", "https://token@github.com/file"])
def test_transport_rejects_unsafe_redirects(url):
    with pytest.raises(desktop.DesktopError, match="E_DESKTOP_REDIRECT"):
        desktop._SafeRedirect().redirect_request(urllib.request.Request("https://github.com/owner/repo"),
                                                  None, 302, "Found", {}, url)


def test_default_transport_is_anonymous_and_sanitizes_errors(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "fixture-token-not-a-credential")
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token-not-a-credential")
    seen = []
    class Opener:
        def open(self, request, timeout):
            seen.append(request)
            raise urllib.error.URLError("fixture-token-not-a-credential")
    monkeypatch.setattr(desktop.urllib.request, "build_opener", lambda *a: Opener())
    with pytest.raises(desktop.DesktopError) as error:
        list(desktop.anonymous_chunks("https://github.com/alice/repo/releases/download/v1.0.0/test.dmg"))
    assert "fixture-token" not in str(error.value)
    assert "Authorization" not in seen[0].headers


def test_schema_contract_fields_match_validator():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    schema = json.loads((root / "schemas" / "desktop.schema.json").read_text())
    assert set(schema["required"]) == desktop.DESKTOP_FIELDS
    artifact = schema["properties"]["artifacts"]["items"]
    assert set(artifact["required"]) == desktop.ARTIFACT_FIELDS
    assert artifact["properties"]["bytes"]["maximum"] == desktop.MAX_ARTIFACT_BYTES
    assert artifact["properties"]["evidence"]["properties"]["bytes"]["maximum"] == desktop.MAX_EVIDENCE_BYTES
    assert artifact["properties"]["format"]["enum"] == list(desktop.ARTIFACT_FORMATS)
    assert schema["properties"]["artifacts"]["maxItems"] == desktop.MAX_ARTIFACTS


@pytest.mark.parametrize("rapp_id", [None, "../escape", "NotSnakeCase"])
def test_metadata_projection_id_cannot_escape_output_directory(native_release, rapp_id):
    native_release.manifest["id"] = rapp_id
    assert any("E_DESKTOP_ID" in e for e in desktop.validate_metadata(native_release.manifest))


def test_metadata_fetch_cap_stops_without_unbounded_buffering(monkeypatch):
    closed = []
    def chunks(url):
        try:
            yield b"too large"
            pytest.fail("reader should stop once metadata cap is exceeded")
        finally:
            closed.append(True)
    monkeypatch.setattr(desktop, "anonymous_chunks", chunks)
    with pytest.raises(desktop.DesktopError, match="E_DESKTOP_METADATA_SIZE"):
        desktop.anonymous_bytes("unused", max_bytes=3)
    assert closed == [True]


@pytest.mark.parametrize("blob", [
    b'{"subject":{"bytes":1,"bytes":2}}',
    b'{"subject":{"bytes":NaN}}',
    b'{"value":Infinity}',
    b"[]",
])
def test_native_evidence_json_is_unambiguous(blob):
    with pytest.raises(desktop.DesktopError, match="E_DESKTOP_JSON"):
        desktop.load_json_object(blob)


def test_zip_supports_stapled_notarized_app_without_a_container_ticket(native_zip_release):
    n = native_zip_release
    assert desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream) == []
    assert len(n.stream_calls) == 2
    for artifact in n.desktop["artifacts"]:
        assert artifact["format"] == "zip"
        assert artifact["evidence"]["url"] == artifact["url"] + ".evidence.json"
        report = n.reports[artifact["arch"]]
        assert report["notarization"]["method"] == "stapled-app"
        assert not {"submission_id", "submitted_sha256", "log"} & report["notarization"].keys()
        assert report["subject"]["sha256"] == artifact["sha256"]


@pytest.mark.parametrize("path,value,code", [
    (("notarization",), {"submission_id": "fake", "submitted_sha256": "a" * 64, "log": {}}, "E_DESKTOP_APP_NOTARIZATION"),
    (("notarization", "method"), "zip-ticket", "E_DESKTOP_APP_NOTARIZATION"),
    (("notarization", "app_path"), "../MyThing.app", "E_DESKTOP_APP_NOTARIZATION"),
    (("notarization", "app_path"), "nested/MyThing.app", "E_DESKTOP_APP_NOTARIZATION"),
    (("notarization", "app_path"), "MyThing.zip", "E_DESKTOP_APP_NOTARIZATION"),
    (("notarization", "app_path"), None, "E_DESKTOP_APP_NOTARIZATION"),
    (("notarization", "bundle_id"), "dev.other.app", "E_DESKTOP_APP_NOTARIZATION"),
    (("notarization", "version"), "9.0.0", "E_DESKTOP_APP_NOTARIZATION"),
    (("notarization", "minimum_os"), "11.0", "E_DESKTOP_APP_NOTARIZATION"),
    (("signing", "codesign_verify", "output"), "Other.app: valid on disk\nOther.app: satisfies its Designated Requirement", "E_DESKTOP_SIGNING"),
    (("signing", "codesign_verify", "output"), "OtherMyThing.app: valid on disk\nOtherMyThing.app: satisfies its Designated Requirement", "E_DESKTOP_SIGNING"),
    (("gatekeeper", "output"), "archive.zip: accepted\nsource=Notarized Developer ID\norigin=Developer ID Application: Fixture Publisher (TESTTEAM01)", "E_DESKTOP_GATEKEEPER"),
    (("stapler", "output"), "Processing: archive.zip\nThe validate action worked!", "E_DESKTOP_STAPLER"),
    (("stapler", "output"), "Processing: /fixture/MyThing.app.zip\nThe validate action worked!", "E_DESKTOP_STAPLER"),
    (("stapler", "output"), "Processing: /fixture/OtherMyThing.app\nThe validate action worked!", "E_DESKTOP_STAPLER"),
    (("stapler", "output"), "The validate action worked!", "E_DESKTOP_STAPLER"),
    (("stapler", "exit_code"), 1, "E_DESKTOP_STAPLER"),
])
def test_zip_requires_matching_enclosed_app_reports(native_zip_release, path, value, code):
    n = native_zip_release
    _set(n.reports["arm64"], path, value)
    n.refresh()
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any(code in error for error in errors), errors
    assert not n.stream_calls


@pytest.mark.parametrize("other", ["Other.app", "OtherMyThing.app"])
def test_zip_codesign_details_must_name_the_enclosed_app(native_zip_release, other):
    n = native_zip_release
    signing = n.reports["arm64"]["signing"]
    signing["codesign_details"] = signing["codesign_details"].replace("MyThing.app/Contents/MacOS/", other + "/Contents/MacOS/")
    n.refresh()
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any("E_DESKTOP_SIGNING" in error for error in errors)


def test_zip_rejects_an_added_fake_container_ticket(native_zip_release):
    n = native_zip_release
    n.reports["arm64"]["notarization"]["zip_ticket"] = "invented"
    n.refresh()
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any("E_DESKTOP_APP_NOTARIZATION" in error for error in errors)


@pytest.mark.parametrize("change,code", [
    (lambda b: b + b" ", "E_DESKTOP_BYTES_MISMATCH"),
    (lambda b: b"X" + b[1:], "E_DESKTOP_HASH_MISMATCH"),
])
def test_final_zip_bytes_have_independent_exact_pins(native_zip_release, change, code):
    n = native_zip_release
    url = n.desktop["artifacts"][0]["url"]
    n.binaries[url] = change(n.binaries[url])
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any(code in error for error in errors)


def test_both_formats_per_architecture_have_distinct_evidence_urls(native_zip_release):
    n = native_zip_release
    for zip_artifact in list(n.desktop["artifacts"]):
        dmg = copy.deepcopy(zip_artifact)
        dmg.update(format="dmg", url=zip_artifact["url"][:-4] + ".dmg")
        dmg["evidence"]["url"] = zip_artifact["url"][:-4] + ".evidence.json"
        n.desktop["artifacts"].append(dmg)
    assert desktop.validate_metadata(n.manifest) == []
    assert len({a["evidence"]["url"] for a in n.desktop["artifacts"]}) == 4
    n.desktop["artifacts"].append(copy.deepcopy(n.desktop["artifacts"][0]))
    assert any("E_DESKTOP_ARTIFACTS" in e for e in desktop.validate_metadata(n.manifest))


def test_duplicate_zip_for_same_architecture_is_rejected(native_zip_release):
    n = native_zip_release
    n.desktop["artifacts"].append(copy.deepcopy(n.desktop["artifacts"][0]))
    assert any("E_DESKTOP_ARCH" in e for e in desktop.validate_metadata(n.manifest))


@pytest.mark.parametrize("flags", ["0x0(none)", "0x0(runtime)", "0x10000(adhoc)"])
def test_runtime_word_is_not_a_substitute_for_hardened_runtime_flags(native_zip_release, flags):
    n = native_zip_release
    signing = n.reports["arm64"]["signing"]
    signing["codesign_details"] = signing["codesign_details"].replace("0x10000(runtime)", flags) + "\nruntime claimed elsewhere\n"
    n.refresh()
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any("E_DESKTOP_SIGNING" in error for error in errors)


def _real_spctl_form(release):
    report = release.reports["arm64"]
    app = "RAPPVoice.app"
    original_app = report["notarization"].get("app_path", "Fixture.app")
    signing = report["signing"]
    signing["codesign_details"] = signing["codesign_details"].replace(original_app, app)
    signing["codesign_verify"]["output"] = signing["codesign_verify"]["output"].replace(original_app, app)
    if release.desktop["artifacts"][0]["format"] == "zip":
        report["notarization"]["app_path"] = app
        report["stapler"]["output"] = report["stapler"]["output"].replace(original_app, app)
    report["gatekeeper"]["output"] = (
        Path(__file__).parent / "fixtures" / "spctl-notarized-no-origin.txt"
    ).read_text()
    return report


@pytest.mark.parametrize("fixture_name", ["native_release", "native_zip_release"])
def test_real_spctl_form_without_origin_is_accepted(request, fixture_name):
    n = request.getfixturevalue(fixture_name)
    report = _real_spctl_form(n)
    original = copy.deepcopy(report)
    assert report["gatekeeper"]["output"] == "RAPPVoice.app: accepted\nsource=Notarized Developer ID\n"
    n.refresh()
    assert desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream) == []
    assert report == original
    assert "origin=" not in report["gatekeeper"]["output"]


@pytest.mark.parametrize("origin", [
    "origin=Developer ID Application: Other Publisher (TESTTEAM01)\n",
    "origin=\n",
    "origin=Developer ID Application: Fixture Publisher (TESTTEAM01)\n" * 2,
])
@pytest.mark.parametrize("fixture_name", ["native_release", "native_zip_release"])
def test_present_gatekeeper_origin_must_match_codesign(request, fixture_name, origin):
    n = request.getfixturevalue(fixture_name)
    report = _real_spctl_form(n)
    report["gatekeeper"]["output"] += origin
    n.refresh()
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any("E_DESKTOP_GATEKEEPER" in error for error in errors)
    assert not n.stream_calls


@pytest.mark.parametrize("field", ["authority", "team_id"])
def test_missing_origin_still_requires_codesign_authority_and_team(native_zip_release, field):
    n = native_zip_release
    report = _real_spctl_form(n)
    del report["signing"][field]
    n.refresh()
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any("E_DESKTOP_SIGNING" in error for error in errors)
    assert not n.stream_calls


@pytest.mark.parametrize("old,new", [
    ("Authority=Developer ID Application: Fixture Publisher (TESTTEAM01)", "Authority=Developer ID Application: Other Publisher (TESTTEAM01)"),
    ("TeamIdentifier=TESTTEAM01", "TeamIdentifier=OTHERTEAM1"),
])
def test_missing_origin_still_rejects_mismatched_codesign_details(native_zip_release, old, new):
    n = native_zip_release
    report = _real_spctl_form(n)
    report["signing"]["codesign_details"] = report["signing"]["codesign_details"].replace(old, new)
    n.refresh()
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any("E_DESKTOP_SIGNING" in error for error in errors)
    assert not n.stream_calls


@pytest.mark.parametrize("old,new", [
    ("RAPPVoice.app", "OtherRAPPVoice.app"),
    (": accepted", ": rejected"),
    ("source=Notarized Developer ID", "source=Developer ID"),
])
def test_missing_origin_preserves_exact_app_status_and_notary_source(native_zip_release, old, new):
    n = native_zip_release
    report = _real_spctl_form(n)
    report["gatekeeper"]["output"] = report["gatekeeper"]["output"].replace(old, new)
    n.refresh()
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any("E_DESKTOP_GATEKEEPER" in error for error in errors)
    assert not n.stream_calls


@pytest.mark.parametrize("fixture_name", ["native_release", "native_zip_release"])
def test_content_addressed_evidence_names_bind_exact_report_hash(request, fixture_name, address_native_evidence):
    n = request.getfixturevalue(fixture_name)
    legacy = {a["evidence"]["url"]: n.routes[a["evidence"]["url"]] for a in n.desktop["artifacts"]}
    address_native_evidence(n)
    for artifact in n.desktop["artifacts"]:
        evidence = artifact["evidence"]
        assert evidence["url"].endswith(f".evidence.{evidence['sha256']}.json")
    assert desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream) == []
    assert all(n.routes[url] == blob for url, blob in legacy.items())


@pytest.mark.parametrize("fixture_name", ["native_release", "native_zip_release"])
@pytest.mark.parametrize("suffix", ["0" * 64, "a" * 63, "A" * 64])
def test_evidence_filename_suffix_must_equal_full_lowercase_metadata_hash(request, fixture_name, suffix):
    n = request.getfixturevalue(fixture_name)
    evidence = n.desktop["artifacts"][0]["evidence"]
    assert evidence["sha256"] != suffix
    evidence["url"] = evidence["url"][:-5] + "." + suffix + ".json"
    assert any("E_DESKTOP_URL" in e for e in desktop.validate_metadata(n.manifest))


@pytest.mark.parametrize("old,new", [
    ("https://", "http://"),
    ("/alice/native-app/", "/other/native-app/"),
    ("/releases/download/v0.1.0/", "/releases/download/v9.0.0/"),
    ("my_thing-0.1.0-arm64.zip", "my_thing-0.1.0-x86_64.zip"),
])
def test_addressed_evidence_retains_scheme_repo_release_and_arch_bindings(
        native_zip_release, address_native_evidence, old, new):
    n = native_zip_release
    address_native_evidence(n)
    evidence = n.desktop["artifacts"][0]["evidence"]
    evidence["url"] = evidence["url"].replace(old, new)
    assert any("E_DESKTOP_URL" in e for e in desktop.validate_metadata(n.manifest))


def test_evidence_correction_appends_new_asset_and_preserves_archive_tag_and_old_report(
        native_zip_release, address_native_evidence):
    n = native_zip_release
    report = _real_spctl_form(n)
    correct_details = report["signing"]["codesign_details"]
    report["signing"]["codesign_details"] = correct_details.replace(
        "/fixture/RAPPVoice.app/", "/privateRAPPVoice.app/")
    n.refresh()
    artifact = n.desktop["artifacts"][0]
    archive = {key: copy.deepcopy(value) for key, value in artifact.items() if key != "evidence"}
    archive_bytes = n.binaries[artifact["url"]]
    tag = n.desktop["release_tag"]
    old_url = artifact["evidence"]["url"]
    old_bytes = n.routes[old_url]
    assert any("E_DESKTOP_SIGNING" in e for e in desktop.verify_release(
        n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream))

    report["signing"]["codesign_details"] = correct_details
    address_native_evidence(n)
    assert artifact["evidence"]["url"] != old_url
    assert n.routes[old_url] == old_bytes
    assert n.binaries[artifact["url"]] == archive_bytes
    assert n.desktop["release_tag"] == tag
    assert {key: value for key, value in artifact.items() if key != "evidence"} == archive
    assert old_url in {asset["browser_download_url"] for asset in n.api_release["assets"]}
    assert "origin=" not in report["gatekeeper"]["output"]
    assert desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream) == []


def test_addressed_report_does_not_accept_private_prefix_concatenation(
        native_zip_release, address_native_evidence):
    n = native_zip_release
    report = _real_spctl_form(n)
    report["signing"]["codesign_details"] = report["signing"]["codesign_details"].replace(
        "/fixture/RAPPVoice.app/", "/privateRAPPVoice.app/")
    address_native_evidence(n)
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any("E_DESKTOP_SIGNING" in e for e in errors)
    assert not n.stream_calls


def test_addressed_report_still_verifies_actual_evidence_bytes(native_zip_release, address_native_evidence):
    n = native_zip_release
    address_native_evidence(n)
    url = n.desktop["artifacts"][0]["evidence"]["url"]
    n.routes[url] = b"X" + n.routes[url][1:]
    errors = desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any("E_DESKTOP_HASH_MISMATCH" in e for e in errors)
    assert not n.stream_calls
