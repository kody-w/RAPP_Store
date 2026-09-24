"""Verify Dock's exact dependency/capability bytes; never install or run discovered code."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent
CURRENT_GRAIL_COMMIT = "c60521e2cacbcbfa585a118c1275093d7bb15b74"
CURRENT_KERNEL_SHA256 = (
    "35618683ebc3d1c2bfaff47f60182fd756f3a8de53c53dd907ec1099d631930a"
)
MAX_FILE_BYTES = 4 * 1024 * 1024


class DistributionRefused(ValueError):
    pass


def read_regular(path: Path, *, private: bool = False) -> bytes:
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise DistributionRefused(
            "safe no-follow file access is unavailable on this host"
        )
    path = Path(os.path.abspath(path))
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        file_fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
        try:
            before = os.fstat(file_fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > MAX_FILE_BYTES
                or (
                    private
                    and (
                        before.st_uid != os.geteuid()
                        or stat.S_IMODE(before.st_mode) != 0o600
                    )
                )
            ):
                raise DistributionRefused("unsafe or oversized selected file")
            with os.fdopen(file_fd, "rb", closefd=False) as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(file_fd)
            if len(data) > MAX_FILE_BYTES or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise DistributionRefused("selected file changed during verification")
            return data
        finally:
            os.close(file_fd)
    except OSError as error:
        raise DistributionRefused("selected file is missing or unsafe") from error
    finally:
        os.close(descriptor)


def load_json(path: Path, *, private: bool = False) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise DistributionRefused("duplicate JSON member")
            value[key] = item
        return value

    try:
        return json.loads(read_regular(path, private=private), object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise DistributionRefused("selected JSON is invalid") from error


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def relative_path(value: str) -> str:
    if not isinstance(value, str):
        raise DistributionRefused("file inventory path must be text")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise DistributionRefused("file inventory path is not a safe relative path")
    return value


def verify_files(root: Path, entries: list[dict[str, Any]]) -> None:
    if not isinstance(entries, list) or not 1 <= len(entries) <= 512:
        raise DistributionRefused("invalid bounded file inventory")
    seen = set()
    total_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise DistributionRefused("invalid file commitment")
        name = relative_path(entry["path"])
        if name in seen:
            raise DistributionRefused("duplicate file commitment")
        seen.add(name)
        data = read_regular(root / name)
        total_bytes += len(data)
        if total_bytes > 32 * 1024 * 1024:
            raise DistributionRefused(
                "selected file inventory exceeds its total byte bound"
            )
        if (
            len(data) != entry["bytes"]
            or hashlib.sha256(data).hexdigest() != entry["sha256"]
        ):
            raise DistributionRefused(
                "selected immutable bytes differ from the reviewed pin"
            )


def grail_pin() -> dict[str, Any]:
    pin = load_json(ROOT / "GRAIL_PIN.json")
    if (
        not isinstance(pin, dict)
        or pin.get("schema") != "scotty-current-grail-pin/1"
        or pin.get("repository") != "https://github.com/microsoft/aibast-agents-library"
        or pin.get("commit") != CURRENT_GRAIL_COMMIT
        or pin.get("version") != "0.6.16"
        or pin.get("kernel") != "brainstem.py"
        or not any(
            item.get("path") == "brainstem.py"
            and item.get("sha256") == CURRENT_KERNEL_SHA256
            for item in pin.get("files", [])
        )
    ):
        raise DistributionRefused("current Grail dependency pin is invalid")
    return pin


def verify_grail(root: Path) -> dict[str, Any]:
    pin = grail_pin()
    verify_files(root, pin["files"])
    return {
        "repository": pin["repository"],
        "commit": pin["commit"],
        "version": pin["version"],
        "kernel_sha256": CURRENT_KERNEL_SHA256,
        "kernel_modified": False,
        "strict_current_rapp1_wire_qualified": False,
    }


def capability_manifest(root: Path = ROOT) -> dict[str, Any]:
    manifest = load_json(root / "SCOTTY_CAPABILITY_LOCK.json")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema", "grail_commit", "files"}
        or manifest["schema"] != "scotty-capability-files/1"
        or manifest["grail_commit"] != CURRENT_GRAIL_COMMIT
    ):
        raise DistributionRefused("capability file inventory is invalid")
    return manifest


def verify_capability(root: Path = ROOT) -> dict[str, Any]:
    manifest = capability_manifest(root)
    verify_files(root, manifest["files"])
    return {
        "status": "byte-verified",
        "files": len(manifest["files"]),
        "authority": "package-integrity-only-not-execution-approval",
    }


def public_path(value: str) -> str:
    """The Store boundary is stricter than the historical capability boundary."""
    name = relative_path(value)
    if (
        len(name) > 512
        or not name.isascii()
        or any(part.startswith(".") for part in name.split("/"))
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or any(part.casefold() in {"secrets", "credentials", "__pycache__", "node_modules"}
               for part in name.split("/"))
        or name.lower().endswith((".pyc", ".pyo", ".key", ".pem"))
    ):
        raise DistributionRefused("public payload contains a forbidden path")
    return name


def scan_public_payload(payload: dict[str, bytes]) -> dict[str, Any]:
    """Inspect *all* members, including nested archives; never extract or import."""
    forbidden = (
        rb"/Users/[A-Za-z0-9_.-]+/",
        rb"/home/(?!ai/|node/|app/|vastbase/|dify/|redis/)[A-Za-z0-9_.-]+/",
        rb"[A-Za-z]:\\Users\\",
        rb"(?i)session-state[/\\]",
        rb"(?i)(?:offline|qualification)-(?=[a-f0-9]{0,7}[a-f])[a-f0-9]{8}\b",
        rb"(?i)scotty[-]qualification/",
        rb"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        rb"(?i)\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}",
        rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----",
    )
    patterns = tuple(re.compile(pattern) for pattern in forbidden)
    totals = {"files": 0, "bytes": 0, "archives": 0}

    def visit(entries: dict[str, bytes], depth: int) -> None:
        if depth > 4:
            raise DistributionRefused("public archive nesting exceeds its bound")
        seen: set[str] = set()
        all_names = {name.casefold() for name in entries}
        for name, data in sorted(entries.items()):
            public_path(name)
            if (name.casefold() in seen or not isinstance(data, bytes)
                    or any(str(parent).casefold() in all_names for parent in PurePosixPath(name).parents
                           if str(parent) != ".")):
                raise DistributionRefused("public payload contains colliding members")
            seen.add(name.casefold())
            totals["files"] += 1
            totals["bytes"] += len(data)
            if totals["files"] > 4096 or totals["bytes"] > 64 * 1024 * 1024:
                raise DistributionRefused("public payload exceeds its scan bound")
            inspected = data
            owner = Path.home().name.encode()
            if (len(owner) >= 6 and owner in data
                    or any(pattern.search(inspected) for pattern in patterns)):
                raise DistributionRefused("public payload contains private or session material: " + name)
            if name.endswith(".json"):
                try:
                    pending = [json.loads(data)]
                    while pending:
                        value = pending.pop()
                        if isinstance(value, dict):
                            pending.extend(value.keys())
                            pending.extend(value.values())
                        elif isinstance(value, list):
                            pending.extend(value)
                        elif isinstance(value, str):
                            text = value.encode()
                            if (len(owner) >= 6 and owner in text
                                    or any(pattern.search(text) for pattern in patterns)):
                                raise DistributionRefused("public JSON contains encoded private material: " + name)
                except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
                    raise DistributionRefused("public JSON cannot be inspected") from error
            nested: dict[str, bytes] = {}
            stream = io.BytesIO(data)
            if zipfile.is_zipfile(stream):
                totals["archives"] += 1
                with zipfile.ZipFile(stream) as archive:
                    if (len(archive.infolist()) + totals["files"] > 4096
                            or sum(member.file_size for member in archive.infolist())
                            + totals["bytes"] > 64 * 1024 * 1024):
                        raise DistributionRefused("public nested archive exceeds its scan bound")
                    for member in archive.infolist():
                        public_path(member.filename.rstrip("/"))
                        mode = member.external_attr >> 16
                        if (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
                                or member.flag_bits & 1):
                            raise DistributionRefused("public archive contains a linked or encrypted member")
                        if member.is_dir():
                            continue
                        if member.filename in nested or member.file_size > 32 * 1024 * 1024:
                            raise DistributionRefused("public archive contains duplicate or oversized members")
                        nested[member.filename] = archive.read(member)
            elif data.startswith(b"\x1f\x8b") or name.endswith((".tar", ".tgz", ".tar.gz")):
                totals["archives"] += 1
                try:
                    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
                        declared, members = 0, 0
                        for member in archive:
                            declared += member.size
                            members += 1
                            if (declared + totals["bytes"] > 64 * 1024 * 1024
                                    or members + totals["files"] > 4096):
                                raise DistributionRefused("public nested archive exceeds its scan bound")
                            public_path(member.name.rstrip("/"))
                            if not member.isfile() and not member.isdir():
                                raise DistributionRefused("public archive contains a linked or special member")
                            if member.isdir():
                                continue
                            if member.name in nested or member.size > 32 * 1024 * 1024:
                                raise DistributionRefused("public archive contains duplicate or oversized members")
                            nested[member.name] = archive.extractfile(member).read()
                except tarfile.TarError as error:
                    raise DistributionRefused("public nested archive cannot be inspected") from error
            if nested:
                visit(nested, depth + 1)
    visit(payload, 0)
    return {
        "schema": "scotty-public-scan/1", "status": "passed",
        **totals, "max_archive_depth": 4,
        "scope": "path-and-byte-policy-not-a-secret-detector-or-runtime-qualification",
    }
