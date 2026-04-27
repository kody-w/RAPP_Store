# rapp-validator: allow-template-placeholders (this file mirrors the validator
# and legitimately contains the placeholder string list as constants)
"""publish_to_rapp_store_agent.py — submit a rapplication to the RAPP store.

A rapplication that publishes other rapplications. Drop into your local
brainstem's agents/ directory and ask it to publish either a local
directory/.zip OR a public GitHub repo (federation mode).

Two submission modes:

  * BUNDLE   — send your rapplication's files for inclusion in
               kody-w/rapp_store. The maintainer copies them into the
               canonical catalog at promotion time.
  * FEDERATION — your rapp lives in your own public GitHub repo. The
               catalog adds an entry whose singleton_url points at
               raw.githubusercontent.com/<your-repo>. Nothing is copied.

Actions:

  * validate_local <path>      — pre-flight a local rapp dir or .zip
  * validate_repo <github-url> — pre-flight a federated rapp
  * bundle <path>              — zip a local rapp dir
  * submit_bundle <path>       — validate + open a [RAPP] issue with the bundle
  * submit_repo <github-url>   — validate + open a [RAPP] issue with a federation block
  * status <issue-number>      — check approval status of a prior submission
  * spec                       — print SPEC.md for this version

The agent never pushes commits. It opens GitHub issues against
kody-w/rapp_store; a maintainer (or workflow) approves them. The same
validation rules that gate approval run locally first, so the user gets
fast feedback before sending anything.

Reads GH_TOKEN or GITHUB_TOKEN from the environment for the GitHub API.
Without one, validate_* still works; submit_* tells the caller how to set
it up (or how to file the issue manually with the printed payload).
"""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent  # local brainstem
except ImportError:  # pragma: no cover - cloud / openrappter
    try:
        from basic_agent import BasicAgent  # type: ignore
    except ImportError:
        from openrappter.agents.basic_agent import BasicAgent  # type: ignore


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/publish-to-rapp-store",
    "display_name": "PublishToRappStore",
    "version": "0.1.0",
    "description": (
        "Publish a rapplication to the RAPP store catalog. Validates "
        "locally against SPEC.md, then opens a GitHub issue on "
        "kody-w/rapp_store. Supports both bundle (copy into catalog) and "
        "federation (point at submitter's own repo) submissions."
    ),
    "author": "RAPP",
    "tags": ["publish", "store", "submission", "rapplication", "federation"],
    "category": "platform",
    "quality_tier": "official",
    "requires_env": [],
    "example_call": {"args": {"action": "validate_local", "path": "/path/to/my_rapp"}},
}


# ── Constants (mirrored from scripts/lib_rapp.py) ─────────────────────────

CATALOG_OWNER_REPO = "kody-w/rapp_store"
CATALOG_RAW_BASE = f"https://raw.githubusercontent.com/{CATALOG_OWNER_REPO}/main"
CATALOG_INDEX_URL = f"{CATALOG_RAW_BASE}/index.json"
ISSUES_API = f"https://api.github.com/repos/{CATALOG_OWNER_REPO}/issues"

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
PUBLISHER_RE = re.compile(r"^@[a-zA-Z0-9][a-zA-Z0-9-]*$")

RESERVED_IDS = frozenset({
    "scripts", "tests", "versions", "eggs", "senses",
    "binder", "dashboard", "kanban", "swarms", "webhook",
    "vibe_builder", "learn_new", "swarm_factory",
    "publish_to_rapp_store",
})

OFFICIAL_PUBLISHERS = frozenset({"@rapp", "@rarbookworld"})

ACCEPTED_BASIC_AGENT_IMPORTS = (
    "from agents.basic_agent import BasicAgent",
    "from basic_agent import BasicAgent",
    "from openrappter.agents.basic_agent import BasicAgent",
)

TEMPLATE_PLACEHOLDERS = (
    "{{PLACEHOLDER}}", "{{TEAM_NAME}}", "{{CLASS_NAME}}",
    "YOUR LOGIC GOES HERE", "TODO REPLACE", "RAPP AGENT TEMPLATE",
    "@your_username/",
)

MAX_BUNDLE_BYTES = 5 * 1024 * 1024
MAX_SINGLETON_BYTES = 200 * 1024
MAX_UI_BYTES = 500 * 1024


# ── Validation helpers ────────────────────────────────────────────────────

class _ValidationFailure(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def _validate_manifest(m):
    errs = []
    if m.get("schema") != "rapp-application/1.0":
        errs.append(f"E_MANIFEST_SCHEMA: schema must be 'rapp-application/1.0', got {m.get('schema')!r}")
    rid = m.get("id")
    if not isinstance(rid, str) or not ID_RE.match(rid):
        errs.append(f"E_BAD_ID: id must match {ID_RE.pattern}, got {rid!r}")
    if not m.get("name"):
        errs.append("E_BAD_NAME: name is required")
    v = m.get("version")
    if not isinstance(v, str) or not SEMVER_RE.match(v):
        errs.append(f"E_BAD_VERSION: version must be MAJOR.MINOR.PATCH, got {v!r}")
    pub = m.get("publisher")
    if not isinstance(pub, str) or not PUBLISHER_RE.match(pub):
        errs.append(f"E_BAD_PUBLISHER: publisher must match @username, got {pub!r}")
    if not m.get("summary"):
        errs.append("E_BAD_SUMMARY: summary is required")
    if not m.get("category"):
        errs.append("E_BAD_CATEGORY: category is required")
    tags = m.get("tags")
    if not isinstance(tags, list) or not tags:
        errs.append("E_BAD_TAGS: tags must be a non-empty list")
    if not m.get("agent") and not m.get("service"):
        errs.append("E_NO_ENTRYPOINT: manifest must declare agent and/or service")
    return errs


def _validate_singleton_text(src, name="singleton"):
    errs = []
    if "rapp-validator: allow-template-placeholders" not in src:
        for ph in TEMPLATE_PLACEHOLDERS:
            if ph in src:
                errs.append(f"E_TEMPLATE_PLACEHOLDER: unresolved {ph!r} in {name}")
    if not any(imp in src for imp in ACCEPTED_BASIC_AGENT_IMPORTS):
        errs.append(f"E_NO_BASIC_AGENT_IMPORT: {name} must import BasicAgent")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return errs + [f"E_SINGLETON_SYNTAX: {e}"]

    found_manifest = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__manifest__":
                    found_manifest = True
                    if not isinstance(node.value, ast.Dict):
                        errs.append("E_MANIFEST_NOT_DICT: __manifest__ must be a dict literal")
    if not found_manifest:
        errs.append("E_NO_INTERNAL_MANIFEST: missing top-level __manifest__ dict")

    public = [n for n in tree.body
              if isinstance(n, ast.ClassDef)
              and n.name != "BasicAgent"
              and not n.name.startswith("_Internal")
              and n.name.endswith("Agent")]
    if not public:
        errs.append("E_NO_AGENT_CLASS: no public class ending in 'Agent'")
    elif len(public) > 1:
        errs.append(f"E_MULTIPLE_AGENT_CLASSES: {[c.name for c in public]}")
    else:
        cls = public[0]
        bases = {b.id if isinstance(b, ast.Name) else
                 b.attr if isinstance(b, ast.Attribute) else None
                 for b in cls.bases}
        if "BasicAgent" not in bases:
            errs.append(f"E_NOT_BASIC_AGENT: {cls.name} must extend BasicAgent")
        if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "perform"
                   for n in cls.body):
            errs.append(f"E_NO_PERFORM: {cls.name} missing perform()")
    return errs


def _validate_dir(rapp_dir, *, expected_publisher=None, existing_catalog=None):
    rapp_dir = Path(rapp_dir)
    errs = []
    if not (rapp_dir / "manifest.json").is_file():
        return {"ok": False, "errors": ["E_NO_MANIFEST: missing manifest.json"]}
    try:
        manifest = json.loads((rapp_dir / "manifest.json").read_text())
    except json.JSONDecodeError as e:
        return {"ok": False, "errors": [f"E_BAD_MANIFEST_JSON: {e}"]}

    errs.extend(_validate_manifest(manifest))
    if errs:
        return {"ok": False, "manifest": manifest, "errors": errs}

    rid = manifest["id"]
    if rapp_dir.name != rid:
        errs.append(f"E_DIR_NAME_MISMATCH: dir '{rapp_dir.name}' != id '{rid}'")
    if rid in RESERVED_IDS:
        errs.append(f"E_RESERVED_ID: '{rid}' is reserved by the platform")

    if expected_publisher:
        pub = manifest["publisher"]
        if pub in OFFICIAL_PUBLISHERS and expected_publisher.lower() not in {"@kody-w", "@rapp"}:
            errs.append(f"E_PUBLISHER_MISMATCH: '{pub}' is reserved")
        elif pub not in OFFICIAL_PUBLISHERS and pub.lower() != expected_publisher.lower():
            errs.append(f"E_PUBLISHER_MISMATCH: '{pub}' != submitter '{expected_publisher}'")

    if existing_catalog is not None:
        for r in existing_catalog.get("rapplications", []):
            if r.get("id") == rid:
                if not _semver_gt(manifest["version"], r.get("version", "0.0.0")):
                    errs.append(f"E_VERSION_NOT_BUMPED: {manifest['version']} <= {r.get('version')}")

    if manifest.get("agent"):
        ap = rapp_dir / manifest["agent"]
        if not ap.is_file():
            errs.append(f"E_SINGLETON_MISSING: {manifest['agent']}")
        else:
            sb = ap.stat().st_size
            if sb > MAX_SINGLETON_BYTES:
                errs.append(f"E_SINGLETON_TOO_LARGE: {sb} > {MAX_SINGLETON_BYTES}")
            errs.extend(_validate_singleton_text(ap.read_text(encoding="utf-8", errors="replace"),
                                                 name=ap.name))

    if manifest.get("ui"):
        up = rapp_dir / manifest["ui"]
        if not up.is_file():
            errs.append(f"E_UI_MISSING: {manifest['ui']}")
        elif up.stat().st_size > MAX_UI_BYTES:
            errs.append(f"E_UI_TOO_LARGE: {up.stat().st_size} > {MAX_UI_BYTES}")

    if not (rapp_dir / "README.md").is_file():
        errs.append("E_NO_README: missing README.md")
    if not (rapp_dir / "index_entry.json").is_file():
        errs.append("E_NO_INDEX_ENTRY: missing index_entry.json")

    if errs:
        return {"ok": False, "manifest": manifest, "errors": errs}
    return {"ok": True, "manifest": manifest, "errors": []}


def _validate_zip_bytes(blob, *, extract_to=None, **kw):
    if len(blob) > MAX_BUNDLE_BYTES:
        return {"ok": False, "errors": [f"E_BUNDLE_TOO_LARGE: {len(blob)} > {MAX_BUNDLE_BYTES}"]}
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as e:
        return {"ok": False, "errors": [f"E_BAD_ZIP: {e}"]}
    for info in zf.infolist():
        if info.filename.startswith("/") or ".." in info.filename.replace("\\", "/").split("/"):
            return {"ok": False, "errors": [f"E_PATH_TRAVERSAL: {info.filename}"]}
    import tempfile
    target = Path(extract_to) if extract_to else Path(tempfile.mkdtemp(prefix="rapp_pub_"))
    target.mkdir(parents=True, exist_ok=True)
    zf.extractall(target)
    zf.close()
    rapp_dir = _unwrap(target)
    if rapp_dir is None:
        return {"ok": False, "errors": ["E_NO_MANIFEST: bundle has no manifest.json"]}
    return _validate_dir(rapp_dir, **kw)


def _unwrap(extract_to):
    if (extract_to / "manifest.json").is_file():
        return extract_to
    children = [c for c in extract_to.iterdir() if not c.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir() and (children[0] / "manifest.json").is_file():
        return children[0]
    for c in children:
        if c.is_dir() and (c / "manifest.json").is_file():
            return c
    return None


def _semver_gt(a, b):
    ma, mb = SEMVER_RE.match(a or ""), SEMVER_RE.match(b or "")
    if not ma or not mb:
        return False
    return tuple(int(x) for x in ma.groups()) > tuple(int(x) for x in mb.groups())


def _http_get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {
        "User-Agent": "publish-to-rapp-store/0.1",
        "Accept": "*/*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_post(url, payload, token):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "publish-to-rapp-store/0.1",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
        raise RuntimeError(f"GitHub API HTTP {e.code}: {body}") from e


def _parse_repo_url(url):
    m = re.match(
        r"^https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?"
        r"(?:/(?:tree|blob)/([^/]+)(?:/(.+?))?)?/?$", url.strip())
    if not m:
        raise ValueError(f"not a github url: {url!r}")
    return m.group(1), (m.group(2) or "main"), (m.group(3) or "")


def _bundle_dir_to_zip(rapp_dir):
    rapp_dir = Path(rapp_dir)
    if not (rapp_dir / "manifest.json").is_file():
        raise ValueError(f"not a rapp dir: {rapp_dir}")
    rid = rapp_dir.name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(rapp_dir.rglob("*")):
            if p.is_file():
                zf.write(p, f"{rid}/{p.relative_to(rapp_dir).as_posix()}")
    return buf.getvalue()


def _format_validation(result):
    if result.get("ok"):
        m = result.get("manifest", {})
        return f"VALID: {m.get('id')}@{m.get('version')} by {m.get('publisher')}"
    return "INVALID:\n  - " + "\n  - ".join(result.get("errors", ["unknown"]))


def _fetch_catalog(catalog_url=None):
    try:
        return json.loads(_http_get(catalog_url or CATALOG_INDEX_URL))
    except Exception:
        return {"rapplications": []}


# ── Federation pre-flight ─────────────────────────────────────────────────

def _validate_federation(repo, ref, path, expected_publisher=None, fetcher=None,
                         existing_catalog=None):
    fetch = fetcher or (lambda u: _http_get(u))
    raw_base = f"https://raw.githubusercontent.com/{repo}/{ref}"
    if path:
        raw_base = f"{raw_base}/{path}"
    try:
        manifest_blob = fetch(f"{raw_base}/manifest.json")
    except Exception as e:
        return {"ok": False, "errors": [f"E_FETCH_MANIFEST: {e}"]}
    try:
        manifest = json.loads(manifest_blob.decode("utf-8") if isinstance(manifest_blob, bytes) else manifest_blob)
    except Exception as e:
        return {"ok": False, "errors": [f"E_BAD_MANIFEST_JSON: {e}"]}

    errs = _validate_manifest(manifest)
    if errs:
        return {"ok": False, "manifest": manifest, "errors": errs}

    rid = manifest["id"]
    if rid in RESERVED_IDS:
        errs.append(f"E_RESERVED_ID: '{rid}'")
    if expected_publisher:
        pub = manifest["publisher"]
        if pub in OFFICIAL_PUBLISHERS and expected_publisher.lower() not in {"@kody-w", "@rapp"}:
            errs.append(f"E_PUBLISHER_MISMATCH: '{pub}' is reserved")
        elif pub not in OFFICIAL_PUBLISHERS and pub.lower() != expected_publisher.lower():
            errs.append(f"E_PUBLISHER_MISMATCH: '{pub}' != '{expected_publisher}'")

    if existing_catalog is not None:
        for r in existing_catalog.get("rapplications", []):
            if r.get("id") == rid:
                if not _semver_gt(manifest["version"], r.get("version", "0.0.0")):
                    errs.append(f"E_VERSION_NOT_BUMPED: {manifest['version']} <= {r.get('version')}")

    integrity = {}
    if manifest.get("agent"):
        try:
            sblob = fetch(f"{raw_base}/{manifest['agent']}")
            sblob = sblob if isinstance(sblob, bytes) else sblob.encode()
        except Exception as e:
            errs.append(f"E_SINGLETON_MISSING: {manifest['agent']}: {e}")
        else:
            if len(sblob) > MAX_SINGLETON_BYTES:
                errs.append(f"E_SINGLETON_TOO_LARGE: {len(sblob)}")
            errs.extend(_validate_singleton_text(sblob.decode("utf-8", "replace"),
                                                 name=Path(manifest["agent"]).name))
            integrity["singleton_sha256"] = hashlib.sha256(sblob).hexdigest()
            integrity["singleton_bytes"] = len(sblob)

    commit_sha = None
    try:
        c = json.loads(fetch(f"https://api.github.com/repos/{repo}/commits/{ref}"))
        commit_sha = c.get("sha") if isinstance(c, dict) else None
    except Exception:
        pass

    if errs:
        return {"ok": False, "manifest": manifest, "errors": errs, "integrity": integrity}

    return {
        "ok": True, "manifest": manifest, "errors": [], "integrity": integrity,
        "source": {
            "type": "federation",
            "repo": repo, "ref": ref, "path": path,
            "commit_sha": commit_sha,
        },
        "raw_base": raw_base,
    }


# ── BasicAgent entrypoint ─────────────────────────────────────────────────

class PublishToRappStoreAgent(BasicAgent):
    def __init__(self):
        self.name = "PublishToRappStore"
        self.metadata = {
            "name": self.name,
            "description": (
                "Publish a rapplication to the kody-w/rapp_store catalog. "
                "Supports local bundles and federation (a public GitHub repo "
                "URL). Validates against SPEC.md, then opens a [RAPP] issue "
                "with the structured submission payload. The store maintainer "
                "(or an automation) approves the issue, after which the rapp "
                "appears in the catalog."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "validate_local", "validate_repo",
                            "bundle",
                            "submit_bundle", "submit_repo",
                            "status", "spec",
                        ],
                        "description": "What to do.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Local path to a rapp directory or .zip (for validate_local / bundle / submit_bundle).",
                    },
                    "repo_url": {
                        "type": "string",
                        "description": "Public GitHub URL like https://github.com/<owner>/<repo>[/tree/<ref>[/<path>]] (for validate_repo / submit_repo).",
                    },
                    "issue_number": {
                        "type": "integer",
                        "description": "Issue number to query (for status).",
                    },
                    "submitter": {
                        "type": "string",
                        "description": "GitHub @username of the submitter (defaults to env GITHUB_ACTOR or the @rapp publisher in the manifest).",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, validate and print the payload but do not open an issue.",
                    },
                },
                "required": ["action"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get("action")
        try:
            if action == "spec":
                return self._spec()
            if action == "validate_local":
                return self._validate_local(kwargs)
            if action == "validate_repo":
                return self._validate_repo(kwargs)
            if action == "bundle":
                return self._bundle(kwargs)
            if action == "submit_bundle":
                return self._submit_bundle(kwargs)
            if action == "submit_repo":
                return self._submit_repo(kwargs)
            if action == "status":
                return self._status(kwargs)
            return json.dumps({"error": f"unknown action: {action}"})
        except _ValidationFailure as e:
            return json.dumps({"ok": False, "errors": e.errors})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    # ── Action handlers ──────────────────────────────────────────────────

    def _spec(self):
        return ("RAPP store submission. SPEC.md authoritative; canonical at "
                f"{CATALOG_RAW_BASE}/SPEC.md. Validation rules in this file "
                "match the receiver's. Two modes: BUNDLE (files copied into "
                "rapp_store) and FEDERATION (catalog points at submitter's "
                "own public repo via raw.githubusercontent.com).")

    def _resolve_local(self, path_arg, kwargs=None):
        p = Path(path_arg).expanduser().resolve()
        if not p.exists():
            raise _ValidationFailure([f"E_PATH_NOT_FOUND: {p}"])
        submitter = self._submitter_arg(kwargs)
        catalog = _fetch_catalog()
        if p.is_file() and p.suffix == ".zip":
            blob = p.read_bytes()
            res = _validate_zip_bytes(blob,
                                       expected_publisher=submitter,
                                       existing_catalog=catalog)
            return res, blob
        if p.is_dir():
            res = _validate_dir(p,
                                  expected_publisher=submitter,
                                  existing_catalog=catalog)
            return res, None
        raise _ValidationFailure([f"E_BAD_PATH: {p} is not a directory or .zip"])

    def _submitter_arg(self, kwargs):
        # Submitter precedence: explicit kwarg → env → None (skip identity check).
        if kwargs and kwargs.get("submitter"):
            s = kwargs["submitter"]
            return s if s.startswith("@") else f"@{s}"
        actor = os.getenv("GITHUB_ACTOR")
        if actor:
            return f"@{actor}"
        return None

    def _validate_local(self, kwargs):
        path = kwargs.get("path")
        if not path:
            return json.dumps({"error": "path is required"})
        result, _ = self._resolve_local(path, kwargs)
        return json.dumps({
            "ok": result["ok"],
            "summary": _format_validation(result),
            "errors": result.get("errors", []),
            "manifest": result.get("manifest", {}),
        }, indent=2)

    def _validate_repo(self, kwargs):
        url = kwargs.get("repo_url")
        if not url:
            return json.dumps({"error": "repo_url is required"})
        repo, ref, path = _parse_repo_url(url)
        result = _validate_federation(
            repo, ref, path,
            expected_publisher=self._submitter_arg(kwargs),
            existing_catalog=_fetch_catalog())
        return json.dumps({
            "ok": result["ok"],
            "summary": _format_validation(result),
            "errors": result.get("errors", []),
            "manifest": result.get("manifest", {}),
            "source": result.get("source"),
        }, indent=2)

    def _bundle(self, kwargs):
        path = kwargs.get("path")
        if not path:
            return json.dumps({"error": "path is required"})
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            return json.dumps({"error": f"not a directory: {p}"})
        blob = _bundle_dir_to_zip(p)
        out = p.parent / f"{p.name}-{json.loads((p / 'manifest.json').read_text())['version']}.zip"
        out.write_bytes(blob)
        return json.dumps({
            "ok": True,
            "bundle_path": str(out),
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }, indent=2)

    def _submit_bundle(self, kwargs):
        path = kwargs.get("path")
        dry_run = bool(kwargs.get("dry_run"))
        if not path:
            return json.dumps({"error": "path is required"})
        result, blob = self._resolve_local(path, kwargs)
        if not result["ok"]:
            return json.dumps({"ok": False, "errors": result["errors"]}, indent=2)
        if blob is None:
            blob = _bundle_dir_to_zip(Path(path).expanduser().resolve())
        m = result["manifest"]

        body = self._issue_body_bundle(m, blob)
        title = f"[RAPP] {m['publisher']}/{m['id']} v{m['version']}"
        labels = ["rapplication-submission", "pending-review", "mode:bundle"]
        return self._open_issue_or_print(title, body, labels, dry_run, m)

    def _submit_repo(self, kwargs):
        url = kwargs.get("repo_url")
        dry_run = bool(kwargs.get("dry_run"))
        if not url:
            return json.dumps({"error": "repo_url is required"})
        repo, ref, path = _parse_repo_url(url)
        result = _validate_federation(
            repo, ref, path,
            expected_publisher=self._submitter_arg(kwargs),
            existing_catalog=_fetch_catalog())
        if not result["ok"]:
            return json.dumps({"ok": False, "errors": result["errors"]}, indent=2)
        m = result["manifest"]
        body = self._issue_body_federation(m, result["source"], result.get("integrity", {}))
        title = f"[RAPP] {m['publisher']}/{m['id']} v{m['version']}"
        labels = ["rapplication-submission", "pending-review", "mode:federation"]
        return self._open_issue_or_print(title, body, labels, dry_run, m)

    def _status(self, kwargs):
        n = kwargs.get("issue_number")
        if not n:
            return json.dumps({"error": "issue_number is required"})
        try:
            data = json.loads(_http_get(f"{ISSUES_API}/{int(n)}"))
        except Exception as e:
            return json.dumps({"error": f"failed to fetch issue #{n}: {e}"})
        labels = [l.get("name") for l in data.get("labels", [])]
        return json.dumps({
            "issue": int(n),
            "title": data.get("title"),
            "state": data.get("state"),
            "labels": labels,
            "html_url": data.get("html_url"),
            "approved": "approved" in labels,
            "rejected": "failed" in labels or "rejected" in labels,
        }, indent=2)

    # ── Issue body construction ──────────────────────────────────────────

    def _issue_body_bundle(self, manifest, blob):
        sha = hashlib.sha256(blob).hexdigest()
        b64 = base64.b64encode(blob).decode("ascii")
        wrapped = "\n".join(b64[i:i + 76] for i in range(0, len(b64), 76))
        meta = {
            "submission_type": "bundle",
            "id": manifest["id"],
            "version": manifest["version"],
            "publisher": manifest["publisher"],
            "name": manifest.get("name"),
            "category": manifest.get("category"),
            "tags": manifest.get("tags", []),
            "bundle_bytes": len(blob),
            "bundle_sha256": sha,
        }
        return (
            "## Rapplication Submission\n\n"
            "**Mode:** bundle (files copied into rapp_store on approval)\n\n"
            "```json\n" + json.dumps(meta, indent=2) + "\n```\n\n"
            "<details><summary>Bundle (base64-encoded zip)</summary>\n\n"
            "```bundle\n" + wrapped + "\n```\n"
            "</details>\n\n"
            "_Submitted by `@rapp/publish-to-rapp-store` agent. The receiver "
            "workflow will validate this bundle against SPEC.md and stage it "
            "for maintainer approval._\n"
        )

    def _issue_body_federation(self, manifest, source, integrity):
        meta = {
            "submission_type": "federation",
            "id": manifest["id"],
            "version": manifest["version"],
            "publisher": manifest["publisher"],
            "name": manifest.get("name"),
            "category": manifest.get("category"),
            "tags": manifest.get("tags", []),
            "source": source,
            "integrity": integrity,
        }
        return (
            "## Rapplication Submission\n\n"
            f"**Mode:** federation (catalog points at `{source['repo']}@{source['ref']}`)\n\n"
            "```json\n" + json.dumps(meta, indent=2) + "\n```\n\n"
            "_Submitted by `@rapp/publish-to-rapp-store` agent. The receiver "
            "workflow will refetch the manifest + singleton from the source "
            "repo and validate against SPEC.md before staging._\n"
        )

    def _open_issue_or_print(self, title, body, labels, dry_run, manifest):
        token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
        if dry_run or not token:
            return json.dumps({
                "ok": True,
                "dry_run": True,
                "reason": "dry_run set" if dry_run else "no GH_TOKEN in env",
                "title": title,
                "labels": labels,
                "body_preview": body[:500] + ("..." if len(body) > 500 else ""),
                "instructions": (
                    f"To submit manually: open an issue at "
                    f"https://github.com/{CATALOG_OWNER_REPO}/issues/new with "
                    f"the title and body above, and the labels {labels}. "
                    "Or set GH_TOKEN and re-run with dry_run=false."
                ),
            }, indent=2)
        try:
            resp = _http_post(ISSUES_API, {
                "title": title,
                "body": body,
                "labels": labels,
            }, token)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, indent=2)
        return json.dumps({
            "ok": True,
            "issue": resp.get("number"),
            "html_url": resp.get("html_url"),
            "manifest_id": manifest["id"],
            "manifest_version": manifest["version"],
        }, indent=2)
