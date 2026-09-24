"""Bounded, read-only projections over verified Dock receipts; never job control.

History lists artifact publication time (terminal time for jobs without outputs).
Lineage matches recorded input bytes to earlier verified outputs, not filenames,
prompts, native-ID resemblance, or conversations. Equal-content producers remain
ambiguous. Querying never initializes a reporter, repairs a head, retries a
receipt, opens artifact content, or starts an application.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import heapq
import json
import os
import re
import stat
import sys
import threading
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, time, timedelta, timezone as utc_timezone
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import dock_exhaust as E
import dock_portability as P

SCHEMA = "rapp-dock-history/1"
MAX_RESULT_BYTES = 6144
MAX_JOBS = 1000
MAX_SCAN_ENTRIES = 10000
MAX_SCAN_BYTES = 64 * 1024 * 1024
MAX_OPERATIONS_BYTES = 256 * 1024
MAX_PAGE_ROWS = 20
MAX_LINEAGE_ROWS = 2000
MAX_CACHE_ENTRIES = 1024
MAX_CACHE_BYTES = 16 * 1024 * 1024
_REGISTRY_NAME = "_rapp_dock_history_projection_registry"
_CACHE_PROFILE = "verified-receipt-projection/2"
_APPS = frozenset({"intelligence", "scrapling", "presenton", "open-seo", "dify", "openshorts", "dock", "all"})
_TERMINAL = frozenset(E.TERMINAL)
_ACTIVE = frozenset({"queued", "running"})
_OP_FILE = re.compile(r"([a-z0-9]+(?:-[a-z0-9]+)*)\.json")
_INSTANCE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_VIEW = ContextVar("dock_history_read_view", default=None)


class HistoryError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        self.message = code
        super().__init__(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise HistoryError(code)


def _bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _registry():
    candidate = ModuleType(_REGISTRY_NAME)
    candidate.lock = threading.RLock()
    candidate.cache = OrderedDict()
    candidate.cache_bytes = 0
    candidate.heads = {}
    candidate.files = OrderedDict()
    candidate.identities = {}
    candidate.operations = OrderedDict()
    registry = sys.modules.setdefault(_REGISTRY_NAME, candidate)
    with registry.lock:
        for name in ("files", "operations", "identities"):
            if not hasattr(registry, name):
                setattr(registry, name, OrderedDict() if name != "identities" else {})
    return registry


def _clock() -> str:
    return datetime.now(utc_timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _instance(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 64 and _INSTANCE.fullmatch(value) is not None


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        info.st_mode, info.st_uid, info.st_nlink,
    )


@contextmanager
def _read_view(home: Path):
    """Hold only shallow no-follow directory descriptors for one read snapshot."""
    with P._directory(home) as root:
        cache = {(): root}
        token = _VIEW.set((home, cache, 2))
        try:
            yield
        finally:
            _VIEW.reset(token)
            for parts, descriptor in cache.items():
                if parts:
                    os.close(descriptor)


@contextmanager
def _job_view():
    current = _VIEW.get()
    if current is None:
        yield
        return
    home, cache, _ = current
    original = set(cache)
    token = _VIEW.set((home, cache, 4))
    try:
        yield
    finally:
        _VIEW.reset(token)
        for key in list(cache):
            if key not in original and len(key) > 2:
                os.close(cache.pop(key))


@contextmanager
def _directory(path: Path):
    view = _VIEW.get()
    if view is None or not path.is_relative_to(view[0]):
        with P._directory(path) as descriptor:
            yield descriptor
        return
    home, cache, depth = view
    parts = path.relative_to(home).parts
    _require(all(part not in {"", ".", ".."} for part in parts), "history-unsafe-directory")
    prefix = max((key for key in cache if parts[:len(key)] == key), key=len)
    descriptor = os.dup(cache[prefix])
    try:
        for position, part in enumerate(parts[len(prefix):], len(prefix) + 1):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            key = parts[:position]
            if position <= depth and key not in cache and len(cache) < 32:
                cache[key] = os.dup(descriptor)
        yield descriptor
    finally:
        os.close(descriptor)


def _private_directory(path: Path):
    with _directory(path) as descriptor:
        info = os.fstat(descriptor)
        _require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700, "history-unsafe-directory")


def _stat_regular(path: Path, limit: int) -> os.stat_result:
    with _directory(path.parent) as parent:
        info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
    _require(
        stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_size <= limit,
        "history-unsafe-file",
    )
    return info


@contextmanager
def _open_regular(path: Path, limit: int):
    with _directory(path.parent) as parent:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(descriptor)
        _require(
            stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and before.st_uid == os.geteuid() and stat.S_IMODE(before.st_mode) == 0o600
            and before.st_size <= limit,
            "history-unsafe-file",
        )
        yield descriptor, before
        _require(_signature(before) == _signature(os.fstat(descriptor)), "history-changing-state")
    finally:
        os.close(descriptor)


def _read_private(path: Path, limit: int, budget: list[int] | None = None) -> bytes:
    with _open_regular(path, limit) as (descriptor, before):
        if budget is not None:
            _require(before.st_size <= budget[0], "history-byte-limit")
            budget[0] -= before.st_size
        chunks, length = [], 0
        while True:
            chunk = os.read(descriptor, min(65536, limit + 1 - length))
            if not chunk:
                break
            chunks.append(chunk)
            length += len(chunk)
            _require(length <= limit, "history-read-limit")
        _require(length == before.st_size, "history-changing-state")
        return b"".join(chunks)


class JobHistory:
    """A disposable in-memory read model; home and retained evidence stay untouched."""

    def __init__(self, home: str | Path) -> None:
        try:
            self.home = P._absolute(Path(home).expanduser())
            self.exhaust = E.JobExhaust(self.home)
        except (OSError, ValueError, TypeError):
            raise HistoryError("history-unavailable") from None
        self.canonical = self.exhaust.canonical
        self.r = self.canonical.r

    def _json(self, raw: bytes) -> dict[str, Any]:
        value = self.canonical.decode(raw)
        _require(isinstance(value, dict), "history-invalid-record")
        return value

    def _names(self, directory: Path, pattern: re.Pattern | None, cap: int) -> tuple[list[str], int, bool, str]:
        try:
            with _directory(directory) as descriptor:
                info = os.fstat(descriptor)
                _require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700, "history-unsafe-directory")
                selected, seen = [], 0
                with os.scandir(descriptor) as entries:
                    for entry in entries:
                        seen += 1
                        if seen > MAX_SCAN_ENTRIES:
                            return sorted(selected, reverse=True), seen - 1, True, "scan-entry-limit"
                        if pattern is not None and pattern.fullmatch(entry.name) is None:
                            continue
                        if pattern is None and not _instance(entry.name):
                            continue
                        if len(selected) < cap:
                            heapq.heappush(selected, entry.name)
                        elif entry.name > selected[0]:
                            heapq.heapreplace(selected, entry.name)
                return sorted(selected, reverse=True), seen, seen > cap, "job-limit" if seen > cap else ""
        except (P.PortabilityError, OSError, HistoryError):
            return [], 0, True, "directory-unavailable"

    def _identity(self) -> tuple[str, str]:
        anchor = self._json(_read_private(self.home / ".job-exhaust.json", 4096))
        raw = _read_private(self.home / "exhaust/rappid.json", 4096)
        value = self._json(raw)
        _require(anchor == {
            "schema": "rapp-dock-job-reporter-anchor/1", "sha256": P.sha256(raw),
        }, "history-invalid-identity")
        _require(
            set(value) == {"schema", "rappid", "role", "identity_origin", "created_utc", "key_material", "authority_adoption"}
            and value["schema"] == "rapp/1" and self.r.rappid_valid(value["rappid"])
            and self.r.rappid_parts(value["rappid"])["slug"] == "job-reporter"
            and value["role"] == "dock-job-reporter"
            and value["identity_origin"] == "local-keyless-mint-once"
            and self.r.utc_valid(value["created_utc"]) and value["key_material"] == "none-created"
            and value["authority_adoption"] == "not-established" and raw == self.canonical.encode(value),
            "history-invalid-identity",
        )
        writer = E._registry()
        with writer.lock:
            accepted = writer.identities.get(str(self.home / "exhaust/rappid.json"))
        _require(accepted is None or accepted == P.sha256(raw), "history-observed-identity-change")
        registry = _registry()
        with registry.lock:
            previous = registry.identities.setdefault(str(self.home), P.sha256(raw))
        _require(previous == P.sha256(raw), "history-observed-identity-change")
        return value["rappid"], P.sha256(raw)

    @staticmethod
    def _operation_record(value: dict[str, Any]) -> dict[str, Any]:
        """Only operational coverage, never private arguments, result text or paths."""
        op_id = value.get("id")
        _require(_instance(op_id), "history-invalid-record")
        _require(
            value.get("kind") in {"job", "run", "lifecycle"}
            and value.get("application") in _APPS and value.get("status") in _TERMINAL | _ACTIVE,
            "history-invalid-record",
        )
        return {
            "id": op_id, "kind": value.get("kind"),
            "application": value.get("application"), "status": value.get("status"),
        }

    def _summary(self, manifest: dict[str, Any], receipt_sha: str) -> dict[str, Any]:
        frames = manifest["payload"]["transcript"]
        operation = frames[0]["payload"]["detail"]["operation"]
        terminal = frames[-1]["payload"]["detail"]
        _require(operation["application"] in _APPS, "history-invalid-application")
        observations = [frame["payload"]["detail"]["observed"] for frame in frames if "observed" in frame["payload"]["detail"]]
        final = terminal["observed"]
        versions, conflicts = {}, []
        for key in ("capability_revision", "adapter_sha256", "compose_sha256", "source_commit", "execution_mode"):
            values = list(dict.fromkeys(item.get(key) for item in observations if item.get(key) is not None))
            versions[key] = values[0] if len(values) == 1 else None
            if len(values) > 1:
                conflicts.append(key)
        versions["images"] = next((copy.deepcopy(item["images"]) for item in reversed(observations) if item.get("images")), [])
        inputs = []
        seen = set()
        for frame in frames:
            observed = frame["payload"]["detail"].get("observed", {})
            for item in observed.get("inputs", []):
                identity = (item["name"], item["sha256"], item["bytes"])
                if identity not in seen:
                    seen.add(identity)
                    inputs.append({**copy.deepcopy(item), "recorded_utc": frame["utc"]})
        _require(len(inputs) <= E.MAX_ARTIFACTS, "history-input-limit")
        artifacts = []
        for frame in frames:
            if frame["payload"]["event"] == "artifacts-published":
                artifacts.extend({**copy.deepcopy(item), "published_utc": frame["utc"]} for item in frame["payload"]["detail"]["artifacts"])
        return {
            "operation_id": operation["job_id"], "application": operation["application"],
            "job": operation["name"], "kind": operation["kind"], "outcome": terminal["outcome"],
            "error_code": terminal["error_code"], "created_utc": operation["created_utc"],
            "started_utc": terminal["started_utc"], "finished_utc": terminal["finished_utc"] or frames[-1]["utc"],
            "terminal_utc": frames[-1]["utc"], "artifacts": artifacts, "inputs": inputs,
            "versions": versions, "provider": copy.deepcopy(final["provider"]),
            "version_conflicts": conflicts,
            "profile": frames[0]["payload"]["schema"],
            "receipt": {
                "address": E._address("rapp/1:egg-manifest", self.r.egg_address(manifest)),
                "sha256": receipt_sha,
                "frame_address": E._address("rapp/1:wave", frames[-1]["frame_hash"]),
                "verification": "structural-only",
            },
            "_head": {"seq": frames[-1]["seq"], "frame_hash": frames[-1]["frame_hash"]},
            "_frame_hashes": [frame["frame_hash"] for frame in frames],
            "_frame_bytes_sha256": [P.sha256(self.canonical.encode(frame)) for frame in frames],
            "_index": self.exhaust._index(frames),
            "_index_sha256": P.sha256(self.canonical.encode(self.exhaust._index(frames))),
        }

    def _verified_receipt(self, path: Path, op_id: str, reporter: str, budget: list[int]):
        info = _stat_regular(path, E.MAX_RECEIPT_BYTES)
        _require(info.st_size <= budget[0], "history-byte-limit")
        budget[0] -= info.st_size
        signature = _signature(info)
        key = (_CACHE_PROFILE, str(self.home), str(path), reporter, signature)
        registry = _registry()
        with registry.lock:
            cached = registry.cache.get(key)
            if cached is not None:
                registry.cache.move_to_end(key)
                return copy.deepcopy(cached[0]), signature
        with _open_regular(path, E.MAX_RECEIPT_BYTES) as (descriptor, opened):
            _require(signature == _signature(opened), "history-changing-state")
            raw = os.read(descriptor, info.st_size + 1)
            _require(len(raw) == info.st_size, "history-changing-state")
            manifest = self.exhaust.inspect_receipt(raw, operation_id=op_id, reporter=reporter)
            summary = self._summary(manifest, P.sha256(raw))
            cost = len(_bytes(summary))
            with registry.lock:
                previous = registry.cache.pop(key, None)
                if previous is not None:
                    registry.cache_bytes -= previous[1]
                registry.cache[key] = (copy.deepcopy(summary), cost)
                registry.cache_bytes += cost
                while len(registry.cache) > MAX_CACHE_ENTRIES or registry.cache_bytes > MAX_CACHE_BYTES:
                    _, (_, removed) = registry.cache.popitem(last=False)
                    registry.cache_bytes -= removed
            return summary, signature

    def _verify_head(self, summary: dict[str, Any], reporter: str, budget: list[int]) -> None:
        op_id = summary["operation_id"]
        directory = self.home / "exhaust/streams" / op_id
        _private_directory(directory)
        index_path = directory / "rapp-frame-index.json"
        index_info = _stat_regular(index_path, 16384)
        _require(index_info.st_size <= budget[0], "history-byte-limit")
        budget[0] -= index_info.st_size
        index = summary["_index"]
        snapshots = {}
        frame_directory = directory / "frames"
        _private_directory(frame_directory)
        with _directory(frame_directory) as descriptor, os.scandir(descriptor) as entries:
            for entry in entries:
                if re.fullmatch(r"\.exhaust-[0-9a-f]{32}\.pending", entry.name):
                    continue
                _require(len(snapshots) < E.MAX_FRAMES, "history-frame-limit")
                info = entry.stat(follow_symlinks=False)
                _require(
                    stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_size <= E.MAX_FRAME_BYTES,
                    "history-unsafe-file",
                )
                snapshots[entry.name] = _signature(info)
        _require(set(snapshots) == {Path(member).name for member in index["frames"]}, "history-fork-or-gap")
        frame_bytes = sum(item[2] for item in snapshots.values())
        _require(frame_bytes <= budget[0], "history-byte-limit")
        budget[0] -= frame_bytes
        registry = _registry()
        key = (str(self.home), reporter, op_id)
        with registry.lock:
            cached_files = registry.files.get(key)
        stamp = (summary["receipt"]["sha256"], _signature(index_info), sorted(snapshots.items()))
        if cached_files != stamp:
            raw = _read_private(index_path, 16384)
            _require(P.sha256(raw) == summary["_index_sha256"], "history-receipt-head-mismatch")
            for position, member in enumerate(index["frames"]):
                raw = _read_private(directory / member, E.MAX_FRAME_BYTES)
                _require(P.sha256(raw) == summary["_frame_bytes_sha256"][position], "history-receipt-frame-mismatch")
            with registry.lock:
                registry.files[key] = stamp
                registry.files.move_to_end(key)
                while len(registry.files) > MAX_CACHE_ENTRIES:
                    registry.files.popitem(last=False)
        writer = E._registry()
        with writer.lock:
            accepted = writer.heads.get(str(directory))
        _require(accepted is None or (
            summary["_head"]["seq"] >= accepted[0] and summary["_frame_hashes"][accepted[0]] == accepted[1]
        ), "history-observed-rollback")
        with registry.lock:
            old = registry.heads.get(key)
            _require(old is None or (
                summary["_head"]["seq"] >= old[0] and summary["_frame_hashes"][old[0]] == old[1]
            ), "history-observed-rollback")
            registry.heads[key] = (summary["_head"]["seq"], summary["_head"]["frame_hash"])

    def _verified_local_receipt(self, path, op_id, reporter, budget):
        with _job_view():
            summary, signature = self._verified_receipt(path, op_id, reporter, budget)
            self._verify_head(summary, reporter, budget)
            return summary, signature

    def _coverage(self) -> dict[str, Any]:
        return {
            "discovered": 0, "verified": 0, "pending": 0, "active": 0,
            "invalid": 0, "unexamined": 0, "operations_seen": 0,
            "scope": "all-scanned-local-job-receipts", "complete": True, "reasons": [],
        }

    def _inventory(self, priority: str | None = None):
        try:
            with _read_view(self.home):
                return self._inventory_read(priority)
        except (OSError, P.PortabilityError):
            coverage = self._coverage()
            if not os.path.lexists(self.home):
                return {}, {}, coverage, P.sha256(b"absent"), {}
            coverage.update(invalid=1, complete=False, reasons=["home-unavailable"])
            return {}, {}, coverage, P.sha256(b"unavailable"), {}

    def _coverage_record(self, path: Path, budget: list[int]) -> dict[str, Any]:
        info = _stat_regular(path, MAX_OPERATIONS_BYTES)
        _require(info.st_size <= budget[0], "history-byte-limit")
        budget[0] -= info.st_size
        key = (str(path), _signature(info))
        registry = _registry()
        with registry.lock:
            cached = registry.operations.get(key)
            if cached is not None:
                registry.operations.move_to_end(key)
                return dict(cached)
        with _open_regular(path, MAX_OPERATIONS_BYTES) as (descriptor, opened):
            _require(_signature(info) == _signature(opened), "history-changing-state")
            raw = os.read(descriptor, info.st_size + 1)
            _require(len(raw) == info.st_size, "history-changing-state")
            parsed = json.loads(raw, object_pairs_hook=self._unique)
            _require(isinstance(parsed, dict), "history-invalid-record")
            record = self._operation_record(parsed)
            with registry.lock:
                registry.operations[key] = record
                while len(registry.operations) > MAX_CACHE_ENTRIES:
                    registry.operations.popitem(last=False)
            return dict(record)

    def _inventory_read(self, priority: str | None = None):
        coverage = self._coverage()
        try:
            with _directory(self.home) as directory:
                info = os.fstat(directory)
                _require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700, "history-unsafe-home")
        except (OSError, P.PortabilityError, HistoryError):
            if not os.path.lexists(self.home):
                return {}, {}, coverage, P.sha256(b"absent"), {}
            coverage.update(invalid=1, complete=False, reasons=["home-unavailable"])
            return {}, {}, coverage, P.sha256(b"unavailable"), {}
        stream_root = self.home / "exhaust/streams"
        if not os.path.lexists(stream_root):
            stream_names, stream_seen, stream_partial, stream_reason = [], 0, False, ""
        else:
            stream_names, stream_seen, stream_partial, stream_reason = self._names(stream_root, None, MAX_JOBS)
        ops_root = self.home / "ops"
        if not os.path.lexists(ops_root):
            op_names, op_seen, op_partial, op_reason = [], 0, False, ""
        else:
            op_names, op_seen, op_partial, op_reason = self._names(ops_root, _OP_FILE, MAX_JOBS)
        coverage["operations_seen"] = op_seen
        candidates = set(stream_names)
        records, statuses, stamps, invalid_ops = {}, {}, [], set()
        budget = [MAX_SCAN_BYTES]
        for name in op_names:
            op_id = name[:-5]
            try:
                record = self._coverage_record(ops_root / name, budget)
                _require(record.get("id") == op_id and _instance(op_id), "history-invalid-record")
                stamps.append([name, record])
                if record.get("kind") not in {"job", "run"}:
                    continue
                _require(record.get("application") in _APPS, "history-invalid-record")
                status = record.get("status")
                _require(status in _TERMINAL | _ACTIVE, "history-invalid-record")
                records[op_id] = record
                statuses[op_id] = status
                candidates.add(op_id)
            except HistoryError as error:
                invalid_ops.add(op_id)
                candidates.add(op_id)
                stamps.append([name, error.code])
                if error.code == "history-byte-limit":
                    coverage["reasons"].append("operation-byte-limit")
            except (OSError, ValueError, TypeError, P.PortabilityError, RecursionError):
                invalid_ops.add(op_id)
                candidates.add(op_id)
                stamps.append([name, "invalid"])
        if priority is not None and os.path.lexists(stream_root / priority):
            candidates.add(priority)
        ordered = sorted(candidates, key=lambda item: (item == priority, item), reverse=True)
        coverage["discovered"] = len(ordered)
        if len(ordered) > MAX_JOBS:
            coverage["unexamined"] += len(ordered) - MAX_JOBS
            ordered = ordered[:MAX_JOBS]
        if stream_partial or op_partial:
            coverage["reasons"].extend(reason for reason in (stream_reason, op_reason) if reason)
            coverage["unexamined"] += max(0, stream_seen - len(stream_names)) + max(0, op_seen - len(op_names))
        if not ordered:
            coverage["complete"] = not coverage["reasons"]
            return {}, statuses, coverage, P.sha256(_bytes(stamps)), records
        try:
            reporter, anchor = self._identity()
        except (OSError, ValueError, TypeError, P.PortabilityError):
            coverage.update(invalid=len(ordered), complete=False)
            coverage["reasons"].append("reporter-unavailable")
            return {}, statuses, coverage, P.sha256(_bytes(stamps)), records
        summaries = {}
        stamps.append(["reporter", anchor])
        for op_id in ordered:
            record = records.get(op_id)
            application = record.get("application") if record else None
            if application is None:
                try:
                    genesis = self._json(_read_private(stream_root / op_id / "frames/00000000.json", E.MAX_FRAME_BYTES, budget))
                    application = genesis["payload"]["detail"]["operation"]["application"]
                    _require(application in _APPS, "history-invalid-record")
                except HistoryError as error:
                    if error.code == "history-byte-limit":
                        coverage["unexamined"] += 1
                        coverage["reasons"].append("genesis-byte-limit")
                    else:
                        coverage["invalid"] += 1
                    stamps.append([op_id, error.code])
                    continue
                except (OSError, ValueError, TypeError, KeyError, P.PortabilityError):
                    coverage["invalid"] += 1
                    stamps.append([op_id, "invalid-genesis"])
                    continue
            path = self.home / "outputs" / application / op_id / "receipt.egg"
            if not os.path.lexists(path):
                if statuses.get(op_id) in _ACTIVE:
                    coverage["active"] += 1
                elif op_id in invalid_ops:
                    coverage["invalid"] += 1
                else:
                    coverage["pending"] += 1
                stamps.append([op_id, "receipt-missing"])
                continue
            try:
                summary, signature = self._verified_local_receipt(path, op_id, reporter, budget)
                _require(summary["application"] == application, "history-receipt-location-mismatch")
                summaries[op_id] = summary
                coverage["verified"] += 1
                stamps.append([op_id, summary["receipt"]["sha256"], list(signature), summary["_head"]])
                if record and statuses[op_id] in _TERMINAL and statuses[op_id] != summary["outcome"]:
                    coverage["reasons"].append("operation-receipt-disagreement")
            except HistoryError as error:
                if error.code == "history-byte-limit":
                    coverage["unexamined"] += 1
                    coverage["reasons"].append("receipt-byte-limit")
                else:
                    coverage["invalid"] += 1
                stamps.append([op_id, error.code])
            except (OSError, ValueError, TypeError, KeyError, P.PortabilityError):
                coverage["invalid"] += 1
                stamps.append([op_id, "invalid-receipt"])
        coverage["reasons"] = sorted(set(coverage["reasons"]))
        coverage["complete"] = not (
            coverage["pending"] or coverage["active"] or coverage["invalid"]
            or coverage["unexamined"] or coverage["reasons"]
        )
        return summaries, statuses, coverage, P.sha256(_bytes(sorted(stamps, key=lambda value: value[0]))), records

    @staticmethod
    def _unique(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value, "history-invalid-record")
            value[key] = item
        return value

    def _query(self, view: str, *, timezone: str, day: str | None, application: str | None, operation_id: str | None, limit: int):
        _require(type(limit) is int and 1 <= limit <= MAX_PAGE_ROWS, "history-invalid-limit")
        _require(application is None or isinstance(application, str) and application in _APPS, "history-invalid-application")
        _require(operation_id is None or _instance(operation_id), "history-invalid-operation")
        _require(
            isinstance(timezone, str) and 1 <= len(timezone) <= 100
            and re.fullmatch(r"[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*", timezone) is not None
            and ".." not in timezone.split("/"),
            "history-invalid-timezone",
        )
        try:
            zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise HistoryError("history-invalid-timezone") from None
        if day is None:
            selected_day = datetime.now(zone).date()
        else:
            _require(isinstance(day, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is not None, "history-invalid-day")
            try:
                selected_day = date.fromisoformat(day)
            except ValueError:
                raise HistoryError("history-invalid-day") from None
        try:
            start = datetime.combine(selected_day, time.min, zone)
            end = datetime.combine(selected_day + timedelta(days=1), time.min, zone)
        except (ValueError, OverflowError):
            raise HistoryError("history-invalid-day") from None
        query = {
            "view": view, "timezone": timezone, "day": selected_day.isoformat(),
            "application": application, "operation_id": operation_id, "limit": limit,
        }
        bounds = {
            "start_utc": start.astimezone(utc_timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "end_utc": end.astimezone(utc_timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        return query, bounds

    def _cursor(self, token: Any, fingerprint: str, query: dict[str, Any]) -> tuple[int, str]:
        if token is None:
            return 0, _clock()
        _require(isinstance(token, str) and 1 <= len(token) <= 2048 and re.fullmatch(r"[A-Za-z0-9_-]+", token) is not None, "history-invalid-cursor")
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            value = self._json(raw)
        except (ValueError, TypeError):
            raise HistoryError("history-invalid-cursor") from None
        _require(
            set(value) == {"schema", "snapshot", "query", "offset", "utc"}
            and value["schema"] == "rapp-dock-history-cursor/1"
            and type(value["offset"]) is int and value["offset"] >= 0
            and self.r.utc_valid(value["utc"]),
            "history-invalid-cursor",
        )
        _require(value["snapshot"] == fingerprint and value["query"] == P.sha256(_bytes(query)), "history-stale-cursor")
        return value["offset"], value["utc"]

    def _token(self, fingerprint: str, query: dict[str, Any], offset: int, snapshot_utc: str) -> str:
        return base64.urlsafe_b64encode(_bytes({
            "schema": "rapp-dock-history-cursor/1", "snapshot": fingerprint,
            "query": P.sha256(_bytes(query)), "offset": offset, "utc": snapshot_utc,
        })).decode().rstrip("=")

    def _page(self, result, rows, fingerprint, query, cursor):
        offset, snapshot_utc = self._cursor(cursor, fingerprint, query)
        _require(offset <= len(rows), "history-invalid-cursor")
        result.update(
            schema=SCHEMA, snapshot_utc=snapshot_utc, items=[],
            matched_rows=len(rows), returned_rows=0, next_cursor=None,
            truncated=False, verification="structural-only", read_only=True,
        )
        maximum = min(len(rows), offset + query["limit"])
        for end in range(offset + 1, maximum + 1):
            candidate = {
                **result, "items": rows[offset:end], "returned_rows": end - offset,
                "next_cursor": self._token(fingerprint, query, end, snapshot_utc) if end < len(rows) else None,
                "truncated": end < len(rows) or not result["coverage"]["complete"],
            }
            if len(_bytes(candidate)) > MAX_RESULT_BYTES:
                break
            result = candidate
        if not result["items"]:
            _require(offset == len(rows), "history-row-size-exceeded")
            result["truncated"] = not result["coverage"]["complete"]
        _require(len(_bytes(result)) <= MAX_RESULT_BYTES, "history-result-limit")
        return result

    def _row(self, summary, artifact=None):
        return {
            "operation_id": summary["operation_id"], "application": summary["application"],
            "job": summary["job"], "outcome": summary["outcome"],
            "execution_mode": summary["versions"]["execution_mode"],
            "published_utc": artifact["published_utc"] if artifact else None,
            "finished_utc": summary["finished_utc"],
            "artifact": {
                key: copy.deepcopy(artifact[key])
                for key in ("index", "name", "media_type", "bytes", "sha256", "address")
            } if artifact else None,
            "verified_at_production": artifact["verified"] if artifact else None,
            "file_present_now": None, "bytes_checked_at": None,
            "receipt_address": copy.deepcopy(summary["receipt"]["address"]),
        }

    def today(
        self, *, timezone: str = "UTC", day: str | None = None,
        application: str | None = None, limit: int = 10, cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return <=6 KiB of typed rows; a changing corpus explicitly stales cursors."""
        query, bounds = self._query("history", timezone=timezone, day=day, application=application, operation_id=None, limit=limit)
        summaries, _, coverage, fingerprint, _ = self._inventory()
        rows, counts = [], {key: 0 for key in sorted(_TERMINAL)}
        for summary in summaries.values():
            if application is not None and summary["application"] != application:
                continue
            included = False
            for item in summary["artifacts"]:
                if bounds["start_utc"] <= item["published_utc"] < bounds["end_utc"]:
                    rows.append(self._row(summary, item))
                    included = True
            if not summary["artifacts"] and bounds["start_utc"] <= summary["terminal_utc"] < bounds["end_utc"]:
                rows.append(self._row(summary))
                included = True
            if included:
                counts[summary["outcome"]] += 1
        rows.sort(key=lambda row: (row["published_utc"] or row["finished_utc"], row["operation_id"], row["artifact"]["index"] if row["artifact"] else -1))
        return self._page({
            "view": "history", "day": query["day"], "timezone": timezone, "window": bounds,
            "application": application, "coverage": coverage, "outcomes": counts,
            "outcomes_basis": "distinct-publishing-or-no-output-terminal-jobs",
            "time_basis": "artifact-publication-or-no-output-terminal",
            "limitations": ["unsigned-local-evidence", "current-artifact-bytes-not-read", "unverified-operations-not-results"],
        }, rows, fingerprint, query, cursor)

    history = today

    def lineage(
        self, operation_id: str, *, limit: int = 10, cursor: str | None = None,
    ) -> dict[str, Any]:
        """Page measured hash links and version facts, never inferred causal ancestry."""
        query, _ = self._query("lineage", timezone="UTC", day="1970-01-01", application=None, operation_id=operation_id, limit=limit)
        summaries, statuses, coverage, fingerprint, _ = self._inventory(priority=operation_id)
        target = summaries.get(operation_id)
        if target is None:
            status = "receipt-pending" if statuses.get(operation_id) in _TERMINAL else "active" if statuses.get(operation_id) in _ACTIVE else "unavailable"
            return self._page({
                "view": "lineage", "operation_id": operation_id, "status": status,
                "coverage": coverage, "job": None, "recorded_inputs": 0,
                "limitations": ["no-verified-producing-receipt", "no-work-replayed"],
            }, [], fingerprint, query, cursor)
        index = {}
        for summary in summaries.values():
            if summary["operation_id"] == operation_id:
                continue
            for item in summary["artifacts"]:
                index.setdefault((item["sha256"], item["bytes"]), []).append((summary, item))
        rows = []
        relation_limit = False
        for input_index, item in enumerate(target["inputs"]):
            producers = [
                pair for pair in index.get((item["sha256"], item["bytes"]), [])
                if pair[1]["published_utc"] <= item["recorded_utc"]
            ]
            producers.sort(key=lambda pair: (pair[1]["published_utc"], pair[0]["operation_id"], pair[1]["index"]))
            relation = "ambiguous-content-match" if len(producers) > 1 else "recorded-input-output-hash-match" if producers else "parent-not-found" if coverage["complete"] else "parent-unknown-incomplete-coverage"
            common = {
                "kind": "input", "input_index": input_index, "input": copy.deepcopy(item),
                "relation": relation, "producer_count": len(producers), "consumption": "recorded-input-commitment-not-semantic-proof",
                "producer_count_scope": "verified-scanned-corpus",
            }
            if producers:
                for summary, artifact in producers:
                    if len(rows) >= MAX_LINEAGE_ROWS:
                        relation_limit = True
                        break
                    rows.append({
                        **common, "producer": {
                            "operation_id": summary["operation_id"], "job": summary["job"],
                            "artifact_index": artifact["index"], "artifact_address": artifact["address"],
                            "receipt_address": summary["receipt"]["address"],
                            "terminal_address": summary["receipt"]["frame_address"],
                        },
                    })
            else:
                if len(rows) < MAX_LINEAGE_ROWS:
                    rows.append({**common, "producer": None})
                else:
                    relation_limit = True
        for item in target["artifacts"]:
            rows.append({"kind": "output", **self._row(target, item)})
        versions = target["versions"]
        for image in versions["images"]:
            rows.append({"kind": "image", **copy.deepcopy(image)})
        provider = target["provider"]
        job = {
            "application": target["application"], "job": target["job"], "outcome": target["outcome"],
            "error_code": target["error_code"], "created_utc": target["created_utc"],
            "started_utc": target["started_utc"], "finished_utc": target["finished_utc"],
            "profile": target["profile"], "receipt": target["receipt"],
            "versions": {key: value for key, value in versions.items() if key != "images"},
            "version_conflicts": target["version_conflicts"],
            "image_count": len(versions["images"]),
            "provider": {
                "runtime": provider["runtime"], "model": provider["model"],
                "model_evidence": "adapter-reported-not-independently-verified" if provider["model"] else "unknown",
                "calls": provider["calls"], "usage": provider["usage"],
                "attribution": provider.get("attribution", "unknown"), "request_id_count": len(provider["request_ids"]),
            },
        }
        for request_id in provider["request_ids"]:
            rows.append({"kind": "provider-request", "request_id": request_id})
        if relation_limit:
            coverage["complete"] = False
            coverage["reasons"] = sorted(set([*coverage["reasons"], "lineage-relation-limit"]))
        return self._page({
            "view": "lineage", "operation_id": operation_id, "status": "verified-receipt",
            "coverage": coverage, "job": job, "recorded_inputs": len(target["inputs"]),
            "parent_status": "recorded-inputs" if target["inputs"] else "parent-not-recorded",
            "limitations": [
                "unsigned-local-evidence", "current-artifact-bytes-not-read",
                "hash-match-not-unique-authorship", "raw-inputs-and-prompts-not-retained",
                "missing-version-facts-remain-unknown",
            ],
        }, rows, fingerprint, query, cursor)
