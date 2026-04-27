"""
binder_service.py — The package manager for a brainstem.

Fetches the catalog from the public RAPPstore index, downloads agent
files into agents/, and (when a catalog entry includes one) downloads
the matching service file into services/. Tracks installations in
.brainstem_data/binder.json so uninstall is symmetric.

Endpoints:
    GET    /api/binder                  — list installed rapplications
    GET    /api/binder/catalog          — fetch remote catalog
    POST   /api/binder/install          — install by id  (body: {"id": "..."})
    DELETE /api/binder/installed/<id>   — uninstall by id

The brainstem ships clean. This service is bootstrapped by start.sh on
first launch and from then on it installs everything else (including
its own updates and the swarms service).
"""

import hashlib
import json
import os

name = "binder"

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, ".brainstem_data")
_STATE_FILE = os.path.join(_DATA_DIR, "binder.json")
_AGENTS_DIR = os.path.join(_BASE_DIR, "agents")
_SERVICES_DIR = os.path.join(_BASE_DIR, "services")
# Distros and mirrors are first-class: RAPPSTORE_URL overrides the default
# catalog. A "RAPP Ubuntu" or "RAPP Arch" fork sets this to its own mirror
# and binder transparently installs from there. Sacred wire stays the same.
_CATALOG_URL = os.getenv("RAPPSTORE_URL", "https://raw.githubusercontent.com/kody-w/RAPP/main/rapp_store/index.json")


def _read():
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE) as f:
            return json.load(f)
    return {"installed": []}


def _write(data):
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _fetch_catalog():
    try:
        import requests
        resp = requests.get(_CATALOG_URL, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"rapplications": []}


def _download(url, expected_sha=None):
    """Download a file and (optionally) verify its SHA256. Returns text content
    or raises with a useful message."""
    import requests
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"download failed: HTTP {resp.status_code}")
    content = resp.text
    if expected_sha:
        actual_sha = hashlib.sha256(content.encode()).hexdigest()
        if actual_sha != expected_sha:
            raise RuntimeError("SHA256 mismatch — file may be corrupted")
    return content


def _write_to_dir(directory, filename, content):
    os.makedirs(directory, exist_ok=True)
    filepath = os.path.join(directory, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def _remove_from_dir(directory, filename):
    if not filename:
        return
    filepath = os.path.join(directory, filename)
    if os.path.exists(filepath):
        os.remove(filepath)


def handle(method, path, body):
    # GET /api/binder — list installed rapplications
    if method == "GET" and path == "":
        return _read(), 200

    # GET /api/binder/catalog — fetch remote catalog
    if method == "GET" and path == "catalog":
        return _fetch_catalog(), 200

    # POST /api/binder/install — install a rapplication by id, optionally pinned to a version
    if method == "POST" and path == "install":
        rapp_id = body.get("id", "")
        version = body.get("version", "")  # optional; empty = latest from catalog
        if not rapp_id:
            return {"error": "id required"}, 400

        catalog = _fetch_catalog()
        entry = next((r for r in catalog.get("rapplications", []) if r.get("id") == rapp_id), None)
        if not entry:
            return {"error": f"rapplication '{rapp_id}' not found in catalog"}, 404

        # Version pinning: if the caller asked for a specific version and the
        # catalog entry lists available_versions, swap URLs/SHAs to that version.
        # Edge clients pin to a specific version URL; everyone else gets latest.
        if version:
            available = entry.get("available_versions", [])
            if available and version not in available:
                return {"error": f"version '{version}' not available; have {available}"}, 404
            # Rewrite the URLs to point at the versioned path
            for fld in ("singleton_url", "service_url"):
                u = entry.get(fld)
                if u and "/versions/" not in u:
                    base, fname = u.rsplit("/", 1)
                    entry[fld] = f"{base}/versions/{version}/{fname}"
            # Pinned installs can't trust the catalog's SHA fields (those are
            # for latest); the caller is responsible for verifying out-of-band.
            entry.pop("singleton_sha256", None)
            entry.pop("service_sha256", None)
            entry["version"] = version

        installed = {"id": rapp_id, "version": entry.get("version", "?")}

        # Agent file (optional — pure services like binder/swarms may not have one)
        agent_url = entry.get("singleton_url")
        agent_filename = entry.get("singleton_filename")
        if agent_url and agent_filename:
            try:
                content = _download(agent_url, entry.get("singleton_sha256"))
            except Exception as e:
                return {"error": f"agent download failed: {e}"}, 502
            _write_to_dir(_AGENTS_DIR, agent_filename, content)
            installed["agent_filename"] = agent_filename
            # Backwards-compat: keep `filename` for older binder.json readers
            installed["filename"] = agent_filename

        # Service file (optional — some rapplications are agent-only)
        service_url = entry.get("service_url")
        service_filename = entry.get("service_filename")
        if service_url and service_filename:
            try:
                content = _download(service_url, entry.get("service_sha256"))
            except Exception as e:
                return {"error": f"service download failed: {e}"}, 502
            _write_to_dir(_SERVICES_DIR, service_filename, content)
            installed["service_filename"] = service_filename

        if "agent_filename" not in installed and "service_filename" not in installed:
            return {"error": "rapplication has neither agent nor service files"}, 400

        # Track installation (replace any existing entry for this id)
        state = _read()
        state["installed"] = [e for e in state["installed"] if e.get("id") != rapp_id]
        state["installed"].append(installed)
        _write(state)
        return {"status": "ok", "installed": installed}, 200

    # DELETE /api/binder/installed/<id> — uninstall a rapplication
    if method == "DELETE" and path.startswith("installed/"):
        rapp_id = path[len("installed/"):]
        state = _read()
        entry = next((e for e in state["installed"] if e.get("id") == rapp_id), None)
        if not entry:
            return {"error": "not installed"}, 404

        _remove_from_dir(_AGENTS_DIR, entry.get("agent_filename") or entry.get("filename"))
        _remove_from_dir(_SERVICES_DIR, entry.get("service_filename"))

        state["installed"] = [e for e in state["installed"] if e.get("id") != rapp_id]
        _write(state)
        return {"status": "ok", "uninstalled": rapp_id}, 200

    return {"error": "not found"}, 404
