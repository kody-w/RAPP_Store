"""Offline source checks are not browser, full-startup or WCAG evidence."""
import json
import gzip
from pathlib import Path
import re
import shutil

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
    assert {"core-budget", "baseline-invalid"} <= {f["code"] for f in result["errors"]}


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


def debt(*keys, **counts):
    return {"format": pages.BASELINE_FORMAT, "debt": {**{key: 1 for key in keys}, **counts}}


def test_reviewed_debt_survives_line_shifts_and_harmless_edits(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n")
    site(tmp_path, '<input id="q"><div onclick="go()">Go</div><a href="./guide.md">Guide</a>')
    before = pages.check(tmp_path)["errors"]
    keys = ["index.html:control-label:input#q", "index.html:pointer-only:div[onclick='go()']",
            "index.html:raw-markdown-link:a[href='./guide.md']"]
    assert [f["key"] for f in before] == keys
    site(tmp_path, "\n" * 40 + '<p>New copy above the old debt.</p>\n<input class="wide" id="q">'
         '<div class="card"\n onclick="  go()">Go now</div><a target="_blank" href="./guide.md">The guide</a>')
    shifted = pages.check(tmp_path, baseline=debt(*keys))
    assert shifted["ok"], shifted["errors"]
    assert [f["key"] for f in shifted["known_debt"]] == keys
    assert all(new["line"] > old["line"] for old, new in zip(before, shifted["known_debt"]))
    assert not shifted["improved"]


def test_new_debt_fails_even_when_it_repeats_reviewed_debt(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n")
    site(tmp_path, '<a href="./guide.md">One</a>\n<a href="./guide.md">Two</a>\n<input name="fresh">')
    key = "index.html:raw-markdown-link:a[href='./guide.md']"
    fresh = "index.html:control-label:input[name='fresh']"
    elsewhere = key.replace("index.html", "submit.html")
    result = pages.check(tmp_path, baseline=debt(key))
    assert not result["ok"]
    assert [f["key"] for f in result["known_debt"]] == [key]
    errors = {f["key"]: f for f in result["errors"]}
    assert set(errors) == {key, fresh}
    assert "acknowledges only 1" in errors[key]["message"] and errors[key]["line"] == 2
    exact = pages.check(tmp_path, baseline=debt(**{key: 2}))
    assert [f["key"] for f in exact["errors"]] == [fresh]
    moved = pages.check(tmp_path, baseline=debt(**{elsewhere: 2}))
    assert sorted(f["key"] for f in moved["errors"]) == sorted([key, key, fresh])
    assert [i["key"] for i in moved["improved"]] == [elsewhere]


def test_removed_debt_is_reported_as_improved_without_failing(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n")
    site(tmp_path, '<input id="kept"><a href="./guide.md">Guide</a>')
    link = "index.html:raw-markdown-link:a[href='./guide.md']"
    result = pages.check(tmp_path, baseline=debt(
        "index.html:control-label:input#kept", "index.html:pointer-only:div#fixed", **{link: 3}))
    assert result["ok"], result["errors"]
    assert len(result["known_debt"]) == 2
    assert [(i["key"], i["resolved"], i["reviewed"]) for i in result["improved"]] == [
        ("index.html:pointer-only:div#fixed", 1, 1), (link, 2, 3)]
    assert all("remove this baseline entry" in i["message"] for i in result["improved"])


@pytest.mark.parametrize("baseline", [
    ["index.html:control-label:input@1"],
    debt("index.html:raw-markdown-link:a@1"),
    ["index.html:link-missing:img[src='missing.png']"],
    ["not-a-key"],
    [7],
    debt(**{"index.html:control-label:input#q": 0}),
    debt(**{"index.html:control-label:input#q": True}),
    {"format": "rapp-store-pages-debt/1", "debt": {"index.html:control-label:input#q": 1}},
    "index.html:control-label:input#q",
])
def test_baseline_rejects_line_keys_unexemptable_rules_and_bad_counts(tmp_path, baseline):
    site(tmp_path, '<input id="q">')
    result = pages.check(tmp_path, baseline=baseline)
    assert not result["ok"]
    assert any(f["code"] == "baseline-invalid" for f in result["errors"])
    assert not result["known_debt"]


def test_selector_keys_are_line_free_and_bounded():
    assert pages.selector("input", {"id": "pat-input", "name": "x"}) == "input#pat-input"
    assert pages.selector("a", {"id": "odd id"}) == "a[id='odd id']"
    assert pages.selector("div", {"onclick": "open('x')", "class": "c", "role": "button"}) == (
        "div[role='button'][onclick='open(\\'x\\')']")
    long = pages.selector("img", {"src": "data:image/png;base64," + "A" * 5000})
    assert len(long) < 140 and "sha256:" in long
    assert long != pages.selector("img", {"src": "data:image/png;base64," + "A" * 4999 + "B"})


def copy_site(destination):
    def skip(directory, names):
        top = Path(directory).resolve() == ROOT
        return {name for name in names if name == "__pycache__" or (top and name.startswith("."))}
    shutil.copytree(ROOT, destination, ignore=skip)
    return destination


def test_committed_baseline_survives_front_door_line_shifts(tmp_path):
    baseline = json.loads((ROOT / "docs/pages-check-baseline.json").read_text())
    original = pages.check(ROOT, baseline=baseline)
    site_copy = copy_site(tmp_path / "site")
    assert pages.check(site_copy, baseline=baseline) == original
    for name in ("index.html", "submit.html"):
        page = site_copy / name
        text = page.read_text(encoding="utf-8")
        body = text.index(">", text.index("<body")) + 1
        page.write_text(text[:body] + "\n<!-- shifted -->" * 19 + text[body:], encoding="utf-8")
    shifted = pages.check(site_copy, baseline=baseline)
    assert shifted["ok"], shifted["errors"]
    assert not shifted["improved"]
    assert [f["key"] for f in shifted["known_debt"]] == [f["key"] for f in original["known_debt"]]
    lines = [(f.get("line"), g.get("line")) for f, g in zip(original["known_debt"], shifted["known_debt"])]
    assert all(new == old + 19 for old, new in lines if old is not None)
    assert sum(old is not None for old, _ in lines) >= 8


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
    reviewed = json.loads(baseline.read_text())
    result = pages.check(ROOT, baseline=reviewed)
    assert result["ok"], result["errors"]
    assert len(result["known_debt"]) == sum(reviewed["debt"].values()) == 10
    assert not result["improved"]
    assert not any(re.search(r"@\d+$", f["key"]) for f in result["known_debt"])
    core = result["local_core"]["resources"]
    assert {"index.html", "index.json"} <= {row["path"] for row in core}
    for row in core:
        data = (ROOT / row["path"]).read_bytes()
        assert (row["bytes"], row["gzip_bytes"]) == (len(data), len(gzip.compress(data, compresslevel=9, mtime=0)))
    assert result["local_core"]["gzip_bytes"] == sum(row["gzip_bytes"] for row in core) <= pages.CORE_BUDGET
    assert len(core) <= 3
    assert any("RAR/main/registry.json" in url for url in result["external_startup_urls"])
    assert "NOT VERIFIED" in result["full_startup_budget"]
    assert pages.main(["--root", str(ROOT), "--baseline", str(baseline)]) == 0
    assert json.loads(capsys.readouterr().out)["known_debt"]
    assert before == {p: (ROOT / p).read_bytes() for p in before}
