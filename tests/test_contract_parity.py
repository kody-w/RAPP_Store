"""Batch differential tests keep the stdlib installer and browser contract aligned."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import lib_rapp
from test_publishable_template import sample


ROOT = Path(__file__).resolve().parent.parent
REPLACEMENTS = (None, True, 0, 2.0, "", [], {})


def paths(value, path=(), *, maximum=4):
    if len(path) > maximum:
        return
    members = value.items() if isinstance(value, dict) else (
        enumerate(value[:2]) if isinstance(value, list) else ()
    )
    for key, child in members:
        yield path + (key,)
        yield from paths(child, path + (key,), maximum=maximum)


def changed(value, path, replacement):
    result = copy.deepcopy(value)
    parent = result
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = replacement
    return result


def decision(action):
    try:
        return "reject" if action() else "accept"
    except Exception as error:
        return "unexpected:" + type(error).__name__


def browser_batch(request):
    node = shutil.which("node")
    assert node, "Node is required for shared contract parity"
    script = r"""
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const contract = require(data.contract);
const base = Object.fromEntries(Object.entries(data.files || {}).map(([key, value]) =>
  [key, Buffer.from(value, 'base64')]));
const result = Promise.all(data.cases.map(async item => {
  try {
    if (data.kind === 'manifest') return contract.validate(item.manifest).length ? 'reject' : 'accept';
    const manifest = structuredClone(data.manifest);
    manifest.files[item.file] = item.sha256;
    const files = {...base, [item.file]: Buffer.from(item.body, 'base64')};
    return (await contract.validateReferences(manifest, files)).length ? 'reject' : 'accept';
  } catch (error) { return 'unexpected:' + error.name; }
}));
result.then(value => console.log(JSON.stringify(value))).catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run([node, "-e", script], input=json.dumps({
        "contract": str(ROOT / "store-contract.js"), **request,
    }), check=True, capture_output=True, text=True, timeout=60)
    return json.loads(result.stdout)


def test_manifest_field_type_matrix_agrees(sample):
    manifest, _ = sample
    cases, expected, labels = [], [], []
    for path in paths(manifest):
        for replacement in REPLACEMENTS:
            candidate = changed(manifest, path, replacement)
            cases.append({"manifest": candidate})
            expected.append(decision(lambda: lib_rapp._validate_manifest(candidate)))
            labels.append(".".join(map(str, path)) + ":" + type(replacement).__name__)
    actual = browser_batch({"kind": "manifest", "cases": cases})
    differences = [(label, py, js) for label, py, js in zip(labels, expected, actual)
                   if py != js or py.startswith("unexpected")]
    assert not differences, differences
    assert len(cases) >= 900


def test_referenced_declaration_type_matrix_agrees(sample):
    manifest, files = sample
    local = manifest["local_docker"]
    references = [local[key] for key in (
        "component_lock", "requirements_file", "jobs_file", "state_lifecycle_file",
    )] + [local["readiness"]["live_results"]]
    cases, expected, labels = [], [], []
    for name in references:
        original = json.loads(files[name])
        for path in paths(original, maximum=6):
            for replacement in REPLACEMENTS:
                declaration = changed(original, path, replacement)
                body = json.dumps(declaration).encode()
                candidate = copy.deepcopy(manifest)
                candidate["files"][name] = hashlib.sha256(body).hexdigest()
                changed_files = {**files, name: body}
                expected.append(decision(lambda: lib_rapp._application_contract_errors(candidate, changed_files)))
                cases.append({
                    "file": name, "body": base64.b64encode(body).decode(),
                    "sha256": candidate["files"][name],
                })
                labels.append(name + ":" + ".".join(map(str, path)) + ":" + type(replacement).__name__)
    actual = browser_batch({
        "kind": "references", "manifest": manifest, "cases": cases,
        "files": {name: base64.b64encode(blob).decode() for name, blob in files.items()},
    })
    differences = [(label, py, js) for label, py, js in zip(labels, expected, actual)
                   if py != js or py.startswith("unexpected")]
    assert not differences, differences
    assert len(cases) >= 1200
