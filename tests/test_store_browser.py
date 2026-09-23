"""Static JSON-schema/browser preflight and Python admission share feature boundaries."""
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess

import jsonschema
import pytest
from referencing import Registry, Resource

import lib_rapp
from test_application_contract import complete_application
from test_desktop_ui import HARNESS


ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def browser(request):
    assert NODE, "Node is required for browser contract validation"
    code = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const contract = require(input.contract);
(async () => {
  if (input.mode === 'parse') {
    try { console.log(JSON.stringify({value: contract.parseJSON(input.text)})); }
    catch (error) { console.log(JSON.stringify({error: error.message})); }
  } else if (input.mode === 'install') {
    console.log(JSON.stringify(contract.canInstall(input.entry)));
  } else if (input.mode === 'files') {
    let reads = 0;
    const errors = await contract.validateFiles(input.manifest, name => {
      reads++;
      if (input.files) return Buffer.from(input.files[name], 'base64');
      return fs.readFileSync(input.root + '/' + name);
    }, input.paths);
    console.log(JSON.stringify({errors, reads}));
  } else {
    console.log(JSON.stringify(contract.validate(input.manifest)));
  }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
"""
    result = subprocess.run([NODE, "-e", code], input=json.dumps({
        "contract": str(ROOT / "store-contract.js"), **request,
    }), capture_output=True, text=True, check=True, timeout=20)
    return json.loads(result.stdout)


def schema_validator(name):
    schemas = [json.loads(path.read_text()) for path in (ROOT / "schemas").glob("*.schema.json")]
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema))
                                         for schema in schemas)
    schema = json.loads((ROOT / "schemas" / name).read_text())
    return jsonschema.Draft202012Validator(schema, registry=registry)


def test_application_schemas_are_valid_and_offline():
    for name in ("application.schema.json", "local-docker.schema.json"):
        validator = schema_validator(name)
        validator.check_schema(validator.schema)


def test_portable_complete_app_passes_python_schema_and_browser(complete_application):
    directory, manifest = complete_application
    assert lib_rapp.validate_dir(directory).ok
    assert not list(schema_validator("application.schema.json").iter_errors(manifest))
    assert browser({"manifest": manifest}) == []
    assert browser({"mode": "files", "manifest": manifest, "root": str(directory)}) == {
        "errors": [], "reads": len(manifest["files"]),
    }


@pytest.mark.parametrize("change", [
    lambda m: m["requires"].append("unrecognized-device/1"),
    lambda m: m.pop("requires"),
    lambda m: m.update(schema="rapp-application/999.0"),
    lambda m: m.update(unrecognized_policy={"ignored": True}),
    lambda m: m["runtime"].update(commit="d" * 40),
    lambda m: m["runtime"].update(additional_runtime=True),
    lambda m: m.update(permissions=["host-root"]),
    lambda m: m.update(profiles=["unqualified-profile"]),
    lambda m: m.update(agent="singleton/absent_agent.py"),
    lambda m: m["files"].update({"../outside.py": "a" * 64}),
    lambda m: m["files"].update({"source/name.py": False}),
    lambda m: m["files"].update({"README.MD": "a" * 64}),
    lambda m: m["state"].update(preserve=False),
    lambda m: m["providers"].update(spend_limit=1),
    lambda m: m["lifecycle"].update(install="run-shell-command"),
    lambda m: m["provenance"].update(deployed="true"),
    lambda m: m.update(id=m["id"] + "\n"),
    lambda m: m.update(version=m["version"] + "\n"),
    lambda m: m.update(publisher=m["publisher"] + "\n"),
    lambda m: m["files"].update({"README.md": m["files"]["README.md"] + "\n"}),
    lambda m: m["files"].update({"source/caf\u00e9.txt": "a" * 64}),
])
def test_mandatory_contract_negatives_agree(complete_application, change):
    directory, original = complete_application
    manifest = copy.deepcopy(original)
    change(manifest)
    assert lib_rapp._validate_manifest(manifest)
    assert browser({"manifest": manifest})


def test_unknown_feature_never_reads_locked_files_in_browser(complete_application):
    _, manifest = complete_application
    manifest["requires"].append("future-required-device/99")
    result = browser({"mode": "files", "manifest": manifest})
    assert result["errors"]
    assert result["reads"] == 0


@pytest.mark.parametrize("text", [
    '{"requires":[],"requires":["unknown/1"]}',
    '{"outer":{"same":1,"same":2}}',
    '{"cost":1e999}',
    '{"x": [1,]}',
    '\u00a0{"x":1}',
])
def test_browser_json_refuses_ambiguous_or_nonfinite_metadata(text):
    assert browser({"mode": "parse", "text": text}).get("error")


def test_browser_json_keeps_prototype_names_as_data():
    result = browser({"mode": "parse", "text": '{"__proto__":{"polluted":true},"escaped":"a\\\\b"}'})
    assert result["value"] == {"__proto__": {"polluted": True}, "escaped": "a\\b"}


def render_complete(entry):
    script = re.search(r"<script>(.*?)</script>", (ROOT / "index.html").read_text(), re.DOTALL)[1]
    script = script.replace("loadAll().then(openFromHash);", "")
    harness = HARNESS.replace("vm.runInThisContext(input.script);",
                              "globalThis.RappStoreContract = require(input.contract); vm.runInThisContext(input.script);")
    result = subprocess.run([NODE, "-e", harness], input=json.dumps({
        "entry": entry, "script": script, "contract": str(ROOT / "store-contract.js"),
    }), capture_output=True, text=True, check=True, timeout=15)
    return json.loads(result.stdout)


def test_incomplete_rich_card_has_no_bare_install_or_browser_fallback(complete_application):
    _, manifest = complete_application
    entry = lib_rapp.build_index_entry(manifest, {}, manifest["id"])
    entry.update(singleton_url="https://example.com/unsafe-shortcut.py",
                 service_url="https://example.com/unsafe-service.py",
                 egg_url="api/v1/egg/unsafe.egg",
                 hatcher_url="api/v1/hatcher/unsafe_hatcher_agent.py",
                 ui_url="https://example.com/ui.html")
    result = render_complete(entry)
    hrefs = [link.get("href", "") for link in result["links"]]
    assert "No complete installer is offered" in result["text"]
    assert "Install — drop it into your brainstem" not in result["text"]
    assert not any("vbrainstem" in href or "unsafe" in href for href in hrefs)


@pytest.mark.parametrize("manifest", [None, {}, {"schema": "unknown"}])
def test_invalid_complete_row_never_falls_back_to_singleton(manifest):
    result = render_complete({
        "id": "synthetic", "name": "Synthetic", "application": manifest,
        "singleton_url": "https://example.com/unsafe-shortcut.py",
        "hatcher_url": "api/v1/hatcher/unsafe_hatcher_agent.py",
    })
    assert "No complete installer is offered" in result["text"]
    assert not any("unsafe" in link.get("href", "") for link in result["links"])


def test_can_install_requires_exact_complete_artifact_pins(complete_application):
    _, manifest = complete_application
    entry = lib_rapp.build_index_entry(manifest, {}, manifest["id"])
    entry.update(
        installable=True, install_blockers=[], package_sha256="a" * 64, hatcher_sha256="b" * 64,
        egg_url="https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/egg/test-" + "a" * 64 + ".egg",
        hatcher_url="https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/hatcher/test_" + "b" * 64 + "_hatcher_agent.py",
    )
    assert browser({"mode": "install", "entry": entry})
    for change in (
        lambda e: e.update(requires=[]),
        lambda e: e.update(version="999.0.0"),
        lambda e: e.update(hatcher_sha256="c" * 64),
        lambda e: e.update(egg_url=e["egg_url"] + "?mutable=1"),
        lambda e: e.update(installable=False),
        lambda e: e.update(install_blockers=["Candidate remains blocked."]),
    ):
        changed = copy.deepcopy(entry)
        change(changed)
        assert not browser({"mode": "install", "entry": changed})


def route_browser_integration(entry, *, available=True):
    script = re.search(r"<script>(.*?)</script>", (ROOT / "vbrainstem.html").read_text(), re.DOTALL)[1]
    code = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {
  dest: {removeAttribute(name) {delete this[name];}, textContent: '', href: 'initial-link'},
  'application-status': {textContent: ''},
};
const redirects = [];
globalThis.document = {getElementById: id => nodes[id]};
globalThis.location = {hash: '#rapp=synthetic', replace: url => redirects.push(url)};
globalThis.setTimeout = callback => callback();
globalThis.fetch = async () => ({ok: input.available, json: async () => ({rapplications: input.entry ? [input.entry] : []})});
vm.runInThisContext(input.script);
setImmediate(() => console.log(JSON.stringify({redirects, nodes})));
"""
    result = subprocess.run([NODE, "-e", code], input=json.dumps({
        "entry": entry, "available": available, "script": script,
    }), capture_output=True, text=True, check=True, timeout=15)
    return json.loads(result.stdout)


@pytest.mark.parametrize("extension", [
    {"application": None},
    {"application_schema": None},
    {"local_docker": None},
    {"requires": ["future-feature/99"]},
    {"requires": None},
    {"schema": "rapp-application/2.0"},
])
def test_vbrainstem_never_redirects_rich_or_malformed_requirements(extension):
    result = route_browser_integration({"id": "synthetic", **extension})
    assert result["redirects"] == []
    assert "href" not in result["nodes"]["dest"]
    assert "no browser or bare-singleton fallback" in result["nodes"]["application-status"]["textContent"]


def test_vbrainstem_preserves_known_simple_integration():
    result = route_browser_integration({"id": "synthetic", "requires": []})
    assert len(result["redirects"]) == 1
    assert result["redirects"][0].endswith("#rapp=synthetic")


def test_vbrainstem_does_not_guess_on_failed_catalog_lookup():
    assert route_browser_integration(None)["redirects"] == []
    assert route_browser_integration({"id": "synthetic"}, available=False)["redirects"] == []


def test_real_submission_preflight_uses_shared_feature_contract(complete_application):
    _, manifest = complete_application
    page = (ROOT / "submit.html").read_text()
    script = page[page.index("const ID_RE"):page.index("// ── Bundle tab")]
    code = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
globalThis.RappStoreContract = require(input.contract);
vm.runInThisContext(input.script);
const valid = validateManifest(input.manifest, 'alice');
input.manifest.requires.push('future-required-feature/99');
const refused = validateManifest(input.manifest, 'alice');
console.log(JSON.stringify({valid, refused}));
"""
    result = subprocess.run([NODE, "-e", code], input=json.dumps({
        "manifest": manifest, "script": script, "contract": str(ROOT / "store-contract.js"),
    }), capture_output=True, text=True, check=True, timeout=15)
    result = json.loads(result.stdout)
    assert result["valid"]["errs"] == []
    assert any("Static validation is not deployment" in warning for warning in result["valid"]["warns"])
    assert any("E_UNSUPPORTED_REQUIREMENT" in error for error in result["refused"]["errs"])


def test_simple_submission_has_no_contract_schema_dependency():
    page = (ROOT / "submit.html").read_text()
    script = page[page.index("const ID_RE"):page.index("// ── Bundle tab")]
    manifest = {
        "schema": "rapp-application/1.0", "id": "synthetic", "name": "Synthetic",
        "version": "1.0.0", "publisher": "@example", "summary": "Synthetic simple app.",
        "category": "platform", "tags": ["rapplication"], "agent": "singleton/example_agent.py",
        "ui": "ui/index.html", "requires": [],
    }
    code = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
vm.runInThisContext(input.script);
console.log(JSON.stringify(validateManifest(input.manifest, 'example')));
"""
    result = subprocess.run([NODE, "-e", code], input=json.dumps({
        "manifest": manifest, "script": script,
    }), capture_output=True, text=True, check=True, timeout=15)
    assert json.loads(result.stdout)["errs"] == []


@pytest.mark.parametrize("entry,expected_loads", [
    ({"id": "simple", "name": "Simple"}, 0),
    ({"id": "native", "desktop": None}, 0),
    ({"id": "rich", "application": None}, 1),
])
def test_legacy_store_browsing_has_no_new_schema_fetch(entry, expected_loads):
    script = re.search(r"<script>(.*?)</script>", (ROOT / "index.html").read_text(), re.DOTALL)[1]
    script = script.replace("loadAll().then(openFromHash);", "")
    code = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let schemaLoads = 0;
globalThis.RappStoreContract = {ready: async () => {schemaLoads++;}};
globalThis.document = {
  querySelector: () => ({addEventListener(){}, style:{}}),
  querySelectorAll: () => [], addEventListener(){},
};
globalThis.window = {addEventListener(){}};
globalThis.fetch = async () => ({json: async () => ({rapplications: [input.entry]})});
vm.runInThisContext(input.script);
loadRapps().then(() => console.log(JSON.stringify({schemaLoads})));
"""
    result = subprocess.run([NODE, "-e", code], input=json.dumps({
        "entry": entry, "script": script,
    }), capture_output=True, text=True, check=True, timeout=15)
    assert json.loads(result.stdout)["schemaLoads"] == expected_loads
