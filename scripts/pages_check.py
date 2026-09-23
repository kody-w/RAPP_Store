#!/usr/bin/env python3
"""Offline Pages regression checks using only the Python standard library.

This is source lint, not browser/WCAG certification or a measured waterfall.
An explicit baseline can acknowledge existing lint debt, never broken links,
HTML structure errors, or a budget overrun. External fetches are not downloaded.

Finding keys are ``page:rule:selector``. The selector is the element ID, or the
tag plus identity attributes such as ``href``, ``name`` or ``onclick``; it never
contains a source line, so moving markup does not change it. Baseline counts are
exact: an extra matching finding is new debt and fails, while a missing one is
reported as improved.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
INTERACTIVE = frozenset(("a", "button", "input", "select", "textarea", "summary"))
BASELINABLE = frozenset(("control-label", "pointer-only", "raw-markdown-link", "blocking-startup"))
IDENTITY_ATTRS = ("href", "src", "action", "name", "type", "for", "role", "onclick", "placeholder")
BASELINE_FORMAT = "rapp-store-pages-debt/2"
BASELINE_KEY = re.compile(r"(?P<path>[^:]+):(?P<code>[a-z-]+):(?P<selector>.+)", re.DOTALL)
CORE_BUDGET = 65_536
HTML_BUDGET = 65_536
PAGES_HOST = "kody-w.github.io"
SITE_PATH = "/RAPP_Store/"


def attribute_value(value):
    """Whitespace-normalized, quoted selector value; long values keep a content hash."""
    text = " ".join(value.split())
    if len(text) > 96:
        text = text[:64] + "…sha256:" + hashlib.sha256(text.encode()).hexdigest()[:16]
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def selector(tag, attrs):
    """Stable element identity: ID first, else tag plus identity attributes in a fixed order."""
    if ident := attrs.get("id"):
        return f"{tag}#{ident}" if re.fullmatch(r"[A-Za-z][\w-]*", ident) else f"{tag}[id={attribute_value(ident)}]"
    return tag + "".join(f"[{name}={attribute_value(attrs[name])}]" for name in IDENTITY_ATTRS if attrs.get(name))


def reviewed_debt(baseline):
    """Exact reviewed counts by stable key, plus problems for entries that can never be honored."""
    counts, problems = Counter(), []
    if baseline is None:
        return counts, problems
    if isinstance(baseline, dict):
        if baseline.get("format") != BASELINE_FORMAT or not isinstance(baseline.get("debt"), dict):
            return counts, [f"Baseline object needs format {BASELINE_FORMAT!r} and a debt object of key counts"]
        entries = list(baseline["debt"].items())
    elif isinstance(baseline, list):
        entries = [(key, 1) for key in baseline]
    else:
        return counts, ["Baseline must be a list of finding keys or a versioned debt object"]
    for key, count in entries:
        match = BASELINE_KEY.fullmatch(key) if isinstance(key, str) else None
        if not match:
            problems.append(f"{key!r}: expected a page:rule:selector finding key")
        elif type(count) is not int or count < 1:
            problems.append(f"{key}: count must be a positive integer")
        elif match["code"] not in BASELINABLE:
            problems.append(f"{key}: {match['code']} findings can never be baseline-exempted")
        elif re.search(r"@\d+$", match["selector"]):
            problems.append(f"{key}: source-line keys are not stable; use the reported selector key")
        else:
            counts[key] += count
    return counts, problems


class Document(HTMLParser):
    def __init__(self, path, text):
        super().__init__(convert_charrefs=True)
        self.path, self.text = path, text
        self.nodes, self.stack, self.findings, self.links = [], [], [], []
        self.ids, self.doctype = {}, False
        self.feed(text)
        self.close()
        if self.stack:
            self.add("html-unclosed", "document", "Unclosed elements: " + ", ".join(n["tag"] for n in self.stack))
        if not self.doctype:
            self.add("html-doctype", "document", "Missing HTML doctype")
        for tag in ("html", "head", "body", "title"):
            count = sum(n["tag"] == tag for n in self.nodes)
            if count != 1:
                self.add("html-structure", tag, f"Expected one {tag}, found {count}")
        self.lint_accessibility()

    def add(self, code, subject, message):
        """Record a finding; element subjects carry a stable selector key and a line for humans."""
        if isinstance(subject, dict):
            location, stable, line = subject["where"], subject["selector"], subject["line"]
        else:
            location = stable = subject
            line = None
        finding = {"key": f"{self.path}:{code}:{stable}", "path": self.path,
                   "code": code, "location": location, "message": message}
        if line is not None:
            finding["line"] = line
        self.findings.append(finding)

    def handle_decl(self, decl):
        if decl.lower() == "doctype html":
            self.doctype = True

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        line = self.getpos()[0]
        where = f"{tag}#{attrs['id']}" if attrs.get("id") else f"{tag}@{line}"
        node = {"tag": tag, "attrs": attrs, "where": where, "selector": selector(tag, attrs), "line": line,
                "text": [], "ancestors": self.stack[:]}
        self.nodes.append(node)
        if len(attrs) != len(pairs):
            self.add("html-attribute", node, "Duplicate attribute")
        if value := attrs.get("id"):
            if value in self.ids:
                self.add("html-id", node, "Duplicate element ID")
            self.ids[value] = node
        for attr in ("href", "src", "action"):
            if attrs.get(attr):
                self.links.append((attr, attrs[attr], node))
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1]["tag"] != tag:
            line = self.getpos()[0]
            self.add("html-nesting", {"where": f"{tag}@{line}", "selector": f"</{tag}>", "line": line},
                     f"Unexpected closing {tag}")
            return
        self.stack.pop()

    def handle_data(self, text):
        if self.stack and self.stack[-1]["tag"] not in ("script", "style"):
            for node in self.stack:
                node["text"].append(text)

    def name(self, node):
        attrs = node["attrs"]
        if attrs.get("aria-label", "").strip():
            return attrs["aria-label"]
        refs = attrs.get("aria-labelledby", "").split()
        if refs and all(ref in self.ids for ref in refs):
            return "".join("".join(self.ids[ref]["text"]) for ref in refs).strip()
        return "".join(node["text"]).strip()

    def lint_accessibility(self):
        labels = {n["attrs"].get("for") for n in self.nodes if n["tag"] == "label" and self.name(n)}
        for node in self.nodes:
            tag, attrs = node["tag"], node["attrs"]
            if tag == "html" and not attrs.get("lang", "").strip():
                self.add("html-lang", node, "Document needs a language")
            if tag == "title" and not self.name(node):
                self.add("document-title", node, "Document needs a nonempty title")
            if tag == "img" and "alt" not in attrs:
                self.add("image-alt", node, "Image needs alt text (empty is allowed for decoration)")
            if tag == "iframe" and not attrs.get("title", "").strip():
                self.add("frame-title", node, "Frame needs a descriptive title")
            if tag in ("button", "a") and not self.name(node):
                self.add("control-name", node, f"{tag} has no source-visible accessible name")
            if tag in ("input", "select", "textarea") and attrs.get("type", "").lower() != "hidden":
                wrapped = any(p["tag"] == "label" and self.name(p) for p in node["ancestors"])
                if (not attrs.get("aria-label") and not attrs.get("aria-labelledby")
                        and attrs.get("id") not in labels and not wrapped):
                    self.add("control-label", node, "Control needs an explicit label; placeholder is not a label")
            if "aria-labelledby" in attrs and any(ref not in self.ids for ref in attrs["aria-labelledby"].split()):
                self.add("label-target", node, "aria-labelledby target does not exist")
            if "onclick" in attrs and tag not in INTERACTIVE:
                if "tabindex" not in attrs or not ({"onkeydown", "onkeyup"} & attrs.keys()):
                    self.add("pointer-only", node, "Click target needs native keyboard semantics")


def local_target(root, source, url):
    """Resolve only this site's local URLs; never fetch arbitrary external URLs."""
    if re.search(r"%(?![0-9a-fA-F]{2})", url):
        raise ValueError("Malformed percent escape")
    parts = urlsplit(url)
    if parts.scheme in ("javascript", "vbscript"):
        raise ValueError("Executable link scheme is not allowed")
    path = unquote(parts.path, errors="strict")
    fragment = unquote(parts.fragment, errors="strict")
    if parts.netloc:
        if parts.scheme not in ("http", "https"):
            raise ValueError("Unsupported network URL")
        if parts.netloc == PAGES_HOST and path.lower().startswith(SITE_PATH.lower()):
            path = path[len(SITE_PATH):]
        elif parts.netloc == "github.com" and path.lower().startswith("/kody-w/rapp_store/blob/main/"):
            path = path[len("/kody-w/rapp_store/blob/main/"):]
            fragment = ""  # GitHub renders Markdown anchors; no renderer is bundled here.
        else:
            return None, fragment
        target = root / path
    elif parts.scheme:
        return None, fragment
    elif path.startswith("/"):
        if not path.lower().startswith(SITE_PATH.lower()):
            raise ValueError("Root-relative link escapes the project Pages base")
        target = root / path[len(SITE_PATH):]
    else:
        target = source.parent / path if path else source
    target = target.resolve()
    if not target.is_relative_to(root):
        raise ValueError("Local link escapes the repository")
    if target.is_dir():
        target /= "index.html"
    return target, fragment


def check(root, *, baseline=None, core_budget=CORE_BUDGET, html_budget=HTML_BUDGET):
    root = Path(root).resolve()
    pages = sorted([*root.glob("*.html"), *(root / "docs").rglob("*.html")])
    docs = {}
    for path in pages:
        docs[path] = Document(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
    findings = []
    if root / "index.html" not in docs:
        findings.append({"key": "index.html:missing:document", "path": "index.html", "code": "missing",
                         "location": "document", "message": "Homepage is missing"})
    try:
        catalog = json.loads((root / "index.json").read_text())
        ids = {r["id"] for r in catalog["rapplications"]}
    except (OSError, ValueError, KeyError, TypeError):
        ids = set()
        findings.append({"key": "index.json:catalog:document", "path": "index.json", "code": "catalog",
                         "location": "document", "message": "Canonical application catalog is missing or invalid"})
    core = {root / "index.html", root / "index.json"}
    external_startup = set()
    for path, doc in list(docs.items()):
        for attr, url, node in doc.links:
            try:
                target, fragment = local_target(root, path, url)
            except (ValueError, UnicodeError) as exc:
                doc.add("link-url", node, f"{url}: {exc}")
                continue
            if target is not None:
                if not target.is_file():
                    doc.add("link-missing", node, f"{url}: local target is missing (directories need index.html)")
                    continue
                if fragment.startswith("rapp="):
                    rid = fragment.removeprefix("rapp=")
                    if not re.fullmatch(r"[a-z][a-z0-9_]*", rid) or rid not in ids:
                        doc.add("deep-link", node, f"{url}: unknown or malformed canonical application deep link")
                elif fragment and target.suffix == ".html":
                    target_doc = docs.get(target) or Document(
                        target.relative_to(root).as_posix(), target.read_text(encoding="utf-8"))
                    if fragment not in target_doc.ids:
                        doc.add("link-fragment", node, f"{url}: fragment target does not exist")
                if target.suffix == ".md" and not url.startswith("https://github.com/"):
                    doc.add("raw-markdown-link", node, f"{url}: use a rendered GitHub blob link (Constitution XII)")
            resource = attr == "src" or (node["tag"] == "link" and node["attrs"].get("rel") == "stylesheet")
            if resource and path == root / "index.html":
                if target is not None:
                    core.add(target)
                else:
                    external_startup.add(url)
        if path == root / "index.html":
            sources = re.search(r"const SOURCES\s*=\s*\{(.*?)\n\};", doc.text, re.DOTALL)
            if sources:
                for url in re.findall(r"\burl:\s*['\"]([^'\"]+)['\"]", sources[1]):
                    target, _ = local_target(root, path, url)
                    if target is None:
                        external_startup.add(url)
                    elif not target.is_file():
                        doc.add("link-missing", "startup", f"{url}: startup catalog is missing")
            if "Promise.allSettled([loadRapps(), loadAgents()" in doc.text:
                doc.add("blocking-startup", "loadAll", "Local render waits for external catalogs; the full startup budget is not met")
        decoded_bytes = path.stat().st_size
        if decoded_bytes > html_budget:
            doc.add("html-budget", "document", f"HTML is {decoded_bytes} bytes; budget is {html_budget}")
        findings.extend(doc.findings)
    weights = [{"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                "gzip_bytes": len(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0))}
               for path in sorted(core) if path.is_file()]
    total = sum(row["gzip_bytes"] for row in weights)
    if total > core_budget or len(weights) > 3:
        findings.append({"key": "index.html:core-budget:startup", "path": "index.html",
                         "code": "core-budget", "location": "startup",
                         "message": f"Local application core: {total} gzip bytes/{len(weights)} resources; "
                                    f"budget {core_budget} bytes/3 resources"})
    reviewed, problems = reviewed_debt(baseline)
    for problem in problems:
        findings.append({"key": f"baseline:baseline-invalid:{problem}", "path": "baseline",
                         "code": "baseline-invalid", "location": "baseline", "message": problem})
    remaining, debt, errors = Counter(reviewed), [], []
    for finding in findings:
        if finding["code"] in BASELINABLE and remaining[finding["key"]] > 0:
            remaining[finding["key"]] -= 1
            debt.append(finding)
            continue
        if finding["key"] in reviewed:
            finding = {**finding, "message": f"{finding['message']} (new: the baseline acknowledges "
                                             f"only {reviewed[finding['key']]} finding(s) with this key)"}
        errors.append(finding)
    improved = [{"key": key, "resolved": count, "reviewed": reviewed[key],
                 "message": "Reviewed debt no longer found; lower or remove this baseline entry"}
                for key, count in sorted(remaining.items()) if count > 0]
    return {
        "ok": not errors, "scope": "Offline source regression checks; not WCAG, network, or browser certification",
        "errors": errors, "known_debt": debt, "improved": improved,
        "html_pages": [p.relative_to(root).as_posix() for p in pages],
        "local_core": {"resources": weights, "gzip_bytes": total, "budget_gzip_bytes": core_budget,
                       "scope": "Homepage, canonical catalog and static same-page assets only"},
        "external_startup_urls": sorted(external_startup),
        "full_startup_budget": "NOT VERIFIED: external catalogs, Zoo generation and runtime fetches are excluded; "
                               "see docs/CI.md for the measured existing overrun",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--baseline", type=Path,
                        help="Reviewed lint-debt counts keyed by stable selector, not a pass for accessibility")
    parser.add_argument("--core-budget", type=int, default=CORE_BUDGET)
    parser.add_argument("--html-budget", type=int, default=HTML_BUDGET)
    args = parser.parse_args(argv)
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    result = check(args.root, baseline=baseline, core_budget=args.core_budget, html_budget=args.html_budget)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
