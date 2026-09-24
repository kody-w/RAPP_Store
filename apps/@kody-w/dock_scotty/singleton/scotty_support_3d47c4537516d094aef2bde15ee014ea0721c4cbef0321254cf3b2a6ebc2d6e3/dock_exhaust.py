"""Private, keyless job observations and inert capsules using pinned RAPP/1.

Call accepted before effects, phase only for meaningful transitions, and terminal
with the saved operation. A failed terminal write means provenance is pending;
retry it without resubmitting the job. bundle carries all declared output bytes,
not Docker images, private inputs, credentials, databases, or execution authority.
Constructing JobExhaust does not initialize a reporter or touch the Dock home.
"""

from __future__ import annotations

import functools
import hashlib
import importlib as _imports
import importlib.metadata as _metadata
import math
import os
import re
import stat
import sys
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

# The unchanged scoped loader snapshots importlib before lazy stdlib submodules
# load. Populate that revision-local facade, not a global import hook.
if not hasattr(_imports, "metadata"):
    _imports.metadata = _metadata

import dock_portability as P

RUNTIME = "rapp-dock/job-exhaust/1"
EVENT_SCHEMA = "rapp-dock-job-event/1"
EVENT_SCHEMA_V2 = "rapp-dock-job-event/2"
CURRENT_EVENT_SCHEMA = EVENT_SCHEMA_V2
EVENT_SCHEMAS = frozenset({EVENT_SCHEMA, EVENT_SCHEMA_V2})
MAX_FRAMES = 128
MAX_FRAME_BYTES = 16 * 1024
MAX_HISTORY_BYTES = 768 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_ARTIFACTS = 64
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
MAX_SUPPORT_BYTES = 32 * 1024 * 1024
MAX_SUPPORT_FILE_BYTES = 4 * 1024 * 1024
TERMINAL = frozenset(
    {"succeeded", "partial", "failed", "cancelled", "interrupted", "indeterminate"}
)
_INSTANCE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_LABEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}")
_HEX = re.compile(r"[0-9a-f]{64}")
_SECRET_KEY = re.compile(
    r"token|password|passwd|secret|credential|authorization|cookie|"
    r"api.?key|private.?key|access.?key|headers|environment|^env$", re.I
)
_TOKEN = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|"
    rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b|"
    rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b|"
    rb"(?i:authorization\s*[:=]\s*[\"']?(?:bearer|basic)\s+\S+)"
)
_ASSIGNMENT = re.compile(
    rb"(?i:[\"']?(?:[a-z0-9_]*(?:api_key|access_token|github_token|"
    rb"password|secret_key)|authorization)[\"']?\s*[:=]\s*[\"']?"
    rb"[A-Za-z0-9_+/.-]+)"
)
_FORBIDDEN_PARTS = frozenset(
    {".git", ".ssh", ".aws", ".azure", ".brainstem", ".copilot", "secrets", "credentials"}
)
_REGISTRY_NAME = "_rapp_dock_job_exhaust_registry"


class ExhaustError(ValueError):
    """Stable, redacted failure; never evidence that an application was retried."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ExhaustError(code)


def _guard(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ExhaustError:
            raise
        except (P.PortabilityError, OSError, ValueError, TypeError, UnicodeError, RecursionError):
            raise ExhaustError("exhaust-unavailable", "Job provenance could not be verified or persisted.") from None
    return wrapped


def _registry():
    candidate = ModuleType(_REGISTRY_NAME)
    candidate.lock = threading.RLock()
    candidate.locks = {}
    candidate.identities = {}
    candidate.heads = {}
    return sys.modules.setdefault(_REGISTRY_NAME, candidate)


@contextmanager
def _process_lock(key: str):
    registry = _registry()
    with registry.lock:
        lock = registry.locks.setdefault(key, threading.RLock())
    with lock:
        yield


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _address(space: str, digest: str) -> dict[str, str]:
    return {"space": space, "hash": digest}


def _digest(value: Any) -> str | None:
    return value if isinstance(value, str) and _HEX.fullmatch(value) else None


def _integer(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def _label(value: Any) -> str | None:
    if not isinstance(value, str) or not _LABEL.fullmatch(value):
        return None
    return None if _TOKEN.search(value.encode()) or _SECRET_KEY.search(value) else value


def _time(value: Any) -> str | None:
    if value is None:
        return None
    _require(isinstance(value, str) and len(value) <= 40, "exhaust-invalid-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(parsed.tzinfo is not None, "exhaust-invalid-time")
        return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except ValueError:
        raise ExhaustError("exhaust-invalid-time") from None


def _redacted(value: Any, depth: int = 0) -> Any:
    _require(depth <= 16, "exhaust-metadata-limit")
    if isinstance(value, dict):
        _require(len(value) <= 256 and all(isinstance(k, str) for k in value), "exhaust-metadata-limit")
        keys = [unicodedata.normalize("NFC", key) for key in value]
        _require(len(set(keys)) == len(keys), "exhaust-ambiguous-keys")
        return {
            unicodedata.normalize("NFC", key): (
                "[redacted]" if _SECRET_KEY.search(key) else _redacted(item, depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        _require(len(value) <= 256, "exhaust-metadata-limit")
        return [_redacted(item, depth + 1) for item in value]
    if isinstance(value, str):
        _require(len(value) <= 65536, "exhaust-metadata-limit")
        raw = value.encode("utf-8")
        return _ASSIGNMENT.sub(b"[redacted]", _TOKEN.sub(b"[redacted]", raw)).decode("utf-8")
    if type(value) is float:
        _require(math.isfinite(value), "exhaust-invalid-number")
        return {"type": "decimal", "value": repr(value)}
    _require(value is None or isinstance(value, bool) or type(value) is int, "exhaust-invalid-metadata")
    return value


def _name(value: Any) -> str:
    _require(isinstance(value, str) and 1 <= len(value) <= 255, "artifact-invalid-name")
    name = unicodedata.normalize("NFC", value)
    _require("/" not in name and "\\" not in name and name not in {".", ".."}, "artifact-invalid-name")
    _require(not any(ord(c) < 32 for c in name), "artifact-invalid-name")
    if _TOKEN.search(name.encode()) or _SECRET_KEY.search(name):
        return "redacted-" + hashlib.sha256(name.encode()).hexdigest()
    return name


def _media_type(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) <= 127
        and re.fullmatch(
            r"[A-Za-z0-9.+_-]+/[A-Za-z0-9.+_-]+(?:;\s?charset=[A-Za-z0-9._-]+)?",
            value,
        ) is not None
    )


def _execution_mode(value: dict[str, Any], result: dict[str, Any]) -> str | None:
    explicit = _label(value.get("execution_mode"))
    if explicit is not None:
        return explicit
    detail = result.get("result") if isinstance(result.get("result"), dict) else result
    generation = detail.get("generation")
    if generation == "gateway-authored, Presenton-exported":
        return "gateway-authored-presenton-exported"
    if generation == "Presenton-native generation":
        return "presenton-native"
    if detail.get("indexing_technique") == "economy":
        return "dify-economy-indexing"
    if detail.get("retrieval") == "keyword":
        return "dify-keyword-retrieval"
    if detail.get("fetch_mode") in {"http", "browser", "dynamic", "stealth"}:
        return "scrapling-" + detail["fetch_mode"]
    if detail.get("ai_selected") is True and _integer(detail.get("verified_clip_count")) is not None:
        return "ai-selected-native-rendered"
    return None


def _private_dir(path: Path) -> bool:
    created = False
    with P._directory(path.parent) as parent:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent)
            os.fsync(parent)
            created = True
        except FileExistsError:
            pass
    P._private_directory(path)
    return created


def _private_read(path: Path, limit: int = MAX_RECEIPT_BYTES) -> bytes:
    raw, info = P._read_snapshot(path, limit=limit)
    _require(info["owner"] == os.geteuid() and info["mode"] == 0o600, "exhaust-private-file")
    return raw


@contextmanager
def _file_lock(path: Path, *, create: bool):
    import fcntl

    with P._directory(path.parent) as parent:
        created = False
        if create:
            try:
                descriptor = os.open(
                    path.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600, dir_fd=parent,
                )
                created = True
                os.fsync(parent)
            except FileExistsError:
                descriptor = os.open(path.name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        else:
            descriptor = os.open(path.name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(descriptor)
        _require(
            stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == 0
            and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600,
            "exhaust-private-lock",
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield created
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _publish(path: Path, raw: bytes, *, previous: bytes | None = None) -> None:
    """Atomic publication under the owning store lock, never a partial final file."""
    exists = os.path.lexists(path)
    if exists:
        current = _private_read(path, max(len(raw), MAX_RECEIPT_BYTES))
        if previous is None:
            _require(current == raw, "exhaust-file-conflict")
            return
        _require(current == previous, "exhaust-head-conflict")
    else:
        _require(previous is None, "exhaust-head-lost")
    staging = path.with_name(".exhaust-" + uuid.uuid4().hex + ".pending")
    try:
        P._write_new(staging, raw)
        with P._directory(path.parent) as parent:
            _require(os.path.lexists(path) == exists, "exhaust-file-conflict")
            if exists:
                _require(_private_read(path, max(len(raw), MAX_RECEIPT_BYTES)) == current, "exhaust-file-conflict")
            os.replace(staging.name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
    finally:
        with P._directory(path.parent) as parent:
            try:
                os.unlink(staging.name, dir_fd=parent)
            except FileNotFoundError:
                pass


class JobExhaust:
    """One private reporter, independent memory streams, no scheduler or authority."""

    @_guard
    def __init__(self, home: str | Path) -> None:
        self.home = P._absolute(Path(home).expanduser())
        self.root = self.home / "exhaust"
        self.canonical = P.Canonical(Path(__file__).absolute().parent / "deploy/local/rapp1")
        self.r = self.canonical.r

    def _encode(self, value: Any) -> bytes:
        return self.canonical.encode(value)

    def _commitment(self, value: Any) -> dict[str, Any]:
        raw = self._encode(_redacted(value))
        _require(len(raw) <= 65536, "exhaust-metadata-limit")
        return {"sha256": P.sha256(raw), "bytes": len(raw)}

    def _identity(self, role: str) -> dict[str, Any]:
        now = _utc()
        _require(self.r.utc_valid(now), "exhaust-invalid-utc")
        return {
            "schema": "rapp/1",
            "rappid": self.r.mint_rappid("rapp-dock", role),
            "role": "dock-" + role,
            "identity_origin": "local-keyless-mint-once",
            "created_utc": now,
            "key_material": "none-created",
            "authority_adoption": "not-established",
        }

    def _read_identity(self, path: Path, role: str, expected_sha256: str | None = None) -> dict[str, Any]:
        raw = _private_read(path)
        _require(expected_sha256 is None or P.sha256(raw) == expected_sha256, "exhaust-invalid-anchor")
        value = self.canonical.decode(raw)
        _require(
            isinstance(value, dict)
            and set(value) == {"schema", "rappid", "role", "identity_origin", "created_utc", "key_material", "authority_adoption"}
            and value["schema"] == "rapp/1" and self.r.rappid_valid(value["rappid"])
            and self.r.rappid_parts(value["rappid"])["slug"] == role
            and value["role"] == "dock-" + role
            and value["identity_origin"] == "local-keyless-mint-once"
            and self.r.utc_valid(value["created_utc"])
            and value["key_material"] == "none-created"
            and value["authority_adoption"] == "not-established"
            and raw == self._encode(value),
            "exhaust-invalid-identity",
        )
        registry = _registry()
        with registry.lock:
            old = registry.identities.setdefault(str(path), P.sha256(raw))
        _require(old == P.sha256(raw), "exhaust-identity-changed")
        return value

    def _store(self, *, initialize: bool = False) -> dict[str, Any]:
        if initialize:
            _private_dir(self.home)
        else:
            P._private_directory(self.home)
        with _process_lock(str(self.home)), _file_lock(self.home / ".job-exhaust.lock", create=initialize):
            anchor = self.home / ".job-exhaust.json"
            if not os.path.lexists(self.root):
                _require(initialize and not os.path.lexists(anchor), "exhaust-state-lost")
                _private_dir(self.root)
                _private_dir(self.root / "streams")
                raw = self._encode(self._identity("job-reporter"))
                _publish(self.root / "rappid.json", raw)
                _publish(anchor, self._encode({
                    "schema": "rapp-dock-job-reporter-anchor/1", "sha256": P.sha256(raw),
                }))
            P._private_directory(self.root)
            P._private_directory(self.root / "streams")
            commitment = self.canonical.decode(_private_read(anchor))
            _require(
                isinstance(commitment, dict) and set(commitment) == {"schema", "sha256"}
                and commitment["schema"] == "rapp-dock-job-reporter-anchor/1"
                and _digest(commitment["sha256"]) is not None,
                "exhaust-invalid-anchor",
            )
            return self._read_identity(self.root / "rappid.json", "job-reporter", commitment["sha256"])

    def _op_id(self, value: Any) -> str:
        _require(isinstance(value, str) and 1 <= len(value) <= 64 and bool(_INSTANCE.fullmatch(value)), "exhaust-invalid-operation")
        return value

    def _operation(self, op: dict[str, Any]) -> dict[str, Any]:
        _require(isinstance(op, dict), "exhaust-invalid-operation")
        op_id = self._op_id(op.get("id"))
        app = op.get("application") or "dock"
        _require(isinstance(app, str) and 1 <= len(app) <= 64 and bool(_INSTANCE.fullmatch(app)), "exhaust-invalid-application")
        kind, name = _label(op.get("kind")), _label(op.get("name"))
        _require(kind is not None and name is not None, "exhaust-invalid-operation")
        _require(isinstance(op.get("arguments", {}), dict), "exhaust-invalid-arguments")
        return {
            "job_id": op_id, "application": app, "kind": kind, "name": name,
            "arguments": self._commitment(op.get("arguments", {})),
            "created_utc": _time(op.get("created")),
            "raw_inputs_retained": False, "credentials_retained": False,
        }

    def _facts(
        self, value: Any, *, infer_revision: bool = True, schema: str = EVENT_SCHEMA_V2,
    ) -> dict[str, Any]:
        _require(schema in EVENT_SCHEMAS, "exhaust-invalid-profile")
        value = value if isinstance(value, dict) else {}
        result = value.get("result") if isinstance(value.get("result"), dict) else {}
        native = value.get("native", result.get("native", {}))
        native = native if isinstance(native, dict) else {}
        ids = {}
        for key in sorted(native):
            if isinstance(key, str) and (key.endswith("_id") or key == "id") and _label(key):
                item = native[key]
                if _label(item) is not None or _integer(item) is not None:
                    ids[key] = item
        _require(len(ids) <= 32, "exhaust-metadata-limit")
        provider = value.get("provider", result.get("provider"))
        provider = provider if isinstance(provider, dict) else {}
        runtime = provider.get("runtime")
        runtime = runtime if runtime in {"copilot-cli-in-docker", "none"} else "unknown"
        requests = provider.get("request_ids", [])
        _require(isinstance(requests, list) and len(requests) <= 32, "exhaust-metadata-limit")
        request_ids = [item for item in requests if _label(item) is not None]
        counters = provider.get("usage")
        usage = {
            key: _integer(counters.get(key))
            for key in ("input_tokens", "output_tokens", "total_tokens", "cache_read_tokens", "cache_write_tokens")
        } if isinstance(counters, dict) else None
        if usage is not None and schema == EVENT_SCHEMA_V2:
            for target, source in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
                if usage[target] is None:
                    usage[target] = _integer(counters.get(source))
        inputs = value.get("inputs", value.get("sealed_inputs", []))
        _require(isinstance(inputs, list) and len(inputs) <= MAX_ARTIFACTS, "exhaust-metadata-limit")
        selected = []
        for item in inputs:
            _require(isinstance(item, dict) and _digest(item.get("sha256")) is not None and _integer(item.get("bytes")) is not None, "exhaust-invalid-input-descriptor")
            selected.append({
                "name": _name(item.get("name")), "bytes": item["bytes"],
                "sha256": item["sha256"], "retention": "digest-only",
            })
        images = value.get("images", [])
        _require(isinstance(images, list) and len(images) <= 32, "exhaust-metadata-limit")
        image_ids = []
        for image in images:
            if isinstance(image, dict):
                image_id = image.get("id", image.get("image_id"))
                image_ids.append({
                    "image_id": image_id if isinstance(image_id, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) else None,
                    "manifest_sha256": _digest(image.get("manifest_sha256")),
                    "architecture": image.get("architecture") if image.get("architecture") in {"arm64", "amd64", "linux/arm64", "linux/amd64"} else None,
                })
                if schema == EVENT_SCHEMA_V2:
                    image_ids[-1]["service"] = _label(image.get("service"))
        revision = _digest(value.get("capability_revision"))
        location = Path(__file__).absolute().parent.name
        if infer_revision and location.startswith("scotty_support_"):
            revision = _digest(location.removeprefix("scotty_support_")) or revision
        facts = {
            "native": ids,
            "provider": {
                "runtime": runtime, "model": _label(provider.get("model")),
                "calls": _integer(provider.get("calls")), "request_ids": request_ids, "usage": usage,
            },
            "inputs": selected, "images": image_ids,
            "capability_revision": revision,
            "adapter_sha256": _digest(value.get("adapter_sha256")),
            "compose_sha256": _digest(value.get("compose_sha256")),
            "source_commit": value.get("source_commit") if isinstance(value.get("source_commit"), str) and re.fullmatch(r"[0-9a-f]{40}", value["source_commit"]) else None,
        }
        if schema == EVENT_SCHEMA_V2:
            facts["execution_mode"] = _execution_mode(value, result)
            correlation = native.get("gateway_correlation", result.get("result", {}).get("gateway_correlation")
                                     if isinstance(result.get("result"), dict) else None)
            attribution = provider.get("attribution")
            if attribution not in {"exact-request", "app-window", "unknown", "none"}:
                attribution = "app-window" if isinstance(correlation, dict) and correlation.get("kind") == "app-window" else "none" if runtime == "none" else "unknown"
            facts["provider"]["attribution"] = attribution
        return facts

    @_guard
    def source_facts(self, application: str, capability_root: str | Path | None = None) -> dict[str, Any]:
        """Hash only locked adapter/Compose source, never env-resolved config or code execution."""
        self._op_id(application)
        root = P._absolute(Path(capability_root) if capability_root is not None else Path(__file__).absolute().parent)
        raw = P.read_regular(root / "SCOTTY_CAPABILITY_LOCK.json")
        lock = self.canonical.decode(raw)
        _require(
            isinstance(lock, dict) and set(lock) == {"schema", "grail_commit", "files"}
            and lock["schema"] == "scotty-capability-files/1" and lock["grail_commit"] == P.GRAIL["commit"]
            and isinstance(lock["files"], list) and 1 <= len(lock["files"]) <= 512,
            "capability-unverified",
        )
        revision = P.sha256(raw)
        if root.name.startswith("scotty_support_"):
            _require(root.name == "scotty_support_" + revision, "capability-revision-mismatch")
        selected = {}
        prefix = "deploy/local/" + application.replace("-", "_") + "/"
        for item in lock["files"]:
            _require(
                isinstance(item, dict) and set(item) == {"path", "bytes", "sha256"}
                and self.canonical.path(item["path"]) == item["path"]
                and _integer(item["bytes"]) is not None and item["bytes"] <= MAX_SUPPORT_FILE_BYTES
                and _digest(item["sha256"]) is not None,
                "capability-unverified",
            )
            name = item["path"]
            _require(name not in selected, "capability-unverified")
            selected[name] = item
        adapter = prefix + "adapter.py"
        compositions = [prefix + name for name in ("compose.yaml", "compose.yml", "compose.json") if prefix + name in selected]
        _require(adapter in selected and len(compositions) == 1, "capability-incomplete")
        result = {"capability_revision": revision}
        for key, name in (("adapter_sha256", adapter), ("compose_sha256", compositions[0])):
            data, info = P._read_snapshot(root / name, limit=MAX_SUPPORT_FILE_BYTES)
            _require(
                not info["mode"] & 0o022 and len(data) == selected[name]["bytes"]
                and P.sha256(data) == selected[name]["sha256"],
                "capability-changed",
            )
            result[key] = selected[name]["sha256"]
        return result

    @_guard
    def inspect_receipt(
        self, raw: bytes, *, operation_id: str | None = None, reporter: str | None = None,
    ) -> dict[str, Any]:
        """Pure, complete session/profile verification; no writer, retry, or head repair."""
        _require(isinstance(raw, bytes) and len(raw) <= MAX_RECEIPT_BYTES, "exhaust-invalid-receipt")
        _require(self.r.verify_egg(raw)[0], "exhaust-invalid-receipt")
        manifest, files = self.r.read_egg(raw)
        _require(
            manifest["variant"] == "session" and not files and manifest["sig"] is None
            and manifest["payload"]["runtime"] == RUNTIME,
            "exhaust-invalid-receipt",
        )
        frames = manifest["payload"]["transcript"]
        _require(2 <= len(frames) <= MAX_FRAMES, "exhaust-invalid-receipt")
        first = frames[0].get("payload", {})
        _require(isinstance(first, dict), "exhaust-invalid-receipt")
        selected_id = self._op_id(first.get("job_id"))
        _require(operation_id is None or selected_id == operation_id, "exhaust-operation-conflict")
        _require(reporter is None or manifest["rappid"] == reporter, "exhaust-invalid-identity")
        self._validate(frames, selected_id, manifest["rappid"])
        _require(
            frames[-1]["payload"]["event"] == "terminal" and manifest["created_utc"] == frames[-1]["utc"],
            "exhaust-invalid-receipt",
        )
        return manifest

    @contextmanager
    def _job(self, op_id: str, *, create: bool = False):
        identity = self._store(initialize=create)
        directory = self.root / "streams" / self._op_id(op_id)
        with _process_lock(str(directory)):
            if create:
                _private_dir(directory)
                _private_dir(directory / "frames")
            else:
                P._private_directory(directory)
                P._private_directory(directory / "frames")
            with _file_lock(directory / ".stream.lock", create=create):
                yield directory, identity

    def _index(self, frames: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schema": "rapp-frame-index/1", "stream_id": frames[0]["stream_id"],
            "frames": [f"frames/{frame['seq']:08d}.json" for frame in frames],
            "head": {"seq": frames[-1]["seq"], "frame_hash": frames[-1]["frame_hash"]},
        }

    def _validate_detail(self, event: str, detail: dict[str, Any], op_id: str, schema: str) -> None:
        if event == "accepted":
            _require(set(detail) == {"operation", "observed"}, "exhaust-invalid-event")
            operation = detail["operation"]
            _require(isinstance(operation, dict) and set(operation) == {
                "job_id", "application", "kind", "name", "arguments", "created_utc",
                "raw_inputs_retained", "credentials_retained",
            }, "exhaust-invalid-event")
            arguments = operation["arguments"]
            _require(
                operation["job_id"] == op_id
                and self._op_id(operation["application"]) == operation["application"]
                and _label(operation["kind"]) is not None and _label(operation["name"]) is not None
                and isinstance(arguments, dict) and set(arguments) == {"sha256", "bytes"}
                and _digest(arguments["sha256"]) is not None and _integer(arguments["bytes"]) is not None
                and (operation["created_utc"] is None or self.r.utc_valid(operation["created_utc"]))
                and operation["raw_inputs_retained"] is False and operation["credentials_retained"] is False,
                "exhaust-invalid-event",
            )
        elif event == "phase":
            _require(
                set(detail) == {"phase", "observed"}
                and _label(detail["phase"]) is not None and len(detail["phase"]) <= 64,
                "exhaust-invalid-event",
            )
        elif event == "artifacts-published":
            _require(
                set(detail) == {"completion_sha256", "artifacts"} and _digest(detail["completion_sha256"]) is not None
                and isinstance(detail["artifacts"], list) and 1 <= len(detail["artifacts"]) <= 16,
                "exhaust-invalid-event",
            )
            for artifact in detail["artifacts"]:
                _require(
                    isinstance(artifact, dict) and set(artifact) == {
                        "index", "name", "media_type", "bytes", "sha256", "verified", "address",
                    } and _integer(artifact["index"]) is not None and artifact["index"] < MAX_ARTIFACTS
                    and _name(artifact["name"]) == artifact["name"] and _media_type(artifact["media_type"])
                    and _integer(artifact["bytes"]) is not None and _digest(artifact["sha256"]) is not None
                    and type(artifact["verified"]) is bool
                    and isinstance(artifact["address"], dict) and set(artifact["address"]) == {"space", "hash"}
                    and artifact["address"]["space"] == "rapp/1:egg" and _digest(artifact["address"]["hash"]) is not None,
                    "exhaust-invalid-event",
                )
        elif event == "terminal":
            _require(
                set(detail) == {
                    "outcome", "error_code", "started_utc", "finished_utc", "observed",
                    "completion_sha256", "output_count", "artifacts_refs",
                } and detail["outcome"] in TERMINAL
                and (detail["error_code"] is None or _label(detail["error_code"]) is not None)
                and all(detail[key] is None or self.r.utc_valid(detail[key]) for key in ("started_utc", "finished_utc"))
                and _digest(detail["completion_sha256"]) is not None
                and _integer(detail["output_count"]) is not None and detail["output_count"] <= MAX_ARTIFACTS
                and isinstance(detail["artifacts_refs"], list),
                "exhaust-invalid-event",
            )
        if "observed" in detail:
            _require(
                isinstance(detail["observed"], dict)
                and detail["observed"] == self._facts(detail["observed"], infer_revision=False, schema=schema),
                "exhaust-invalid-event",
            )

    def _validate(self, frames: list[dict[str, Any]], op_id: str, reporter: str) -> None:
        head = None
        events = {"accepted", "phase", "artifacts-published", "terminal"}
        total, artifacts, artifact_frames = 0, [], []
        schema = None
        for frame in frames:
            raw = self._encode(frame)
            total += len(raw)
            _require(len(raw) <= MAX_FRAME_BYTES and total <= MAX_HISTORY_BYTES, "exhaust-history-limit")
            _require(isinstance(frame, dict), "exhaust-tampered")
            ok, _, _ = self.r.verify_frame(frame, head=head, stream_id_of_record=f"{reporter}:{op_id}")
            _require(ok and frame["kind"] == "memory.tool-call" and frame["sig"] is None, "exhaust-tampered")
            payload = frame["payload"]
            if schema is None:
                schema = payload.get("schema")
            _require(
                set(payload) == {"schema", "job_id", "event", "context_ref", "detail"}
                and schema in EVENT_SCHEMAS and payload["schema"] == schema and payload["job_id"] == op_id
                and payload["event"] in events and isinstance(payload["detail"], dict),
                "exhaust-invalid-event",
            )
            self._validate_detail(payload["event"], payload["detail"], op_id, schema)
            if head is None:
                _require(payload["event"] == "accepted" and payload["context_ref"] is None, "exhaust-invalid-genesis")
            else:
                _require(
                    payload["event"] != "accepted"
                    and head["payload"]["event"] != "terminal"
                    and payload["context_ref"] == _address("rapp/1:particle", frames[0]["payload_hash"]),
                    "exhaust-invalid-transition",
                )
            if payload["event"] == "phase":
                _require(head is not None and head["payload"]["event"] in {"accepted", "phase"}, "exhaust-invalid-transition")
            if payload["event"] == "artifacts-published":
                artifacts.extend(payload["detail"]["artifacts"])
                artifact_frames.append(frame)
                _require(
                    [item["index"] for item in artifacts] == list(range(len(artifacts)))
                    and len(artifacts) <= MAX_ARTIFACTS
                    and all(
                        item["payload"]["detail"]["completion_sha256"] == payload["detail"]["completion_sha256"]
                        for item in artifact_frames
                    ),
                    "exhaust-invalid-transition",
                )
            if payload["event"] == "terminal":
                detail = payload["detail"]
                completion = {
                    key: detail[key]
                    for key in ("outcome", "error_code", "started_utc", "finished_utc", "observed")
                }
                completion["artifacts"] = [
                    {key: value for key, value in item.items() if key != "address"} for item in artifacts
                ]
                _require(
                    detail["output_count"] == len(artifacts)
                    and detail["artifacts_refs"] == [
                        _address("rapp/1:particle", item["payload_hash"]) for item in artifact_frames
                    ]
                    and all(item["payload"]["detail"]["completion_sha256"] == detail["completion_sha256"] for item in artifact_frames)
                    and self.canonical.digest(completion) == detail["completion_sha256"]
                    and (detail["outcome"] != "succeeded" or all(item["verified"] for item in artifacts)),
                    "exhaust-invalid-transition",
                )
            head = frame

    def _advance(self, directory: Path, frames: list[dict[str, Any]], previous: bytes | None) -> None:
        _publish(directory / "rapp-frame-index.json", self._encode(self._index(frames)), previous=previous)
        registry = _registry()
        with registry.lock:
            registry.heads[str(directory)] = (frames[-1]["seq"], frames[-1]["frame_hash"])

    def _load(self, directory: Path, identity: dict[str, Any]) -> list[dict[str, Any]]:
        with P._directory(directory / "frames") as descriptor:
            names = sorted(name for name in os.listdir(descriptor) if not re.fullmatch(r"\.exhaust-[0-9a-f]{32}\.pending", name))
        _require(len(names) <= MAX_FRAMES, "exhaust-history-limit")
        _require(names == [f"{index:08d}.json" for index in range(len(names))], "exhaust-fork-or-gap")
        frames = []
        for name in names:
            raw = _private_read(directory / "frames" / name, MAX_FRAME_BYTES)
            frame = self.canonical.decode(raw)
            _require(self._encode(frame) == raw, "exhaust-noncanonical-frame")
            frames.append(frame)
        self._validate(frames, directory.name, identity["rappid"])
        index_path = directory / "rapp-frame-index.json"
        old = _private_read(index_path) if os.path.lexists(index_path) else None
        index = self.canonical.decode(old) if old is not None else None
        registry = _registry()
        with registry.lock:
            high = registry.heads.get(str(directory))
        if high:
            _require(len(frames) > high[0] and frames[high[0]]["frame_hash"] == high[1], "exhaust-rollback-or-fork")
        if index is None:
            _require(high is None and len(frames) <= 1, "exhaust-head-lost")
        else:
            _require(
                isinstance(index, dict) and set(index) == {"schema", "stream_id", "frames", "head"}
                and isinstance(index["head"], dict) and set(index["head"]) == {"seq", "frame_hash"},
                "exhaust-invalid-head",
            )
            seq = _integer(index["head"]["seq"])
            _require(seq is not None and seq < len(frames), "exhaust-head-lost")
            _require(index == self._index(frames[:seq + 1]), "exhaust-head-conflict")
            _require(len(frames) - seq - 1 <= 1, "exhaust-fork-or-gap")
            _require(high is None or seq >= high[0], "exhaust-rollback-or-fork")
        if frames and (index is None or index != self._index(frames)):
            # A single fully verified durable successor can precede a crashed head write.
            self._advance(directory, frames, old)
        elif frames:
            with registry.lock:
                registry.heads[str(directory)] = (frames[-1]["seq"], frames[-1]["frame_hash"])
        return frames

    def _append(self, directory, identity, frames, event: str, detail: dict[str, Any]):
        now = _utc()
        _require(self.r.utc_valid(now), "exhaust-invalid-utc")
        if frames:
            now = max(now, frames[-1]["utc"])
        payload = {
            "schema": frames[0]["payload"]["schema"] if frames else CURRENT_EVENT_SCHEMA,
            "job_id": directory.name, "event": event,
            "context_ref": _address("rapp/1:particle", frames[0]["payload_hash"]) if frames else None,
            "detail": detail,
        }
        frame = self.r.build_frame(
            "memory.tool-call", f"{identity['rappid']}:{directory.name}", len(frames), now,
            payload, frames[-1]["payload_hash"] if frames else None,
        )
        candidate = [*frames, frame]
        _require(len(candidate) <= MAX_FRAMES, "exhaust-history-limit")
        self._validate(candidate, directory.name, identity["rappid"])
        if event in {"accepted", "phase"}:
            _require(
                len(candidate) <= MAX_FRAMES - 5
                and sum(len(self._encode(item)) for item in candidate) <= MAX_HISTORY_BYTES - 5 * MAX_FRAME_BYTES,
                "exhaust-terminal-reserve",
            )
        previous = _private_read(directory / "rapp-frame-index.json") if frames else None
        _publish(directory / "frames" / f"{frame['seq']:08d}.json", self._encode(frame))
        self._advance(directory, candidate, previous)
        frames.append(frame)
        return _address("rapp/1:wave", frame["frame_hash"])

    @_guard
    def accepted(self, op: dict[str, Any]) -> dict[str, str]:
        operation = self._operation(op)
        op_id = operation["job_id"]
        with self._job(op_id, create=True) as (directory, identity):
            frames = self._load(directory, identity)
            schema = frames[0]["payload"]["schema"] if frames else CURRENT_EVENT_SCHEMA
            detail = {"operation": operation, "observed": self._facts(op, schema=schema)}
            if frames:
                _require(frames[0]["payload"]["detail"] == detail, "exhaust-operation-conflict")
                return _address("rapp/1:wave", frames[0]["frame_hash"])
            return self._append(directory, identity, frames, "accepted", detail)

    @_guard
    def phase(self, op_id: str, phase: str, payload: Any = None) -> dict[str, str]:
        name = _label(phase)
        _require(name is not None and len(name) <= 64, "exhaust-invalid-phase")
        with self._job(op_id) as (directory, identity):
            frames = self._load(directory, identity)
            _require(bool(frames), "job-not-accepted")
            detail = {"phase": name, "observed": self._facts(payload, schema=frames[0]["payload"]["schema"])}
            _require(frames[-1]["payload"]["event"] in {"accepted", "phase"}, "job-already-terminal")
            if frames[-1]["payload"]["event"] == "phase" and frames[-1]["payload"]["detail"] == detail:
                return _address("rapp/1:wave", frames[-1]["frame_hash"])
            return self._append(directory, identity, frames, "phase", detail)

    def _output_dir(self, operation: dict[str, Any], *, create: bool = False) -> Path:
        directory = self.home / "outputs" / operation["application"] / operation["job_id"]
        if create:
            for path in (directory.parent.parent, directory.parent, directory):
                _private_dir(path)
        return directory

    def _selection(self, op: dict[str, Any]) -> list[tuple[Path, dict[str, Any]]]:
        operation = self._operation(op)
        output = self._output_dir(operation)
        result = op.get("result")
        result = {} if result is None else result
        _require(isinstance(result, dict), "artifact-invalid-result")
        artifacts = result.get("artifacts", [])
        _require(isinstance(artifacts, list) and len(artifacts) <= MAX_ARTIFACTS, "artifact-count-exceeded")
        selected, paths = [], set()
        for index, item in enumerate(artifacts):
            _require(isinstance(item, dict), "artifact-invalid-descriptor")
            _require(_digest(item.get("sha256")) is not None and _integer(item.get("bytes")) is not None, "artifact-invalid-descriptor")
            _require(type(item.get("verified")) is bool, "artifact-invalid-descriptor")
            media = item.get("media_type")
            _require(_media_type(media), "artifact-invalid-media-type")
            path = P._absolute(item.get("path"))
            _require(path.is_relative_to(output) and path != output and path not in paths, "artifact-outside-operation")
            relative = path.relative_to(output).as_posix()
            _require(self.r._path_valid(relative) and not self._private_name(relative), "artifact-private-path")
            _require(path.name not in {"receipt.egg", "capsule.egg"}, "artifact-reserved-path")
            paths.add(path)
            selected.append((path, {
                "index": index, "name": _name(item.get("name")), "media_type": media,
                "bytes": item["bytes"], "sha256": item["sha256"], "verified": item["verified"],
            }))
        return selected

    @staticmethod
    def _private_name(name: str) -> bool:
        parts = name.lower().split("/")
        return any(part in _FORBIDDEN_PARTS or part.startswith(".env") and part != ".env.example"
                   or part in {"id_rsa", "id_ed25519"} or part.endswith((".env", ".pem", ".key", ".p12", ".pfx"))
                   for part in parts)

    def _artifact(self, path: Path, expected: dict[str, Any], *, carry: bool = False):
        with P._directory(path.parent) as parent:
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(descriptor)
            _require(
                stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_uid == os.geteuid() and stat.S_IMODE(before.st_mode) == 0o600,
                "artifact-unsafe-file",
            )
            _require(before.st_size == expected["bytes"], "artifact-changed")
            raw_hash = hashlib.sha256()
            file_hash = hashlib.sha256(b"rapp/1:egg\n")
            chunks, count, tail = [], 0, b""
            while True:
                chunk = os.read(descriptor, min(1024 * 1024, before.st_size + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                _require(count <= before.st_size, "artifact-changed")
                _require(not _TOKEN.search(tail + chunk) and not _ASSIGNMENT.search(tail + chunk), "artifact-secret-content")
                tail = chunk[-512:]
                raw_hash.update(chunk)
                file_hash.update(chunk)
                if carry:
                    chunks.append(chunk)
            after = os.fstat(descriptor)
            _require(
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                and count == before.st_size and raw_hash.hexdigest() == expected["sha256"],
                "artifact-changed",
            )
            return {
                **expected, "address": _address("rapp/1:egg", file_hash.hexdigest()),
            }, b"".join(chunks) if carry else None
        finally:
            os.close(descriptor)

    def _completion(self, op: dict[str, Any], selected, schema: str) -> dict[str, Any]:
        _require(op.get("status") in TERMINAL, "job-not-terminal")
        error = op.get("error")
        code = _label(error.get("code")) if isinstance(error, dict) else None
        return {
            "outcome": op["status"], "error_code": code,
            "started_utc": _time(op.get("started")), "finished_utc": _time(op.get("finished")),
            "observed": self._facts(op, infer_revision=False, schema=schema), "artifacts": [item for _, item in selected],
        }

    def _receipt(self, directory, identity, frames, operation) -> dict[str, Any]:
        _require(frames and frames[-1]["payload"]["event"] == "terminal", "job-not-terminal")
        raw = self.r.pack_egg(
            "session", identity["rappid"], frames[-1]["utc"],
            payload={"runtime": RUNTIME, "transcript": frames},
        )
        _require(len(raw) <= MAX_RECEIPT_BYTES and self.r.verify_egg(raw)[0], "exhaust-invalid-receipt")
        output = self._output_dir(operation, create=True)
        path = output / "receipt.egg"
        _publish(path, raw)
        _require(_private_read(path) == raw, "exhaust-invalid-receipt")
        return {
            "receipt_path": str(path),
            "frame_address": _address("rapp/1:wave", frames[-1]["frame_hash"]),
            "verification": "structural-only",
        }

    @_guard
    def terminal(self, op: dict[str, Any]) -> dict[str, Any]:
        operation = self._operation(op)
        selected = self._selection(op)
        with self._job(operation["job_id"]) as (directory, identity):
            frames = self._load(directory, identity)
            _require(frames and frames[0]["payload"]["detail"]["operation"] == operation, "exhaust-operation-conflict")
            completion = self._completion(op, selected, frames[0]["payload"]["schema"])
            if completion["observed"]["capability_revision"] is None:
                completion["observed"]["capability_revision"] = frames[0]["payload"]["detail"]["observed"]["capability_revision"]
            commitment = self.canonical.digest(completion)
            if frames[-1]["payload"]["event"] == "terminal":
                _require(frames[-1]["payload"]["detail"]["completion_sha256"] == commitment, "exhaust-terminal-conflict")
                return self._receipt(directory, identity, frames, operation)
            artifacts = [self._artifact(path, item)[0] for path, item in selected]
            if op["status"] == "succeeded":
                _require(all(item["verified"] for item in artifacts), "output-unverified")
            batches = [artifacts[index:index + 16] for index in range(0, len(artifacts), 16)]
            published = [frame for frame in frames if frame["payload"]["event"] == "artifacts-published"]
            _require(len(published) <= len(batches), "exhaust-terminal-conflict")
            for index, batch in enumerate(batches):
                detail = {"completion_sha256": commitment, "artifacts": batch}
                if index < len(published):
                    _require(published[index]["payload"]["detail"] == detail, "exhaust-terminal-conflict")
                else:
                    self._append(directory, identity, frames, "artifacts-published", detail)
            terminal = {
                key: value for key, value in completion.items() if key != "artifacts"
            }
            terminal.update(
                completion_sha256=commitment, output_count=len(artifacts),
                artifacts_refs=[
                    _address("rapp/1:particle", frame["payload_hash"])
                    for frame in frames if frame["payload"]["event"] == "artifacts-published"
                ],
            )
            self._append(directory, identity, frames, "terminal", terminal)
            return self._receipt(directory, identity, frames, operation)

    def _closure(self, root: Path) -> tuple[str, dict[str, bytes]]:
        root = P._absolute(root)
        lock = P.read_regular(root / "SCOTTY_CAPABILITY_LOCK.json")
        manifest = self.canonical.decode(lock)
        _require(
            isinstance(manifest, dict) and set(manifest) == {"schema", "grail_commit", "files"}
            and manifest["schema"] == "scotty-capability-files/1"
            and manifest["grail_commit"] == P.GRAIL["commit"]
            and isinstance(manifest["files"], list) and 1 <= len(manifest["files"]) <= 512,
            "capability-unverified",
        )
        files, total = {}, 0
        for item in manifest["files"]:
            _require(isinstance(item, dict) and set(item) == {"path", "bytes", "sha256"}, "capability-unverified")
            name = self.canonical.path(item["path"])
            _require(name not in files and not self._private_name(name) and name != "brainstem.py", "capability-private-path")
            _require(_integer(item["bytes"]) is not None and item["bytes"] <= MAX_SUPPORT_FILE_BYTES and _digest(item["sha256"]), "capability-unverified")
            total += item["bytes"]
            _require(total <= MAX_SUPPORT_BYTES, "capability-size-exceeded")
            raw, info = P._read_snapshot(root / name, limit=MAX_SUPPORT_FILE_BYTES)
            _require(len(raw) == item["bytes"] and P.sha256(raw) == item["sha256"], "capability-changed")
            _require(not info["mode"] & 0o022, "capability-unsafe-file")
            _require(not _TOKEN.search(raw), "capability-secret-content")
            files[name] = raw
        _require(
            {"agents/scotty_agent.py", "scotty_revision_agent.py", "dock_exhaust.py", "dock_portability.py",
             "deploy/local/rapp1/rapp.py", "deploy/local/rapp1/SPEC.md"} <= files.keys(),
            "capability-incomplete",
        )
        _require(
            P.sha256(files["deploy/local/rapp1/rapp.py"]) == P.REFERENCE_SHA256
            and P.sha256(files["deploy/local/rapp1/SPEC.md"]) == P.SPEC_SHA256,
            "capability-reference-pin",
        )
        files["SCOTTY_CAPABILITY_LOCK.json"] = lock
        self.canonical.paths(list(files))
        revision = P.sha256(lock)
        entry = files["scotty_revision_agent.py"]
        return revision, {
            "agent.py": entry,
            "scotty_revision.json": self._encode({
                "schema": "scotty-agent-revision/1", "loader_contract": "scotty-revision-loader/1",
                "entrypoint_sha256": P.sha256(entry), "support_sha256": revision,
            }),
            **{f"scotty_support_{revision}/{name}": raw for name, raw in files.items()},
        }

    @_guard
    def bundle(self, op: dict[str, Any], capability_root: str | Path) -> dict[str, Any]:
        """Capture reviewed source and selected outputs; never import carried code."""
        operation = self._operation(op)
        selected = self._selection(op)
        _require(sum(item["bytes"] for _, item in selected) <= MAX_BUNDLE_BYTES, "bundle-size-exceeded")
        receipt = self.terminal(op)
        revision, files = self._closure(Path(capability_root))
        with self._job(operation["job_id"]) as (directory, identity):
            frames = self._load(directory, identity)
            recorded = [
                item for frame in frames if frame["payload"]["event"] == "artifacts-published"
                for item in frame["payload"]["detail"]["artifacts"]
            ]
            expected_revision = frames[0]["payload"]["detail"]["observed"]["capability_revision"]
            _require(expected_revision is None or expected_revision == revision, "capability-revision-mismatch")
            _require(len(recorded) == len(selected), "exhaust-terminal-conflict")
            capsule_artifacts = []
            for (path, item), expected in zip(selected, recorded):
                actual, raw = self._artifact(path, item, carry=True)
                _require(actual == expected, "artifact-changed")
                name = f"state/outputs/{item['index']:02d}-{item['name']}"
                self.canonical.path(name)
                files[name] = raw
                capsule_artifacts.append({**actual, "path": name})
            receipt_raw = _private_read(Path(receipt["receipt_path"]))
            receipt_manifest, _ = self.r.read_egg(receipt_raw)
            _require(
                self.r.verify_egg(receipt_raw)[0]
                and receipt_manifest["payload"] == {"runtime": RUNTIME, "transcript": frames},
                "exhaust-invalid-receipt",
            )
            files["state/receipt.egg"] = receipt_raw
            files["state/exhaust/rappid.json"] = _private_read(self.root / "rappid.json")
            files["state/exhaust/rapp-frame-index.json"] = self._encode(self._index(frames))
            for frame in frames:
                files[f"state/exhaust/frames/{frame['seq']:08d}.json"] = self._encode(frame)
            with _process_lock(str(self.home)), _file_lock(self.home / ".job-exhaust.lock", create=False):
                capsule_identity = self.root / "capsule-rappid.json"
                if not os.path.lexists(capsule_identity):
                    _publish(capsule_identity, self._encode(self._identity("scotty-capsule")))
                capsule = self._read_identity(capsule_identity, "scotty-capsule")
                files["rappid.json"] = _private_read(capsule_identity)
            complete = bool(capsule_artifacts)
            payload = {
                "schema": "rapp-dock-job-capsule/1", "job_id": operation["job_id"],
                "application": operation["application"], "capability_revision": revision,
                "receipt": {
                    "path": "state/receipt.egg",
                    "address": _address("rapp/1:egg-manifest", self.r.egg_address(receipt_manifest)),
                },
                "artifacts": capsule_artifacts, "data_complete": complete,
                "scope": "selected-job-outputs" if complete else "receipt-only",
                "excluded": ["credentials", "private-inputs", "docker-images", "app-databases", "live-session"],
                "auto_execute": False, "verification": "structural-only",
            }
            self.canonical.paths(["manifest.json", *files])
            raw = self.r.pack_egg("rapplication", capsule["rappid"], frames[-1]["utc"], files=files, payload=payload)
            _require(self.r.verify_egg(raw)[0], "exhaust-invalid-bundle")
            manifest, carried = self.r.read_egg(raw)
            _require(
                all(P.sha256(carried[item["path"]]) == item["sha256"] for item in capsule_artifacts),
                "artifact-changed",
            )
            output = self._output_dir(operation) / "capsule.egg"
            _publish(output, raw)
            return {
                "path": str(output), "bytes": len(raw), "sha256": P.sha256(raw),
                "egg_address": _address("rapp/1:egg-manifest", self.r.egg_address(manifest)),
                "data_complete": complete,
            }
