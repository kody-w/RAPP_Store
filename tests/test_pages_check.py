"""Offline source checks are not browser, full-startup or WCAG evidence."""
import json
import gzip
from pathlib import Path

import pytest

import pages_check as pages

ROOT = Path(__file__).resolve().parent.parent


def site(root, content="", *, extra_head="", lang='lang="en"'):
    (root / "index.html").write_text(
        f'<!doctype html><html {lang}><head><title>Store</title>{extra_head}</head>'
        f'<body><main id="home"><h1>Store</h1>{content}</main></body></html>')
    (root / "index.json").write_text('{"rapplications":[{"id":"my_thing"}]}')
    return root


@pytest.mark.parametrize("content,code", [
    ('<img src="missing.png" alt="">', "link-missing"),
    ('<a href="#missing">Link</a>', "link-fragment"),
    ('<a href="#rapp=%ZZ">App</a>', "link-url"),
    ('<a href="#rapp=%FF">App</a>', "link-url"),
    ('<a href="#rapp=missing">App</a>', "deep-link"),
    ('<a href="#rapp=my_thing%2Fbad">App</a>', "deep-link"),
    ('<a href="../outside.html">Out</a>', "link-url"),
    ('<a href="%2e%2e/outside.html">Out</a>', "link-url"),
    ('<a href="/wrong-base/index.html">Out</a>', "link-url"),
    ('<a href="javascript:alert(1)">Bad</a>', "link-url"),
    ('<div id="home">Duplicate</div>', "html-id"),
    ('<div><span>Wrong nesting</div></span>', "html-nesting"),
    ('<div class="a" class="b">Duplicate</div>', "html-attribute"),
    ('<img src="https://example.invalid/picture.png">', "image-alt"),
    ('<input id="query" placeholder="Not a label">', "control-label"),
    ('<button></button>', "control-name"),
    ('<iframe src="https://example.invalid/"></iframe>', "frame-title"),
    ('<div onclick="open()">Open</div>', "pointer-only"),
    ('<input aria-labelledby="missing">', "label-target"),
])
def test_bad_fixture_fails_with_file_and_rule(tmp_path, content, code):
    result = pages.check(site(tmp_path, content))
    assert not result["ok"]
    assert any(f["code"] == code and f["path"] == "index.html" for f in result["errors"])


def test_valid_labels_fragments_scripts_and_rendered_docs(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n")
    site(tmp_path, """
      <label for="q">Search</label><input id="q">
      <label>Wrapped<input id="wrapped"></label>
      <span id="name">Name</span><input aria-labelledby="name">
      <input type="hidden">
      <button aria-label="Close"></button>
      <a href="#home">Home</a><a href="#rapp=my_thing">App</a>
      <a href="https://github.com/kody-w/RAPP_Store/blob/main/guide.md">Guide</a>
      <img src="https://example.invalid/decorative.svg" alt="">
      <script>const html = "<span>not markup";</script>
    """)
    result = pages.check(tmp_path)
    assert result["ok"], result["errors"]
    assert result["local_core"]["gzip_bytes"] > 0
    assert "NOT VERIFIED" in result["full_startup_budget"]


def test_directory_requires_real_rendered_index(tmp_path):
    directory = tmp_path / "docs/proposals"
    directory.mkdir(parents=True)
    site(tmp_path, '<a href="./docs/proposals/">Proposals</a>')
    assert not pages.check(tmp_path)["ok"]
    (directory / "index.html").write_text(
        '<!doctype html><html lang="en"><head><title>Proposals</title></head>'
        '<body><a href="../../">Store</a></body></html>')
    assert pages.check(tmp_path)["ok"]


def test_core_budget_counts_local_assets_and_cannot_be_baselined(tmp_path):
    site(tmp_path, '<script src="app.js"></script>')
    (tmp_path / "app.js").write_text("console.log('fixture');")
    result = pages.check(tmp_path, core_budget=1, baseline=["index.html:core-budget:startup"])
    assert not result["ok"]
    assert {r["path"] for r in result["local_core"]["resources"]} == {"index.html", "index.json", "app.js"}
    assert any(f["code"] == "core-budget" for f in result["errors"])


def test_resource_count_and_decoded_html_budgets(tmp_path):
    site(tmp_path, '<script src="one.js"></script><script src="two.js"></script>' + "é" * 100)
    for name in ("one.js", "two.js"):
        (tmp_path / name).write_text("")
    result = pages.check(tmp_path, html_budget=300)
    assert {f["code"] for f in result["errors"]} >= {"core-budget", "html-budget"}


def test_baseline_only_acknowledges_exact_existing_lint_not_new_debt(tmp_path):
    site(tmp_path, '<input id="old"><input id="new">')
    result = pages.check(tmp_path, baseline=["index.html:control-label:input#old"])
    assert not result["ok"]
    assert [f["location"] for f in result["known_debt"]] == ["input#old"]
    assert [f["location"] for f in result["errors"]] == ["input#new"]


def test_symlink_asset_cannot_escape_site_root(tmp_path):
    outside = tmp_path / "outside.js"
    outside.write_text("not a site resource")
    root = tmp_path / "site"
    root.mkdir()
    site(root, '<script src="escape.js"></script>')
    (root / "escape.js").symlink_to(outside)
    result = pages.check(root)
    assert not result["ok"]
    assert any(f["code"] == "link-url" for f in result["errors"])


def test_missing_structure_and_invalid_catalog_fail(tmp_path):
    site(tmp_path, lang="")
    (tmp_path / "index.json").write_text("invalid")
    result = pages.check(tmp_path)
    assert {"html-lang", "catalog"} <= {f["code"] for f in result["errors"]}


def test_current_front_door_measurement_is_honest_and_nonmutating(capsys):
    before = {p: (ROOT / p).read_bytes() for p in ("index.html", "index.json", "api/v1/index.json")}
    baseline = ROOT / "docs/pages-check-baseline.json"
    result = pages.check(ROOT, baseline=json.loads(baseline.read_text()))
    assert result["ok"], result["errors"]
    assert len(result["known_debt"]) == 10
    assert not result["unused_baseline"]
    assert result["local_core"]["gzip_bytes"] == sum(
        len(gzip.compress(before[name], compresslevel=9, mtime=0)) for name in ("index.html", "index.json"))
    assert len(result["local_core"]["resources"]) == 2
    assert any("RAR/main/registry.json" in url for url in result["external_startup_urls"])
    assert "NOT VERIFIED" in result["full_startup_budget"]
    assert pages.main(["--root", str(ROOT), "--baseline", str(baseline)]) == 0
    assert json.loads(capsys.readouterr().out)["known_debt"]
    assert before == {p: (ROOT / p).read_bytes() for p in before}
