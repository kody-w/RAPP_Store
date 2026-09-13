"""Check full native release shapes against local JSON Schemas and runtime rules."""
import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
import pytest

import lib_desktop


@pytest.fixture
def native_schema_validators():
    root = Path(__file__).resolve().parent.parent / "schemas"
    schemas = [json.loads((root / name).read_text()) for name in (
        "desktop.schema.json", "desktop-evidence.schema.json",
    )]
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    return tuple(Draft202012Validator(schema, registry=registry) for schema in schemas)


@pytest.mark.parametrize("fixture_name", ["native_zip_release", "native_release"])
@pytest.mark.parametrize("addressed", [False, True])
def test_real_shaped_archive_and_report_urls_pass_schema_and_runtime(
        request, native_schema_validators, address_native_evidence, fixture_name, addressed):
    n = request.getfixturevalue(fixture_name)
    if addressed:
        address_native_evidence(n)
    manifest_validator, report_validator = native_schema_validators
    manifest_validator.validate(n.desktop)
    for artifact in n.desktop["artifacts"]:
        report_validator.validate(n.reports[artifact["arch"]])
        assert artifact["url"].endswith("." + artifact["format"])
        assert artifact["evidence"]["url"].endswith(".json")
    assert lib_desktop.validate_metadata(n.manifest) == []
    assert lib_desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream) == []


@pytest.mark.parametrize("fixture_name", ["native_zip_release", "native_release"])
@pytest.mark.parametrize("swapped", ["artifact", "evidence"])
def test_schema_and_runtime_reject_archive_evidence_url_swaps(
        request, native_schema_validators, fixture_name, swapped):
    n = request.getfixturevalue(fixture_name)
    artifact = n.desktop["artifacts"][0]
    if swapped == "artifact":
        artifact["url"] = artifact["evidence"]["url"]
    else:
        artifact["evidence"]["url"] = artifact["url"]
    assert list(native_schema_validators[0].iter_errors(n.desktop))
    assert any("E_DESKTOP_URL" in error for error in lib_desktop.validate_metadata(n.manifest))


@pytest.mark.parametrize("fixture_name", ["native_zip_release", "native_release"])
def test_evidence_subject_url_must_be_an_archive_not_an_evidence_asset(
        request, native_schema_validators, fixture_name):
    n = request.getfixturevalue(fixture_name)
    report = n.reports["arm64"]
    report["subject"]["url"] = n.desktop["artifacts"][0]["evidence"]["url"]
    assert list(native_schema_validators[1].iter_errors(report))
    n.refresh()
    errors = lib_desktop.verify_release(n.manifest, fetcher=n.fetch, artifact_fetcher=n.stream)
    assert any("E_DESKTOP_EVIDENCE_BINDING" in error for error in errors)


def test_runtime_keeps_cross_field_hash_binding_beyond_schema_shape(
        native_zip_release, native_schema_validators, address_native_evidence):
    n = native_zip_release
    address_native_evidence(n)
    manifest = copy.deepcopy(n.manifest)
    evidence = manifest["desktop"]["artifacts"][0]["evidence"]
    evidence["url"] = evidence["url"].replace(evidence["sha256"], "0" * 64)
    native_schema_validators[0].validate(manifest["desktop"])
    assert any("E_DESKTOP_URL" in error for error in lib_desktop.validate_metadata(manifest))
