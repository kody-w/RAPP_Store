"""Native OpenSEO project management, without paid or invented SEO metrics."""
from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import os
import re
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from local_dock import LocalDockError

APP = "open-seo"
TITLE = "OpenSEO — local SEO projects (paid metrics disabled)"
COMPOSE = "compose.yaml"
NEEDS = ()
HEAVY = False
START_TIMEOUT = 240
READY_TIMEOUT = 120
_TOKEN = "open-seo-ingress-token"
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_PAID_WARNING = "Rankings, backlinks, search traffic and keyword-volume reports are off: DataForSEO is disabled."


def urls(ctx) -> dict:
    return {"mcp": ctx.host_url("/mcp"), "health": ctx.host_url("/api/health")}


def prepare(ctx):
    ctx.write_env_file(
        "open-seo.env", {"RAPP_DOCK_OPENSEO_TOKEN": ctx.secret(_TOKEN, nbytes=32)}
    )


def compose_env(ctx) -> dict:
    return {}


def normalize_domain(url: str) -> str:
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise LocalDockError("invalid-input", "A domain or HTTP(S) website URL is required.")
    if "\\" in url or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise LocalDockError("invalid-input", "The website URL contains invalid characters.")
    try:
        parsed = urlsplit(url if "://" in url else "https://" + url)
        if parsed.scheme.lower() not in ("http", "https") or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        if "%" in parsed.netloc or "@" in parsed.netloc:
            raise ValueError()
        if parsed.port not in (None, 80, 443):
            raise ValueError()
        domain = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if (
            not domain or len(domain) > 253 or "." not in domain
            or domain.endswith((".localhost", ".local", ".internal", ".lan", ".home"))
            or not all(_LABEL.fullmatch(label) for label in domain.split("."))
            or domain.split(".")[-1].isdigit()
        ):
            raise ValueError()
        try:
            ipaddress.ip_address(domain)
        except ValueError:
            pass
        else:
            raise ValueError()
    except (UnicodeError, ValueError):
        raise LocalDockError("invalid-input", "Use a credential-free public domain or HTTP(S) website URL.") from None
    return domain


def _decode(response, identifier):
    try:
        text = response.text.strip()
        if text.startswith(("event:", "data:", ":")):
            messages = [
                json.loads(line[5:].strip()) for line in text.splitlines()
                if line.startswith("data:") and line[5:].strip() != "[DONE]"
            ]
            value = next(item for item in messages if isinstance(item, dict) and item.get("id") == identifier)
        else:
            value = json.loads(text)
        if not isinstance(value, dict) or value.get("id") != identifier:
            raise ValueError()
    except (ValueError, TypeError, StopIteration):
        raise LocalDockError("output-invalid", "OpenSEO returned an invalid MCP response.") from None
    if value.get("error"):
        raise LocalDockError("native-job-failed", "OpenSEO refused the MCP request.")
    result = value.get("result")
    if not isinstance(result, dict):
        raise LocalDockError("output-invalid", "OpenSEO returned an invalid MCP result.")
    return result


class _MCP:
    def __init__(self, ctx):
        self.ctx = ctx
        self.number = 0
        self.headers = {
            "Authorization": "Bearer " + ctx.secret(_TOKEN, nbytes=32),
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        }

    def rpc(self, method, params, *, notification=False):
        self.ctx.check_cancelled()
        self.number += 1
        request = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            request["id"] = self.number
        try:
            response = self.ctx.http(
                "POST", self.ctx.host_url("/mcp"), json_body=request, headers=self.headers,
                timeout=30, max_bytes=2 * 1024 * 1024,
            )
        except LocalDockError as error:
            if error.code == "cancelled":
                raise
            raise LocalDockError("app-not-ready", "The guarded OpenSEO MCP endpoint is unavailable.") from None
        if response.status not in (200, 201, 202, 204):
            raise LocalDockError("app-not-ready", "The guarded OpenSEO MCP endpoint is unavailable.")
        headers = {name.lower(): value for name, value in response.headers.items()}
        if headers.get("mcp-session-id"):
            self.headers["Mcp-Session-Id"] = headers["mcp-session-id"]
        return {} if notification else _decode(response, self.number)

    def __enter__(self):
        self.rpc("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "rapp-dock-open-seo", "version": "1"},
        })
        self.rpc("notifications/initialized", {}, notification=True)
        return self

    def __exit__(self, *_args):
        if "Mcp-Session-Id" in self.headers:
            try:
                self.ctx.http("DELETE", self.ctx.host_url("/mcp"), headers=self.headers,
                              timeout=5, max_bytes=16384)
            except Exception:
                pass

    def call(self, name, arguments):
        value = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if value.get("isError") or value.get("is_error"):
            raise LocalDockError("native-job-failed", "The native OpenSEO project operation failed.")
        payload = value.get("structuredContent", value.get("structured_content"))
        if not isinstance(payload, dict):
            try:
                payload = json.loads(value["content"][0]["text"])
            except (KeyError, IndexError, TypeError, ValueError):
                raise LocalDockError("output-invalid", "OpenSEO returned no structured project data.") from None
        if not isinstance(payload, dict):
            raise LocalDockError("output-invalid", "OpenSEO returned invalid project data.")
        return payload


def _health(ctx):
    response = ctx.http("GET", ctx.host_url("/api/health"), timeout=10, max_bytes=65536)
    if response.status != 200:
        raise LocalDockError("app-not-ready", "OpenSEO health is unavailable.")
    try:
        health = response.json()
        checks = health["checks"]
        ok = health["status"] == "ok" and health["authMode"] == "local_noauth"
        ok = ok and checks["database"]["status"] == "ok"
        disabled = checks["dataforseo"]["status"] == "warn" and "Not set" in checks["dataforseo"]["detail"]
        disabled = disabled and "disabled" in checks["ai"]["detail"].lower()
    except (KeyError, TypeError, ValueError):
        ok = disabled = False
    if not ok or not disabled:
        raise LocalDockError("app-not-ready", "OpenSEO must have a ready local database and disabled paid providers.")
    return {"ready": True, "detail": "Native database ready; DataForSEO and OpenRouter disabled."}


def ready(ctx) -> dict:
    try:
        return _health(ctx)
    except LocalDockError:
        return {"ready": False, "detail": "OpenSEO database or disabled-provider policy is not ready."}


def setup(ctx) -> dict:
    _health(ctx)
    with _MCP(ctx) as client:
        _projects(client)
    return {"ready": True, "auth_mode": "local_noauth-behind-authenticated-ingress",
            "paid_metrics_status": "disabled"}


def _projects(client):
    rows = client.call("list_projects", {}).get("projects")
    if not isinstance(rows, list) or len(rows) > 10000 or not all(isinstance(row, dict) for row in rows):
        raise LocalDockError("output-invalid", "OpenSEO returned an invalid project list.")
    return rows


def _matching(rows, domain):
    matches = []
    for row in rows:
        try:
            if normalize_domain(row.get("domain")) == domain:
                matches.append(row)
        except LocalDockError:
            continue
    return sorted(matches, key=lambda row: str(row.get("id", "")))


def _project(row, domain):
    if not isinstance(row, dict):
        raise LocalDockError("output-invalid", "OpenSEO did not return a project.")
    identifier, name = row.get("id"), row.get("name")
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", identifier):
        raise LocalDockError("output-invalid", "OpenSEO returned an invalid native project ID.")
    if not isinstance(name, str) or not 1 <= len(name) <= 200 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise LocalDockError("output-invalid", "OpenSEO returned an invalid project title.")
    try:
        observed_domain = normalize_domain(row.get("domain"))
    except LocalDockError:
        raise LocalDockError("output-invalid", "OpenSEO returned an invalid project domain.") from None
    if observed_domain != domain:
        raise LocalDockError("output-invalid", "The native project's domain did not match the requested domain.")
    return {"id": identifier, "name": name, "domain": domain}


@contextmanager
def _project_lock(ctx):
    path = ctx.state_dir / "project-create.lock"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise LocalDockError("app-not-ready", "The OpenSEO project lock could not be opened safely.") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise LocalDockError("app-not-ready", "The OpenSEO project lock is not a private regular file.")
        deadline = time.monotonic() + 60
        while True:
            ctx.check_cancelled()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LocalDockError("app-not-ready", "Another OpenSEO project operation is still active.") from None
                time.sleep(0.1)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def project_create(ctx, url: str, title: str | None = None) -> dict:
    domain = normalize_domain(url)
    if title is None:
        title = domain
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200 or any(ord(char) < 32 or ord(char) == 127 for char in title):
        raise LocalDockError("invalid-input", "The optional project title must contain 1 to 200 plain-text characters.")
    title = title.strip()
    ctx.phase("reconciling_project")
    ctx.record_native("domain", domain)
    _health(ctx)
    with _project_lock(ctx), _MCP(ctx) as client:
        matches = _matching(_projects(client), domain)
        created = False
        reconciled = False
        if matches:
            selected = _project(matches[0], domain)
        else:
            ctx.phase("creating_project")
            ctx.record_native("submission", "create_project")
            try:
                selected = _project(client.call("create_project", {"name": title, "domain": domain}).get("project"), domain)
                created = True
            except LocalDockError:
                # Never repeat an ambiguous create: reconcile its natural key first.
                matches = _matching(_projects(client), domain)
                if not matches:
                    raise
                selected = _project(matches[0], domain)
                reconciled = True
        ctx.record_native("project_id", selected["id"])
        ctx.phase("reading_back_project")
        readback = next((row for row in _projects(client) if row.get("id") == selected["id"]), None)
        verified = _project(readback, domain)
        if verified != selected:
            raise LocalDockError("output-invalid", "The native project changed before verification.")
    ctx.check_cancelled()
    document = {
        "schema": "rapp-dock-open-seo-project/1", "project": verified,
        "created": created, "reconciled_after_ambiguous_create": reconciled,
        "read_back_verified": True, "paid_metrics_status": "disabled",
        "disabled_providers": ["DataForSEO", "OpenRouter"], "metrics": None,
        "warning": _PAID_WARNING,
    }
    payload = (json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    ctx.phase("saving_project")
    artifact = ctx.save_output("project.json", payload, "application/json")
    saved = Path(artifact["path"]).read_bytes()
    if (
        saved != payload or artifact.get("bytes") != len(payload)
        or artifact.get("sha256") != hashlib.sha256(payload).hexdigest()
        or json.loads(saved)["project"] != verified
    ):
        raise LocalDockError("output-invalid", "The saved native project record failed verification.")
    ctx.mark_verified(artifact)
    return {
        "message": ("Created" if created else "Reused") + " the local OpenSEO project; native read-back verified. "
                   + _PAID_WARNING,
        "result": {
            "native_project_id": verified["id"], "domain": domain, "title": verified["name"],
            "created": created, "read_back_verified": True, "paid_metrics_status": "disabled",
            "metrics": None, "warning": _PAID_WARNING,
        },
        "artifacts": [artifact],
        "provider": {"runtime": "none", "model": None, "calls": 0, "request_ids": []},
        "native": {"project_id": verified["id"], "domain": domain},
    }


JOBS = {
    "project_create": {
        "description": "Create or reuse a native SEO project for a website; paid reports stay disabled.",
        "parameters": {
            "url": {"type": "string", "minLength": 1, "maxLength": 2048},
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
        },
        "required": ["url"], "run": project_create, "heavy": False,
        "aliases": ["website", "seo", "domain", "project", "marketing", "search optimization", "open seo"],
    },
}
