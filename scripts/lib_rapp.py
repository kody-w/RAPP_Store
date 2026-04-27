"""lib_rapp — canonical rapplication validator and bundler.

This module is the single source of truth for SPEC.md §6 (validation rules)
and §4 (singleton contract). Used by:

  - the @rapp/publish-to-rapp-store agent (for local pre-flight checks)
  - .github/workflows/process-rapplication.yml (for server-side validation)
  - .github/workflows/approve-rapplication.yml (for promotion)

Stdlib only. Python 3.8+. No third-party imports.

The validator is intentionally strict on structure and lenient on metadata
fields beyond the required set — the catalog tolerates extra keys.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Constants ─────────────────────────────────────────────────────────────

SCHEMA_MANIFEST = "rapp-application/1.0"
SCHEMA_AGENT_INTERNAL = "rapp-agent/1.0"
SCHEMA_INDEX = "rapp-store/1.0"

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

ACCEPTED_QUALITY_TIERS = frozenset({"official", "verified", "community", "experimental"})

ACCEPTED_BASIC_AGENT_IMPORTS = (
    "from agents.basic_agent import BasicAgent",
    "from basic_agent import BasicAgent",
    "from openrappter.agents.basic_agent import BasicAgent",
)

TEMPLATE_PLACEHOLDERS = (
    "{{PLACEHOLDER}}",
    "{{TEAM_NAME}}",
    "{{CLASS_NAME}}",
    "YOUR LOGIC GOES HERE",
    "TODO REPLACE",
    "RAPP AGENT TEMPLATE",
    "@your_username/",
)

MAX_BUNDLE_BYTES = 5 * 1024 * 1024
MAX_SINGLETON_BYTES = 200 * 1024
MAX_UI_BYTES = 500 * 1024

CATALOG_RAW_BASE = "https://raw.githubusercontent.com/kody-w/rapp_store/main"


# ── Result types ──────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    ok: bool
    rapp_dir: Path | None = None      # bundle root (after wrapper unwrap)
    manifest: dict[str, Any] = field(default_factory=dict)
    index_entry: dict[str, Any] = field(default_factory=dict)
    integrity: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


# ── Public API ────────────────────────────────────────────────────────────

def validate_zip(zip_bytes: bytes, *,
                 expected_publisher: str | None = None,
                 existing_catalog: dict | None = None,
                 extract_to: Path | None = None) -> ValidationResult:
    """Extract a .zip and validate the rapplication inside.

    `expected_publisher`: the GitHub `@username` we expect to be the publisher
        (None to skip the publisher-identity check).
    `existing_catalog`: parsed `index.json` for version-bump enforcement
        (None to skip).
    `extract_to`: where to extract the bundle. If None, the result will not
        retain a directory; callers that need the files should pass a Path.
    """
    if len(zip_bytes) > MAX_BUNDLE_BYTES:
        return ValidationResult(ok=False, errors=[
            f"E_BUNDLE_TOO_LARGE: {len(zip_bytes)} bytes > {MAX_BUNDLE_BYTES} cap"
        ])

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        return ValidationResult(ok=False, errors=[f"E_BAD_ZIP: {e}"])

    safe = _check_zip_safety(zf)
    if safe:
        return ValidationResult(ok=False, errors=safe)

    target = extract_to or Path(_make_temp_dir())
    target.mkdir(parents=True, exist_ok=True)
    zf.extractall(target)
    zf.close()

    rapp_dir = _unwrap_bundle_root(target)
    if rapp_dir is None:
        return ValidationResult(ok=False, errors=["E_NO_MANIFEST: no manifest.json found in bundle"])

    return validate_dir(rapp_dir,
                        expected_publisher=expected_publisher,
                        existing_catalog=existing_catalog)


def validate_dir(rapp_dir: Path, *,
                 expected_publisher: str | None = None,
                 existing_catalog: dict | None = None) -> ValidationResult:
    """Validate an extracted rapplication directory."""
    rapp_dir = Path(rapp_dir)
    errors: list[str] = []

    manifest_path = rapp_dir / "manifest.json"
    if not manifest_path.is_file():
        return ValidationResult(ok=False, rapp_dir=rapp_dir,
                                errors=["E_NO_MANIFEST: missing manifest.json"])
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        return ValidationResult(ok=False, rapp_dir=rapp_dir,
                                errors=[f"E_BAD_MANIFEST_JSON: {e}"])

    errors.extend(_validate_manifest(manifest))
    if errors:
        return ValidationResult(ok=False, rapp_dir=rapp_dir, manifest=manifest, errors=errors)

    rapp_id = manifest["id"]

    if rapp_dir.name != rapp_id:
        errors.append(f"E_DIR_NAME_MISMATCH: directory '{rapp_dir.name}' != manifest.id '{rapp_id}'")

    if rapp_id in RESERVED_IDS:
        errors.append(f"E_RESERVED_ID: '{rapp_id}' is reserved by the platform")

    publisher = manifest["publisher"]
    if expected_publisher is not None:
        if publisher in OFFICIAL_PUBLISHERS and expected_publisher.lower() not in {"@kody-w", "@rapp"}:
            errors.append(f"E_PUBLISHER_MISMATCH: '{publisher}' is reserved; "
                          f"submitter is '{expected_publisher}'")
        elif publisher not in OFFICIAL_PUBLISHERS and publisher.lower() != expected_publisher.lower():
            errors.append(f"E_PUBLISHER_MISMATCH: manifest.publisher '{publisher}' != "
                          f"submitter '{expected_publisher}'")

    if existing_catalog is not None:
        prev = _find_catalog_entry(existing_catalog, rapp_id)
        if prev and not _semver_gt(manifest["version"], prev.get("version", "0.0.0")):
            errors.append(f"E_VERSION_NOT_BUMPED: manifest.version '{manifest['version']}' "
                          f"must be > existing '{prev.get('version')}'")

    agent_rel = manifest.get("agent")
    service_rel = manifest.get("service")
    ui_rel = manifest.get("ui")

    singleton_path: Path | None = None
    if agent_rel:
        singleton_path = rapp_dir / agent_rel
        if not singleton_path.is_file():
            errors.append(f"E_SINGLETON_MISSING: {agent_rel} not found in bundle")
        else:
            sb = singleton_path.stat().st_size
            if sb > MAX_SINGLETON_BYTES:
                errors.append(f"E_SINGLETON_TOO_LARGE: {sb} bytes > {MAX_SINGLETON_BYTES} cap")
            errors.extend(_validate_singleton(singleton_path))

    if service_rel:
        svc_path = rapp_dir / service_rel
        if not svc_path.is_file():
            errors.append(f"E_SERVICE_MISSING: {service_rel} not found in bundle")
        else:
            errors.extend(_validate_service(svc_path))

    if ui_rel:
        ui_path = rapp_dir / ui_rel
        if not ui_path.is_file():
            errors.append(f"E_UI_MISSING: {ui_rel} not found in bundle")
        else:
            ub = ui_path.stat().st_size
            if ub > MAX_UI_BYTES:
                errors.append(f"E_UI_TOO_LARGE: {ub} bytes > {MAX_UI_BYTES} cap")

    index_entry_path = rapp_dir / "index_entry.json"
    index_entry: dict = {}
    if index_entry_path.is_file():
        try:
            index_entry = json.loads(index_entry_path.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"E_BAD_INDEX_ENTRY_JSON: {e}")
    else:
        errors.append("E_NO_INDEX_ENTRY: missing index_entry.json")

    if not (rapp_dir / "README.md").is_file():
        errors.append("E_NO_README: missing README.md")

    integrity = compute_integrity(rapp_dir, manifest) if singleton_path else {}

    if errors:
        return ValidationResult(ok=False, rapp_dir=rapp_dir, manifest=manifest,
                                index_entry=index_entry, integrity=integrity, errors=errors)
    return ValidationResult(ok=True, rapp_dir=rapp_dir, manifest=manifest,
                            index_entry=index_entry, integrity=integrity, errors=[])


def compute_integrity(rapp_dir: Path, manifest: dict) -> dict[str, Any]:
    """Compute SHA256/lines/bytes for the singleton, service, and UI files."""
    rapp_dir = Path(rapp_dir)
    out: dict[str, Any] = {}
    if manifest.get("agent"):
        p = rapp_dir / manifest["agent"]
        if p.is_file():
            out.update(_file_integrity(p, "singleton"))
    if manifest.get("service"):
        p = rapp_dir / manifest["service"]
        if p.is_file():
            out.update(_file_integrity(p, "service"))
    if manifest.get("ui"):
        p = rapp_dir / manifest["ui"]
        if p.is_file():
            data = p.read_bytes()
            out["ui_sha256"] = hashlib.sha256(data).hexdigest()
            out["ui_bytes"] = len(data)
    return out


def build_index_entry(manifest: dict, integrity: dict, rapp_id: str) -> dict[str, Any]:
    """Construct the canonical catalog entry, overwriting integrity + URLs.

    Submitter-supplied `index_entry.json` is the merge base; the receiver
    overrides URLs, sha256, lines, bytes from the actual files."""
    entry: dict[str, Any] = {
        "id": rapp_id,
        "name": manifest["name"],
        "version": manifest["version"],
        "summary": manifest.get("summary", ""),
        "category": manifest.get("category", ""),
        "tags": manifest.get("tags", []),
        "license": manifest.get("license", "BSD-style"),
        "publisher": manifest["publisher"],
    }
    for opt in ("tagline", "manifest_name", "produced_by", "metrics",
                "optional_dependencies", "spec_post"):
        if opt in manifest:
            entry[opt] = manifest[opt]

    if manifest.get("agent"):
        agent_rel = manifest["agent"]
        agent_filename = Path(agent_rel).name
        entry["singleton_filename"] = agent_filename
        entry["singleton_url"] = f"{CATALOG_RAW_BASE}/{rapp_id}/{agent_rel}"
        if "singleton_sha256" in integrity:
            entry["singleton_sha256"] = integrity["singleton_sha256"]
        if "singleton_lines" in integrity:
            entry["singleton_lines"] = integrity["singleton_lines"]
        if "singleton_bytes" in integrity:
            entry["singleton_bytes"] = integrity["singleton_bytes"]

    if manifest.get("service"):
        svc_rel = manifest["service"]
        entry["service_filename"] = Path(svc_rel).name
        entry["service_url"] = f"{CATALOG_RAW_BASE}/{rapp_id}/{svc_rel}"
        if "service_sha256" in integrity:
            entry["service_sha256"] = integrity["service_sha256"]

    if manifest.get("ui"):
        ui_rel = manifest["ui"]
        entry["ui_filename"] = Path(ui_rel).name
        entry["ui_url"] = f"{CATALOG_RAW_BASE}/{rapp_id}/{ui_rel}"

    return entry


def merge_index_entry(catalog: dict, entry: dict) -> dict:
    """Insert or replace an entry in the catalog's `rapplications` list.

    Preserves the existing order: if `entry["id"]` is already in the catalog,
    it is replaced in place; otherwise it is appended at the end."""
    out = dict(catalog)
    rapps = list(out.get("rapplications", []))
    for i, r in enumerate(rapps):
        if r.get("id") == entry["id"]:
            rapps[i] = entry
            break
    else:
        rapps.append(entry)
    out["rapplications"] = rapps
    return out


def validate_federation(repo: str, ref: str = "main", path: str = "", *,
                        expected_publisher: str | None = None,
                        existing_catalog: dict | None = None,
                        fetcher=None) -> ValidationResult:
    """Validate a federated rapplication served from a public GitHub repo.

    Fetches manifest.json + the singleton (and optional ui/service) via
    raw.githubusercontent.com, runs the same §6 validation as for bundles,
    and returns a ValidationResult whose `index_entry` carries a `source`
    block pinning repo/ref/commit_sha.

    `repo` is "<owner>/<name>". `ref` is a branch, tag, or commit SHA. `path`
    is the rapp directory inside the repo (empty if the repo root IS the
    rapp). `fetcher` is an optional callable (url) -> bytes for testing;
    defaults to urllib.

    All HTTP is anonymous — public GitHub raw + public commits API only.
    Rate limiting may apply; the receiver retries with backoff."""
    fetch = fetcher or _default_fetcher()
    errors: list[str] = []

    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
        return ValidationResult(ok=False, errors=[f"E_BAD_REPO: '{repo}' must be '<owner>/<name>'"])

    rel_path = path.strip("/")
    raw_base = f"https://raw.githubusercontent.com/{repo}/{ref}"
    if rel_path:
        raw_base = f"{raw_base}/{rel_path}"

    try:
        manifest_blob = fetch(f"{raw_base}/manifest.json")
    except FetchError as e:
        return ValidationResult(ok=False, errors=[f"E_FETCH_MANIFEST: {e}"])

    try:
        manifest = json.loads(manifest_blob.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return ValidationResult(ok=False, errors=[f"E_BAD_MANIFEST_JSON: {e}"])

    errors.extend(_validate_manifest(manifest))
    if errors:
        return ValidationResult(ok=False, manifest=manifest, errors=errors)

    rapp_id = manifest["id"]
    if rapp_id in RESERVED_IDS:
        errors.append(f"E_RESERVED_ID: '{rapp_id}' is reserved by the platform")

    publisher = manifest["publisher"]
    if expected_publisher is not None:
        if publisher in OFFICIAL_PUBLISHERS and expected_publisher.lower() not in {"@kody-w", "@rapp"}:
            errors.append(f"E_PUBLISHER_MISMATCH: '{publisher}' is reserved; "
                          f"submitter is '{expected_publisher}'")
        elif publisher not in OFFICIAL_PUBLISHERS and publisher.lower() != expected_publisher.lower():
            errors.append(f"E_PUBLISHER_MISMATCH: manifest.publisher '{publisher}' != "
                          f"submitter '{expected_publisher}'")

    if existing_catalog is not None:
        prev = _find_catalog_entry(existing_catalog, rapp_id)
        if prev and not _semver_gt(manifest["version"], prev.get("version", "0.0.0")):
            errors.append(f"E_VERSION_NOT_BUMPED: manifest.version '{manifest['version']}' "
                          f"must be > existing '{prev.get('version')}'")

    integrity: dict[str, Any] = {}
    agent_rel = manifest.get("agent")
    service_rel = manifest.get("service")
    ui_rel = manifest.get("ui")

    singleton_blob: bytes | None = None
    if agent_rel:
        try:
            singleton_blob = fetch(f"{raw_base}/{agent_rel}")
        except FetchError as e:
            errors.append(f"E_SINGLETON_MISSING: {agent_rel}: {e}")
        else:
            if len(singleton_blob) > MAX_SINGLETON_BYTES:
                errors.append(f"E_SINGLETON_TOO_LARGE: {len(singleton_blob)} bytes")
            errors.extend(_validate_singleton_bytes(singleton_blob, agent_rel))
            integrity.update({
                "singleton_sha256": hashlib.sha256(singleton_blob).hexdigest(),
                "singleton_bytes": len(singleton_blob),
                "singleton_lines": singleton_blob.count(b"\n") + (0 if singleton_blob.endswith(b"\n") else 1),
            })

    if service_rel:
        try:
            svc_blob = fetch(f"{raw_base}/{service_rel}")
        except FetchError as e:
            errors.append(f"E_SERVICE_MISSING: {service_rel}: {e}")
        else:
            errors.extend(_validate_service_bytes(svc_blob, service_rel))
            integrity["service_sha256"] = hashlib.sha256(svc_blob).hexdigest()
            integrity["service_bytes"] = len(svc_blob)

    if ui_rel:
        try:
            ui_blob = fetch(f"{raw_base}/{ui_rel}")
        except FetchError as e:
            errors.append(f"E_UI_MISSING: {ui_rel}: {e}")
        else:
            if len(ui_blob) > MAX_UI_BYTES:
                errors.append(f"E_UI_TOO_LARGE: {len(ui_blob)} bytes")
            integrity["ui_sha256"] = hashlib.sha256(ui_blob).hexdigest()
            integrity["ui_bytes"] = len(ui_blob)

    commit_sha: str | None = None
    try:
        commit_blob = fetch(f"https://api.github.com/repos/{repo}/commits/{ref}")
        commit_sha = json.loads(commit_blob.decode("utf-8")).get("sha")
    except FetchError:
        pass  # commit-sha pinning is best-effort; entry is still valid without it
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    if errors:
        return ValidationResult(ok=False, manifest=manifest,
                                integrity=integrity, errors=errors)

    entry = build_index_entry(manifest, integrity, rapp_id)
    entry = _rewrite_for_federation(entry, manifest, repo, ref, rel_path, commit_sha)

    return ValidationResult(ok=True, manifest=manifest,
                            index_entry=entry, integrity=integrity, errors=[])


def _rewrite_for_federation(entry: dict, manifest: dict, repo: str,
                            ref: str, rel_path: str, commit_sha: str | None) -> dict:
    raw_base = f"https://raw.githubusercontent.com/{repo}/{ref}"
    if rel_path:
        raw_base = f"{raw_base}/{rel_path}"
    if manifest.get("agent"):
        entry["singleton_url"] = f"{raw_base}/{manifest['agent']}"
    if manifest.get("service"):
        entry["service_url"] = f"{raw_base}/{manifest['service']}"
    if manifest.get("ui"):
        entry["ui_url"] = f"{raw_base}/{manifest['ui']}"
    src: dict[str, Any] = {
        "type": "federation",
        "repo": repo,
        "ref": ref,
        "path": rel_path,
    }
    if commit_sha:
        src["commit_sha"] = commit_sha
    entry["source"] = src
    return entry


def parse_repo_url(url: str) -> tuple[str, str, str]:
    """Parse a GitHub URL like https://github.com/<owner>/<repo>[/tree/<ref>[/<path>]]
    into (repo, ref, path). Defaults: ref='main', path=''."""
    m = re.match(
        r"^https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?"
        r"(?:/(?:tree|blob)/([^/]+)(?:/(.+?))?)?/?$", url.strip())
    if not m:
        raise ValueError(f"not a github url: {url!r}")
    repo = m.group(1)
    ref = m.group(2) or "main"
    path = m.group(3) or ""
    return repo, ref, path


def _validate_singleton_bytes(blob: bytes, name: str) -> list[str]:
    """Same as _validate_singleton but takes bytes (no filesystem path)."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        f.write(blob)
        tmp = Path(f.name)
    try:
        return _validate_singleton(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _validate_service_bytes(blob: bytes, name: str) -> list[str]:
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        f.write(blob)
        tmp = Path(f.name)
    try:
        return _validate_service(tmp)
    finally:
        tmp.unlink(missing_ok=True)


class FetchError(Exception):
    """Raised when an HTTP fetch fails (404, network, etc)."""


def _default_fetcher():
    import urllib.request
    import urllib.error

    def fetch(url: str) -> bytes:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "rapp-store-validator/1.0",
                "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise FetchError(f"HTTP {e.code} for {url}") from e
        except urllib.error.URLError as e:
            raise FetchError(f"network error for {url}: {e}") from e
    return fetch


def bundle_dir(rapp_dir: Path) -> bytes:
    """Zip a rapp directory into a bundle. The archive contains <id>/...
    so it round-trips with the unwrap logic in validate_zip."""
    rapp_dir = Path(rapp_dir)
    if not (rapp_dir / "manifest.json").is_file():
        raise ValueError(f"not a rapp dir: {rapp_dir} (no manifest.json)")
    rapp_id = rapp_dir.name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(rapp_dir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(rapp_dir)
                zf.write(p, f"{rapp_id}/{rel.as_posix()}")
    return buf.getvalue()


# ── Internals ─────────────────────────────────────────────────────────────

def _make_temp_dir() -> str:
    import tempfile
    return tempfile.mkdtemp(prefix="rapp_validate_")


def _check_zip_safety(zf: zipfile.ZipFile) -> list[str]:
    errs: list[str] = []
    total = 0
    for info in zf.infolist():
        name = info.filename
        if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
            errs.append(f"E_PATH_TRAVERSAL: {name}")
        total += info.file_size
        if total > MAX_BUNDLE_BYTES * 4:  # uncompressed cap, anti-zipbomb
            errs.append(f"E_ZIP_BOMB: uncompressed total exceeds {MAX_BUNDLE_BYTES * 4}")
            break
    return errs


def _unwrap_bundle_root(extract_to: Path) -> Path | None:
    """If the zip has a single top-level directory containing manifest.json,
    return that. Otherwise if extract_to itself contains manifest.json,
    return extract_to. Otherwise None."""
    if (extract_to / "manifest.json").is_file():
        return extract_to
    children = [c for c in extract_to.iterdir() if not c.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir() and (children[0] / "manifest.json").is_file():
        return children[0]
    for c in children:
        if c.is_dir() and (c / "manifest.json").is_file():
            return c
    return None


def _validate_manifest(m: dict) -> list[str]:
    errs: list[str] = []
    if m.get("schema") != SCHEMA_MANIFEST:
        errs.append(f"E_MANIFEST_SCHEMA: schema must be '{SCHEMA_MANIFEST}', got '{m.get('schema')}'")

    rapp_id = m.get("id")
    if not isinstance(rapp_id, str) or not ID_RE.match(rapp_id):
        errs.append(f"E_BAD_ID: id must match {ID_RE.pattern}, got {rapp_id!r}")

    if not isinstance(m.get("name"), str) or not m.get("name"):
        errs.append("E_BAD_NAME: name is required")

    version = m.get("version")
    if not isinstance(version, str) or not SEMVER_RE.match(version):
        errs.append(f"E_BAD_VERSION: version must be MAJOR.MINOR.PATCH, got {version!r}")

    publisher = m.get("publisher")
    if not isinstance(publisher, str) or not PUBLISHER_RE.match(publisher):
        errs.append(f"E_BAD_PUBLISHER: publisher must match @username, got {publisher!r}")

    if not isinstance(m.get("summary"), str) or not m.get("summary"):
        errs.append("E_BAD_SUMMARY: summary is required")

    if not isinstance(m.get("category"), str) or not m.get("category"):
        errs.append("E_BAD_CATEGORY: category is required")

    tags = m.get("tags")
    if not isinstance(tags, list) or not tags:
        errs.append("E_BAD_TAGS: tags must be a non-empty list")

    if not m.get("agent") and not m.get("service"):
        errs.append("E_NO_ENTRYPOINT: manifest must declare agent and/or service")

    qt = m.get("quality_tier")
    if qt is not None and qt not in ACCEPTED_QUALITY_TIERS:
        errs.append(f"E_BAD_QUALITY_TIER: quality_tier must be one of {sorted(ACCEPTED_QUALITY_TIERS)}")

    return errs


def _validate_singleton(path: Path) -> list[str]:
    errs: list[str] = []
    src = path.read_text(encoding="utf-8", errors="replace")

    # A file that legitimately defines the placeholder list (e.g. a publishing
    # agent that mirrors this validator) can opt out of the placeholder check
    # by including the marker comment below in its source.
    if "rapp-validator: allow-template-placeholders" not in src:
        for ph in TEMPLATE_PLACEHOLDERS:
            if ph in src:
                errs.append(f"E_TEMPLATE_PLACEHOLDER: unresolved '{ph}' in {path.name}")

    if not any(imp in src for imp in ACCEPTED_BASIC_AGENT_IMPORTS):
        errs.append(f"E_NO_BASIC_AGENT_IMPORT: {path.name} must import BasicAgent")

    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        errs.append(f"E_SINGLETON_SYNTAX: {e}")
        return errs

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

    public_classes: list[ast.ClassDef] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.name == "BasicAgent" or node.name.startswith("_Internal"):
                continue
            if node.name.endswith("Agent"):
                public_classes.append(node)

    if len(public_classes) == 0:
        errs.append("E_NO_AGENT_CLASS: no public class ending in 'Agent' (extending BasicAgent)")
    elif len(public_classes) > 1:
        errs.append(f"E_MULTIPLE_AGENT_CLASSES: {[c.name for c in public_classes]} "
                    f"(only one public *Agent allowed; prefix internals with _Internal)")
    else:
        cls = public_classes[0]
        bases = {b.id if isinstance(b, ast.Name) else (
                  b.attr if isinstance(b, ast.Attribute) else None)
                 for b in cls.bases}
        if "BasicAgent" not in bases:
            errs.append(f"E_NOT_BASIC_AGENT: {cls.name} must extend BasicAgent (bases={bases})")
        has_perform = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "perform"
                          for n in cls.body)
        if not has_perform:
            errs.append(f"E_NO_PERFORM: {cls.name} missing perform() method")

    return errs


def _validate_service(path: Path) -> list[str]:
    errs: list[str] = []
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"E_SERVICE_SYNTAX: {e}"]
    has_name = False
    has_handle = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "name":
                    has_name = True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "handle":
            has_handle = True
    if not has_name:
        errs.append("E_SERVICE_NO_NAME: service must declare module-level `name`")
    if not has_handle:
        errs.append("E_SERVICE_NO_HANDLE: service must define handle(method, path, body)")
    return errs


def _file_integrity(p: Path, prefix: str) -> dict[str, Any]:
    data = p.read_bytes()
    return {
        f"{prefix}_sha256": hashlib.sha256(data).hexdigest(),
        f"{prefix}_bytes": len(data),
        f"{prefix}_lines": data.count(b"\n") + (0 if data.endswith(b"\n") else 1),
    }


def _find_catalog_entry(catalog: dict, rapp_id: str) -> dict | None:
    for r in catalog.get("rapplications", []):
        if r.get("id") == rapp_id:
            return r
    return None


def _semver_gt(a: str, b: str) -> bool:
    ma = SEMVER_RE.match(a)
    mb = SEMVER_RE.match(b)
    if not ma or not mb:
        return False
    return tuple(int(x) for x in ma.groups()) > tuple(int(x) for x in mb.groups())
