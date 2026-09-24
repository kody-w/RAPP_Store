"""Explicit, inert RAPP/1 setup-checkpoint transport; never a runtime or installer."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import secrets
import stat
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path, PurePosixPath
from types import MappingProxyType, ModuleType
from typing import Any

REFERENCE_COMMIT = "591e014ad39e223b00ab343ae26e5d9a867ebeee"
REFERENCE_SHA256 = "1a04362b02f14c1e37b70c6b4f72d79e92df1cc9c2b5b394e8e1b141fc0b6050"
SPEC_SHA256 = "348e7d5baa94aaf2ce4c5354f3cb261f389298a04af65e271a686d3b62f7c384"
GRAIL = {
    "repository": "https://github.com/microsoft/aibast-agents-library",
    "commit": "c60521e2cacbcbfa585a118c1275093d7bb15b74",
    "version": "0.6.16",
    "kernel_sha256": "35618683ebc3d1c2bfaff47f60182fd756f3a8de53c53dd907ec1099d631930a",
}
RUNTIME = "rapp-dock-portability/setup-checkpoint/1"
SELECTION_SCHEMA = "rapp-dock-portability-selection/1"
CHECKPOINT_SCHEMA = "rapp-dock-portability-checkpoint/1"
FILE_SCHEMA = "rapp-dock-portability-file/1"
MAX_FILES = 64
MAX_BYTES = 450_000
MAX_EGG_BYTES = 1_048_576
MAX_REPORTER_FRAMES = 128
STATE_NAMES = frozenset({"runtime_identity", "conversations", "jobs", "history", "idempotency", "authority"})
ROLES = frozenset({"source", "observation", "grail", *STATE_NAMES})
_HEX = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_KEY = re.compile(rb"(?m)^-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----\r?$")
_ENV_SECRET = re.compile(
    rb"(?m)^(?:OPENAI_API_KEY|AWS_SECRET_ACCESS_KEY|SCRAPLING_MCP_AUTH_TOKEN|GITHUB_TOKEN)\s*=\s*\S+"
)


class PortabilityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise PortabilityError(code, message)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _closed(value: Any, keys: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise PortabilityError("REFUSE_SHAPE", f"{where}: exact keys required")
    return value


def _absolute(value: str | Path) -> Path:
    raw = os.fspath(value)
    path = Path(raw)
    require(
        path.is_absolute() and ".." not in path.parts and "\0" not in raw,
        "REFUSE_PATH", "explicit absolute non-traversing path required",
    )
    return path


@contextmanager
def _directory(path: Path) -> Iterator[int]:
    path = _absolute(path)
    require(
        hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd,
        "REFUSE_PLATFORM", "descriptor-relative no-follow filesystem support required",
    )
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    except OSError as error:
        raise PortabilityError("REFUSE_PATH", "unsafe or unavailable directory") from error
    finally:
        os.close(descriptor)


def _private_directory(path: Path) -> None:
    with _directory(path) as descriptor:
        info = os.fstat(descriptor)
        require(
            info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
            "REFUSE_PRIVATE_PATH", "output/landing parent must be owned by this user and mode 0700",
        )


def _read_snapshot(path: Path, *, limit: int = MAX_EGG_BYTES) -> tuple[bytes, dict[str, int]]:
    path = _absolute(path)
    with _directory(path.parent) as parent:
        try:
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except OSError as error:
            raise PortabilityError("REFUSE_FILE", "explicit input is missing or unsafe") from error
        try:
            before = os.fstat(descriptor)
            require(
                stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit,
                "REFUSE_FILE", "bounded regular single-link input required",
            )
            chunks = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(65536, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                require(total <= limit, "REFUSE_BOUND", "input exceeds its bound")
            after = os.fstat(descriptor)
            require(
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                "REFUSE_CHANGED_INPUT", "input changed during capture",
            )
            return b"".join(chunks), {
                "device": before.st_dev, "inode": before.st_ino, "size": before.st_size,
                "mode": stat.S_IMODE(before.st_mode), "owner": before.st_uid,
            }
        finally:
            os.close(descriptor)


def read_regular(path: Path, *, limit: int = MAX_EGG_BYTES) -> bytes:
    return _read_snapshot(path, limit=limit)[0]


def _write_new(path: Path, raw: bytes) -> None:
    with _directory(path.parent) as parent:
        try:
            descriptor = os.open(
                path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=parent,
            )
        except OSError as error:
            raise PortabilityError("REFUSE_OVERWRITE", "create-only output already exists or is unsafe") from error
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as output:
                output.write(raw)
                output.flush()
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(parent)


def _replace_owned(path: Path, raw: bytes, expected_sha256: str) -> None:
    require(sha256(read_regular(path)) == expected_sha256, "REFUSE_REPORTER_RACE", "reporter head changed")
    temporary = path.parent / (".head-" + secrets.token_hex(16))
    _write_new(temporary, raw)
    with _directory(path.parent) as parent:
        try:
            require(
                sha256(read_regular(path)) == expected_sha256,
                "REFUSE_REPORTER_RACE", "reporter head changed before publication",
            )
            os.replace(temporary.name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary.name, dir_fd=parent)
            except FileNotFoundError:
                pass


@dataclass(frozen=True)
class OwnerAnchor:
    owner_rappid: str
    spki_der: bytes
    checkpoint_rappid: str


@dataclass(frozen=True)
class PacketBinding:
    path: Path
    egg_address: str
    egg_sha256: str

    def __post_init__(self) -> None:
        _absolute(self.path)
        require(
            isinstance(self.egg_address, str) and _HEX.fullmatch(self.egg_address) is not None
            and isinstance(self.egg_sha256, str) and _HEX.fullmatch(self.egg_sha256) is not None,
            "REFUSE_PACKET_BINDING", "configured packet must bind both exact canonical address and raw bytes",
        )


class Canonical:
    """Explicit pinned source binding, independent of the RAPP Work product."""

    def __init__(self, root: Path) -> None:
        root = _absolute(root)
        source = read_regular(root / "rapp.py")
        specification = read_regular(root / "SPEC.md")
        require(
            sha256(source) == REFERENCE_SHA256 and sha256(specification) == SPEC_SHA256,
            "REFUSE_REFERENCE_PIN", "canonical RAPP/1 reference/specification bytes differ from the accepted pin",
        )
        module = ModuleType("dock_portability._canonical_rapp1")
        module.__file__ = str(root / "rapp.py")
        exec(compile(source, module.__file__, "exec"), module.__dict__)  # noqa: S102 -- exact pinned reference, never egg content
        self.r = module

    @classmethod
    def from_capabilities(cls) -> Canonical:
        """Use the qualified public resource API, not private _R or an egg-supplied module."""
        try:
            version = metadata.version("rapp-capabilities")
        except metadata.PackageNotFoundError as error:
            raise PortabilityError(
                "REFUSE_REFERENCE_PACKAGE", "qualified rapp-capabilities==0.1.1 is not installed",
            ) from error
        require(
            version == "0.1.1", "REFUSE_REFERENCE_PACKAGE",
            "this portability binding requires the qualified rapp-capabilities 0.1.1 artifact",
        )
        try:
            from rapp_capabilities.rapp1 import (
                canonical_reference_path,
                canonical_reference_sha256,
                pinned_parent,
            )
        except ImportError as error:
            raise PortabilityError(
                "REFUSE_REFERENCE_PACKAGE", "qualified public RAPP/1 resource APIs are unavailable",
            ) from error
        pin = pinned_parent()
        require(
            pin.get("protocol") == "rapp/1"
            and pin.get("repository") == "https://github.com/kody-w/rapp-1"
            and pin.get("commit") == REFERENCE_COMMIT
            and pin.get("reference_sha256") == REFERENCE_SHA256
            and pin.get("spec_sha256") == SPEC_SHA256
            and canonical_reference_sha256() == REFERENCE_SHA256,
            "REFUSE_REFERENCE_PIN", "standalone capability resources disagree with the exact portability pin",
        )
        path = canonical_reference_path()
        require(
            isinstance(path, Path) and path.name == "rapp.py",
            "REFUSE_REFERENCE_PACKAGE", "canonical reference must be the named installed package resource",
        )
        return cls(path.parent)

    def encode(self, value: Any) -> bytes:
        try:
            return str(self.r.canonical(value)).encode("utf-8")
        except ValueError as error:
            raise PortabilityError("REFUSE_CANONICAL", str(error)) from error

    def decode(self, raw: bytes) -> Any:
        try:
            return self.r._strict_json(raw)
        except (ValueError, UnicodeError) as error:
            raise PortabilityError("REFUSE_JSON", "strict canonical-domain JSON required") from error

    def particle(self, value: Any) -> str:
        return str(self.r.H("rapp/1:particle", value))

    def digest(self, value: Any) -> str:
        return sha256(self.encode(value))

    def path(self, value: str) -> str:
        require(
            isinstance(value, str) and self.r._path_valid(value),
            "REFUSE_PATH", "canonical portable relative path required",
        )
        return value

    def paths(self, values: list[str]) -> None:
        require(
            self.r._path_set_valid(values),
            "REFUSE_PATH", "duplicate, traversing or cross-platform-colliding archive paths",
        )

    def verifier(self, anchor: OwnerAnchor | None) -> Any:
        if anchor is None:
            return None
        require(
            self.r.rappid_valid(anchor.owner_rappid)
            and self.r.rappid_valid(anchor.checkpoint_rappid)
            and isinstance(anchor.spki_der, bytes)
            and self.r.Hb("rapp/1:rappid", anchor.spki_der)
            == self.r.rappid_parts(anchor.owner_rappid)["hash"],
            "REFUSE_ANCHOR", "independent owner fingerprint and SPKI must agree",
        )

        def verify(unsigned: dict[str, Any], signature: str, expected: str | None = None) -> Any:
            if expected is not None and expected != anchor.owner_rappid:
                return False, "foreign required signer"
            return self.r.verify_detached_jws(
                unsigned, signature, anchor.spki_der, expected_kid=anchor.owner_rappid
            )
        return verify


def _reporter_identity(value: Any, canonical: Canonical) -> dict[str, Any]:
    record = _closed(value, {
        "schema", "rappid", "role", "identity_origin", "created_utc", "created_on_platform",
        "created_on_host_role", "creation_plan_sha256", "key_material", "authority_adoption",
        "source_runtime_identity",
    }, "setup reporter identity")
    require(
        record["schema"] == "rapp/1" and canonical.r.rappid_valid(record["rappid"])
        and record["role"] == "dock-setup-checkpoint-reporter"
        and record["identity_origin"] == "owner-approved-new-mint-once"
        and canonical.r.utc_valid(record["created_utc"])
        and record["key_material"] == "none-created"
        and record["authority_adoption"] == "not-established"
        and record["source_runtime_identity"] == "absent"
        and isinstance(record["creation_plan_sha256"], str)
        and _HEX.fullmatch(record["creation_plan_sha256"]) is not None,
        "REFUSE_REPORTER_IDENTITY", "reporter must remain a distinct mint-once setup identity, not runtime/owner authority",
    )
    _platform(record["created_on_platform"])
    require(
        record["created_on_host_role"] == (
            "this-mac" if record["created_on_platform"].startswith("darwin/") else "local-host"
        ),
        "REFUSE_REPORTER_IDENTITY", "reporter origin contradicts its recorded platform",
    )
    return record


def plan_reporter(
    root: Path, canonical: Canonical, *, owner_label: str, slug: str, created_utc: str,
) -> dict[str, Any]:
    root = _absolute(root)
    _private_directory(root.parent)
    require(not os.path.lexists(root), "REFUSE_OVERWRITE", "reporter already exists; never remint on reopen")
    require(
        isinstance(owner_label, str) and 1 <= len(owner_label) <= 39
        and isinstance(slug, str) and 1 <= len(slug) <= 100
        and canonical.r._LCLABEL.fullmatch(owner_label) is not None
        and canonical.r._LCLABEL.fullmatch(slug) is not None
        and canonical.r.utc_valid(created_utc),
        "REFUSE_REPORTER_IDENTITY", "canonical reporter labels and explicit UTC required",
    )
    plan = {
        "schema": "rapp-dock-reporter-creation-plan/1", "root": str(root),
        "owner_label": owner_label, "slug": slug, "created_utc": created_utc,
        "created_on_platform": host_platform(),
        "scope": "new-local-setup-checkpoint-reporter-only",
        "source_runtime_identity": "absent", "source_runtime_history": "absent",
        "key_material": "none-created", "authority_adoption": "not-established",
        "execution": "not-granted",
    }
    return {"plan": plan, "plan_sha256": canonical.digest(plan)}


def create_reporter(
    plan: Mapping[str, Any], approved_plan_sha256: str, canonical: Canonical,
) -> dict[str, Any]:
    value = dict(plan)
    current = plan_reporter(
        Path(value["root"]), canonical, owner_label=value["owner_label"],
        slug=value["slug"], created_utc=value["created_utc"],
    )
    require(
        current["plan"] == value and current["plan_sha256"] == approved_plan_sha256,
        "REFUSE_PLAN", "explicit scoped reporter-creation approval and complete exact plan required",
    )
    root = Path(value["root"])
    with _directory(root.parent) as parent:
        try:
            os.mkdir(root.name, 0o700, dir_fd=parent)
        except FileExistsError as error:
            raise PortabilityError("REFUSE_OVERWRITE", "reporter appeared; never remint") from error
        os.fsync(parent)
    # Identity allocation happens once, only after exclusive creation and exact local approval.
    identity = {
        "schema": "rapp/1",
        "rappid": canonical.r.mint_rappid(value["owner_label"], value["slug"]),
        "role": "dock-setup-checkpoint-reporter",
        "identity_origin": "owner-approved-new-mint-once",
        "created_utc": value["created_utc"], "created_on_platform": value["created_on_platform"],
        "created_on_host_role": "this-mac" if value["created_on_platform"].startswith("darwin/") else "local-host",
        "creation_plan_sha256": approved_plan_sha256,
        "key_material": "none-created", "authority_adoption": "not-established",
        "source_runtime_identity": "absent",
    }
    _reporter_identity(identity, canonical)
    _write_new(root / "creation-plan.json", canonical.encode(value))
    _write_new(root / "rappid.json", canonical.encode(identity))
    _write_new(root / ".reporter.lock", b"")
    with _directory(root) as parent:
        os.mkdir("frames", 0o700, dir_fd=parent)
        os.fsync(parent)
    _write_new(root / "head.json", canonical.encode({
        "schema": "rapp-dock-reporter-head/1", "rappid": identity["rappid"],
        "seq": None, "frame_hash": None,
    }))
    return {"status": "created-local-reporter", "identity": identity, "execution": "not-granted"}


class ReporterStore:
    """Private checkpoint-reporter continuity, never a runtime/workspace/authority bootstrap."""

    def __init__(self, root: Path, canonical: Canonical) -> None:
        self.root, self.canonical = _absolute(root), canonical
        with self.locked():
            self.read()

    @contextmanager
    def locked(self) -> Iterator[None]:
        import fcntl

        _private_directory(self.root)
        with _directory(self.root) as parent:
            try:
                descriptor = os.open(
                    ".reporter.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent,
                )
            except OSError as error:
                raise PortabilityError("REFUSE_REPORTER_STATE", "reporter lock is missing or unsafe") from error
        try:
            info = os.fstat(descriptor)
            require(
                stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.geteuid(),
                "REFUSE_REPORTER_STATE", "private, regular, single-link reporter lock required",
            )
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _private(self, path: Path) -> bytes:
        raw, info = _read_snapshot(path)
        require(
            info["owner"] == os.geteuid() and info["mode"] == 0o600,
            "REFUSE_REPORTER_STATE", "reporter files must remain private",
        )
        return raw

    def read(self) -> tuple[dict[str, Any], list[dict[str, Any]], bytes]:
        with _directory(self.root) as descriptor:
            require(
                sorted(os.listdir(descriptor)) == [
                    ".reporter.lock", "creation-plan.json", "frames", "head.json", "rappid.json",
                ],
                "REFUSE_REPORTER_STATE", "reporter store layout changed or initialization was interrupted",
            )
        require(self._private(self.root / ".reporter.lock") == b"", "REFUSE_REPORTER_STATE", "invalid reporter lock")
        record_raw = self._private(self.root / "rappid.json")
        record = _reporter_identity(self.canonical.decode(record_raw), self.canonical)
        require(self.canonical.encode(record) == record_raw, "REFUSE_REPORTER_STATE", "reporter identity bytes changed")
        creation = self.canonical.decode(self._private(self.root / "creation-plan.json"))
        parts = self.canonical.r.rappid_parts(record["rappid"])
        require(
            self.canonical.digest(creation) == record["creation_plan_sha256"]
            and creation["created_on_platform"] == record["created_on_platform"]
            and creation["created_utc"] == record["created_utc"]
            and parts["owner"] == creation["owner_label"] and parts["slug"] == creation["slug"],
            "REFUSE_REPORTER_STATE", "reporter creation provenance changed",
        )
        head_raw = self._private(self.root / "head.json")
        head = _closed(
            self.canonical.decode(head_raw), {"schema", "rappid", "seq", "frame_hash"}, "reporter head",
        )
        require(
            head["schema"] == "rapp-dock-reporter-head/1" and head["rappid"] == record["rappid"]
            and (
                (head["seq"] is None and head["frame_hash"] is None)
                or (type(head["seq"]) is int and 0 <= head["seq"] < MAX_REPORTER_FRAMES
                    and isinstance(head["frame_hash"], str) and _HEX.fullmatch(head["frame_hash"]) is not None)
            ),
            "REFUSE_REPORTER_STATE", "reporter head is malformed",
        )
        directory = self.root / "frames"
        _private_directory(directory)
        with _directory(directory) as descriptor:
            names = sorted(os.listdir(descriptor))
        count = 0 if head["seq"] is None else head["seq"] + 1
        require(
            len(names) == count and names == [f"{index:08d}.json" for index in range(count)],
            "REFUSE_LOST_STATE", "reporter history is missing, forked or has an uncommitted successor",
        )
        frames: list[dict[str, Any]] = []
        total = 0
        for name in names:
            raw = self._private(directory / name)
            total += len(raw)
            require(total <= MAX_EGG_BYTES, "REFUSE_BOUND", "reporter history exceeds the bounded session profile")
            frame = self.canonical.decode(raw)
            ok, step, reason = self.canonical.r.verify_frame(
                frame, head=frames[-1] if frames else None, stream_id_of_record=record["rappid"],
            )
            require(
                ok and frame["kind"] == "body.pulse" and frame["sig"] is None
                and self.canonical.encode(frame) == raw,
                "REFUSE_REPORTER_STATE", f"canonical reporter history refused at {step}: {reason}",
            )
            checkpoint = _checkpoint(frame["payload"], self.canonical)
            identities = [item for item in checkpoint["objects"] if item["path"] == "reporter/rappid.json"]
            require(
                len(identities) == 1
                and base64.b64decode(identities[0]["bytes_b64"], validate=True) == record_raw,
                "REFUSE_REPORTER_IDENTITY", "retained checkpoints disagree with the mint-once reporter record",
            )
            frames.append(frame)
        require(
            not frames or frames[-1]["frame_hash"] == head["frame_hash"],
            "REFUSE_LOST_STATE", "reporter retained head no longer resolves to exact history",
        )
        return record, frames, head_raw

    def append(self, frame: dict[str, Any], *, expected_head_sha256: str) -> None:
        record, frames, raw = self.read()
        require(
            sha256(raw) == expected_head_sha256 and len(frames) < MAX_REPORTER_FRAMES,
            "REFUSE_REPORTER_STATE", "reporter head changed or history bound reached",
        )
        ok, step, reason = self.canonical.r.verify_frame(
            frame, head=frames[-1] if frames else None, stream_id_of_record=record["rappid"],
        )
        require(
            ok and frame["kind"] == "body.pulse" and frame["sig"] is None,
            "REFUSE_REPORTER_STATE", f"successor refused at {step}: {reason}",
        )
        checkpoint = _checkpoint(frame["payload"], self.canonical)
        identities = [item for item in checkpoint["objects"] if item["path"] == "reporter/rappid.json"]
        require(
            len(identities) == 1
            and base64.b64decode(identities[0]["bytes_b64"], validate=True) == self.canonical.encode(record),
            "REFUSE_REPORTER_IDENTITY", "successor must preserve the exact reporter context",
        )
        _write_new(self.root / "frames" / f"{len(frames):08d}.json", self.canonical.encode(frame))
        _replace_owned(self.root / "head.json", self.canonical.encode({
            "schema": "rapp-dock-reporter-head/1", "rappid": record["rappid"],
            "seq": frame["seq"], "frame_hash": frame["frame_hash"],
        }), expected_head_sha256)


def _public_safe_selection(path: str, role: str, classification: str) -> None:
    require(
        classification == "neutral",
        "REFUSE_SEALING_REQUIRED",
        "only explicitly selected neutral technical material is supported; GODD needs canonical sealing and scoped custody",
    )
    require(
        role not in {"conversations", "history", "jobs", "authority"},
        "REFUSE_STATE_CUSTODY",
        "private runtime/authority history requires a qualified sealed custody migration, not plaintext export",
    )
    parts = PurePosixPath(path).parts
    forbidden = {".git", ".ssh", ".aws", ".azure", ".kube", "custody", "credentials"}
    require(
        not any(part.casefold() in forbidden for part in parts)
        and not any(
            part.startswith(".env") or part in {"id_rsa", "id_ed25519", "id_ecdsa"}
            or part.endswith((".pem", ".key", ".p12", ".pfx"))
            for part in parts
        ),
        "REFUSE_SECRET", "credential/custody/owner-key paths are never portable checkpoint inputs",
    )


def _platform(value: Any) -> str:
    if not isinstance(value, str) or value not in {
        "linux/amd64", "linux/arm64", "darwin/arm64", "darwin/amd64",
    }:
        raise PortabilityError("REFUSE_PLATFORM", "explicit supported OS/architecture descriptor required")
    return value


def host_platform() -> str:
    system = {"darwin": "darwin", "linux": "linux"}.get(sys.platform)
    architecture = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64", "AMD64": "amd64"}.get(
        platform.machine()
    )
    require(system is not None and architecture is not None, "REFUSE_PLATFORM", "unsupported landing host")
    return f"{system}/{architecture}"


def _state(value: Any, records: list[dict[str, Any]]) -> None:
    _closed(value, set(STATE_NAMES), "state inventory")
    roles = {name: sorted(item["path"] for item in records if item["role"] == name) for name in STATE_NAMES}
    for name in STATE_NAMES:
        item = _closed(value[name], {"status", "paths"}, f"state.{name}")
        require(
            isinstance(item["status"], str) and item["status"] in {"absent", "present"}
            and isinstance(item["paths"], list) and all(isinstance(path, str) for path in item["paths"])
            and item["paths"] == sorted(set(item["paths"]))
            and item["paths"] == roles[name]
            and bool(item["paths"]) == (item["status"] == "present"),
            "REFUSE_LOST_STATE", "declared state presence and preserved exact file inventory disagree",
        )


def _checkpoint(value: Any, canonical: Canonical) -> dict[str, Any]:
    checkpoint = _closed(value, {
        "schema", "kind", "created_utc", "source", "target", "grail", "state",
        "blockers", "pending_work", "files", "objects", "execution",
    }, "checkpoint")
    require(
        checkpoint["schema"] == CHECKPOINT_SCHEMA and checkpoint["kind"] == "deployment-setup"
        and canonical.r.utc_valid(checkpoint["created_utc"])
        and checkpoint["grail"] == GRAIL,
        "REFUSE_CHECKPOINT", "setup checkpoint and unchanged current Grail binding are required",
    )
    for side in ("source", "target"):
        descriptor = _closed(checkpoint[side], {"platform", "memory_bytes"}, side)
        _platform(descriptor["platform"])
        require(
            type(descriptor["memory_bytes"]) is int and 0 < descriptor["memory_bytes"] <= 2**53 - 1,
            "REFUSE_CHECKPOINT", "host memory is descriptive bounded integer metadata",
        )
    require(
        checkpoint["execution"] == {
            "permission": "not-granted",
            "auto_execute": False,
            "architecture_requalification": "required",
            "authority_adoption": "required",
        },
        "REFUSE_EXECUTION_PERMISSION",
        "verified portable data must remain separate from application execution permission",
    )
    for field in ("blockers", "pending_work"):
        require(
            isinstance(checkpoint[field], list) and 1 <= len(checkpoint[field]) <= 64
            and all(isinstance(text, str) and 0 < len(text) <= 1024 for text in checkpoint[field]),
            "REFUSE_CHECKPOINT", "real blockers and pending setup work must remain explicit",
        )
    require(
        isinstance(checkpoint["objects"], list) and isinstance(checkpoint["files"], list)
        and 1 <= len(checkpoint["objects"]) == len(checkpoint["files"]) <= MAX_FILES,
        "REFUSE_BOUND", "non-empty bounded closure of referenced objects is required",
    )
    objects: dict[str, dict[str, Any]] = {}
    for supplied in checkpoint["objects"]:
        item = _closed(supplied, {"schema", "path", "role", "data_class", "sha256", "bytes_b64"}, "file object")
        canonical.path(item["path"])
        require(
            item["path"] != "frames" and not item["path"].startswith("frames/"),
            "REFUSE_PATH", "checkpoint history paths are reserved",
        )
        require(
            item["schema"] == FILE_SCHEMA and item["role"] in ROLES
            and isinstance(item["sha256"], str) and _HEX.fullmatch(item["sha256"]) is not None
            and isinstance(item["bytes_b64"], str),
            "REFUSE_OBJECT", "invalid checkpoint object descriptor",
        )
        _public_safe_selection(item["path"], item["role"], item["data_class"])
        try:
            raw = base64.b64decode(item["bytes_b64"], validate=True)
        except (ValueError, TypeError) as error:
            raise PortabilityError("REFUSE_OBJECT", "invalid object bytes encoding") from error
        require(
            base64.b64encode(raw).decode("ascii") == item["bytes_b64"] and sha256(raw) == item["sha256"],
            "REFUSE_OBJECT", "referenced object bytes/hash disagree",
        )
        require(not _PRIVATE_KEY.search(raw) and not _ENV_SECRET.search(raw), "REFUSE_SECRET", "secret-bearing bytes refused")
        if item["role"] == "grail":
            require(
                item["sha256"] == GRAIL["kernel_sha256"],
                "REFUSE_GRAIL_DRIFT", "selected Grail kernel differs from the unchanged pinned current release",
            )
        if item["path"] == "reporter/rappid.json":
            require(item["role"] == "observation", "REFUSE_REPORTER_IDENTITY", "reporter is not a source runtime identity")
            _reporter_identity(canonical.decode(raw), canonical)
        digest = canonical.particle(item)
        require(digest not in objects, "REFUSE_OBJECT", "duplicate referenced object")
        objects[digest] = item
    resolved = []
    for reference in checkpoint["files"]:
        item = _closed(reference, {"path", "address"}, "file reference")
        address = _closed(item["address"], {"space", "hash"}, "typed object address")
        require(
            address["space"] == "rapp/1:particle"
            and isinstance(address["hash"], str) and _HEX.fullmatch(address["hash"]) is not None
            and address["hash"] in objects
            and objects[address["hash"]]["path"] == item["path"],
            "REFUSE_MISSING_OBJECT", "a referenced canonical object is missing, foreign or rebound",
        )
        resolved.append(objects[address["hash"]])
    require(
        len({item["path"] for item in resolved}) == len(resolved),
        "REFUSE_OBJECT", "duplicate referenced path",
    )
    canonical.paths(["checkpoint.egg", "checkpoint.json", "frames/0.json", "landing-receipt.json",
                     *[item["path"] for item in resolved]])
    require(
        sum(len(base64.b64decode(item["bytes_b64"])) for item in resolved) <= MAX_BYTES,
        "REFUSE_BOUND", "portable source/artifact byte closure exceeds the bound",
    )
    _state(checkpoint["state"], resolved)
    return checkpoint


def _capture(
    selection: Mapping[str, Any], canonical: Canonical, *, reporter: ReporterStore | None = None,
) -> tuple[bytes, dict[str, Any]]:
    value = _closed(dict(selection), {
        "schema", "checkpoint_rappid", "created_utc", "roots", "files", "source", "target",
        "state", "blockers", "pending_work", "output",
    }, "selection")
    require(value["schema"] == SELECTION_SCHEMA, "REFUSE_SELECTION", "unsupported selection schema")
    require(
        isinstance(value["checkpoint_rappid"], str) and canonical.r.rappid_valid(value["checkpoint_rappid"]),
        "REFUSE_CHECKPOINT_IDENTITY",
        "explicit real checkpoint/exporter RAPPID required; no NAS identity is minted or inferred",
    )
    require(canonical.r.utc_valid(value["created_utc"]), "REFUSE_TIME", "explicit millisecond UTC required")
    prefix: list[dict[str, Any]] = []
    reporter_context = None
    reporter_raw = None
    if reporter is not None:
        identity, prefix, head_raw = reporter.read()
        require(
            identity["rappid"] == value["checkpoint_rappid"],
            "REFUSE_REPORTER_IDENTITY", "selection cannot replace the persisted reporter identity",
        )
        require(
            value["created_utc"] >= identity["created_utc"],
            "REFUSE_TIME", "checkpoint cannot predate its actual reporter creation",
        )
        reporter_raw = canonical.encode(identity)
        reporter_context = {
            "root": str(reporter.root), "rappid": identity["rappid"],
            "identity_sha256": sha256(reporter_raw), "head_sha256": sha256(head_raw),
            "prior_frames": len(prefix),
        }
    require(
        isinstance(value["roots"], dict) and 1 <= len(value["roots"]) <= 8
        and isinstance(value["files"], list) and 1 <= len(value["files"]) <= MAX_FILES,
        "REFUSE_SELECTION", "explicit bounded source roots and exact file allowlist required",
    )
    records, preconditions = [], []
    for supplied in value["files"]:
        item = _closed(supplied, {"root", "source", "path", "sha256", "role", "data_class"}, "selected file")
        require(item["root"] in value["roots"], "REFUSE_SELECTION", "selected root is not allowlisted")
        canonical.path(item["source"])
        canonical.path(item["path"])
        require(
            item["path"] != "reporter/rappid.json",
            "REFUSE_REPORTER_IDENTITY", "managed reporter metadata is supplied only by the explicit reporter store",
        )
        require(item["role"] in ROLES, "REFUSE_SELECTION", "unknown selected file role")
        _public_safe_selection(item["source"], item["role"], item["data_class"])
        _public_safe_selection(item["path"], item["role"], item["data_class"])
        root = _absolute(value["roots"][item["root"]])
        require(
            not any(part in {".ssh", ".aws", ".azure", ".kube", "custody"} for part in root.parts),
            "REFUSE_SECRET", "custody/credential roots cannot be captured",
        )
        path = root / item["source"]
        raw, identity = _read_snapshot(path, limit=MAX_BYTES)
        require(
            sha256(raw) == item["sha256"], "REFUSE_CHANGED_INPUT", "selected source bytes changed",
        )
        preconditions.append({
            "root": item["root"], "source": item["source"], "sha256": sha256(raw),
            **identity,
        })
        records.append({
            "schema": FILE_SCHEMA, "path": item["path"], "role": item["role"],
            "data_class": item["data_class"], "sha256": sha256(raw),
            "bytes_b64": base64.b64encode(raw).decode("ascii"),
        })
    if reporter_raw is not None:
        records.append({
            "schema": FILE_SCHEMA, "path": "reporter/rappid.json", "role": "observation",
            "data_class": "neutral", "sha256": sha256(reporter_raw),
            "bytes_b64": base64.b64encode(reporter_raw).decode("ascii"),
        })
    records.sort(key=lambda item: item["path"])
    checkpoint = {
        "schema": CHECKPOINT_SCHEMA, "kind": "deployment-setup", "created_utc": value["created_utc"],
        "source": value["source"], "target": value["target"], "grail": dict(GRAIL),
        "state": value["state"], "blockers": value["blockers"], "pending_work": value["pending_work"],
        "objects": records,
        "files": [{"path": item["path"], "address": {
            "space": "rapp/1:particle", "hash": canonical.particle(item),
        }} for item in records],
        "execution": {
            "permission": "not-granted", "auto_execute": False,
            "architecture_requalification": "required", "authority_adoption": "required",
        },
    }
    _checkpoint(checkpoint, canonical)
    frame = canonical.r.build_frame(
        "body.pulse", value["checkpoint_rappid"], len(prefix), value["created_utc"], checkpoint,
        prefix[-1]["payload_hash"] if prefix else None,
    )
    egg = canonical.r.pack_egg(
        "session", value["checkpoint_rappid"], value["created_utc"],
        payload={"runtime": RUNTIME, "transcript": [*prefix, frame]},
    )
    require(len(egg) <= MAX_EGG_BYTES, "REFUSE_BOUND", "canonical session egg exceeds its bound")
    report = verify_egg(egg, canonical)
    output = _absolute(value["output"])
    _private_directory(output.parent)
    require(not os.path.lexists(output), "REFUSE_OVERWRITE", "export output already exists")
    plan = {
        "schema": "rapp-dock-portability-export-plan/1",
        "selection_sha256": canonical.digest(value), "output": str(output),
        "egg_sha256": sha256(egg), "egg_address": report["egg_address"],
        "checkpoint_frame_hash": frame["frame_hash"], "preconditions": preconditions,
        "reporter": reporter_context,
        "authority": "structural-only", "execution": "not-granted",
    }
    return egg, plan


def plan_export(
    selection: Mapping[str, Any], canonical: Canonical, *, reporter: ReporterStore | None = None,
) -> dict[str, Any]:
    if reporter is None:
        _, plan = _capture(selection, canonical)
    else:
        with reporter.locked():
            _, plan = _capture(selection, canonical, reporter=reporter)
    return {"plan": plan, "plan_sha256": canonical.digest(plan)}


def create_egg(
    selection: Mapping[str, Any], plan: Mapping[str, Any], approved_plan_sha256: str, canonical: Canonical,
    *, reporter: ReporterStore | None = None,
) -> dict[str, Any]:
    def publish() -> dict[str, Any]:
        raw, current = _capture(selection, canonical, reporter=reporter)
        require(
            dict(plan) == current and canonical.digest(current) == approved_plan_sha256,
            "REFUSE_PLAN", "complete current export plan and exact approved SHA-256 required",
        )
        _write_new(Path(current["output"]), raw)
        require(read_regular(Path(current["output"])) == raw, "REFUSE_WRITE", "published egg differs from approved bytes")
        if reporter is not None:
            manifest, _ = canonical.r.read_egg(raw)
            reporter.append(
                manifest["payload"]["transcript"][-1],
                expected_head_sha256=current["reporter"]["head_sha256"],
            )
        return {**verify_egg(raw, canonical), "path": current["output"]}

    if reporter is None:
        return publish()
    with reporter.locked():
        return publish()


def verify_egg(
    raw: bytes, canonical: Canonical, *, expected_address: str | None = None,
    anchor: OwnerAnchor | None = None, require_authenticated: bool = False,
) -> dict[str, Any]:
    require(
        isinstance(raw, bytes) and 0 < len(raw) <= MAX_EGG_BYTES,
        "REFUSE_BOUND", "bounded non-empty canonical egg bytes required",
    )
    verifier = canonical.verifier(anchor)
    ok, step, reason = canonical.r.verify_egg(raw, signature_verifier=verifier)
    require(ok, "REFUSE_EGG", f"canonical egg refused at {step}: {reason}")
    manifest, packed = canonical.r.read_egg(raw)
    require(
        manifest["variant"] == "session" and not packed
        and manifest["payload"]["runtime"] == RUNTIME,
        "REFUSE_CHECKPOINT", "only inert setup-checkpoint session eggs are accepted",
    )
    address = str(canonical.r.egg_address(manifest))
    require(expected_address is None or expected_address == address, "REFUSE_EGG_ADDRESS", "egg address differs from approval")
    frames = manifest["payload"]["transcript"]
    require(
        isinstance(frames, list) and 1 <= len(frames) <= MAX_REPORTER_FRAMES,
        "REFUSE_HISTORY", "a bounded non-empty real setup-checkpoint history is required",
    )
    previous = None
    for frame in frames:
        require(
            isinstance(frame, dict) and frame.get("kind") == "body.pulse"
            and frame.get("stream_id") == manifest["rappid"],
            "REFUSE_FRAME", "checkpoint must use the canonical body.pulse kind and exact reporter identity",
        )
        ok, step, reason = canonical.r.verify_frame(
            frame, head=previous, stream_id_of_record=manifest["rappid"], signature_verifier=verifier,
        )
        require(ok, "REFUSE_FRAME", f"canonical checkpoint frame refused at {step}: {reason}")
        payload = _checkpoint(frame["payload"], canonical)
        require(payload["created_utc"] == frame["utc"], "REFUSE_FRAME", "checkpoint/frame time mismatch")
        for item in payload["objects"]:
            if item["path"] == "reporter/rappid.json":
                identity = _reporter_identity(canonical.decode(base64.b64decode(item["bytes_b64"])), canonical)
                require(
                    identity["rappid"] == manifest["rappid"]
                    and frame["utc"] >= identity["created_utc"],
                    "REFUSE_REPORTER_IDENTITY", "reporter metadata names another checkpoint stream",
                )
        previous = frame
    frame = frames[-1]
    checkpoint = _checkpoint(frame["payload"], canonical)
    require(
        checkpoint["created_utc"] == frame["utc"] == manifest["created_utc"],
        "REFUSE_FRAME", "checkpoint and frame times differ",
    )
    if anchor is not None:
        require(
            manifest["rappid"] == anchor.checkpoint_rappid,
            "REFUSE_FOREIGN_AUTHORITY", "checkpoint is outside the independent identity anchor",
        )
    signed = manifest["sig"] is not None and all(frame["sig"] is not None for frame in frames)
    require(
        all((manifest["sig"] is None) == (frame["sig"] is None) for frame in frames),
        "REFUSE_SIGNATURE", "partial signing must not masquerade as a signed checkpoint",
    )
    require(
        not require_authenticated,
        "REFUSE_ADOPTION_REQUIRED",
        "authenticated acceptance needs the owner's adopted registry/kind/genesis, freshness, "
        "world/custody policy and retained high-water; this tool proves structural integrity/signatures only",
    )
    return {
        "schema": "rapp-dock-portability-verification/1",
        "egg_address": {"space": "rapp/1:egg-manifest", "hash": address},
        "egg_sha256": sha256(raw), "checkpoint_rappid": manifest["rappid"],
        "checkpoint_frame_hash": frame["frame_hash"], "frames_verified": len(frames),
        "files_verified": len(checkpoint["files"]),
        "scope": "signature-verified-not-adopted" if signed else "structural-only",
        "authenticated_acceptance": "not-established", "execution": "not-granted",
        "source": checkpoint["source"], "target": checkpoint["target"],
        "state": checkpoint["state"], "blockers": checkpoint["blockers"],
        "pending_work": checkpoint["pending_work"], "grail": checkpoint["grail"],
        "grail_kernel": (
            "included-exact" if any(item["role"] == "grail" for item in checkpoint["objects"])
            else "not-included-runtime-qualification-required"
        ),
    }


def plan_landing(
    raw: bytes, target: Path, canonical: Canonical, *, expected_address: str,
    target_platform: str, anchor: OwnerAnchor | None = None,
) -> dict[str, Any]:
    verified = verify_egg(raw, canonical, expected_address=expected_address, anchor=anchor)
    target = _absolute(target)
    _private_directory(target.parent)
    require(not os.path.lexists(target), "REFUSE_OVERWRITE", "landing target already exists")
    require(
        _platform(target_platform) == verified["target"]["platform"],
        "REFUSE_PLATFORM", "landing host platform differs from the reviewed checkpoint target",
    )
    manifest, _ = canonical.r.read_egg(raw)
    checkpoint = manifest["payload"]["transcript"][-1]["payload"]
    plan = {
        "schema": "rapp-dock-portability-landing-plan/1",
        "target": str(target), "target_platform": target_platform,
        "egg_address": verified["egg_address"], "egg_sha256": verified["egg_sha256"],
        "checkpoint_frame_hash": verified["checkpoint_frame_hash"],
        "files": [{"path": item["path"], "sha256": item["sha256"]}
                  for item in checkpoint["objects"]],
        "execution": "not-granted", "auto_execute": False,
    }
    return {"plan": plan, "plan_sha256": canonical.digest(plan)}


def land(
    raw: bytes, plan: Mapping[str, Any], approved_plan_sha256: str, canonical: Canonical,
    *, anchor: OwnerAnchor | None = None,
) -> dict[str, Any]:
    proposed = dict(plan)
    current = plan_landing(
        raw, Path(proposed["target"]), canonical,
        expected_address=proposed["egg_address"]["hash"],
        target_platform=proposed["target_platform"], anchor=anchor,
    )
    require(
        current["plan"] == proposed and current["plan_sha256"] == approved_plan_sha256,
        "REFUSE_PLAN", "complete current landing plan and exact approved SHA-256 required",
    )
    require(
        host_platform() == proposed["target_platform"],
        "REFUSE_PLATFORM", "actual landing host does not match the reviewed target OS/architecture",
    )
    manifest, _ = canonical.r.read_egg(raw)
    frames = manifest["payload"]["transcript"]
    checkpoint = frames[-1]["payload"]
    target = Path(proposed["target"])
    files = {item["path"]: base64.b64decode(item["bytes_b64"], validate=True)
             for item in checkpoint["objects"]}
    files["checkpoint.egg"] = raw
    files["checkpoint.json"] = canonical.encode(checkpoint)
    files.update({f"frames/{index}.json": canonical.encode(frame) for index, frame in enumerate(frames)})
    receipt = {
        "schema": "rapp-dock-portability-landing/1", "plan_sha256": approved_plan_sha256,
        "egg_address": proposed["egg_address"], "egg_sha256": sha256(raw),
        "target_platform": proposed["target_platform"],
        "files": [{"path": path, "sha256": sha256(data)} for path, data in sorted(files.items())],
        "runtime_started": False, "execution": "not-granted",
        "state": checkpoint["state"],
    }
    files["landing-receipt.json"] = canonical.encode(receipt)
    with _directory(target.parent) as parent:
        try:
            os.mkdir(target.name, 0o700, dir_fd=parent)
        except FileExistsError as error:
            raise PortabilityError("REFUSE_OVERWRITE", "landing target appeared before create-only publication") from error
        os.fsync(parent)
    # An interrupted landing is retained and refused on retry; never overwrite or erase newer state.
    for relative, data in sorted(files.items()):
        cursor = target
        for part in PurePosixPath(relative).parts[:-1]:
            with _directory(cursor) as parent:
                try:
                    os.mkdir(part, 0o700, dir_fd=parent)
                    os.fsync(parent)
                except FileExistsError:
                    info = os.stat(part, dir_fd=parent, follow_symlinks=False)
                    require(stat.S_ISDIR(info.st_mode), "REFUSE_PATH", "landing directory collision")
            cursor /= part
        _write_new(target / relative, data)
    return inspect_landing(
        target, canonical, expected_egg_address=proposed["egg_address"]["hash"], anchor=anchor,
    )


def inspect_landing(
    root: Path, canonical: Canonical, *, expected_egg_address: str, anchor: OwnerAnchor | None = None,
) -> dict[str, Any]:
    root = _absolute(root)
    _private_directory(root)
    raw_egg = read_regular(root / "checkpoint.egg")
    verified = verify_egg(raw_egg, canonical, expected_address=expected_egg_address, anchor=anchor)
    manifest, _ = canonical.r.read_egg(raw_egg)
    canonical_frames = manifest["payload"]["transcript"]
    canonical_checkpoint = canonical_frames[-1]["payload"]
    receipt = canonical.decode(read_regular(root / "landing-receipt.json"))
    _closed(receipt, {"schema", "plan_sha256", "egg_address", "egg_sha256", "target_platform",
                      "files", "runtime_started", "execution", "state"}, "landing receipt")
    require(
        receipt["schema"] == "rapp-dock-portability-landing/1"
        and receipt["egg_address"] == {"space": "rapp/1:egg-manifest", "hash": expected_egg_address}
        and receipt["egg_sha256"] == sha256(raw_egg)
        and receipt["target_platform"] == verified["target"]["platform"]
        and receipt["runtime_started"] is False and receipt["execution"] == "not-granted",
        "REFUSE_LANDING", "landing receipt cannot grant execution or identify another egg",
    )
    committed_files = {
        item["path"]: base64.b64decode(item["bytes_b64"], validate=True)
        for item in canonical_checkpoint["objects"]
    }
    committed_files.update({
        "checkpoint.egg": raw_egg,
        "checkpoint.json": canonical.encode(canonical_checkpoint),
    })
    committed_files.update({
        f"frames/{index}.json": canonical.encode(frame) for index, frame in enumerate(canonical_frames)
    })
    require(
        receipt["files"] == [
            {"path": path, "sha256": sha256(data)} for path, data in sorted(committed_files.items())
        ],
        "REFUSE_LOST_STATE", "local receipt differs from the original canonical egg closure",
    )
    expected = {"landing-receipt.json"}
    for record in receipt["files"]:
        _closed(record, {"path", "sha256"}, "landed file")
        path = canonical.path(record["path"])
        require(
            path not in expected and sha256(read_regular(root / path)) == record["sha256"],
            "REFUSE_LOST_STATE", "landed checkpoint/source/state bytes were removed or changed",
        )
        expected.add(path)
    found: set[str] = set()
    expected_directories = {
        parent.as_posix()
        for relative in expected
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }
    pending = [root]
    seen_directories: set[str] = set()
    count = 0
    while pending:
        directory = pending.pop()
        _private_directory(directory)
        with _directory(directory) as descriptor, os.scandir(descriptor) as entries:
            for entry in entries:
                count += 1
                require(
                    count <= len(expected) + len(expected_directories),
                    "REFUSE_LOST_STATE", "unexpected landed directory entries",
                )
                relative = (directory / entry.name).relative_to(root).as_posix()
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    require(relative in expected_directories, "REFUSE_LOST_STATE", "unexpected landed directory")
                    seen_directories.add(relative)
                    pending.append(directory / entry.name)
                else:
                    require(
                        stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                        and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600,
                        "REFUSE_PATH", "landed files must remain private, regular and single-link",
                    )
                    found.add(relative)
    require(seen_directories == expected_directories, "REFUSE_LOST_STATE", "landed directory inventory changed")
    require(found == expected, "REFUSE_LOST_STATE", "landed file inventory changed")
    frames = [
        canonical.decode(read_regular(root / f"frames/{index}.json")) for index in range(len(canonical_frames))
    ]
    checkpoint = canonical.decode(read_regular(root / "checkpoint.json"))
    require(
        isinstance(frames, list) and len(frames) == len(canonical_frames)
        and frames[-1].get("payload") == checkpoint
        and frames == canonical_frames
        and checkpoint == canonical_checkpoint
        and checkpoint["state"] == receipt["state"],
        "REFUSE_LOST_STATE", "checkpoint/history/state linkage changed",
    )
    _checkpoint(checkpoint, canonical)
    return {
        "status": "landed-inert", "egg_address": receipt["egg_address"],
        "files_verified": len(receipt["files"]), "state": receipt["state"],
        "frames_verified": len(frames),
        "execution": "not-granted", "runtime_started": False,
        "continuation": {"blockers": checkpoint["blockers"], "pending_work": checkpoint["pending_work"]},
    }


def execution_permission(_verified: Mapping[str, Any], _target_platform: str) -> None:
    raise PortabilityError(
        "REFUSE_EXECUTION_PERMISSION",
        "landing is data only; architecture-specific applications require new target qualification, "
        "owner approval, custody and execution fencing",
    )


class PortabilityTools:
    """A stateless agent-facing facade; configuration is trusted host input, never model input."""

    def __init__(
        self, canonical: Canonical, *, packets: Mapping[str, PacketBinding],
        landing_parent: Path, target_platform: str,
        approved_landings: Mapping[str, bytes] | None = None, anchor: OwnerAnchor | None = None,
    ) -> None:
        require(type(canonical) is Canonical, "REFUSE_REFERENCE_PIN", "explicit verified canonical binding required")
        require(len(packets) <= 32, "REFUSE_PACKET_BINDING", "bounded configured packet catalog required")
        for name, packet in packets.items():
            self._name(name)
            require(type(packet) is PacketBinding, "REFUSE_PACKET_BINDING", "exact immutable packet binding required")
        approvals = dict(approved_landings or {})
        require(len(approvals) <= 32, "REFUSE_PLAN", "bounded parent-reviewed landing plans required")
        for digest, raw in approvals.items():
            require(
                isinstance(digest, str) and _HEX.fullmatch(digest) is not None and isinstance(raw, bytes),
                "REFUSE_PLAN", "approval configuration requires complete immutable canonical plan bytes",
            )
            value = canonical.decode(raw)
            require(
                canonical.encode(value) == raw and canonical.digest(value) == digest,
                "REFUSE_PLAN", "configured parent approval must bind the exact complete plan",
            )
        self.canonical = canonical
        self.packets = MappingProxyType(dict(packets))
        self.approved_landings = MappingProxyType(approvals)
        self.landing_parent = _absolute(landing_parent)
        self.target_platform = _platform(target_platform)
        self.anchor = anchor

    @staticmethod
    def _name(value: Any) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value) is None:
            raise PortabilityError("REFUSE_TOOL_SCOPE", "configured alias or simple target name required")
        return value

    def _packet(
        self, packet_id: str, *, retained_path: Path | None = None,
    ) -> tuple[bytes, PacketBinding, dict[str, Any]]:
        self._name(packet_id)
        require(
            bool(self.packets), "REFUSE_MISSING_CHECKPOINT_INPUT",
            "no actual checkpoint packet is configured; explicit genuine checkpoint identity and exact egg binding are missing",
        )
        require(packet_id in self.packets, "REFUSE_TOOL_SCOPE", "packet is outside the configured catalog")
        binding = self.packets[packet_id]
        raw = read_regular(binding.path if retained_path is None else retained_path)
        require(sha256(raw) == binding.egg_sha256, "REFUSE_PACKET_BINDING", "configured packet bytes changed")
        report = verify_egg(raw, self.canonical, expected_address=binding.egg_address, anchor=self.anchor)
        return raw, binding, report

    @staticmethod
    def _summary(packet_id: str, report: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "packet_id": packet_id,
            "egg_address": report["egg_address"],
            "scope": report.get("scope", "verified-inert-landing"),
            "files_verified": report["files_verified"],
            "state": {name: item["status"] for name, item in report["state"].items()},
            "execution": "not-granted",
            "authenticated_acceptance": "not-established",
            "missing_authority_inputs": [
                *(["actual-signing-keeper"] if report.get("scope") == "structural-only" else []),
                "owner-adopted-registry-kind-genesis",
                "fresh-world-custody-policy-and-retained-high-water",
            ],
        }

    def plan_for_review(self, packet_id: str, target_name: str) -> dict[str, Any]:
        """Trusted parent review API. Do not expose arbitrary configuration or this full plan to models."""
        raw, binding, _ = self._packet(packet_id)
        target = self.landing_parent / self._name(target_name)
        return plan_landing(
            raw, target, self.canonical, expected_address=binding.egg_address,
            target_platform=self.target_platform, anchor=self.anchor,
        )

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """The only model-callable entrypoint: verify, inspect, plan, or preapproved inert land."""
        value = dict(arguments)
        operation = value.get("operation")
        required = {
            "verify": {"operation", "packet_id"},
            "inspect": {"operation", "packet_id", "target_name"},
            "plan": {"operation", "packet_id", "target_name"},
            "land": {"operation", "packet_id", "target_name", "approved_plan_sha256"},
        }
        if not isinstance(operation, str) or operation not in required:
            raise PortabilityError(
                "REFUSE_TOOL_OPERATION", "only verify, inspect, plan and explicitly approved inert land are exposed",
            )
        _closed(value, required[operation], "Scotty portability request")
        if operation == "verify":
            _, _, verified = self._packet(value["packet_id"])
            result = self._summary(value["packet_id"], verified)
            return {"status": "verified-data-only", **result}
        target_name = self._name(value["target_name"])
        target = self.landing_parent / target_name
        if operation == "inspect":
            _, binding, verified = self._packet(
                value["packet_id"], retained_path=target / "checkpoint.egg",
            )
            result = self._summary(value["packet_id"], verified)
            inspected = inspect_landing(
                target, self.canonical, expected_egg_address=binding.egg_address, anchor=self.anchor,
            )
            return {
                "status": inspected["status"], **result, "target_name": target_name,
                "runtime_started": False,
                "pending_work_count": len(inspected["continuation"]["pending_work"]),
            }
        raw, _, verified = self._packet(value["packet_id"])
        result = self._summary(value["packet_id"], verified)
        planned = self.plan_for_review(value["packet_id"], target_name)
        digest = planned["plan_sha256"]
        if operation == "plan":
            return {
                "status": "planned-data-only", **result, "target_name": target_name,
                "target_platform": self.target_platform, "plan_sha256": digest,
                "write_approval": "parent-exact-plan-required",
            }
        require(
            isinstance(value["approved_plan_sha256"], str)
            and value["approved_plan_sha256"] == digest
            and digest in self.approved_landings
            and self.approved_landings[digest] == self.canonical.encode(planned["plan"]),
            "REFUSE_LOCAL_WRITE_APPROVAL",
            "model text or possession of a digest is not approval; parent-reviewed exact plan is missing",
        )
        landed = land(raw, planned["plan"], digest, self.canonical, anchor=self.anchor)
        return {
            "status": landed["status"], **result, "target_name": target_name,
            "plan_sha256": digest, "write_approval": "explicit-local-create-only",
            "runtime_started": False,
        }


def _anchor_file(path: Path | None, canonical: Canonical) -> OwnerAnchor | None:
    if path is None:
        return None
    value = _closed(
        canonical.decode(read_regular(path)),
        {"schema", "owner_rappid", "spki_der_b64", "checkpoint_rappid"},
        "independent portability signer anchor",
    )
    require(
        value["schema"] == "rapp-dock-portability-anchor/1",
        "REFUSE_ANCHOR", "unsupported anchor schema",
    )
    try:
        public_key = base64.b64decode(value["spki_der_b64"], validate=True)
    except (ValueError, TypeError) as error:
        raise PortabilityError("REFUSE_ANCHOR", "public SPKI encoding required") from error
    anchor = OwnerAnchor(value["owner_rappid"], public_key, value["checkpoint_rappid"])
    canonical.verifier(anchor)
    return anchor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    reference = parser.add_mutually_exclusive_group(required=True)
    reference.add_argument("--rapp1-root", type=Path, help="explicit exact canonical reference checkout")
    reference.add_argument(
        "--capabilities-package", action="store_true",
        help="use the qualified installed rapp-capabilities==0.1.1 public reference resources",
    )
    sub = parser.add_subparsers(dest="operation", required=True)
    reporter_plan = sub.add_parser("plan-reporter")
    reporter_plan.add_argument("--root", type=Path, required=True)
    reporter_plan.add_argument("--owner-label", required=True)
    reporter_plan.add_argument("--slug", required=True)
    reporter_plan.add_argument("--created-utc", required=True)
    reporter_create = sub.add_parser("create-reporter")
    reporter_create.add_argument("--plan", type=Path, required=True)
    reporter_create.add_argument("--approved-plan-sha256", required=True)
    reporter_status = sub.add_parser("reporter-status")
    reporter_status.add_argument("--reporter-root", type=Path, required=True)
    for name in ("plan", "create"):
        command = sub.add_parser(name)
        command.add_argument("--selection", type=Path, required=True)
        command.add_argument("--reporter-root", type=Path)
        if name == "create":
            command.add_argument("--plan", type=Path, required=True)
            command.add_argument("--approved-plan-sha256", required=True)
    for name in ("verify", "plan-land", "land"):
        command = sub.add_parser(name)
        command.add_argument("--egg", type=Path, required=True)
        command.add_argument("--anchor", type=Path)
        if name in {"verify", "plan-land"}:
            command.add_argument("--egg-address", required=True)
        if name == "verify":
            command.add_argument("--require-authenticated", action="store_true")
        elif name == "plan-land":
            command.add_argument("--target", type=Path, required=True)
            command.add_argument("--target-platform", required=True)
        else:
            command.add_argument("--plan", type=Path, required=True)
            command.add_argument("--approved-plan-sha256", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--root", type=Path, required=True)
    inspect.add_argument("--egg-address", required=True)
    inspect.add_argument("--anchor", type=Path)
    try:
        args = parser.parse_args(argv)
        canonical = Canonical.from_capabilities() if args.capabilities_package else Canonical(args.rapp1_root)
        if args.operation == "plan-reporter":
            result = plan_reporter(
                args.root, canonical, owner_label=args.owner_label, slug=args.slug, created_utc=args.created_utc,
            )
        elif args.operation == "create-reporter":
            saved = canonical.decode(read_regular(args.plan))
            result = create_reporter(saved["plan"], args.approved_plan_sha256, canonical)
        elif args.operation == "reporter-status":
            store = ReporterStore(args.reporter_root, canonical)
            with store.locked():
                identity, frames, _ = store.read()
            result = {
                "identity": identity, "frames": len(frames),
                "head": frames[-1]["frame_hash"] if frames else None,
                "authority_adoption": "not-established", "execution": "not-granted",
            }
        elif args.operation in {"plan", "create"}:
            selection = canonical.decode(read_regular(args.selection))
            reporter = ReporterStore(args.reporter_root, canonical) if args.reporter_root else None
            if args.operation == "plan":
                result = plan_export(selection, canonical, reporter=reporter)
            else:
                saved = canonical.decode(read_regular(args.plan))
                result = create_egg(
                    selection, saved["plan"], args.approved_plan_sha256, canonical, reporter=reporter,
                )
        elif args.operation == "inspect":
            result = inspect_landing(
                args.root, canonical, expected_egg_address=args.egg_address,
                anchor=_anchor_file(args.anchor, canonical),
            )
        else:
            raw = read_regular(args.egg)
            anchor = _anchor_file(args.anchor, canonical)
            if args.operation == "verify":
                result = verify_egg(raw, canonical, expected_address=args.egg_address,
                                    require_authenticated=args.require_authenticated, anchor=anchor)
            elif args.operation == "plan-land":
                result = plan_landing(raw, args.target, canonical, expected_address=args.egg_address,
                                      target_platform=args.target_platform, anchor=anchor)
            else:
                saved = canonical.decode(read_regular(args.plan))
                result = land(raw, saved["plan"], args.approved_plan_sha256, canonical, anchor=anchor)
        print(canonical.encode(result).decode("utf-8"))
        return 0
    except (PortabilityError, OSError, KeyError, TypeError, ValueError) as error:
        print(json.dumps({
            "status": "refused", "code": getattr(error, "code", "REFUSE_INPUT"),
            "message": str(error), "execution": "not-granted",
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
