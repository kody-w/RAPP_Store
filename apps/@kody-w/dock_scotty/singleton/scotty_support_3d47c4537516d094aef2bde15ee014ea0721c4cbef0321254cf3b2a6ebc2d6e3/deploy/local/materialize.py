#!/usr/bin/env python3
"""Explicit public-input materialization; job-time image resolution is read-only.

Inspect:     python deploy/local/materialize.py --app all
Materialize: python deploy/local/materialize.py --app all --materialize --cache ./materialized
Rebuild:     python deploy/local/materialize.py --component intelligence --build --cache ./materialized

Give the controller the same cache as its private ``home/materialize`` directory.
Existing image IDs are observations, not downloadable artifacts. Rebuilds receive
content-named tags and a local receipt with the actual ID; bit reproducibility
and fresh-machine application acceptance are deliberately not claimed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = "deploy/local/components.lock.json"
RECEIPT = "materialized-images.json"
MAX_INPUT = 2 * 1024 * 1024 * 1024
MAX_METADATA = 4 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
REGISTRY_REF = re.compile(r"[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}")
PUBLIC_HOSTS = frozenset({
    "github.com", "codeload.github.com", "objects.githubusercontent.com",
    "release-assets.githubusercontent.com", "raw.githubusercontent.com",
    "files.pythonhosted.org", "registry.npmjs.org", "deb.debian.org",
    "huggingface.co", "cdn-lfs.huggingface.co", "cdn-lfs-us-1.huggingface.co",
    "cas-bridge.xethub.hf.co", "download-r2.pytorch.org",
})


class MaterializeRefused(ValueError):
    def __init__(self, code: str, component: str = "", detail: str = ""):
        self.code, self.component, self.detail = code, component, detail
        super().__init__(code + (": " + component if component else ""))


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _json(raw: bytes) -> Any:
    def unique(pairs):
        answer = {}
        for key, value in pairs:
            if key in answer:
                raise MaterializeRefused("duplicate-json-member")
            answer[key] = value
        return answer
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise MaterializeRefused("invalid-json") from error


def _relative(name: str) -> str:
    if (not isinstance(name, str) or not name or len(name) > 512
            or str(PurePosixPath(name)) != name or name.startswith("/")
            or "\\" in name or any(part.startswith(".") or part.casefold() in {"secrets", "credentials"}
                                   for part in name.split("/"))
            or name.lower().endswith((".key", ".pem", "copilot.env", "credentials.json"))
            or any(ord(char) < 32 for char in name)):
        raise MaterializeRefused("unsafe-input-path")
    return name


def _safe_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        if item.is_symlink():
            raise MaterializeRefused("linked-input-path")
    return path


def _read(path: Path, bound: int = MAX_METADATA) -> bytes:
    path = _safe_path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise MaterializeRefused("public-input-file-unavailable") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > bound:
            raise MaterializeRefused("unsafe-input-file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(bound + 1)
        after = os.fstat(fd)
        if (len(data) > bound or (before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_ino, after.st_size, after.st_mtime_ns)):
            raise MaterializeRefused("input-changed")
        return data
    except OSError as error:
        raise MaterializeRefused("public-input-file-unavailable") from error
    finally:
        os.close(fd)


def _directory(path: Path) -> Path:
    path = _safe_path(path)
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)
    _safe_path(path)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise MaterializeRefused("cache-not-private")
    return path


def _commit_file(path: Path, data: bytes) -> None:
    _directory(path.parent)
    _safe_path(path)
    staging = path.with_name(path.name + ".partial-" + uuid.uuid4().hex)
    try:
        with staging.open("xb") as target:
            os.chmod(staging, 0o600)
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def _diagnostic(cache: Path, component: str, phase: str, result) -> None:
    parts = []
    for value in (result.stdout, result.stderr):
        parts.append(value.encode() if isinstance(value, str) else value or b"")
    data = (b"Public-input build diagnostic; no runtime credentials supplied.\n"
            + b"\n".join(parts))[-65536:]
    _commit_file(cache / "diagnostics" / (component + "-" + phase + "-" + uuid.uuid4().hex + ".log"), data)


def _public_url(url: str) -> str:
    if not isinstance(url, str):
        raise MaterializeRefused("non-public-input-url")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise MaterializeRefused("non-public-input-url") from error
    if (parsed.scheme != "https" or parsed.hostname not in PUBLIC_HOSTS
            or parsed.username or parsed.password or port not in {None, 443}
            or parsed.fragment or any(ord(char) < 32 for char in url)):
        raise MaterializeRefused("non-public-input-url")
    return url


def _registry_reference(reference: str) -> None:
    if not isinstance(reference, str) or not REGISTRY_REF.fullmatch(reference):
        raise MaterializeRefused("mutable-registry-reference")
    repository = reference.split("@", 1)[0]
    first = repository.split("/", 1)[0]
    if ("/" in repository and ("." in first or ":" in first or first == "localhost")
            and first not in {"ghcr.io", "docker.io", "registry-1.docker.io"}):
        raise MaterializeRefused("non-public-registry")


class _PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, url):
        _public_url(url)
        return super().redirect_request(request, fp, code, msg, headers, url)


def _check_artifact(item: dict) -> None:
    if (not isinstance(item, dict)
            or set(item) != {"url", "sha256", "bytes", "license"}
            or not isinstance(item["sha256"], str) or not SHA.fullmatch(item["sha256"])
            or type(item["bytes"]) is not int or not 1 <= item["bytes"] <= MAX_INPUT
            or not isinstance(item["license"], str) or not item["license"]):
        raise MaterializeRefused("invalid-public-artifact-lock")
    _public_url(item["url"])


def fetch_artifact(item: dict, cache: Path, *, opener=None) -> Path:
    """Anonymous TLS fetch with a bounded write, SHA-256 and exact-size checks."""
    _check_artifact(item)
    destination = _safe_path(cache / "inputs" / item["sha256"])
    if destination.exists():
        _verify_download(destination, item)
        return destination
    _directory(destination.parent)
    pending = destination.with_name(destination.name + ".partial-" + uuid.uuid4().hex)
    if opener is None:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _PublicRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
    request = urllib.request.Request(item["url"], headers={"User-Agent": "RAPP-Dock-materializer/1"})
    try:
        digest, total = hashlib.sha256(), 0
        with opener.open(request, timeout=60) as response, pending.open("xb") as target:
            os.chmod(pending, 0o600)
            _public_url(response.geturl())
            while block := response.read(min(1024 * 1024, item["bytes"] - total + 1)):
                total += len(block)
                if total > item["bytes"]:
                    raise MaterializeRefused("public-input-size-mismatch")
                digest.update(block)
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        if total != item["bytes"] or digest.hexdigest() != item["sha256"]:
            raise MaterializeRefused("public-input-digest-mismatch")
        if destination.exists():
            _verify_download(destination, item)
        else:
            os.link(pending, destination)
        return destination
    except (urllib.error.URLError, OSError) as error:
        raise MaterializeRefused("public-input-fetch-failed") from error
    finally:
        pending.unlink(missing_ok=True)


def _verify_download(path: Path, item: dict) -> None:
    _safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != item["bytes"]:
            raise MaterializeRefused("public-input-size-mismatch")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(fd)
        if (digest != item["sha256"] or (info.st_ino, info.st_size, info.st_mtime_ns)
                != (after.st_ino, after.st_size, after.st_mtime_ns)):
            raise MaterializeRefused("public-input-digest-mismatch")
    finally:
        os.close(fd)


def load_lock(root: Path = ROOT) -> dict:
    try:
        return _load_lock(root)
    except MaterializeRefused:
        raise
    except (OSError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as error:
        raise MaterializeRefused("invalid-components-lock") from error


def _load_lock(root: Path) -> dict:
    lock = _json(_read(root / LOCK_PATH))
    if (not isinstance(lock, dict)
            or set(lock) - {"schema", "profile", "artifacts", "components", "applications", "input_sets"}
            or not {"schema", "profile", "artifacts", "components", "applications"} <= set(lock)
            or lock["schema"] != "rapp-dock-components/1"
            or not isinstance(lock["components"], dict) or not 1 <= len(lock["components"]) <= 64
            or not isinstance(lock["artifacts"], dict) or len(lock["artifacts"]) > 64
            or not isinstance(lock["applications"], dict) or not isinstance(lock["profile"], dict)):
        raise MaterializeRefused("invalid-components-lock")
    for artifact in lock["artifacts"].values():
        _check_artifact(artifact)
    environments = set()
    for name, item in lock["components"].items():
        if (not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name)
                or not isinstance(item, dict)
                or set(item) != {"kind", "platform", "env", "reference", "recipe",
                                 "observed_image_ids", "source", "license", "blockers"}
                or item["kind"] not in {"registry", "dockerfile", "openshorts-offline", "blocked-build"}
                or item["platform"] not in {"linux/amd64", "linux/arm64"}
                or not re.fullmatch(r"RAPP_DOCK_IMAGE_[A-Z0-9_]+", item["env"])
                or not isinstance(item["blockers"], list)
                or any(not isinstance(value, str) for value in item["blockers"])
                or not isinstance(item["observed_image_ids"], list)
                or any(not isinstance(value, str) or not IMAGE_ID.fullmatch(value)
                       for value in item["observed_image_ids"])):
            raise MaterializeRefused("invalid-component", name)
        if item["env"] in environments:
            raise MaterializeRefused("duplicate-component-environment", name)
        environments.add(item["env"])
        if item["kind"] == "registry":
            _registry_reference(item["reference"])
            if item["recipe"] is not None or item["observed_image_ids"]:
                raise MaterializeRefused("registry-has-build-recipe", name)
        elif item["reference"] is not None:
            raise MaterializeRefused("local-build-is-not-a-registry-artifact", name)
        if item["kind"] == "dockerfile":
            _recipe_files(item, root, lock)
        if item["kind"] == "openshorts-offline":
            _openshorts_inputs(item, root, lock)
        if item["kind"] == "blocked-build" and (not item["blockers"] or item["recipe"] is not None):
            raise MaterializeRefused("missing-public-build-blocker", name)
    for app, services in lock["applications"].items():
        if (not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", app) or not isinstance(services, dict)
                or not services or any(component not in lock["components"] for component in services.values())):
            raise MaterializeRefused("invalid-application-components")
    return lock


def _recipe_files(component: dict, root: Path, lock: dict) -> dict[str, bytes]:
    recipe = component["recipe"]
    if (not isinstance(recipe, dict) or set(recipe) != {"files", "bases", "artifacts"}
            or not isinstance(recipe["files"], list) or not 1 <= len(recipe["files"]) <= 64
            or not isinstance(recipe["bases"], list) or not recipe["bases"]
            or not isinstance(recipe["artifacts"], list)):
        raise MaterializeRefused("invalid-build-recipe")
    files = {}
    for item in recipe["files"]:
        if (not isinstance(item, dict) or set(item) != {"path", "target", "sha256", "bytes"}
                or not isinstance(item["sha256"], str) or not SHA.fullmatch(item["sha256"])
                or type(item["bytes"]) is not int):
            raise MaterializeRefused("invalid-build-input")
        path, target = _relative(item["path"]), _relative(item["target"])
        data = _read(root / path)
        if target in files or len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise MaterializeRefused("build-input-drift")
        files[target] = data
    if "Dockerfile" not in files:
        raise MaterializeRefused("missing-locked-dockerfile")
    for base in recipe["bases"]:
        _registry_reference(base)
    dockerfile = files["Dockerfile"].decode()
    bases = re.findall(r"(?im)^FROM\s+([^\s]+)", dockerfile)
    if bases != recipe["bases"] or re.search(r"(?im)^\s*ADD\s|^\s*#\s*syntax=", dockerfile):
        raise MaterializeRefused("unlocked-dockerfile-input")
    targets = set(files)
    for artifact in recipe["artifacts"]:
        if (not isinstance(artifact, dict) or set(artifact) != {"artifact", "member", "target"}
                or artifact["artifact"] not in lock["artifacts"]):
            raise MaterializeRefused("invalid-recipe-artifact")
        _relative(artifact["target"])
        if artifact["target"] in targets:
            raise MaterializeRefused("colliding-build-input")
        targets.add(artifact["target"])
        if artifact["member"] is not None:
            _relative(artifact["member"])
    return files


def _openshorts_dockerfile(role: str, files: dict[str, bytes]) -> bytes:
    if role == "backend":
        return files["qualification/Dockerfile.backend-offline"]
    if role == "frontend":
        return b"""FROM node@sha256:929b04d7c782f04f615cf785488fed452b6569f87c73ff666ad553a7554f0006 AS compile
WORKDIR /home/node/work
ENV NPM_CONFIG_USERCONFIG=/opt/qualification/npmrc NPM_CONFIG_GLOBALCONFIG=/dev/null \\
    NODE_OPTIONS=--max-old-space-size=1536 UV_THREADPOOL_SIZE=4 \\
    VITE_API_URL="" VITE_OPENPANEL_API_URL="" VITE_OPENPANEL_CLIENT_ID=""
COPY qualification/npmrc /opt/qualification/npmrc
COPY qualification/offline-npm-lock.mjs qualification/frontend-build.sh frontend-artifacts.json ./
COPY tarballs/ ./tarballs/
COPY source/dashboard/ ./dashboard/
RUN sh /home/node/work/frontend-build.sh
FROM nginx@sha256:7396be67b6f53012a5cf955fa9040619294c25ccacf11e22af5de1b572fc756e
LABEL org.opencontainers.image.source="https://github.com/mutonby/openshorts" \\
      org.opencontainers.image.revision="0db0a3a04ba06b3dc74a670f38e335910c294249" \\
      rapp.dock.component="openshorts-frontend"
COPY --from=compile /home/node/work/dashboard/dist/ /usr/share/nginx/html/
COPY qualification/private-nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""
    if role == "renderer":
        original = files["qualification/Dockerfile.renderer-offline"]
        replacements = (
            (b"COPY render-service/ /app/", b"COPY --from=compile /build/render-service/ /app/"),
            (b"COPY remotion/ /app/remotion/", b"COPY --from=compile /build/remotion/ /app/remotion/"),
        )
        for before, after in replacements:
            if original.count(before) != 1:
                raise MaterializeRefused("renderer-build-template-drift")
            original = original.replace(before, after)
        return b"""FROM node@sha256:fc3faf127a182135fd956e68d570b1932a758f8008866d8dd6e131cf89de9605 AS compile
WORKDIR /build
ENV NPM_CONFIG_USERCONFIG=/opt/qualification/npmrc NPM_CONFIG_GLOBALCONFIG=/dev/null \\
    NODE_OPTIONS=--max-old-space-size=1536 UV_THREADPOOL_SIZE=4
COPY qualification/npmrc /opt/qualification/npmrc
COPY qualification/offline-npm-lock.mjs ./
COPY tarballs/ ./tarballs/
COPY source/render-service/ ./render-service/
COPY source/remotion/ ./remotion/
RUN for project in render-service remotion; do \\
      cd /build/$project && \\
      node /build/offline-npm-lock.mjs package-lock.json artifact-manifest.json /build/tarballs && \\
      npm ci --offline --ignore-scripts || exit 1; \\
    done && cd /build/render-service && npm run build
""" + original
    raise MaterializeRefused("unknown-openshorts-role")


def _openshorts_inputs(component: dict, root: Path, lock: dict) -> tuple[dict, dict[str, bytes], bytes]:
    recipe = component["recipe"]
    if (not isinstance(recipe, dict)
            or set(recipe) != {"role", "input_set", "input_set_sha256", "dockerfile_sha256", "bases"}
            or recipe["role"] not in {"backend", "frontend", "renderer"}
            or component["platform"] != "linux/amd64"):
        raise MaterializeRefused("invalid-openshorts-recipe")
    groups = lock.get("input_sets", {})
    group = groups.get(recipe["input_set"]) if isinstance(groups, dict) else None
    if (not isinstance(group, dict) or set(group) != {"source", "files", "dependencies"}
            or hashlib.sha256(canonical(group)).hexdigest() != recipe["input_set_sha256"]
            or not isinstance(group["files"], list) or not 1 <= len(group["files"]) <= 64
            or not isinstance(group["dependencies"], list) or len(group["dependencies"]) > 16):
        raise MaterializeRefused("public-input-set-drift")
    _check_artifact(group["source"])
    files = {}
    for selected in group["files"]:
        if (not isinstance(selected, dict) or set(selected) != {"path", "target", "sha256", "bytes"}
                or type(selected["bytes"]) is not int or not 0 <= selected["bytes"] <= MAX_METADATA
                or not isinstance(selected["sha256"], str) or not SHA.fullmatch(selected["sha256"])):
            raise MaterializeRefused("invalid-public-helper-pin")
        target = _relative(selected["target"])
        data = _read(root / _relative(selected["path"]))
        if (target in files or len(data) != selected["bytes"]
                or hashlib.sha256(data).hexdigest() != selected["sha256"]):
            raise MaterializeRefused("public-helper-drift")
        files[target] = data
    for dependency in group["dependencies"]:
        if (not isinstance(dependency, dict)
                or set(dependency) != {"role", "manifest", "kind", "target"}
                or dependency["role"] not in {"backend", "frontend", "renderer"}
                or dependency["kind"] not in {"npm", "wheels", "system", "models"}
                or dependency["manifest"] not in files):
            raise MaterializeRefused("invalid-public-dependency-manifest")
        _relative(dependency["target"])
        manifest = _json(files[dependency["manifest"]])
        if not isinstance(manifest.get("artifacts"), list) or not 1 <= len(manifest["artifacts"]) <= 1024:
            raise MaterializeRefused("unbounded-public-dependencies")
        for artifact in manifest["artifacts"]:
            _dependency_pin(artifact, dependency["kind"])
    dockerfile = _openshorts_dockerfile(recipe["role"], files)
    if hashlib.sha256(dockerfile).hexdigest() != recipe["dockerfile_sha256"]:
        raise MaterializeRefused("public-dockerfile-drift")
    if re.findall(r"(?im)^FROM\s+([^\s]+)", dockerfile.decode()) != recipe["bases"]:
        raise MaterializeRefused("public-build-base-drift")
    for base in recipe["bases"]:
        _registry_reference(base)
    return group, files, dockerfile


def _dependency_pin(item: dict, kind: str) -> tuple[str, str, str, int | None]:
    if not isinstance(item, dict):
        raise MaterializeRefused("invalid-public-dependency")
    algorithm = "sha512" if kind == "npm" else "sha256"
    digest = item.get("sha512_hex" if kind == "npm" else "sha256")
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{" + ("128" if kind == "npm" else "64") + "}", digest):
        raise MaterializeRefused("unpinned-public-dependency")
    if kind == "npm" and item.get("integrity") != "sha512-" + base64.b64encode(bytes.fromhex(digest)).decode():
        raise MaterializeRefused("inconsistent-public-npm-integrity")
    name = digest + ".tgz" if kind == "npm" else item.get("path" if kind == "models" else "filename")
    _relative(name)
    _public_url(item.get("url"))
    size = item.get("bytes")
    if size is not None and (type(size) is not int or not 1 <= size <= MAX_INPUT):
        raise MaterializeRefused("invalid-public-dependency-size")
    return algorithm, digest, name, size


def _dependency_cached(path: Path, algorithm: str, digest: str, size: int | None) -> int:
    _safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 1 <= before.st_size <= MAX_INPUT or size is not None and before.st_size != size):
            raise MaterializeRefused("public-dependency-size-mismatch")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            actual = hashlib.file_digest(stream, algorithm).hexdigest()
        after = os.fstat(fd)
        if (actual != digest or (before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_ino, after.st_size, after.st_mtime_ns)):
            raise MaterializeRefused("public-dependency-digest-mismatch")
        return before.st_size
    finally:
        os.close(fd)


def fetch_dependency(item: dict, kind: str, cache: Path, *, opener=None) -> Path:
    """Older hash-bound wheel/npm inventories lack lengths: bound and observe them."""
    algorithm, digest, _, size = _dependency_pin(item, kind)
    path = _safe_path(cache / "inputs" / (algorithm + "-" + digest))
    if path.exists():
        _dependency_cached(path, algorithm, digest, size)
        return path
    _directory(path.parent)
    pending = path.with_name(path.name + ".partial-" + uuid.uuid4().hex)
    opener = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _PublicRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    maximum = size if size is not None else MAX_INPUT
    request = urllib.request.Request(item["url"], headers={"User-Agent": "RAPP-Dock-materializer/1"})
    try:
        hasher, total = hashlib.new(algorithm), 0
        with opener.open(request, timeout=60) as response, pending.open("xb") as target:
            os.chmod(pending, 0o600)
            _public_url(response.geturl())
            while block := response.read(min(1024 * 1024, maximum - total + 1)):
                total += len(block)
                if total > maximum:
                    raise MaterializeRefused("public-dependency-size-mismatch")
                hasher.update(block)
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        if not total or size is not None and size != total or hasher.hexdigest() != digest:
            raise MaterializeRefused("public-dependency-digest-mismatch")
        try:
            os.link(pending, path)
        except FileExistsError:
            _dependency_cached(path, algorithm, digest, size)
        observation = {
            "schema": "rapp-dock-public-input-observation/1", "url": item["url"],
            "algorithm": algorithm, "digest": digest, "bytes": total,
            "length_predeclared": size is not None, "integrity": "verified",
        }
        _commit_file(cache / "input-observations" / (algorithm + "-" + digest + ".json"),
                     canonical(observation))
        return path
    except (urllib.error.URLError, OSError) as error:
        _commit_file(cache / "diagnostics" / ("public-input-" + digest + "-" + uuid.uuid4().hex + ".json"),
                     canonical({"url": item["url"], "digest": digest,
                                "error_type": type(error).__name__,
                                "reason_type": type(getattr(error, "reason", None)).__name__,
                                "http_status": getattr(error, "code", None)}))
        raise MaterializeRefused("public-dependency-fetch-failed", detail=digest) from error
    finally:
        pending.unlink(missing_ok=True)


def _build_openshorts(name: str, item: dict, lock: dict, root: Path, cache: Path, run: Callable) -> dict:
    group, files, dockerfile = _openshorts_inputs(item, root, lock)
    tag, fingerprint = image_tag(name, item), recipe_digest(item)
    if _inspect(tag, item["platform"], run) is not None:
        raise MaterializeRefused("content-tag-already-exists-use-recorded-id", name)
    for base in dict.fromkeys(item["recipe"]["bases"]):
        if _registry(base, item["platform"], run) is None:
            result = run(["pull", "--platform", item["platform"], base],
                         check=False, capture_output=True, timeout=1800)
            if result.returncode or _registry(base, item["platform"], run) is None:
                raise MaterializeRefused("public-base-pull-failed", name)
    source = fetch_artifact(group["source"], cache)
    role = item["recipe"]["role"]
    artifacts, locations = {}, []
    for dependency in group["dependencies"]:
        if dependency["role"] != role:
            continue
        for artifact in _json(files[dependency["manifest"]])["artifacts"]:
            algorithm, digest, filename, _ = _dependency_pin(artifact, dependency["kind"])
            key = algorithm + "-" + digest
            artifacts.setdefault(key, (artifact, dependency["kind"]))
            locations.append((key, dependency["target"] + "/" + filename))
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {key: pool.submit(fetch_dependency, artifact, kind, cache)
                   for key, (artifact, kind) in artifacts.items()}
        try:
            downloaded = {key: future.result() for key, future in futures.items()}
        except MaterializeRefused as error:
            for future in futures.values():
                future.cancel()
            raise MaterializeRefused(error.code, name, error.detail) from error
    stage = _directory(cache / ("build-" + fingerprint + "-" + uuid.uuid4().hex))
    context_tar = stage / "context.tar"
    try:
        helper = _directory(stage / "helpers")
        for relative, data in files.items():
            target = helper / relative
            _directory(target.parent)
            target.write_bytes(data)
            target.chmod(0o600)
        assets = _directory(stage / "assets")
        for key, relative in sorted(set(locations)):
            target = assets / _relative(relative)
            _directory(target.parent)
            shutil.copyfile(downloaded[key], target)
            target.chmod(0o600)
        context = stage / "context"
        environment = {"PATH": os.defpath, "HOME": str(stage), "PYTHONDONTWRITEBYTECODE": "1"}
        prepared = subprocess.run(
            [sys.executable, str(helper / "qualification/prepare_offline.py"),
             "--source-archive", str(source.absolute()), "--assets-root", str(assets),
             "--output", str(context), "--role", role],
            env=environment, timeout=600, capture_output=True, check=False,
        )
        if prepared.returncode:
            _diagnostic(cache, name, "prepare", prepared)
            raise MaterializeRefused("locked-public-preparation-failed", name)
        (context / "Dockerfile").write_bytes(dockerfile)
        total = 0
        with context_tar.open("xb") as stream, tarfile.open(fileobj=stream, mode="w|") as archive:
            context_tar.chmod(0o600)
            for path in sorted(context.rglob("*")):
                _safe_path(path)
                if path.is_dir():
                    continue
                info = path.stat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise MaterializeRefused("unsafe-public-build-context", name)
                total += info.st_size
                if total > 8 * 1024 * 1024 * 1024:
                    raise MaterializeRefused("public-build-context-too-large", name)
                member = tarfile.TarInfo(path.relative_to(context).as_posix())
                member.size, member.mode = info.st_size, 0o755 if info.st_mode & 0o111 else 0o644
                with path.open("rb") as content:
                    archive.addfile(member, content)
        with context_tar.open("rb") as stream:
            built = run(
                ["build", "--pull=false", "--network=none", "--platform", item["platform"],
                 "--tag", tag, "--label", "rapp.dock.recipe.sha256=" + fingerprint, "-"],
                stdin=stream, timeout=3600, capture_output=True, check=False,
            )
        if built.returncode:
            _diagnostic(cache, name, "build", built)
            raise MaterializeRefused("locked-public-build-failed", name)
        image = _inspect(tag, item["platform"], run)
        if image is None or image["labels"].get("rapp.dock.recipe.sha256") != fingerprint:
            raise MaterializeRefused("built-image-identity-mismatch", name)
        return {**image, "resolution": "built-public-inputs"}
    finally:
        shutil.rmtree(stage)


def recipe_digest(component: dict) -> str:
    identity = {key: component[key] for key in ("kind", "platform", "reference", "recipe", "source")}
    return hashlib.sha256(canonical(identity)).hexdigest()


def image_tag(name: str, component: dict) -> str:
    return "rapp-dock/" + name + ":" + recipe_digest(component)


def docker_runner(*, cache: Path | None = None, executable: str = "docker") -> Callable:
    """No caller tokens/proxies or Docker credential helpers reach public pulls."""
    env = {name: os.environ[name] for name in ("PATH", "HOME") if name in os.environ}
    env["LC_ALL"] = "C"
    probe = subprocess.run(
        [executable, "context", "inspect", "desktop-linux", "--format", "{{.Endpoints.docker.Host}}"],
        env=env, capture_output=True, timeout=10, check=False,
    )
    endpoint = probe.stdout.decode().strip()
    allowed = {"unix://" + str(Path.home() / ".docker/run/docker.sock"),
               "unix://" + str(Path.home() / ".docker/desktop/docker.sock")}
    if probe.returncode or endpoint not in allowed:
        raise MaterializeRefused("local-docker-desktop-required")
    args = [executable, "--host", endpoint]
    plugin = None
    if cache is not None:
        config = _directory(cache / "docker-public")
        config_file = config / "config.json"
        binary = Path(shutil.which(executable) or executable).resolve()
        for candidate in (
            binary.parent.parent / "cli-plugins/docker-buildx",
            Path.home() / ".docker/cli-plugins/docker-buildx",
        ):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                plugin = candidate.resolve()
                break
        config_bytes = canonical({"cliPluginsExtraDirs": [str(plugin.parent)]}) if plugin else b"{}\n"
        if config_file.exists():
            current = _read(config_file)
            if current not in {b"{}\n", config_bytes}:
                raise MaterializeRefused("public-docker-config-drift")
            if current != config_bytes:
                _commit_file(config_file, config_bytes)
        else:
            _commit_file(config_file, config_bytes)
        args += ["--config", str(config)]
        env["DOCKER_BUILDKIT"] = "1"

    def run(arguments, **kwargs):
        if (not isinstance(arguments, list) or not arguments
                or not (arguments[:2] == ["image", "inspect"]
                        or cache is not None and arguments[0] in {"pull", "build"})):
            raise MaterializeRefused("docker-operation-not-allowed")
        if arguments[0] == "build" and plugin is None:
            raise MaterializeRefused("docker-buildkit-required")
        kwargs.setdefault("check", False)
        kwargs.setdefault("capture_output", True)
        return subprocess.run(args + arguments, env=env, **kwargs)
    return run


def _inspect(reference: str, platform: str, run: Callable) -> dict | None:
    result = run(["image", "inspect", reference], timeout=20)
    if result.returncode:
        stderr = result.stderr.decode(errors="replace") if isinstance(result.stderr, bytes) else result.stderr or ""
        if any(marker in stderr.lower() for marker in ("no such image", "no such object", "not found")):
            return None
        raise MaterializeRefused("docker-inspection-failed")
    values = _json(result.stdout)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise MaterializeRefused("invalid-image-inspection")
    image = values[0]
    if (not isinstance(image.get("Id"), str) or not IMAGE_ID.fullmatch(image["Id"])
            or (str(image.get("Os")) + "/" + str(image.get("Architecture"))) != platform):
        raise MaterializeRefused("image-platform-or-id-mismatch")
    configuration = image.get("Config")
    if configuration is not None and not isinstance(configuration, dict):
        raise MaterializeRefused("invalid-image-inspection")
    labels = (configuration or {}).get("Labels") or {}
    digests = image.get("RepoDigests") or []
    if not isinstance(labels, dict) or not isinstance(digests, list) or any(not isinstance(value, str) for value in digests):
        raise MaterializeRefused("invalid-image-inspection")
    return {"image_id": image["Id"], "platform": platform,
            "repo_digests": digests, "labels": labels}


def _registry(reference: str, platform: str, run: Callable) -> dict | None:
    image = _inspect(reference, platform, run)
    if image is not None:
        digest = reference.rsplit("@", 1)[1]
        if (image["image_id"] != digest
                and not any(value.rsplit("@", 1)[-1] == digest for value in image["repo_digests"])):
            raise MaterializeRefused("registry-digest-mismatch")
    return image


def _receipt(state_dir: Path | None) -> dict:
    if state_dir is None:
        return {"schema": "rapp-dock-materialized/1", "images": {}}
    path = _safe_path(state_dir / RECEIPT)
    if not path.exists():
        return {"schema": "rapp-dock-materialized/1", "images": {}}
    info = path.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise MaterializeRefused("materialization-receipt-not-private")
    data = _json(_read(path))
    if (not isinstance(data, dict) or set(data) != {"schema", "images"}
            or data["schema"] != "rapp-dock-materialized/1" or not isinstance(data["images"], dict)):
        raise MaterializeRefused("invalid-materialization-receipt")
    fields = {"recipe_sha256", "image_id", "platform", "resolution", "registry_reference"}
    for name, record in data["images"].items():
        if (not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name)
                or not isinstance(record, dict) or set(record) != fields
                or not isinstance(record["recipe_sha256"], str) or not SHA.fullmatch(record["recipe_sha256"])
                or not isinstance(record["image_id"], str) or not IMAGE_ID.fullmatch(record["image_id"])
                or not isinstance(record["platform"], str) or record["platform"] not in {"linux/amd64", "linux/arm64"}
                or not isinstance(record["resolution"], str) or record["resolution"] not in {
                    "built-public-inputs", "locked-local-observation-not-public-download",
                    "locked-public-registry-digest"}):
            raise MaterializeRefused("invalid-materialization-receipt")
        if record["resolution"] == "locked-public-registry-digest":
            _registry_reference(record["registry_reference"])
        elif record["registry_reference"] is not None:
            raise MaterializeRefused("invalid-materialization-receipt")
    return data


def _resolve(name: str, item: dict, receipt: dict, run: Callable) -> dict | None:
    if item["kind"] == "registry":
        image = _registry(item["reference"], item["platform"], run)
        if image is not None:
            return {**image, "resolution": "locked-public-registry-digest"}
        return None
    fingerprint = recipe_digest(item)
    record = receipt["images"].get(name)
    if record is not None and not isinstance(record, dict):
        raise MaterializeRefused("invalid-recorded-image", name)
    if record is not None and record.get("recipe_sha256") == fingerprint:
        if not isinstance(record.get("image_id"), str) or not IMAGE_ID.fullmatch(record["image_id"]):
            raise MaterializeRefused("invalid-recorded-image", name)
        image = _inspect(record["image_id"], item["platform"], run)
        if image is not None:
            if (image["image_id"] != record["image_id"]
                    or record.get("resolution") == "built-public-inputs"
                    and image["labels"].get("rapp.dock.recipe.sha256") != fingerprint):
                raise MaterializeRefused("recorded-image-drift", name)
            if (record.get("resolution") != "built-public-inputs"
                    and image["image_id"] not in item["observed_image_ids"]):
                raise MaterializeRefused("unlocked-local-image", name)
            return {**image, "resolution": record["resolution"]}
    for expected in item["observed_image_ids"]:
        image = _inspect(expected, item["platform"], run)
        if image is not None:
            if image["image_id"] != expected:
                raise MaterializeRefused("observed-image-id-mismatch", name)
            return {**image, "resolution": "locked-local-observation-not-public-download"}
    return None


def resolve_images(app: str, *, root: Path = ROOT, state_dir: Path | None = None,
                   run: Callable | None = None) -> dict[str, str]:
    """Read-only controller API; run(argv, timeout=20) returns a CompletedProcess."""
    lock = load_lock(root)
    if app not in lock["applications"]:
        raise MaterializeRefused("unknown-application")
    run = run or docker_runner()
    receipt = _receipt(state_dir)
    answer = {}
    for name in sorted(set(lock["applications"][app].values())):
        item = lock["components"][name]
        image = _resolve(name, item, receipt, run)
        if image is None:
            raise MaterializeRefused("image-not-materialized", name)
        answer[item["env"]] = image["image_id"]
    return answer


def _build(name: str, item: dict, lock: dict, root: Path, cache: Path, run: Callable) -> dict:
    if item["kind"] != "dockerfile":
        raise MaterializeRefused("public-build-blocked", name, "; ".join(item["blockers"]))
    files = _recipe_files(item, root, lock)
    for base in item["recipe"]["bases"]:
        if _registry(base, item["platform"], run) is None:
            result = run(["pull", "--platform", item["platform"], base],
                         check=False, capture_output=True, timeout=1800)
            if result.returncode or _registry(base, item["platform"], run) is None:
                raise MaterializeRefused("public-base-pull-failed", name)
    artifacts = []
    for selected in item["recipe"]["artifacts"]:
        artifact = lock["artifacts"][selected["artifact"]]
        path = fetch_artifact(artifact, cache)
        artifacts.append((selected, path))
    tag = image_tag(name, item)
    if _inspect(tag, item["platform"], run) is not None:
        raise MaterializeRefused("content-tag-already-exists-use-recorded-id", name)
    context = cache / ("context-" + recipe_digest(item) + ".tar")
    if context.exists() or context.is_symlink():
        raise MaterializeRefused("build-context-collision", name)
    try:
        with context.open("xb") as stream, tarfile.open(fileobj=stream, mode="w|") as archive:
            os.chmod(context, 0o600)
            for target, data in sorted(files.items()):
                member = tarfile.TarInfo(target)
                member.size, member.mode = len(data), 0o644
                archive.addfile(member, io.BytesIO(data))
            for selected, path in artifacts:
                if selected["member"] is None:
                    member = tarfile.TarInfo(selected["target"])
                    member.size, member.mode = path.stat().st_size, 0o644
                    with path.open("rb") as binary:
                        archive.addfile(member, binary)
                    continue
                with tarfile.open(path, "r:gz") as source:
                    members = source.getmembers()
                    matches = [entry for entry in members if entry.name == selected["member"]]
                    if (len(matches) != 1 or not matches[0].isfile()
                            or not 1 <= matches[0].size <= 512 * 1024 * 1024
                            or any(entry.issym() or entry.islnk() or entry.isdev() for entry in members)):
                        raise MaterializeRefused("unsafe-public-archive-member", name)
                    member = tarfile.TarInfo(selected["target"])
                    member.size, member.mode = matches[0].size, 0o755
                    with source.extractfile(matches[0]) as binary:
                        archive.addfile(member, binary)
        with context.open("rb") as stream:
            result = run([
                "build", "--pull=false", "--network=none", "--platform", item["platform"],
                "--tag", tag, "--label", "rapp.dock.recipe.sha256=" + recipe_digest(item), "-",
            ], stdin=stream, timeout=3600, check=False, capture_output=True)
        if result.returncode:
            _diagnostic(cache, name, "build", result)
            raise MaterializeRefused("locked-public-build-failed", name)
        image = _inspect(tag, item["platform"], run)
        if image is None or image["labels"].get("rapp.dock.recipe.sha256") != recipe_digest(item):
            raise MaterializeRefused("built-image-identity-mismatch", name)
        return {**image, "resolution": "built-public-inputs"}
    finally:
        context.unlink(missing_ok=True)


def materialize(names: list[str], *, root: Path = ROOT, cache: Path | None = None,
                apply: bool = False, rebuild: bool = False, run: Callable | None = None) -> dict:
    lock = load_lock(root)
    if not names or len(names) != len(set(names)) or any(name not in lock["components"] for name in names):
        raise MaterializeRefused("unknown-or-duplicate-component")
    if apply and cache is None:
        raise MaterializeRefused("explicit-cache-required")
    if apply:
        cache = _directory(cache)
    run = run or docker_runner(cache=cache if apply else None)
    receipt = _receipt(cache)
    rows = {}
    for name in names:
        item = lock["components"][name]
        image = _resolve(name, item, receipt, run)
        if apply and (image is None or rebuild and image["resolution"] != "built-public-inputs"):
            if item["kind"] == "registry":
                if image is None:
                    result = run(["pull", "--platform", item["platform"], item["reference"]],
                                 timeout=1800, check=False, capture_output=True)
                    if result.returncode:
                        raise MaterializeRefused("locked-public-pull-failed", name)
                    image = _registry(item["reference"], item["platform"], run)
                    if image is None:
                        raise MaterializeRefused("pulled-image-unavailable", name)
                    image["resolution"] = "locked-public-registry-digest"
            elif item["kind"] == "dockerfile":
                image = _build(name, item, lock, root, cache, run)
            elif item["kind"] == "openshorts-offline":
                image = _build_openshorts(name, item, lock, root, cache, run)
        rows[name] = {
            "status": "resolved" if image else "blocked",
            "platform": item["platform"], "image_id": image["image_id"] if image else None,
            "resolution": image["resolution"] if image else None,
            "registry_reference": item["reference"],
            "verified_registry_digests": image["repo_digests"] if image and item["kind"] == "registry" else [],
            "public_materialization": (
                "locally-replayed-public-build" if image and image["resolution"] == "built-public-inputs"
                else "blocked" if item["blockers"] else "locked-inputs-available"
            ),
            "blockers": item["blockers"],
            "blockers_scope": "reference-machine-public-replay-not-current-image-health",
            "runtime_qualified": False,
        }
        if image and apply:
            receipt["images"][name] = {
                "recipe_sha256": recipe_digest(item), "image_id": image["image_id"],
                "platform": item["platform"], "resolution": image["resolution"],
                "registry_reference": item["reference"],
            }
            _commit_file(cache / RECEIPT, canonical(receipt))
    return {"schema": "rapp-dock-materialization/1", "images": rows,
            "all_resolved": all(item["status"] == "resolved" for item in rows.values()),
            "runtime_started": False, "existing_images_deleted": False,
            "fresh_machine_acceptance": "not-performed", "mutations_enabled": apply}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--app", default="all")
    selection.add_argument("--component", action="append")
    selection.add_argument("--fetch-artifact", help="Explicit fetch-only; no Docker calls or archive execution.")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--build", action="store_true", help="Explicit rebuild; existing images are retained.")
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args()
    try:
        lock = load_lock()
        if args.fetch_artifact is not None:
            if (args.cache is None or args.materialize or args.build
                    or args.fetch_artifact not in lock["artifacts"]):
                raise MaterializeRefused("explicit-locked-artifact-and-cache-required")
            item = lock["artifacts"][args.fetch_artifact]
            fetch_artifact(item, args.cache)
            print(canonical({"status": "public-input-verified", "artifact": args.fetch_artifact,
                             "sha256": item["sha256"], "bytes": item["bytes"],
                             "runtime_started": False}).decode(), end="")
            return 0
        if args.component:
            names = args.component
        elif args.app == "all":
            names = sorted(lock["components"])
        elif args.app in lock["applications"]:
            names = sorted(set(lock["applications"][args.app].values()))
        else:
            raise MaterializeRefused("unknown-application")
        apply = args.materialize or args.build
        if apply and args.cache is None:
            raise MaterializeRefused("explicit-cache-required")
        result = materialize(
            names, cache=args.cache, apply=apply, rebuild=args.build,
            run=docker_runner(cache=args.cache if apply else None, executable=args.docker),
        )
        print(canonical(result).decode(), end="")
        return 0 if result["all_resolved"] else 2
    except (MaterializeRefused, OSError, subprocess.SubprocessError, tarfile.TarError) as error:
        result = {"status": "refused", "code": getattr(error, "code", "materialization-failed"),
                  "component": getattr(error, "component", "")}
        detail = getattr(error, "detail", "")
        if re.fullmatch(r"[0-9a-f]{64}|[0-9a-f]{128}", detail):
            result["input_digest"] = detail
        print(canonical(result).decode(), end="")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
