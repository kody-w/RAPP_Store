"""Exercise the real static storefront script with a minimal, inert Node DOM."""
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


PAGE = Path(__file__).resolve().parent.parent / "index.html"
HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
class Element {
  constructor(tag) {
    this.tag = tag; this.attrs = {}; this.children = []; this.style = {};
    this.classList = {add(){}, remove(){}, toggle(){}};
  }
  set textContent(value) { this.children = []; this.text = String(value); }
  set innerHTML(value) { this.children = []; this.text = ''; this.html = value; }
  setAttribute(key, value) { this.attrs[key] = value; }
  appendChild(node) { this.children.push(node); return node; }
  addEventListener() {}
}
const nodes = {};
globalThis.document = {
  createElement: tag => new Element(tag),
  createTextNode: text => ({tag: '#text', text}),
  querySelector: selector => nodes[selector] || (nodes[selector] = new Element('div')),
  querySelectorAll: () => [],
  addEventListener() {},
  body: {style: {}},
};
globalThis.window = {addEventListener() {}};
globalThis.history = {replaceState() {}};
globalThis.location = {hash: '', origin: 'https://example.com', pathname: '/', search: ''};
vm.runInThisContext(input.script);
let item;
if (input.kind === 'prototype') {
  item = normalizePrototype(input.entry, {generation_id:'fixture'}, 'https://example.com/generation');
} else if (input.kind === 'agent') {
  item = normalizeAgent(input.entry);
} else {
  item = normalizeRapp(input.entry);
}
openModal(item);
const links = [];
const texts = [];
const html = [];
function walk(node) {
  if (node.text) texts.push(node.text);
  if (node.html) html.push(node.html);
  if (node.tag === 'a') links.push(node.attrs);
  for (const child of node.children || []) walk(child);
}
walk(nodes['#modalContent']);
console.log(JSON.stringify({links, text: texts.join('\n'), html, desktop: !!item.desktop}));
"""


def render(entry, kind="rapp"):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the static storefront behavior test")
    script = re.search(r"<script>(.*?)</script>", PAGE.read_text(), re.DOTALL)[1]
    script = script.replace("loadAll().then(openFromHash);", "")
    result = subprocess.run(
        [node, "-e", HARNESS],
        input=json.dumps({"entry": entry, "kind": kind, "script": script}),
        text=True, capture_output=True, check=True, timeout=15,
    )
    return json.loads(result.stdout)


def test_native_downloads_have_real_architectures_prerequisites_and_evidence(native_release):
    entry = native_release.entry()
    result = render(entry)
    hrefs = [link["href"] for link in result["links"]]
    assert result["desktop"]
    for artifact in entry["desktop"]["artifacts"]:
        assert artifact["url"] in hrefs
        assert artifact["evidence"]["url"] in hrefs
        assert artifact["sha256"] in result["text"]
        assert str(artifact["bytes"]) in result["text"]
    assert "Download for macOS — Apple silicon (arm64)" in result["text"]
    assert "Download for macOS — Intel (x86_64)" in result["text"]
    for field in ("privacy", "agent_integration"):
        assert entry["desktop"][field] in result["text"]
    for field in ("prerequisites", "setup"):
        assert all(value in result["text"] for value in entry["desktop"][field])
    assert "not independent Apple authentication or RAPP/1 acceptance" in result["text"]
    assert "Dropping a .py file into agents/ does not install the native macOS app" in result["text"]
    assert not any("hatcher" in href or href.endswith(".egg") for href in hrefs)
    assert "Install — drop it into your brainstem" not in result["text"]
    assert "Open agent integration in vBrainstem" in result["text"]


@pytest.mark.parametrize("change", [
    lambda e: e["desktop"]["artifacts"][0].update(url="javascript:alert(1)"),
    lambda e: e["desktop"]["artifacts"][0].update(bytes=True),
    lambda e: e["desktop"]["artifacts"][0].update(arch="universal"),
    lambda e: e["desktop"]["source"].update(repo="wrong/owner"),
    lambda e: e["desktop"].update(release_tag="latest"),
    lambda e: e["desktop"].update(privacy=""),
    lambda e: e["desktop"]["artifacts"][0].pop("evidence"),
    lambda e: e.update(desktop=None),
])
def test_invalid_native_metadata_never_falls_back_to_fake_installer(native_release, change):
    entry = copy.deepcopy(native_release.entry())
    change(entry)
    result = render(entry)
    assert not result["desktop"]
    assert "No native installer is offered" in result["text"]
    assert "Install — drop it into your brainstem" not in result["text"]
    assert not any(link["href"].endswith((".dmg", ".egg")) or "hatcher" in link["href"]
                   or link["href"].startswith("javascript:") for link in result["links"])


def test_native_never_offers_supplied_legacy_egg_or_hatcher(native_release):
    entry = native_release.entry()
    entry.update(egg_url="api/v1/egg/my_thing.egg", hatcher_url="api/v1/hatcher/my_thing_hatcher_agent.py")
    result = render(entry)
    assert not any("hatcher" in link["href"] or link["href"].endswith(".egg") for link in result["links"])


def test_native_disclosures_render_as_text_not_html(native_release):
    entry = native_release.entry()
    entry["desktop"]["privacy"] = '<img src=x onerror="alert(1)"> is a literal disclosure fixture.'
    result = render(entry)
    assert entry["desktop"]["privacy"] in result["text"]
    assert not any("onerror" in markup for markup in result["html"])


def test_federated_agent_has_no_manufactured_egg_or_hatcher(native_release):
    entry = native_release.entry()
    del entry["desktop"]
    result = render(entry)
    assert "Agent integration — Python singleton" in result["text"]
    assert not any("hatcher" in link["href"] or link["href"].endswith(".egg") for link in result["links"])


def test_explicit_legacy_downloads_remain_available(native_release):
    entry = native_release.entry()
    del entry["desktop"]
    entry.update(egg_url="api/v1/egg/my_thing.egg", hatcher_url="api/v1/hatcher/my_thing_hatcher_agent.py")
    result = render(entry)
    hrefs = [link["href"] for link in result["links"]]
    assert entry["egg_url"] in hrefs
    assert entry["hatcher_url"] in hrefs
    assert "Install — drop it into your brainstem" in result["text"]
    assert "Open in vBrainstem" in result["text"]


def test_shared_zoo_prototype_dial_remains_inert():
    result = render({
        "id": "fixture", "name": "Fixture", "version": "1.0.0", "summary": "Prototype",
        "identity": "rappid:@example/fixture:" + "a" * 64,
        "artifact": {"url": "https://example.com/pinned.json", "sha256": "a" * 64},
        "wire_contract": "RAPP/1", "ecosystem_acceptance": "not-asserted",
        "external_blockers": ["Needs owner review"],
    }, kind="prototype")
    assert "Dial prototype" in result["text"]
    assert "Store does not execute or install this prototype" in result["text"]
    assert "Needs owner review" in result["text"]
    assert "Install — drop it into your brainstem" not in result["text"]
    assert not any("hatcher" in link["href"] or link["href"].endswith(".egg") for link in result["links"])


def test_zip_storefront_uses_real_downloads_and_plain_finder_instructions(native_zip_release):
    entry = native_zip_release.entry()
    result = render(entry)
    assert result["desktop"]
    hrefs = [link["href"] for link in result["links"]]
    for artifact in entry["desktop"]["artifacts"]:
        assert artifact["url"] in hrefs
        assert artifact["evidence"]["url"] in hrefs
    assert "Apple silicon (arm64) · ZIP" in result["text"]
    assert "Intel (x86_64) · ZIP" in result["text"]
    assert "In Finder, double-click the ZIP to unzip it" in result["text"]
    assert "Drag the extracted .app to Applications" in result["text"]
    assert "ZIP archives themselves cannot be stapled" in result["text"]
    assert not any(link["href"].endswith((".dmg", ".egg")) or "hatcher" in link["href"] for link in result["links"])


def test_storefront_can_offer_zip_and_dmg_for_each_architecture(native_zip_release):
    entry = native_zip_release.entry()
    for original in list(entry["desktop"]["artifacts"]):
        dmg = copy.deepcopy(original)
        dmg.update(format="dmg", url=original["url"][:-4] + ".dmg")
        dmg["evidence"]["url"] = original["url"][:-4] + ".evidence.json"
        entry["desktop"]["artifacts"].append(dmg)
    result = render(entry)
    assert result["desktop"]
    assert "Apple silicon (arm64) · ZIP" in result["text"]
    assert "Apple silicon (arm64) · DMG" in result["text"]
    assert len([link for link in result["links"] if link["href"].endswith((".zip", ".dmg"))]) == 4
