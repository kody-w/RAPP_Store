"""
rapp_zoo_organ.py — the rapp-zoo's HTTP backplane, hosted INSIDE the brainstem.

Per Article XXXVII (Rapplications Are Organisms) + the canonical
rapplication shape (Article XXXVIII once ratified):

    rapp = agents/<name>_agent.py        ← chat face (LLM tool)
         + utils/organs/<name>_organ.py  ← HTTP backplane (UI backend)
         + .brainstem_data/rapp_ui/<rapp_id>/   ← skin
         + .brainstem_data/<rapp_id>/    ← per-rapp state (optional)

This organ replaces the standalone Flask process the rapp-zoo used to
run as on port 7070. Endpoints now live at /api/rapp_zoo/* on the host
brainstem (default 7071). One process, one port, one identity.

Endpoints (all under /api/rapp_zoo/<path>):

    GET  /health              — zoo liveness + per-twin health summary
    GET  /twins               — peers grouped by rappid
    GET  /eggs                — local egg backups + manifest peeks
    GET  /eggs/manifest?path= — peek a single egg's manifest + tree
    GET  /export-egg?path=    — stream an egg as attachment
    POST /import-egg          — receive a base64'd egg blob and save it
                                (organ contract takes a body dict, so
                                 the upload is JSON-wrapped, not multipart;
                                 the rapp_ui handles the b64 encode in JS)
    POST /lay-egg             — pack a twin's repo into an egg
    POST /summon              — materialize an egg into ~/.rapp/twins/...
    POST /hatch               — kernel-update via lay → swap → summon
    POST /start  POST /stop   — process control for twin brainstems
    POST /reveal              — open a workspace dir in the OS file mgr
    GET  /discover            — pointer to the upstream rapp_store API URL

Sibling modules accessed (all kernel-shipped under utils/):
    bond, peer_registry, egg
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import importlib
import io
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

# Module-level organ contract — kernel discovery key
name = "rapp_zoo"


# Two dirname() walks: this file → organs/ → utils/
_UTILS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _UTILS_DIR not in sys.path:
    sys.path.insert(0, _UTILS_DIR)


def _import_sibling(modname: str):
    """Lazy-import a sibling utils module. Returns None on failure."""
    try:
        return importlib.import_module(modname)
    except Exception:
        return None


# Lazy-resolved sibling references — bound on first use so this organ
# loads cleanly even if a sibling is temporarily unavailable.
_bond = None
_peer_registry = None


def _bond_mod():
    global _bond
    if _bond is None:
        _bond = _import_sibling("bond")
    return _bond


def _peers_mod():
    global _peer_registry
    if _peer_registry is None:
        _peer_registry = _import_sibling("peer_registry")
    return _peer_registry


# ── Local file conventions ──────────────────────────────────────────────
# Same shape as the original Flask zoo expected: ~/.rapp/{eggs,twins,pids}/.
# Honors RAPP_HOME for tests.

def _rapp_home() -> str:
    return os.environ.get("RAPP_HOME") or os.path.join(os.path.expanduser("~"), ".rapp")


def _eggs_dir() -> str:
    return os.path.join(_rapp_home(), "eggs")


def _twins_dir() -> str:
    return os.path.join(_rapp_home(), "twins")


def _pids_dir() -> str:
    return os.path.join(_rapp_home(), "pids")


def _pid_file(rid: str) -> str:
    return os.path.join(_pids_dir(), f"{rid}.pid")


def _read_pid(rid: str):
    p = _pid_file(rid)
    if not os.path.exists(p):
        return None
    try:
        return int(pathlib.Path(p).read_text().strip())
    except (ValueError, OSError):
        return None


def _write_pid(rid: str, pid: int):
    os.makedirs(_pids_dir(), exist_ok=True)
    pathlib.Path(_pid_file(rid)).write_text(str(pid))


def _clear_pid(rid: str):
    p = _pid_file(rid)
    if os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _probe_health(port: int, timeout: float = 0.6) -> dict:
    if not port:
        return {"live": False}
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health",
            headers={"User-Agent": "rapp-zoo-organ"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            try:
                h = json.loads(body)
                return {"live": True, "version": h.get("version")}
            except Exception:
                return {"live": r.status == 200}
    except (urllib.error.URLError, OSError, TimeoutError):
        return {"live": False}


# ── Endpoint handlers ───────────────────────────────────────────────────
# Each returns (dict, status_code). The top-level handle() routes to one
# of these based on (method, path).

def _h_health(method, path, body):
    pr = _peers_mod()
    peers = (pr.load() if pr else {"peers": []})["peers"] if pr else []
    live_count = sum(1 for p in peers if _probe_health(p.get("port") or 0)["live"])
    return {
        "name": "rapp-zoo",
        "status": "ok",
        "rapp_home": _rapp_home(),
        "peer_count": len(peers),
        "live_count": live_count,
        "schema": "rapp-zoo-health/1.0",
        "hosted": "in-brainstem-organ",
    }, 200


def _h_twins(method, path, body):
    pr = _peers_mod()
    if not pr:
        return {"twins": [], "error": "peer_registry unavailable"}, 200
    grouped = pr.group_by_twin()
    twins = []
    for rid, peers in sorted(grouped.items()):
        display_name = next((p.get("twin_name") for p in peers if p.get("twin_name")), rid[:8])
        parent_repo = next((p.get("parent_repo") for p in peers if p.get("parent_repo")), None)
        incarnations = []
        for p in peers:
            port = p.get("port") or 0
            probe = _probe_health(port) if port else {"live": False}
            pid = _read_pid(rid)
            incarnations.append({
                "id": p.get("id"),
                "brainstem_dir": p.get("brainstem_dir"),
                "port": port,
                "is_global": bool(p.get("is_global")),
                "is_twin_only": bool(p.get("is_twin_only")),
                "project_name": p.get("project_name"),
                "version": p.get("version"),
                "summoned_from": p.get("summoned_from"),
                "live": probe["live"],
                "pid": pid if pid and _pid_alive(pid) else None,
            })
        twins.append({
            "rappid_uuid": rid,
            "name": display_name,
            "parent_repo": parent_repo,
            "incarnation_count": len(peers),
            "incarnations": incarnations,
        })
    return {"schema": "rapp-zoo-twins/1.0", "twins": twins}, 200


def _h_eggs(method, path, body):
    bond = _bond_mod()
    root = _eggs_dir()
    out = []
    if os.path.isdir(root):
        for rid in sorted(os.listdir(root)):
            rd = os.path.join(root, rid)
            if not os.path.isdir(rd):
                continue
            for fn in sorted(os.listdir(rd), reverse=True):
                if not fn.endswith(".egg"):
                    continue
                full = os.path.join(rd, fn)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                schema = egg_type = kernel_version = None
                if bond:
                    try:
                        with open(full, "rb") as f:
                            blob = f.read()
                        if blob[:4] == b"PK\x03\x04":
                            m = bond.inspect_egg(blob)
                            schema = m.get("schema")
                            egg_type = m.get("type")
                            kernel_version = m.get("kernel_version")
                    except Exception:
                        pass
                out.append({
                    "rappid_uuid": rid,
                    "filename": fn,
                    "path": full,
                    "size_bytes": st.st_size,
                    "schema": schema,
                    "type": egg_type,
                    "kernel_version": kernel_version,
                    "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
                })
    return {"schema": "rapp-zoo-eggs/1.0", "eggs_dir": root, "eggs": out}, 200


def _h_eggs_manifest(method, path, body):
    bond = _bond_mod()
    p = (body or {}).get("path") or ""
    if not p or not os.path.isfile(p):
        return {"error": "path must point at an existing file"}, 400
    if not bond:
        return {"error": "bond utility unavailable"}, 500
    try:
        with open(p, "rb") as f:
            blob = f.read()
        manifest = bond.inspect_egg(blob)
    except Exception as e:
        return {"error": str(e)}, 400
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = sorted(z.namelist())
    except Exception:
        names = []
    return {"ok": True, "manifest": manifest, "file_tree": names,
            "size_bytes": len(blob)}, 200


def _h_export_egg(method, path, body):
    """Returns the egg as base64 in a JSON envelope so it can ride the
    organ's dict-only response shape. The UI decodes and triggers a
    browser download. Path-traversal guarded to ~/.rapp/eggs/."""
    p = (body or {}).get("path") or ""
    if not p:
        return {"error": "path required"}, 400
    p = os.path.abspath(p)
    eggs_root = os.path.abspath(_eggs_dir())
    if not p.startswith(eggs_root + os.sep):
        return {"error": "path must be inside eggs dir"}, 403
    if not os.path.isfile(p):
        return {"error": "not found"}, 404
    with open(p, "rb") as f:
        blob = f.read()
    return {
        "ok": True,
        "filename": os.path.basename(p),
        "size_bytes": len(blob),
        "egg_base64": base64.b64encode(blob).decode("ascii"),
    }, 200


def _h_import_egg(method, path, body):
    """Save a base64'd egg blob into ~/.rapp/eggs/imported/<sha8>-<name>.egg.
    The UI base64-encodes the file before POST (organ contract is JSON-only).
    """
    bond = _bond_mod()
    b64 = (body or {}).get("egg_base64") or ""
    filename = (body or {}).get("filename") or "upload.egg"
    if not b64:
        return {"error": "egg_base64 required"}, 400
    try:
        blob = base64.b64decode(b64)
    except (binascii.Error, ValueError) as e:
        return {"error": f"bad base64: {e}"}, 400
    if blob[:4] != b"PK\x03\x04":
        return {"error": "not a valid egg (no zip header)"}, 400
    if not bond:
        return {"error": "bond utility unavailable"}, 500
    try:
        manifest = bond.inspect_egg(blob)
    except Exception as e:
        return {"error": f"egg has no readable manifest: {e}"}, 400
    sha8 = hashlib.sha256(blob).hexdigest()[:8]
    safe_name = re.sub(r"[^\w.-]", "_", filename)
    if not safe_name.endswith(".egg"):
        safe_name += ".egg"
    out_dir = os.path.join(_eggs_dir(), "imported")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{sha8}-{safe_name}")
    with open(out_path, "wb") as f:
        f.write(blob)
    return {"ok": True, "egg_path": out_path,
            "size_bytes": len(blob), "manifest": manifest}, 200


def _h_lay_egg(method, path, body):
    """Pack an organism's repo into an egg. Dispatches on layout:
       - rappid.json above src/rapp_brainstem/ → bond.pack_organism (2.2-organism)
       - rappid.json + brainstem.py at root  → bond.pack_rapplication via egg.pack_twin_from_repo
    """
    bond = _bond_mod()
    repo_path = (body or {}).get("repo_path") or ""
    if not repo_path or not os.path.isdir(repo_path):
        return {"error": "repo_path missing or not a directory"}, 400
    rappid_at_root = os.path.exists(os.path.join(repo_path, "rappid.json"))
    kernel_at_root = os.path.exists(os.path.join(repo_path, "brainstem.py"))
    instance_src = os.path.join(repo_path, "src", "rapp_brainstem")
    try:
        if rappid_at_root and not kernel_at_root and os.path.isdir(instance_src):
            kver = "?"
            kver_file = os.path.join(instance_src, "VERSION")
            if os.path.exists(kver_file):
                with open(kver_file) as _vf:
                    kver = _vf.read().strip()
            if not bond:
                return {"error": "bond utility unavailable"}, 500
            blob = bond.pack_organism(repo_path, instance_src, kernel_version=kver)
        else:
            egg = _import_sibling("egg")
            if not egg:
                return {"error": "egg utility unavailable"}, 500
            blob = egg.pack_twin_from_repo(repo_path)
    except Exception as e:
        return {"error": f"pack failed: {e}"}, 500
    try:
        with open(os.path.join(repo_path, "rappid.json")) as f:
            rj = json.load(f)
        rid = rj["rappid"]
    except Exception as e:
        return {"error": f"could not read rappid.json: {e}"}, 500
    slug = rid.rsplit(":", 1)[-1] if ":" in rid else rid
    out_dir = os.path.join(_eggs_dir(), slug)
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    out_path = os.path.join(out_dir, f"{ts}.egg")
    with open(out_path, "wb") as f:
        f.write(blob)
    return {"ok": True, "egg_path": out_path,
            "rappid_uuid": rid, "size_bytes": len(blob)}, 200


def _h_summon(method, path, body):
    """Materialize an egg. Schema dispatch:
       - 2.2-organism      → bond.unpack_organism into <host>/<rid-hex>/src/...
       - 2.0/2.1           → egg.summon_twin_egg
       - 2.2-rapplication  → bond.unpack_rapplication into <host>/<rid-hex>/src/...
    """
    bond = _bond_mod()
    egg = _import_sibling("egg")
    p = (body or {}).get("egg_path") or ""
    if not p or not os.path.isfile(p):
        return {"error": "egg_path missing or not a file"}, 400
    host_root = (body or {}).get("host_root") or _twins_dir()
    keep = bool((body or {}).get("keep_existing_kernel"))
    os.makedirs(host_root, exist_ok=True)
    try:
        with open(p, "rb") as f:
            blob = f.read()
    except Exception as e:
        return {"error": f"egg read failed: {e}"}, 500
    if not bond:
        return {"error": "bond utility unavailable"}, 500
    try:
        manifest = bond.inspect_egg(blob)
    except Exception as e:
        return {"error": f"egg has no manifest: {e}"}, 400
    schema = manifest.get("schema", "")
    try:
        if schema == bond.SCHEMA:  # 2.2-organism
            ws = _summon_organism(blob, manifest, host_root, bond)
        elif schema == bond.SCHEMA_RAPP:  # 2.2-rapplication
            rappid = manifest.get("rappid", "")
            slug = rappid.rsplit(":", 1)[-1] if ":" in rappid else (manifest.get("rapp_id") or "rapp")
            workspace = os.path.join(host_root, slug)
            src = os.path.join(workspace, "src", "rapp_brainstem")
            os.makedirs(src, exist_ok=True)
            result = bond.unpack_rapplication(blob, src)
            if not result.get("ok"):
                return {"error": f"unpack errors: {result.get('errors')}"}, 500
            ws = workspace
        else:
            if not egg:
                return {"error": "legacy egg requires utils/egg.py"}, 500
            ws = egg.summon_twin_egg(blob, host_root, keep_existing_kernel=keep)
    except Exception as e:
        return {"error": f"summon failed: {e}"}, 500
    # Best-effort peer registry update
    pr = _peers_mod()
    if pr:
        try:
            rappid_path = os.path.join(ws, "rappid.json")
            if os.path.exists(rappid_path):
                with open(rappid_path) as f:
                    rj = json.load(f)
                claimed = pr.claimed_ports() if hasattr(pr, "claimed_ports") else set()
                port = next((q for q in range(7081, 7200) if q not in claimed), 0)
                pr.upsert(ws, port,
                          version=(rj.get("brainstem") or {}).get("version") or rj.get("kind"),
                          rappid_uuid=rj["rappid"],
                          twin_name=rj.get("name"),
                          parent_repo=rj.get("parent_repo"),
                          summoned_from=p)
        except Exception:
            pass
    return {"ok": True, "workspace": ws, "schema": schema or "unknown"}, 200


def _summon_organism(blob, manifest, host_root, bond):
    rappid = manifest.get("rappid") or "unknown"
    slug = rappid.rsplit(":", 1)[-1] if ":" in rappid else rappid
    if not slug or not re.match(r"^[\w-]+$", slug):
        slug = hashlib.sha256((rappid or "unknown").encode()).hexdigest()[:16]
    workspace = os.path.join(host_root, slug)
    src = os.path.join(workspace, "src", "rapp_brainstem")
    os.makedirs(src, exist_ok=True)
    result = bond.unpack_organism(blob, workspace, src, overwrite_rappid=True)
    if not result.get("ok"):
        raise RuntimeError(f"unpack errors: {result.get('errors')}")
    return workspace


def _h_hatch(method, path, body):
    """Egg-roundtrip kernel update for a twin. Lay → swap kernel → re-summon
    with --keep-existing-kernel."""
    bond = _bond_mod()
    egg = _import_sibling("egg")
    pr = _peers_mod()
    rid = (body or {}).get("rappid_uuid")
    new_kernel = (body or {}).get("new_kernel")
    if not rid or not new_kernel:
        return {"error": "rappid_uuid and new_kernel required"}, 400
    # Resolve new_kernel to a brainstem.py file
    if os.path.isfile(new_kernel) and new_kernel.endswith("brainstem.py"):
        kernel_file = new_kernel
    elif os.path.isdir(new_kernel) and os.path.isfile(os.path.join(new_kernel, "brainstem.py")):
        kernel_file = os.path.join(new_kernel, "brainstem.py")
    elif os.path.isdir(new_kernel) and os.path.isfile(os.path.join(new_kernel, "rapp_brainstem", "brainstem.py")):
        kernel_file = os.path.join(new_kernel, "rapp_brainstem", "brainstem.py")
    else:
        return {"error": f"cannot locate brainstem.py from {new_kernel}"}, 400
    if not pr:
        return {"error": "peer_registry unavailable"}, 500
    grouped = pr.group_by_twin()
    peers = grouped.get(rid) or []
    if not peers:
        return {"error": f"no peer for rappid_uuid {rid}"}, 404
    peer = next((p for p in peers if p.get("is_twin_only")), peers[0])
    ws = peer.get("brainstem_dir")
    if not ws or not os.path.isdir(ws):
        return {"error": f"workspace not found: {ws}"}, 404
    if not egg:
        return {"error": "egg utility unavailable"}, 500
    try:
        blob = egg.pack_twin_from_repo(ws)
        ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
        out_dir = os.path.join(_eggs_dir(), rid)
        os.makedirs(out_dir, exist_ok=True)
        ep = os.path.join(out_dir, f"{ts}.egg")
        with open(ep, "wb") as f:
            f.write(blob)
    except Exception as e:
        return {"error": f"lay-egg step failed: {e}"}, 500
    try:
        shutil.copy2(kernel_file, os.path.join(ws, "brainstem.py"))
    except Exception as e:
        return {"error": f"kernel swap failed: {e}"}, 500
    try:
        ws_after = egg.summon_twin_egg(blob, os.path.dirname(ws),
                                       keep_existing_kernel=True)
    except Exception as e:
        return {"error": f"summon-back failed: {e}"}, 500
    return {"ok": True, "egg_path": ep, "workspace": ws_after,
            "kernel_swapped_from": kernel_file}, 200


def _h_start(method, path, body):
    pr = _peers_mod()
    rid = (body or {}).get("rappid_uuid")
    if not rid:
        return {"error": "rappid_uuid required"}, 400
    pid = _read_pid(rid)
    if pid and _pid_alive(pid):
        return {"ok": True, "already_running": True, "pid": pid}, 200
    if not pr:
        return {"error": "peer_registry unavailable"}, 500
    grouped = pr.group_by_twin()
    peers = grouped.get(rid) or []
    if not peers:
        return {"error": f"no peer for {rid}"}, 404
    peer = next((p for p in peers if p.get("is_twin_only")), peers[0])
    ws = peer.get("brainstem_dir")
    if not ws or not os.path.isdir(ws):
        return {"error": f"workspace not found: {ws}"}, 404
    start_script = os.path.join(ws, "installer", "start.sh")
    if not os.path.isfile(start_script):
        return {"error": f"no start.sh at {start_script}"}, 404
    try:
        proc = subprocess.Popen(["bash", start_script], cwd=ws,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True)
        _write_pid(rid, proc.pid)
    except Exception as e:
        return {"error": f"start failed: {e}"}, 500
    return {"ok": True, "pid": proc.pid, "workspace": ws}, 200


def _h_stop(method, path, body):
    rid = (body or {}).get("rappid_uuid")
    if not rid:
        return {"error": "rappid_uuid required"}, 400
    pid = _read_pid(rid)
    if not pid or not _pid_alive(pid):
        _clear_pid(rid)
        return {"ok": True, "was_running": False}, 200
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
    for _ in range(20):
        if not _pid_alive(pid):
            break
        time.sleep(0.1)
    _clear_pid(rid)
    return {"ok": True, "was_running": True, "pid": pid}, 200


def _h_reveal(method, path, body):
    p = (body or {}).get("path") or ""
    if not p:
        return {"error": "path required"}, 400
    p = os.path.abspath(p)
    rapp_root = os.path.abspath(_rapp_home())
    if not p.startswith(rapp_root + os.sep) and p != rapp_root:
        return {"error": "path must be inside ~/.rapp/"}, 403
    if not os.path.exists(p):
        return {"error": "not found"}, 404
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", p])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception as e:
        return {"error": f"reveal failed: {e}"}, 500
    return {"ok": True, "revealed": p}, 200


def _h_discover(method, path, body):
    upstream = os.environ.get(
        "RAPPSTORE_API_URL",
        "https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/index.json",
    )
    return {
        "schema": "rapp-zoo-discover/1.0",
        "upstream_url": upstream,
        "note": "Static catalog hosted at raw.githubusercontent.com — fetch upstream_url for the catalog.",
    }, 200


# ── Router ──────────────────────────────────────────────────────────────
# Single dispatch table — keeps the organ contract trivial. Path strings
# are everything AFTER /api/rapp_zoo/. method+path → (handler, GET/POST).

_ROUTES = {
    ("GET",  "health"):         _h_health,
    ("GET",  "twins"):          _h_twins,
    ("GET",  "eggs"):           _h_eggs,
    ("GET",  "discover"):       _h_discover,
    ("POST", "eggs/manifest"):  _h_eggs_manifest,
    ("POST", "export-egg"):     _h_export_egg,
    ("POST", "import-egg"):     _h_import_egg,
    ("POST", "lay-egg"):        _h_lay_egg,
    ("POST", "summon"):         _h_summon,
    ("POST", "hatch"):          _h_hatch,
    ("POST", "start"):          _h_start,
    ("POST", "stop"):           _h_stop,
    ("POST", "reveal"):         _h_reveal,
}


def handle(method: str, path: str, body):
    """Organ entry point. The brainstem dispatches /api/rapp_zoo/<path>
    here. Returns (response_dict, status_code).

    `body` is the parsed JSON body (or None for GET). Query-string-style
    GET endpoints accept their args in the body too — the rapp UI
    JSON-encodes them so the contract stays uniform.
    """
    method = (method or "GET").upper()
    p = (path or "").strip("/").lower()
    # Empty path → health check (so /api/rapp_zoo/ pings cleanly)
    if not p:
        return _h_health(method, p, body)
    fn = _ROUTES.get((method, p))
    if not fn:
        return {
            "error": f"unknown route: {method} /api/{name}/{p}",
            "known": [f"{m} {p}" for m, p in _ROUTES],
        }, 404
    return fn(method, p, body or {})
