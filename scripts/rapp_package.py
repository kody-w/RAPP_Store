"""Verified current-Grail cartridges and explicit, preserving installation.

Stdlib only. Generated hatchers embed this module verbatim. Import, contract
validation and package inspection never execute application code or probe a
device. These cartridges are Store installers, not canonical RAPP/1 eggs.
"""

from __future__ import annotations

import ast
import contextlib
import ctypes
import errno
import hashlib
import io
import json
import math
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

APPLICATION_SCHEMA = "rapp-application/2.0"
PACKAGE_SCHEMA = "rapp-egg/2.0"
GRAIL = {
    "repo": "microsoft/aibast-agents-library",
    "commit": "c60521e2cacbcbfa585a118c1275093d7bb15b74",
    "version": "0.6.16",
}
GRAIL_INSTALLER = (
    "https://raw.githubusercontent.com/microsoft/aibast-agents-library/"
    + GRAIL["commit"]
    + "/install.sh"
)
UPGRADE_HELP = (
    "Use the reviewed official Grail installer: "
    + GRAIL_INSTALLER
    + " with --version "
    + GRAIL["commit"]
    + " --no-launch. "
    "Back up owned data first. Store installation never upgrades or bypasses the host."
)
GRAIL_FILES = {
    "brainstem.py": "35618683ebc3d1c2bfaff47f60182fd756f3a8de53c53dd907ec1099d631930a",
    "agents/basic_agent.py": "701488bc00d536a7b23295e7da99c62f24e9b00f233daa325886430c736b78eb",
    "local_storage.py": "c38667c1f65a703174c1d4a8c42cbf36d499178ead41534d0086763e681b7ccb",
    "VERSION": "e94a7f87af28a51ae948939b0fc6f3d7b9853add0d06a4ffb6df7c67c68ffcc5",
    "requirements.txt": "6bc9a8d661873b4cfd6681f8c94b0a347cfcf6fb3a463b19c45bdc4a9cb165ef",
    "index.html": "d60569be2db3f5620498e84a976e060139d2a9650672da2777d6c5e7a7f6437c",
}
FEATURES = frozenset(
    {
        "portable-agents/1",
        "owned-files/1",
        "state-seeds/1",
        "local-docker/1",
    }
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
PUBLISHER_PATTERN = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9-]*$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
MAX_PACKAGE_BYTES = 5 * 1024 * 1024
MAX_EXPANDED_BYTES = 20 * 1024 * 1024
MAX_SUPPORT_FILE_BYTES = 4 * 1024 * 1024
MAX_FILES = 2048
IGNORED_ROOTS = frozenset({"eggs", "versions", "__pycache__"})
LIFECYCLE = {
    "install": "copy-verified-files",
    "upgrade": "preserve-state",
    "uninstall": "preserve-state",
    "recovery": "reinstall-verified-package",
}
LOADER_CONTRACT = "scotty-revision-loader/1"
LOCAL_DOCKER_SCHEMA = "rapp-local-docker/1"
LOCAL_APPS = frozenset(
    {"intelligence", "scrapling", "presenton", "open-seo", "dify", "openshorts"}
)
READINESS_STATUSES = frozenset(
    {"pending", "passed", "failed", "blocked", "not-applicable"}
)
MAX_DECLARATION_BYTES = 256 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_SAFE_INTEGER = (1 << 53) - 1
RETAINED = [
    "application-state",
    "release-history",
    "outputs-and-operation-receipts",
    "credentials-and-identities",
    "docker-volumes",
    "docker-images",
    "unqualified-container-writable-layers",
]


class PackageError(ValueError):
    """An actionable contract, integrity or installation refusal."""


def canonical_json(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode()


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PackageError("E_JSON: duplicate object key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise PackageError("E_JSON: non-finite JSON value")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise PackageError("E_JSON: non-finite JSON value")
    return result


def _json(blob):
    try:
        return json.loads(
            blob,
            object_pairs_hook=_unique,
            parse_constant=_invalid_constant,
            parse_float=_finite_float,
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PackageError("E_JSON: invalid or ambiguous JSON") from exc


def relative_path(value):
    if (
        not isinstance(value, str)
        or not value
        or not value.isascii()
        or len(value) > 512
        or "\\" in value
        or ":" in value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise PackageError("E_PATH: expected a bounded ASCII relative POSIX file path")
    parts = value.split("/")
    if any(not part or part in (".", "..") or part.startswith(".") for part in parts):
        raise PackageError("E_PATH: hidden, absolute and traversal paths are forbidden")
    if any(part.rstrip(" .") != part for part in parts):
        raise PackageError("E_PATH: ambiguous path component")
    try:
        if any(len(part.encode("utf-8")) > 255 for part in parts):
            raise PackageError(
                "E_PATH: path component exceeds the portable filesystem bound"
            )
    except UnicodeError as exc:
        raise PackageError("E_PATH: path contains an invalid Unicode scalar") from exc
    return PurePosixPath(value)


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys():
        raise PackageError(
            "E_CONTRACT: missing required object fields: " + ", ".join(required)
        )
    if any(not isinstance(key, str) for key in value):
        raise PackageError("E_CONTRACT: object field names must be strings")
    unknown = value.keys() - set(required) - set(optional)
    if unknown:
        raise PackageError(
            "E_UNSUPPORTED_REQUIREMENT: unknown fields: " + ", ".join(sorted(unknown))
        )


def _strings(value, field):
    if not isinstance(value, list) or any(
        not isinstance(x, str) or not x for x in value
    ):
        raise PackageError("E_CONTRACT: " + field + " must be a string list")
    if len(set(value)) != len(value):
        raise PackageError("E_CONTRACT: duplicate " + field)


def _sha(value):
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _text(value, field):
    if not isinstance(value, str) or not value:
        raise PackageError("E_CONTRACT: " + field + " must be nonempty text")


def _list(value, field, minimum=0, maximum=2048):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise PackageError("E_CONTRACT: invalid or excessive " + field)


def _enum(value, choices, field):
    if not isinstance(value, str) or value not in choices:
        raise PackageError("E_CONTRACT: unsupported " + field)


def _number(value):
    return type(value) is int or type(value) is float and math.isfinite(value)


def _integer(value):
    if type(value) is int:
        return abs(value) <= MAX_SAFE_INTEGER
    return (
        type(value) is float
        and math.isfinite(value)
        and value.is_integer()
        and abs(value) <= MAX_SAFE_INTEGER
    )


def _typed_equal(left, right):
    if _number(left) or _number(right):
        return _number(left) and _number(right) and left == right
    if type(left) is bool or type(right) is bool:
        return type(left) is bool and type(right) is bool and left is right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, dict) or isinstance(right, dict):
        return (
            isinstance(left, dict)
            and isinstance(right, dict)
            and left.keys() == right.keys()
            and all(_typed_equal(value, right[key]) for key, value in left.items())
        )
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(_typed_equal(a, b) for a, b in zip(left, right, strict=True))
        )
    return isinstance(left, str) and isinstance(right, str) and left == right


def _json_value_key(value):
    if value is None:
        return ("null",)
    if type(value) is bool:
        return ("boolean", value)
    if _number(value):
        return ("number", value)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        return ("array", tuple(_json_value_key(item) for item in value))
    if isinstance(value, dict):
        return (
            "object",
            frozenset((key, _json_value_key(item)) for key, item in value.items()),
        )
    raise PackageError("E_JSON: unsupported value in a typed declaration")


def _local(m):
    return "local-docker/1" in m["requires"]


def validate_contract(m):
    if not isinstance(m, dict) or m.get("schema") != APPLICATION_SCHEMA:
        raise PackageError(
            "E_CONTRACT_UPGRADE: migrate the application to " + APPLICATION_SCHEMA
        )
    required = (
        "schema",
        "id",
        "name",
        "version",
        "publisher",
        "summary",
        "category",
        "tags",
        "agent",
        "agents",
        "runtime",
        "files",
        "requires",
        "profiles",
        "permissions",
        "capabilities",
        "dependencies",
        "services",
        "state",
        "lifecycle",
        "providers",
        "provenance",
    )
    _object(
        m,
        required,
        (
            "ui",
            "service",
            "twin",
            "license",
            "homepage",
            "quality_tier",
            "access",
            "private_repo",
            "access_note",
            "tagline",
            "manifest_name",
            "produced_by",
            "metrics",
            "spec_post",
            "repo_url",
            "kind",
            "type",
            "tool",
            "surfaces",
            "singleton_filename",
            "ui_filename",
            "source_dir",
            "build_command",
            "test_command",
            "_note",
            "local_docker",
        ),
    )
    if m["runtime"] != GRAIL:
        raise PackageError(
            "E_GRAIL_REQUIRED: every supported application must pin " + str(GRAIL)
        )
    if not isinstance(m["id"], str) or not ID_PATTERN.fullmatch(m["id"]):
        raise PackageError("E_BAD_ID: expected snake_case application id")
    if not isinstance(m["publisher"], str) or not PUBLISHER_PATTERN.fullmatch(
        m["publisher"]
    ):
        raise PackageError("E_BAD_PUBLISHER: expected @publisher")
    if not isinstance(m["version"], str) or not VERSION_PATTERN.fullmatch(m["version"]):
        raise PackageError("E_BAD_VERSION: expected MAJOR.MINOR.PATCH")
    for key in ("name", "summary", "category"):
        if not isinstance(m[key], str) or not m[key]:
            raise PackageError("E_CONTRACT: " + key + " must be nonempty text")
    _enum(
        m["category"],
        {
            "productivity",
            "creative",
            "analysis",
            "data",
            "integration",
            "platform",
            "workspace",
        },
        "application category",
    )
    _strings(m["tags"], "tags")
    if not m["tags"]:
        raise PackageError("E_CONTRACT: application tags must not be empty")
    for name in (
        "license",
        "homepage",
        "private_repo",
        "access_note",
        "tagline",
        "manifest_name",
        "produced_by",
        "spec_post",
        "repo_url",
        "kind",
        "type",
        "singleton_filename",
        "ui_filename",
        "source_dir",
        "build_command",
        "test_command",
        "_note",
    ):
        if name in m and not isinstance(m[name], str):
            raise PackageError(
                "E_CONTRACT: optional display fields must retain their declared types"
            )
    if "quality_tier" in m:
        _enum(
            m["quality_tier"],
            {
                "featured",
                "official",
                "verified",
                "community",
                "experimental",
                "deprecated",
                "private",
            },
            "quality tier",
        )
    if m.get("access", "public") != "public":
        raise PackageError(
            "E_UNSUPPORTED_REQUIREMENT: a complete Store application requires public closure qualification"
        )
    if (
        "tool" in m
        and type(m["tool"]) is not bool
        or "metrics" in m
        and not isinstance(m["metrics"], dict)
    ):
        raise PackageError("E_CONTRACT: invalid display-field type")
    if "surfaces" in m:
        _strings(m["surfaces"], "surfaces")
    if "ui" in m:
        relative_path(m["ui"])
    if "service" in m and m["service"] is not None:
        relative_path(m["service"])
    if "twin" in m and m["twin"] is not None:
        raise PackageError(
            "E_UNSUPPORTED_REQUIREMENT: a second runtime is not supported"
        )
    files = m["files"]
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise PackageError(
            "E_CLOSURE: files must explicitly pin the bounded application closure"
        )
    folded = set()
    for name, sha in files.items():
        path = relative_path(name)
        if path.parts[0] in IGNORED_ROOTS or name in (
            "manifest.json",
            "index_entry.json",
        ):
            raise PackageError(
                "E_CLOSURE: snapshots and generated metadata are not application files"
            )
        if name.casefold() in folded:
            raise PackageError("E_CLOSURE: case-insensitive path collision")
        folded.add(name.casefold())
        if not _sha(sha):
            raise PackageError("E_UNPINNED_FILE: " + name)
    for name in files:
        if any(
            str(parent).casefold() in folded
            for parent in PurePosixPath(name).parents
            if str(parent) != "."
        ):
            raise PackageError("E_CLOSURE: a file cannot also be a directory")
    agents = m["agents"]
    _strings(agents, "agents")
    if not agents or m["agent"] not in agents:
        raise PackageError(
            "E_NO_ENTRYPOINT: agent must name one of the portable agents"
        )
    names = []
    for name in agents:
        path = relative_path(name)
        if (
            name not in files
            or not path.name.endswith("_agent.py")
            or not path.stem.isidentifier()
            or path.name == "basic_agent.py"
        ):
            raise PackageError(
                "E_AGENT: every agent must be a pinned portable *_agent.py"
            )
        names.append(path.name.casefold())
    if len(set(names)) != len(names):
        raise PackageError("E_AGENT: agent destination collision")
    for field in ("ui", "service"):
        if m.get(field) and m[field] not in files:
            raise PackageError("E_CLOSURE: " + field + " is not in files")
    for field in ("requires", "profiles", "permissions", "capabilities"):
        _strings(m[field], field)
    if "portable-agents/1" not in m["requires"]:
        raise PackageError("E_CONTRACT: requires must include portable-agents/1")
    if not isinstance(m["dependencies"], list):
        raise PackageError("E_CONTRACT: dependencies must be an explicit list")
    identities = set()
    for dep in m["dependencies"]:
        _object(dep, ("id", "publisher", "version", "package_sha256"))
        if (
            not isinstance(dep["id"], str)
            or not ID_PATTERN.fullmatch(dep["id"])
            or not isinstance(dep["publisher"], str)
            or not PUBLISHER_PATTERN.fullmatch(dep["publisher"])
        ):
            raise PackageError("E_DEPENDENCY: invalid application dependency identity")
        if (
            not isinstance(dep["version"], str)
            or not VERSION_PATTERN.fullmatch(dep["version"])
            or not _sha(dep["package_sha256"])
        ):
            raise PackageError(
                "E_UNPINNED_DEPENDENCY: require exact version and package_sha256"
            )
        identity = (dep["publisher"], dep["id"])
        if identity in identities or identity == (m["publisher"], m["id"]):
            raise PackageError("E_DEPENDENCY: duplicate or self application dependency")
        identities.add(identity)
    if not isinstance(m["services"], list):
        raise PackageError("E_CONTRACT: services must be an explicit list")
    for service in m["services"]:
        _object(service, ("id", "definition", "images"))
        if (
            not isinstance(service["id"], str)
            or not service["id"]
            or not isinstance(service["definition"], str)
            or service["definition"] not in files
            or not isinstance(service["images"], list)
        ):
            raise PackageError(
                "E_CLOSURE: service identity, definition and image pins required"
            )
        for image in service["images"]:
            if not isinstance(image, str) or not re.fullmatch(
                r"[^\s@]+@sha256:[0-9a-f]{64}", image
            ):
                raise PackageError(
                    "E_UNPINNED_DEPENDENCY: service images require digest pins"
                )
    state = m["state"]
    _object(state, ("version", "preserve", "seeds"))
    if (
        not isinstance(state["version"], str)
        or not state["version"]
        or state["preserve"] is not True
    ):
        raise PackageError("E_STATE: a versioned, preserved state contract is required")
    if not isinstance(state["seeds"], dict):
        raise PackageError(
            "E_STATE: seeds must map relative state paths to pinned files"
        )
    seed_paths = set()
    for target, source in state["seeds"].items():
        path = relative_path(target)
        if target.casefold() in seed_paths:
            raise PackageError("E_STATE: state seed path collision")
        seed_paths.add(target.casefold())
        if not isinstance(source, str) or source not in files:
            raise PackageError("E_CLOSURE: state seed is not in files")
        if any(
            str(parent).casefold() in {x.casefold() for x in state["seeds"]}
            for parent in path.parents
            if str(parent) != "."
        ):
            raise PackageError("E_STATE: a state seed cannot also be a directory")
    if m["lifecycle"] != LIFECYCLE:
        raise PackageError(
            "E_UNSUPPORTED_REQUIREMENT: lifecycle hooks require a qualified adapter"
        )
    providers = m["providers"]
    _object(providers, ("mode", "spend_limit", "egress_allowlist"))
    if providers["mode"] not in ("none", "host"):
        raise PackageError(
            "E_UNSUPPORTED_REQUIREMENT: use the Grail host provider; no bundled model loop"
        )
    provenance = m["provenance"]
    _object(provenance, ("status", "source", "deployed", "job_verified"))
    if (
        provenance["status"] not in ("development", "qualified")
        or not isinstance(provenance["source"], str)
        or not provenance["source"]
    ):
        raise PackageError(
            "E_PROVENANCE: explicit source and development/qualified status required"
        )
    if (
        type(provenance["deployed"]) is not bool
        or type(provenance["job_verified"]) is not bool
    ):
        raise PackageError(
            "E_PROVENANCE: deployed and job_verified must be explicit booleans"
        )
    if _local(m) != ("local_docker" in m):
        raise PackageError(
            "E_UNSUPPORTED_REQUIREMENT: local_docker and mandatory local-docker/1 must appear together"
        )
    if _local(m):
        _validate_local_docker(m)


def _validate_local_docker(m):
    local = m["local_docker"]
    _object(
        local,
        (
            "schema",
            "component_lock",
            "loader",
            "requirements_file",
            "jobs_file",
            "state_lifecycle_file",
            "intelligence",
            "exhaust",
            "readiness",
        ),
    )
    if local["schema"] != LOCAL_DOCKER_SCHEMA or "owned-files/1" not in m["requires"]:
        raise PackageError(
            "E_LOCAL_DOCKER: unsupported schema or missing owned-files/1"
        )
    loader = local["loader"]
    _object(loader, ("contract", "entrypoint", "descriptor", "support"))
    if (
        loader["contract"] != LOADER_CONTRACT
        or loader["entrypoint"] != "singleton/scotty_agent.py"
        or loader["descriptor"] != "singleton/scotty_revision.json"
        or not isinstance(loader["support"], str)
        or re.fullmatch(r"singleton/scotty_support_[0-9a-f]{64}/", loader["support"])
        is None
        or m["agents"] != [loader["entrypoint"]]
        or m["agent"] != loader["entrypoint"]
    ):
        raise PackageError(
            "E_LOADER_CONTRACT: local-docker/1 requires the complete single-Scotty layout"
        )
    for name in (
        "component_lock",
        "requirements_file",
        "jobs_file",
        "state_lifecycle_file",
    ):
        value = local[name]
        if (
            not isinstance(value, str)
            or value not in m["files"]
            or not value.endswith(".json")
        ):
            raise PackageError(
                "E_LOCAL_DOCKER: referenced declaration must be a pinned JSON file: "
                + name
            )
    for name in ("entrypoint", "descriptor"):
        if loader[name] not in m["files"]:
            raise PackageError("E_LOADER_CLOSURE: missing pinned " + name)
    if loader["support"] + "SCOTTY_CAPABILITY_LOCK.json" not in m["files"]:
        raise PackageError("E_LOADER_CLOSURE: missing pinned support manifest")
    intelligence = local["intelligence"]
    _object(
        intelligence,
        (
            "runtime",
            "version",
            "model",
            "concurrency",
            "cloud_inference",
            "tools",
            "usage",
            "monetary_cost",
            "hard_spend_cap",
            "other_paid_providers",
        ),
    )
    if (
        intelligence
        != {
            "runtime": "official-copilot-cli-in-docker",
            "version": "1.0.88",
            "model": "gpt-5-mini",
            "concurrency": 2,
            "cloud_inference": True,
            "tools": [],
            "usage": "measured-when-available",
            "monetary_cost": None,
            "hard_spend_cap": None,
            "other_paid_providers": "disabled",
        }
        or not _integer(intelligence["concurrency"])
        or intelligence["cloud_inference"] is not True
    ):
        raise PackageError(
            "E_UNSUPPORTED_REQUIREMENT: unqualified local intelligence policy"
        )
    if local["exhaust"] != {
        "wire": "rapp/1",
        "frame_kind": "memory.tool-call",
        "receipt_variant": "session",
        "capsule_variant": "rapplication",
        "capsule_contains": "selected-outputs-and-producing-source-not-full-app-state",
        "verification": "unsigned-structural-only",
    }:
        raise PackageError("E_UNSUPPORTED_REQUIREMENT: unqualified exhaust contract")
    readiness = local["readiness"]
    _object(
        readiness,
        ("candidate", "fresh_install", "recreation", "live_results"),
        (
            "package_verification",
            "fresh_install_profiles",
            "jobs",
            "current_health",
            "restart",
            "provider_blockers",
            "acceptance_suite",
        ),
    )
    _enum(readiness["candidate"], {"experimental", "qualified"}, "candidate readiness")
    _enum(readiness["fresh_install"], READINESS_STATUSES, "fresh-install readiness")
    for field in ("recreation", "restart"):
        if field not in readiness:
            continue
        _object(
            readiness[field],
            ("dify", "openshorts"),
            LOCAL_APPS - {"dify", "openshorts"},
        )
        for value in readiness[field].values():
            _enum(value, READINESS_STATUSES, field)
    if (
        not isinstance(readiness["live_results"], str)
        or readiness["live_results"] not in m["files"]
    ):
        raise PackageError(
            "E_LOCAL_DOCKER: explicit pinned, candidate-specific readiness is required"
        )
    if "package_verification" in readiness:
        _enum(
            readiness["package_verification"], READINESS_STATUSES, "package readiness"
        )
    for field in ("fresh_install_profiles", "jobs"):
        if field not in readiness:
            continue
        if not isinstance(readiness[field], dict):
            raise PackageError("E_READINESS: readiness projection must be an object")
        for name, value in readiness[field].items():
            _text(name, field)
            if field == "jobs":
                _object(value, ("mode", "status"))
                _text(value["mode"], "job mode")
                value = value["status"]
            _enum(value, READINESS_STATUSES, field)
    if "current_health" in readiness:
        health = readiness["current_health"]
        _object(health, ("status", "observed_at"))
        _enum(
            health["status"],
            {"unknown", "healthy", "unhealthy", "stopped"},
            "current health",
        )
        if health["observed_at"] is not None and not isinstance(
            health["observed_at"], str
        ):
            raise PackageError("E_READINESS: health time must be explicit text or null")
    if "provider_blockers" in readiness:
        _strings(readiness["provider_blockers"], "provider blockers")
    if "acceptance_suite" in readiness:
        suite = readiness["acceptance_suite"]
        _object(suite, ("revision", "status"))
        if suite["revision"] is not None and not isinstance(suite["revision"], str):
            raise PackageError(
                "E_READINESS: acceptance revision must be explicit text or null"
            )
        _enum(suite["status"], READINESS_STATUSES, "acceptance suite")


def require_supported(m):
    """Pure support decision; no runtime, filesystem or Docker probes."""
    validate_contract(m)
    unsupported = set(m["requires"]) - FEATURES
    if unsupported or m["profiles"] or set(m["permissions"]) - {"host-user"}:
        raise PackageError(
            "E_UNSUPPORTED_REQUIREMENT: no qualified enforcer for "
            + repr(
                sorted(unsupported)
                + m["profiles"]
                + sorted(set(m["permissions"]) - {"host-user"})
            )
        )
    if m.get("service") or m.get("twin") or (m["services"] and not _local(m)):
        raise PackageError(
            "E_UNSUPPORTED_REQUIREMENT: service/twin activation needs a qualified adapter; no partial install"
        )
    if (
        m["providers"]["spend_limit"] is not None
        or m["providers"]["egress_allowlist"] is not None
    ):
        raise PackageError(
            "E_UNSUPPORTED_REQUIREMENT: no per-app spend/egress enforcer"
        )


def application_files(root):
    root = _absolute(root)
    _check_path(root, directory=True)
    result = {}
    for directory, names, filenames in os.walk(root, followlinks=False):
        names[:] = sorted(
            name
            for name in names
            if name != "__pycache__"
            and not (Path(directory) == root and name in IGNORED_ROOTS)
        )
        for name in names + sorted(filenames):
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if name == "__pycache__" or rel in ("manifest.json", "index_entry.json"):
                continue
            relative_path(rel)
            if path.is_symlink():
                raise PackageError("E_PATH: symlinks cannot be distributed")
            if name in filenames:
                result[rel] = _read_regular(path, limit=MAX_EXPANDED_BYTES)
        if (
            len(result) > MAX_FILES
            or sum(map(len, result.values())) > MAX_EXPANDED_BYTES
        ):
            raise PackageError("E_PACKAGE_SIZE: application closure exceeds its bound")
    return result


def verify_closure(m, files):
    validate_contract(m)
    if not isinstance(files, dict) or set(files) != set(m["files"]):
        raise PackageError("E_CLOSURE: missing or undeclared files")
    if any(not isinstance(blob, bytes) for blob in files.values()):
        raise PackageError("E_CLOSURE: file contents must be bytes")
    if sum(map(len, files.values())) > MAX_EXPANDED_BYTES:
        raise PackageError("E_PACKAGE_SIZE: expanded closure exceeds 20 MiB")
    for name, blob in files.items():
        if digest(blob) != m["files"][name]:
            raise PackageError("E_FILE_DIGEST: " + name)
    for name in m["agents"]:
        if len(files[name]) > MAX_SUPPORT_FILE_BYTES:
            raise PackageError(
                "E_AGENT_SIZE: portable entrypoint exceeds the 4 MiB loader bound"
            )
        try:
            tree = ast.parse(files[name])
        except (SyntaxError, ValueError, UnicodeError) as exc:
            raise PackageError("E_AGENT_SYNTAX: " + name) from exc
        _portable_agent(tree, name)
        allowed = set(sys.stdlib_module_names) | {"agents", "basic_agent"}
        for node in ast.walk(tree):
            modules = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for module in modules:
                if (
                    module.split(".")[0] not in allowed
                    or module.startswith("agents.")
                    and module != "agents.basic_agent"
                ):
                    raise PackageError("E_UNSUPPORTED_IMPORT: " + module)
    if _local(m):
        _verify_loader(m, files)
        _verify_local_declarations(m, files)


def _portable_agent(tree, name):
    aliases = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module in ("agents.basic_agent", "basic_agent")
        for alias in node.names
        if alias.name == "BasicAgent"
    }
    manifests = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__manifest__"
            for target in node.targets
        )
    ]
    if not aliases or len(manifests) != 1 or not isinstance(manifests[0], ast.Dict):
        raise PackageError(
            "E_AGENT: portable entrypoints need BasicAgent and one literal __manifest__: "
            + name
        )
    try:
        manifest = ast.literal_eval(manifests[0])
    except (ValueError, TypeError, RecursionError) as exc:
        raise PackageError("E_AGENT: manifest must be literal data") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "rapp-agent/1.0"
        or any(
            not isinstance(manifest.get(key), str) or not manifest[key]
            for key in ("name", "version", "description")
        )
    ):
        raise PackageError("E_AGENT: incomplete portable agent manifest")
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if len(classes) > 256:
        raise PackageError(
            "E_AGENT: entrypoint class inventory exceeds its static validation bound"
        )
    descendants = set(aliases)
    for _ in classes:
        descendants.update(
            node.name
            for node in classes
            if any(
                isinstance(base, ast.Name) and base.id in descendants
                for base in node.bases
            )
        )
    visible = [
        node
        for node in classes
        if not node.name.startswith("_")
        and (
            node.name in descendants
            or any(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == "perform"
                for item in node.body
            )
        )
    ]
    if (
        len(visible) != 1
        or not visible[0].name.endswith("Agent")
        or not any(
            isinstance(base, ast.Name) and base.id in aliases
            for base in visible[0].bases
        )
        or not any(
            isinstance(item, ast.FunctionDef) and item.name == "perform"
            for item in visible[0].body
        )
    ):
        raise PackageError(
            "E_AGENT: require exactly one public direct BasicAgent delegate with explicit perform"
        )


def _verify_loader(m, files):
    loader = m["local_docker"]["loader"]
    if len(files[loader["descriptor"]]) > MAX_SUPPORT_FILE_BYTES:
        raise PackageError(
            "E_LOADER_CLOSURE: descriptor exceeds the loader's file bound"
        )
    descriptor = _json(files[loader["descriptor"]])
    _object(
        descriptor, ("schema", "loader_contract", "entrypoint_sha256", "support_sha256")
    )
    revision = loader["support"].rstrip("/").rsplit("_", 1)[-1]
    if (
        descriptor["schema"] != "scotty-agent-revision/1"
        or descriptor["loader_contract"] != LOADER_CONTRACT
        or descriptor["support_sha256"] != revision
        or descriptor["entrypoint_sha256"] != digest(files[loader["entrypoint"]])
    ):
        raise PackageError(
            "E_LOADER_BINDING: descriptor does not bind this bootstrap and support"
        )
    prefix = loader["support"]
    lock_name = prefix + "SCOTTY_CAPABILITY_LOCK.json"
    if digest(files[lock_name]) != revision:
        raise PackageError(
            "E_LOADER_BINDING: support directory must name the capability lock SHA-256"
        )
    lock = _json(files[lock_name])
    _object(lock, ("schema", "grail_commit", "files"))
    if (
        lock["schema"] != "scotty-capability-files/1"
        or lock["grail_commit"] != GRAIL["commit"]
        or not isinstance(lock["files"], list)
        or not 1 <= len(lock["files"]) <= 512
    ):
        raise PackageError("E_LOADER_CONTRACT: invalid capability lock")
    expected = {lock_name}
    for item in lock["files"]:
        _object(item, ("path", "bytes", "sha256"))
        path = relative_path(item["path"])
        name = prefix + str(path)
        if (
            name in expected
            or name not in files
            or type(item["bytes"]) is not int
            or not 0 <= item["bytes"] <= MAX_SUPPORT_FILE_BYTES
            or not _sha(item["sha256"])
            or item["path"] == "brainstem.py"
            or item["bytes"] != len(files[name])
            or item["sha256"] != digest(files[name])
        ):
            raise PackageError(
                "E_LOADER_CLOSURE: missing, duplicated or changed support file"
            )
        expected.add(name)
    if prefix + "agents/scotty_agent.py" not in expected:
        raise PackageError("E_LOADER_CLOSURE: missing scoped Scotty implementation")
    if {name for name in files if name.startswith(prefix)} != expected:
        raise PackageError("E_LOADER_CLOSURE: undeclared support file")


def _verify_local_declarations(m, files):
    """Closed stdlib counterpart to local-docker.schema.json's referenced $defs."""
    local = m["local_docker"]
    references = {
        "componentLock": local["component_lock"],
        "hostProfiles": local["requirements_file"],
        "jobContracts": local["jobs_file"],
        "stateLifecycle": local["state_lifecycle_file"],
        "evidence": local["readiness"]["live_results"],
    }
    documents = {}
    for field, path in references.items():
        if len(files[path]) > MAX_DECLARATION_BYTES:
            raise PackageError("E_LOCAL_DOCKER: referenced declaration exceeds 256 KiB")
        documents[field] = _json(files[path])
    _component_lock(documents["componentLock"], m["files"])
    _host_profiles(documents["hostProfiles"])
    _job_contracts(documents["jobContracts"])
    _state_lifecycle(documents["stateLifecycle"])
    _readiness_evidence(documents["evidence"])
    _crosscheck_declarations(m, documents)
    return documents


def _public_input(value, *, locked):
    _object(value, ("url", "revision", "bytes", "sha256"))
    _text(value["url"], "source URL")
    try:
        url = urlsplit(value["url"])
        host = (url.hostname or "").lower()
        if (
            url.scheme != "https"
            or not host
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or url.port is not None
            or any(c.isspace() for c in value["url"])
            or "@" in value["url"]
            or host == "localhost"
            or host.startswith("[")
            or re.match(r"^[0-9]+(?:\.|$)", host)
            or ":" in host
            or host.endswith((".localhost", ".local", ".internal"))
        ):
            raise ValueError("not public HTTPS")
    except ValueError as exc:
        raise PackageError(
            "E_COMPONENTS: source inputs require credential-free public HTTPS URLs"
        ) from exc
    if value["revision"] is not None:
        _text(value["revision"], "source revision")
    if value["bytes"] is not None and (
        not _integer(value["bytes"]) or value["bytes"] < 1
    ):
        raise PackageError(
            "E_COMPONENTS: source length must be a positive integer or null"
        )
    if value["sha256"] is not None and not _sha(value["sha256"]):
        raise PackageError("E_COMPONENTS: invalid source digest")
    if locked and any(
        value[field] is None for field in ("revision", "bytes", "sha256")
    ):
        raise PackageError(
            "E_COMPONENTS: locked source inputs require complete immutable pins"
        )


def _component_lock(value, files):
    _object(value, ("schema", "mode", "components"))
    if value["schema"] != "rapp-local-components/1":
        raise PackageError("E_COMPONENTS: unsupported component lock")
    _enum(value["mode"], {"template", "locked"}, "component lock mode")
    _list(value["components"], "components", 1, 32)
    by_id = {}
    for component in value["components"]:
        _object(
            component, ("id", "source", "images", "inputs", "dependencies", "licenses")
        )
        name = component["id"]
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z][a-z0-9-]*", name) is None
            or name in by_id
        ):
            raise PackageError("E_COMPONENTS: invalid or duplicate component identity")
        by_id[name] = component
        _list(component["inputs"], "component inputs")
        for source in [component["source"], *component["inputs"]]:
            _public_input(source, locked=value["mode"] == "locked")
        _strings(component["dependencies"], "component dependencies")
        _list(component["images"], "component images", 1, 32)
        for image in component["images"]:
            _object(
                image,
                ("role", "platform", "reference", "build_recipe", "observed_image_id"),
            )
            _text(image["role"], "image role")
            _enum(
                image["platform"],
                {"linux/arm64", "linux/amd64"},
                "guest image platform",
            )
            reference = image["reference"]
            if reference is not None and (
                not isinstance(reference, str)
                or re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", reference) is None
            ):
                raise PackageError("E_COMPONENTS: registry images require digest pins")
            recipe = image["build_recipe"]
            if recipe is not None:
                relative_path(recipe)
                if recipe not in files:
                    raise PackageError("E_CLOSURE: image build recipe is not pinned")
            observed = image["observed_image_id"]
            if observed is not None and (
                not isinstance(observed, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", observed) is None
            ):
                raise PackageError("E_COMPONENTS: invalid observed local image ID")
            if value["mode"] == "locked" and reference is None and recipe is None:
                raise PackageError(
                    "E_COMPONENTS: locked image requires a digest or a pinned build recipe"
                )
        licenses = component["licenses"]
        _object(licenses, ("status", "files", "note"))
        _enum(licenses["status"], {"pending", "reviewed"}, "license review")
        _text(licenses["note"], "license note")
        _strings(licenses["files"], "license files")
        for path in licenses["files"]:
            relative_path(path)
            if path not in files:
                raise PackageError("E_CLOSURE: license input is not pinned")
    for name, component in by_id.items():
        if any(dep not in by_id or dep == name for dep in component["dependencies"]):
            raise PackageError("E_COMPONENTS: unresolved component dependency")
    active, visited = set(), set()

    def visit(name):
        if name in active:
            raise PackageError("E_COMPONENTS: cyclic component dependencies")
        if name in visited:
            return
        active.add(name)
        for dependency in by_id[name]["dependencies"]:
            visit(dependency)
        active.remove(name)
        visited.add(name)

    for name in by_id:
        visit(name)


def _host_profiles(value):
    _object(
        value,
        ("schema", "python_minimum", "grail", "tools", "profiles", "authentication"),
    )
    if (
        value["schema"] != "rapp-local-host-profiles/1"
        or value["python_minimum"] != "3.11"
        or value["grail"] != GRAIL
        or not _typed_equal(
            value["tools"],
            {
                "git": True,
                "docker": True,
                "compose_plugin": True,
                "local_daemon_only": True,
            },
        )
        or not _typed_equal(
            value["authentication"],
            {
                "provider": "github-copilot",
                "custody": "adopter-owned",
                "required_for_ai_jobs": True,
                "export_credentials": False,
            },
        )
    ):
        raise PackageError(
            "E_REQUIREMENTS: unsupported host, tool or authentication requirements"
        )
    _list(value["profiles"], "host profiles", 1, 8)
    identifiers = set()
    for profile in value["profiles"]:
        _object(
            profile,
            (
                "id",
                "host_os",
                "host_arch",
                "guest_platforms",
                "emulation",
                "qualification",
                "fresh_install",
                "reference_resources",
            ),
        )
        _text(profile["id"], "host profile identity")
        if (
            profile["id"] in identifiers
            or profile["host_os"] != "darwin"
            or profile["host_arch"] != "arm64"
            or type(profile["emulation"]) is not bool
        ):
            raise PackageError("E_REQUIREMENTS: duplicate or unsupported host profile")
        identifiers.add(profile["id"])
        _strings(profile["guest_platforms"], "guest platforms")
        if not profile["guest_platforms"] or set(profile["guest_platforms"]) - {
            "linux/arm64",
            "linux/amd64",
        }:
            raise PackageError("E_REQUIREMENTS: unsupported guest platform")
        _enum(
            profile["qualification"],
            {"development-reference", "candidate-qualified"},
            "profile qualification",
        )
        _enum(profile["fresh_install"], READINESS_STATUSES, "profile fresh install")
        resources = profile["reference_resources"]
        _object(resources, ("docker_vm_cpus", "docker_vm_memory_gib", "is_minimum"))
        if (
            not _integer(resources["docker_vm_cpus"])
            or resources["docker_vm_cpus"] < 1
            or not _number(resources["docker_vm_memory_gib"])
            or resources["docker_vm_memory_gib"] <= 0
            or resources["is_minimum"] is not False
        ):
            raise PackageError(
                "E_REQUIREMENTS: measured references must not be represented as minimums"
            )


def _parameter(value, depth=0):
    if depth > 32:
        raise PackageError("E_JOBS: job schema nesting exceeds the bound")
    _object(
        value,
        ("type",),
        (
            "description",
            "enum",
            "default",
            "minLength",
            "maxLength",
            "minimum",
            "maximum",
            "minItems",
            "maxItems",
            "uniqueItems",
            "pattern",
            "format",
            "items",
            "properties",
            "required",
            "additionalProperties",
        ),
    )
    kind = value["type"]
    _enum(
        kind,
        {"object", "array", "string", "integer", "number", "boolean", "null"},
        "parameter type",
    )
    if "description" in value and not isinstance(value["description"], str):
        raise PackageError("E_JOBS: parameter description must be text")
    if "enum" in value:
        _list(value["enum"], "parameter enum", 1)
    for name in ("minLength", "maxLength", "minItems", "maxItems"):
        if name in value and (not _integer(value[name]) or value[name] < 0):
            raise PackageError("E_JOBS: parameter bounds must be nonnegative integers")
    for name in ("minimum", "maximum"):
        if name in value and not _number(value[name]):
            raise PackageError("E_JOBS: parameter numeric bounds must be finite")
    if "uniqueItems" in value and type(value["uniqueItems"]) is not bool:
        raise PackageError("E_JOBS: uniqueItems must be boolean")
    if "pattern" in value and not isinstance(value["pattern"], str):
        raise PackageError("E_JOBS: pattern must be text")
    if "format" in value:
        _enum(value["format"], {"uri", "url"}, "parameter format")
    if "additionalProperties" in value and value["additionalProperties"] is not False:
        raise PackageError("E_JOBS: open job input objects are unsupported")
    if "required" in value:
        _strings(value["required"], "required job arguments")
    if "properties" in value:
        if not isinstance(value["properties"], dict):
            raise PackageError("E_JOBS: properties must be a closed object")
        for name, child in value["properties"].items():
            _text(name, "argument name")
            _parameter(child, depth + 1)
    if kind == "object" and (
        value.get("additionalProperties") is not False
        or not isinstance(value.get("properties"), dict)
        or not isinstance(value.get("required"), list)
        or set(value["required"]) - value["properties"].keys()
    ):
        raise PackageError(
            "E_JOBS: object inputs require closed properties and declared required fields"
        )
    if kind == "array" and "items" not in value:
        raise PackageError("E_JOBS: array inputs require typed items")
    if "items" in value:
        _parameter(value["items"], depth + 1)
    if "default" in value and not _parameter_value(value["default"], value):
        raise PackageError(
            "E_JOBS: default does not satisfy its declared parameter schema"
        )


def _parameter_value(value, schema):
    kind = schema["type"]
    types = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": _integer(value),
        "number": _number(value),
        "boolean": type(value) is bool,
        "null": value is None,
    }
    if not types[kind]:
        return False
    if "enum" in schema and not any(
        _typed_equal(value, candidate) for candidate in schema["enum"]
    ):
        return False
    if kind == "object":
        properties = schema["properties"]
        return (
            not (value.keys() - properties.keys())
            and not (set(schema["required"]) - value.keys())
            and all(
                _parameter_value(item, properties[name]) for name, item in value.items()
            )
        )
    if kind == "array":
        if (
            not schema.get("minItems", 0)
            <= len(value)
            <= schema.get("maxItems", MAX_DECLARATION_BYTES)
        ):
            return False
        if not all(_parameter_value(item, schema["items"]) for item in value):
            return False
        return not schema.get("uniqueItems") or len(
            {_json_value_key(item) for item in value}
        ) == len(value)
    if kind == "string":
        if (
            not schema.get("minLength", 0)
            <= len(value)
            <= schema.get("maxLength", MAX_DECLARATION_BYTES)
        ):
            return False
        if "pattern" in schema:
            if len(schema["pattern"]) > 256 or len(value) > 4096:
                raise PackageError(
                    "E_JOBS: patterned default exceeds the static validation bound"
                )
            _safe_default_pattern(schema["pattern"])
            try:
                if re.search(schema["pattern"], value) is None:
                    return False
            except re.error as exc:
                raise PackageError("E_JOBS: malformed parameter pattern") from exc
    if kind in ("integer", "number"):
        return (
            schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf)
        )
    return True


def _safe_default_pattern(pattern):
    # A single repeated atom and no branches/groups/backreferences keep static
    # default validation bounded without a subprocess or global signal handler.
    in_class = escaped = False
    repeats = 0
    for character in pattern:
        if escaped:
            if character.isdigit():
                raise PackageError(
                    "E_JOBS: backreferences in patterned defaults are unsupported"
                )
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "[" and not in_class:
            in_class = True
        elif character == "]" and in_class:
            in_class = False
        elif not in_class:
            if character in "()|{}":
                raise PackageError(
                    "E_JOBS: complex patterned defaults require separate qualification"
                )
            if character in "*+?":
                repeats += 1
    if repeats > 1:
        raise PackageError(
            "E_JOBS: multiple repetitions in patterned defaults are unsupported"
        )


def _job_contracts(value):
    _object(value, ("schema", "jobs"))
    if value["schema"] != "rapp-local-jobs/1":
        raise PackageError("E_JOBS: unsupported job contract")
    _list(value["jobs"], "jobs", 1, 64)
    identifiers = set()
    for job in value["jobs"]:
        _object(
            job,
            (
                "id",
                "application",
                "journey",
                "mode",
                "input_schema",
                "outputs",
                "providers",
                "limitations",
            ),
        )
        if (
            not isinstance(job["id"], str)
            or re.fullmatch(r"[a-z][a-z0-9-]*\.[a-z][a-z0-9_]*", job["id"]) is None
            or job["id"] in identifiers
        ):
            raise PackageError("E_JOBS: invalid or duplicate job identity")
        identifiers.add(job["id"])
        _enum(job["application"], LOCAL_APPS, "job application")
        _enum(
            job["journey"],
            {
                "diagnostic",
                "web-research",
                "editable-deck",
                "seo-project",
                "knowledge-answer",
                "captioned-shorts",
            },
            "job journey",
        )
        _text(job["mode"], "job mode")
        _parameter(job["input_schema"])
        if job["input_schema"]["type"] != "object":
            raise PackageError("E_JOBS: a job input must be a closed object")
        _list(job["outputs"], "job outputs", 1)
        for output in job["outputs"]:
            _object(output, ("name", "kind", "media_type", "required"))
            _text(output["name"], "job output name")
            _text(output["media_type"], "job output media type")
            _enum(output["kind"], {"artifact", "native-record"}, "job output kind")
            if type(output["required"]) is not bool:
                raise PackageError("E_JOBS: output requirement must be boolean")
        _strings(job["providers"], "job providers")
        if set(job["providers"]) - {"copilot"}:
            raise PackageError("E_UNSUPPORTED_REQUIREMENT: unsupported job provider")
        _strings(job["limitations"], "job limitations")


def _state_lifecycle(value):
    _object(
        value,
        (
            "schema",
            "owned_roots",
            "volumes",
            "sealed_inputs",
            "start",
            "stop",
            "uninstall",
            "upgrade",
            "recovery",
            "credential_export",
            "destructive_operations",
            "retention",
        ),
    )
    fixed = {
        "schema": "rapp-local-state-lifecycle/1",
        "sealed_inputs": True,
        "start": "explicit-use",
        "stop": "retain-data",
        "uninstall": "drain-stop-detach-preserve",
        "upgrade": "preserve-state",
        "recovery": "reconcile-no-replay",
        "credential_export": False,
        "destructive_operations": [],
    }
    if not _typed_equal({name: value[name] for name in fixed}, fixed):
        raise PackageError(
            "E_UNSUPPORTED_REQUIREMENT: unsupported state/lifecycle policy"
        )
    _strings(value["owned_roots"], "owned state roots")
    if not value["owned_roots"]:
        raise PackageError("E_STATE: at least one owned root must be declared")
    for root in value["owned_roots"]:
        relative_path(root)
    _strings(value["volumes"], "preserved volumes")
    _object(
        value["retention"], ("dify", "openshorts"), LOCAL_APPS - {"dify", "openshorts"}
    )
    for retention in value["retention"].values():
        _enum(retention, {"volume-backed", "stop-retain"}, "container layer retention")


def _readiness_evidence(value):
    _object(
        value,
        (
            "schema",
            "synthetic",
            "scope",
            "candidate_digest",
            "acceptance_suite_revision",
            "observed_at",
            "results",
            "limitations",
        ),
    )
    if (
        value["schema"] != "rapp-readiness-evidence/1"
        or type(value["synthetic"]) is not bool
    ):
        raise PackageError("E_READINESS: unsupported evidence contract")
    _enum(
        value["scope"],
        {"authoring-template", "candidate-verification"},
        "evidence scope",
    )
    if value["candidate_digest"] is not None and not _sha(value["candidate_digest"]):
        raise PackageError("E_READINESS: invalid evidence candidate digest")
    revision = value["acceptance_suite_revision"]
    if revision is not None and (
        not isinstance(revision, str)
        or re.fullmatch(r"[0-9a-f]{40,64}", revision) is None
    ):
        raise PackageError("E_READINESS: invalid acceptance-suite revision")
    if value["observed_at"] is not None and not isinstance(value["observed_at"], str):
        raise PackageError(
            "E_READINESS: evidence observation time must be text or null"
        )
    _list(value["results"], "evidence results")
    for result in value["results"]:
        _object(result, ("job", "mode", "status"))
        _text(result["job"], "evidence job")
        _text(result["mode"], "evidence mode")
        _enum(result["status"], READINESS_STATUSES, "evidence status")
    _strings(value["limitations"], "evidence limitations")


def _crosscheck_declarations(m, documents):
    local = m["local_docker"]
    component_ids = {
        component["id"] for component in documents["componentLock"]["components"]
    }
    jobs = {job["id"]: job for job in documents["jobContracts"]["jobs"]}
    for job in jobs.values():
        if job["application"] not in component_ids or not job["id"].startswith(
            job["application"] + "."
        ):
            raise PackageError("E_JOBS: job must belong to a declared component")
        if "copilot" in job["providers"] and "intelligence" not in component_ids:
            raise PackageError(
                "E_JOBS: Copilot jobs require the intelligence component"
            )
    readiness = local["readiness"]
    for name, claim in readiness.get("jobs", {}).items():
        if name not in jobs or jobs[name]["mode"] != claim["mode"]:
            raise PackageError("E_READINESS: unknown job or mode claim")
    evidence = documents["evidence"]
    for result in evidence["results"]:
        if result["job"] not in jobs or jobs[result["job"]]["mode"] != result["mode"]:
            raise PackageError(
                "E_READINESS: evidence must identify a declared job/mode"
            )
    profiles = {
        profile["id"]: profile for profile in documents["hostProfiles"]["profiles"]
    }
    for name, status in readiness.get("fresh_install_profiles", {}).items():
        if name not in profiles or profiles[name]["fresh_install"] != status:
            raise PackageError("E_READINESS: host-profile installation facts disagree")
    for app in ("dify", "openshorts"):
        if (
            readiness["recreation"][app] != "passed"
            and documents["stateLifecycle"]["retention"][app] != "stop-retain"
        ):
            raise PackageError(
                "E_STATE: unqualified recreation must retain container layers"
            )
    if documents["componentLock"]["mode"] == "template" or evidence["synthetic"]:
        if (
            readiness["candidate"] != "experimental"
            or readiness["fresh_install"] != "pending"
            or m["provenance"]["deployed"]
            or m["provenance"]["job_verified"]
            or evidence["scope"] != "authoring-template"
            or evidence["candidate_digest"] is not None
            or evidence["acceptance_suite_revision"] is not None
            or evidence["observed_at"] is not None
            or any(result["status"] == "passed" for result in evidence["results"])
            or "passed" in readiness["recreation"].values()
            or any(
                claim["status"] == "passed"
                for claim in readiness.get("jobs", {}).values()
            )
        ):
            raise PackageError(
                "E_READINESS: synthetic authoring material cannot qualify runtime outcomes"
            )
    elif (
        evidence["candidate_digest"]
        != local["loader"]["support"].rstrip("/").rsplit("_", 1)[-1]
    ):
        raise PackageError(
            "E_READINESS: evidence must identify the exact candidate support revision"
        )


def require_installable(m, files):
    """Static distribution gate, separate from valid inspect-only authoring data."""
    require_supported(m)
    verify_closure(m, files)
    if _local(m):
        documents = _verify_local_declarations(m, files)
        if documents["componentLock"]["mode"] != "locked":
            raise PackageError(
                "E_COMPONENTS_TEMPLATE: template input pins are not installable; use a locked candidate"
            )
        return documents
    return None


def build_package(root, manifest=None):
    root = Path(root)
    manifest = (
        manifest
        if manifest is not None
        else _json(_read_regular(root / "manifest.json"))
    )
    files = application_files(root)
    verify_closure(manifest, files)
    envelope = {
        "schema": PACKAGE_SCHEMA,
        "type": "rapplication",
        "application": manifest,
    }
    envelope_bytes = canonical_json(envelope)
    if len(envelope_bytes) + sum(map(len, files.values())) > MAX_EXPANDED_BYTES:
        raise PackageError(
            "E_PACKAGE_SIZE: envelope and expanded closure exceed 20 MiB"
        )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, blob in [("manifest.json", envelope_bytes)] + [
            ("application/" + n, b) for n, b in sorted(files.items())
        ]:
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100400 << 16
            archive.writestr(info, blob)
    blob = out.getvalue()
    if len(blob) > MAX_PACKAGE_BYTES:
        raise PackageError("E_PACKAGE_SIZE: package exceeds 5 MiB")
    return blob


def read_package(blob, expected_sha256):
    if (
        not isinstance(blob, bytes)
        or not _sha(expected_sha256)
        or digest(blob) != expected_sha256
    ):
        raise PackageError(
            "E_PACKAGE_DIGEST: the complete package does not match its pin"
        )
    if len(blob) > MAX_PACKAGE_BYTES:
        raise PackageError("E_PACKAGE_SIZE: package exceeds 5 MiB")
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            names = archive.namelist()
            if len(names) > MAX_FILES + 1 or len(names) != len(
                {n.casefold() for n in names}
            ):
                raise PackageError(
                    "E_PACKAGE_PATH: duplicate or excessive archive members"
                )
            for info in archive.infolist():
                relative_path(info.filename)
                mode = stat.S_IFMT(info.external_attr >> 16)
                if info.is_dir() or mode not in (0, stat.S_IFREG) or info.flag_bits & 1:
                    raise PackageError(
                        "E_PACKAGE_PATH: only unencrypted regular files are supported"
                    )
            if sum(i.file_size for i in archive.infolist()) > MAX_EXPANDED_BYTES:
                raise PackageError("E_PACKAGE_SIZE: expanded package exceeds 20 MiB")
            if "manifest.json" not in names:
                raise PackageError("E_PACKAGE_SCHEMA: missing envelope")
            envelope = _json(archive.read("manifest.json"))
            _object(envelope, ("schema", "type", "application"))
            if (
                envelope["schema"] != PACKAGE_SCHEMA
                or envelope["type"] != "rapplication"
            ):
                raise PackageError(
                    "E_PACKAGE_SCHEMA: historical cartridges are not an old-host fallback"
                )
            if any(
                n != "manifest.json" and not n.startswith("application/") for n in names
            ):
                raise PackageError("E_PACKAGE_PATH: unexpected archive member")
            files = {
                n[len("application/") :]: archive.read(n)
                for n in names
                if n.startswith("application/")
            }
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
        raise PackageError("E_PACKAGE: invalid or unsupported cartridge") from exc
    verify_closure(envelope["application"], files)
    return envelope["application"], files


def _absolute(path):
    path = Path(path)
    if ".." in path.parts:
        raise PackageError("E_PATH: traversal is not an installation target")
    return Path(os.path.abspath(path))


def _check_path(path, *, directory=False, missing=False):
    path = _absolute(path)
    for current in (*reversed(path.parents), path):
        try:
            info = current.lstat()
        except FileNotFoundError:
            if missing:
                return path
            raise
        if stat.S_ISLNK(info.st_mode):
            raise PackageError("E_PATH: linked installation path")
        if current != path or directory:
            if not stat.S_ISDIR(info.st_mode):
                raise PackageError("E_PATH: expected a directory")
        elif directory is None and stat.S_ISDIR(info.st_mode):
            pass
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PackageError("E_PATH: expected an unlinked regular file")
    return path


@contextlib.contextmanager
def _directory(path):
    path = _absolute(path)
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        yield fd
    except (NotADirectoryError, OSError) as exc:
        if isinstance(exc, NotADirectoryError) or exc.errno == errno.ELOOP:
            raise PackageError(
                "E_PATH: linked or non-directory installation path"
            ) from exc
        raise
    finally:
        os.close(fd)


def _read_regular(path, *, limit=MAX_EXPANDED_BYTES, with_stat=False):
    path = _absolute(path)
    with _directory(path.parent) as parent:
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        try:
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > limit
            ):
                raise PackageError(
                    "E_PATH: file is linked, nonregular or exceeds its bound"
                )
            with os.fdopen(fd, "rb", closefd=False) as stream:
                value = stream.read(limit + 1)
            after = os.fstat(fd)
            if len(value) > limit or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise PackageError("E_PATH: file changed while being read")
            return (value, after) if with_stat else value
        finally:
            os.close(fd)


def _safe_target(root, rel):
    relative_path(rel)
    return _check_path(Path(root) / rel, directory=None, missing=True)


def verify_grail(root):
    """Verify the unchanged pin by installer-owned hashes, never supplied metadata."""
    root = _absolute(root)
    try:
        _check_path(root, directory=True)
        for name, sha in GRAIL_FILES.items():
            if digest(_read_regular(root / name)) != sha:
                raise PackageError(
                    "E_GRAIL_UPGRADE_REQUIRED: runtime bytes differ from the pinned Grail. "
                    + UPGRADE_HELP
                )
        # The official Git layout carries an additional commit assertion. A
        # byte-identical public distribution has no .git; its pinned code is
        # checked above just as strictly, and its persona remains owned state.
        if root.name == "rapp_brainstem" and (root.parent / ".git").exists():
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            command = ["git", "--no-replace-objects", "-C", str(root)]
            commit = subprocess.run(
                command + ["rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            ).stdout.strip()
            if commit != GRAIL["commit"]:
                raise PackageError(
                    "E_GRAIL_UPGRADE_REQUIRED: Git commit differs from the pinned Grail. "
                    + UPGRADE_HELP
                )
            top = subprocess.run(
                command + ["rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            ).stdout.strip()
            if _absolute(top) != root.parent:
                raise PackageError(
                    "E_GRAIL_UPGRADE_REQUIRED: runtime Git layout differs. "
                    + UPGRADE_HELP
                )
            tree = subprocess.run(
                command
                + [
                    "ls-tree",
                    "-rz",
                    "--full-tree",
                    GRAIL["commit"],
                    "--",
                    "rapp_brainstem",
                ],
                check=True,
                capture_output=True,
                timeout=15,
                env=env,
            ).stdout
            if not tree:
                raise PackageError(
                    "E_GRAIL_UPGRADE_REQUIRED: runtime Git tree is missing. "
                    + UPGRADE_HELP
                )
            for record in tree.rstrip(b"\0").split(b"\0"):
                metadata, name = record.split(b"\t", 1)
                mode, kind, expected = metadata.split()
                relative = PurePosixPath(name.decode()).relative_to("rapp_brainstem")
                if "tests" in relative.parts:
                    continue
                if relative.suffix not in (
                    ".py",
                    ".html",
                    ".js",
                    ".css",
                    ".sh",
                    ".ps1",
                    ".cmd",
                ) and relative.name not in ("VERSION", "requirements.txt"):
                    continue
                if mode not in (b"100644", b"100755") or kind != b"blob":
                    raise PackageError(
                        "E_GRAIL_UPGRADE_REQUIRED: unqualified runtime file type. "
                        + UPGRADE_HELP
                    )
                contents = _read_regular(root / str(relative))
                actual = hashlib.sha1(
                    b"blob " + str(len(contents)).encode() + b"\0" + contents
                ).hexdigest()
                if actual != expected.decode("ascii"):
                    raise PackageError(
                        "E_GRAIL_UPGRADE_REQUIRED: tracked runtime bytes differ. "
                        + UPGRADE_HELP
                    )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PackageError(
            "E_GRAIL_UPGRADE_REQUIRED: cannot verify current Grail. " + UPGRADE_HELP
        ) from exc
    return root


def preflight_device(m, root, files=None):
    """Explicit install/use only; never materializes images or starts a service."""
    require_supported(m)
    documents = None
    if _local(m):
        if files is None:
            raise PackageError(
                "E_CLOSURE: local device preflight requires the complete pinned declarations"
            )
        documents = require_installable(m, files)
    minimum = (3, 11) if _local(m) else (3, 10)
    if sys.version_info < minimum:
        raise PackageError(
            f"E_PYTHON_UPGRADE_REQUIRED: Python {minimum[0]}.{minimum[1]}+ is required"
        )
    if (
        os.name != "posix"
        or not hasattr(os, "O_NOFOLLOW")
        or sys.platform not in ("darwin", "linux")
    ):
        raise PackageError(
            "E_UNSUPPORTED_DEVICE: atomic owned installation requires macOS or Linux"
        )
    exclusive_rename = "renameatx_np" if sys.platform == "darwin" else "renameat2"
    if getattr(ctypes.CDLL(None, use_errno=True), exclusive_rename, None) is None:
        raise PackageError(
            "E_UNSUPPORTED_DEVICE: exclusive atomic rename is unavailable"
        )
    root = verify_grail(root)
    _check_path(root / "agents", directory=True)
    for directory in (root, root / "agents"):
        info = directory.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise PackageError(
                "E_PATH: Grail and its discovery directory must be owner-controlled"
            )
    if not _local(m):
        return root
    if shutil.which("git") is None:
        raise PackageError(
            "E_GIT_REQUIRED: the declared public-source toolchain requires Git"
        )
    host_os = platform.system().lower()
    host_arch = {"aarch64": "arm64"}.get(
        platform.machine().lower(), platform.machine().lower()
    )
    if not any(
        profile["host_os"] == host_os and profile["host_arch"] == host_arch
        for profile in documents["hostProfiles"]["profiles"]
    ):
        raise PackageError(
            "E_UNSUPPORTED_DEVICE: this host does not match a declared qualified profile"
        )
    docker = shutil.which("docker")
    if docker is None:
        raise PackageError(
            "E_DOCKER_REQUIRED: install Docker CLI and its Compose v2 plugin"
        )
    try:
        for arguments in (["--version"], ["compose", "version", "--short"]):
            result = subprocess.run(
                [docker, *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
            if (
                result.returncode
                or not result.stdout.strip()
                or len(result.stdout) > 4096
            ):
                raise PackageError(
                    "E_DOCKER_REQUIRED: Docker CLI and Compose v2 version checks must succeed"
                )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PackageError(
            "E_DOCKER_REQUIRED: Docker CLI or Compose v2 is unavailable"
        ) from exc
    return root


def _optional_read(path, *, limit=MAX_EXPANDED_BYTES):
    try:
        return _read_regular(path, limit=limit)
    except FileNotFoundError:
        return None


def _private_directory(path):
    path = _absolute(path)
    if not path.parent.exists():
        _private_directory(path.parent)
    with _directory(path.parent) as parent:
        try:
            os.mkdir(path.name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
        fd = os.open(
            path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
        )
        try:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise PackageError(
                    "E_PATH: installation directories must be owner-controlled"
                )
        finally:
            os.close(fd)
    return path


def _write_new(path, blob, *, mode=0o400):
    path = _absolute(path)
    with _directory(path.parent) as parent:
        fd = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=parent,
        )
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(blob)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(parent)


def _rename_new(source, target):
    """Atomic no-replace publication of either a file or an entire directory."""
    source, target = _absolute(source), _absolute(target)
    libc = ctypes.CDLL(None, use_errno=True)
    name, flag = ("renameatx_np", 4) if sys.platform == "darwin" else ("renameat2", 1)
    operation = getattr(libc, name, None)
    if operation is None:
        raise PackageError(
            "E_UNSUPPORTED_DEVICE: exclusive atomic rename is unavailable"
        )
    operation.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    operation.restype = ctypes.c_int
    with _directory(source.parent) as old, _directory(target.parent) as new:
        result = operation(
            old, os.fsencode(source.name), new, os.fsencode(target.name), flag
        )
        if result:
            code = ctypes.get_errno()
            if code in (errno.EEXIST, errno.ENOTEMPTY):
                raise PackageError("E_COLLISION: publication target already exists")
            if code in (errno.ENOSYS, errno.EINVAL, errno.EXDEV):
                raise PackageError(
                    "E_UNSUPPORTED_DEVICE: same-filesystem exclusive rename is required"
                )
            raise OSError(code, os.strerror(code))
        os.fsync(old)
        os.fsync(new)


def _publish_file(path, contents, *, expected=None, mode=0o400):
    path = _absolute(path)
    _private_directory(path.parent)
    stage = path.parent / (".rapp-write-" + uuid.uuid4().hex)
    _write_new(stage, contents, mode=mode)
    try:
        current = _optional_read(path)
        if current is None:
            if expected is not None:
                raise PackageError(
                    "E_INSTALL_RACE: owned file disappeared before replacement"
                )
            _rename_new(stage, path)
        else:
            if expected is None or digest(current) != expected:
                raise PackageError(
                    "E_INSTALL_RACE: refusing to replace changed or unowned bytes"
                )
            with _directory(path.parent) as parent:
                os.replace(stage.name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
    finally:
        stage.unlink(missing_ok=True)


def _unlink_owned(path, expected):
    path = _absolute(path)
    try:
        contents, observed = _read_regular(path, with_stat=True)
    except FileNotFoundError:
        return False
    if digest(contents) != expected:
        raise PackageError("E_SOURCE_DRIFT: refusing to remove changed source")
    with _directory(path.parent) as parent:
        info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)

        def identity(value):
            return (
                value.st_dev,
                value.st_ino,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
                value.st_mode,
                value.st_nlink,
            )

        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or identity(info) != identity(observed)
        ):
            raise PackageError(
                "E_SOURCE_DRIFT: refusing to remove changed, linked or nonregular source"
            )
        os.unlink(path.name, dir_fd=parent)
        os.fsync(parent)
    return True


@contextlib.contextmanager
def _install_lock(root):
    import fcntl

    data = _private_directory(root / ".brainstem_data")
    with _directory(data) as parent:
        fd = os.open(
            "rapplication-install.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise PackageError("E_PATH: unsafe installation lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PackageError(
                "E_INSTALL_BUSY: another Store installation owns this runtime"
            ) from exc
        yield
    finally:
        # A persistent inode avoids splitting the lock when another installer is
        # opening it. The kernel releases the lock on process loss, not a PID guess.
        os.close(fd)


def _source_layout(m, files):
    if not _local(m):
        return {PurePosixPath(name).name: files[name] for name in m["agents"]}
    loader = m["local_docker"]["loader"]
    names = [loader["entrypoint"], loader["descriptor"]]
    names.extend(name for name in files if name.startswith(loader["support"]))
    return {name[len("singleton/") :]: files[name] for name in names}


def _source_directories(sources):
    return sorted(
        {
            str(parent)
            for name in sources
            for parent in PurePosixPath(name).parents
            if str(parent) != "."
        },
        key=lambda item: (item.count("/"), item),
    )


def _home(root, m):
    data = _check_path(root / ".brainstem_data", directory=True, missing=True)
    home = _safe_target(data, "rapplications/" + m["publisher"] + "/" + m["id"])
    for directory in (data, *reversed(home.relative_to(data).parents), home):
        if not directory.is_absolute():
            directory = data / directory
        if directory.exists():
            _check_path(directory, directory=True)
            info = directory.stat()
            if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise PackageError(
                    "E_PATH: managed application directories must be owner-controlled"
                )
    return home


def _make_receipt(m, sha, sources, *, detached=False):
    value = {
        "schema": "rapp-install/2.0",
        "status": "detached" if detached else "installed",
        "id": m["id"],
        "publisher": m["publisher"],
        "version": m["version"],
        "package_sha256": sha,
        "runtime": GRAIL,
        "state_version": m["state"]["version"],
        "agents": {PurePosixPath(name).name: m["files"][name] for name in m["agents"]},
        "sources": {name: digest(blob) for name, blob in sorted(sources.items())},
        "directories": _source_directories(sources),
        "loader_contract": LOADER_CONTRACT if _local(m) else None,
        "retained": RETAINED if detached else [],
    }
    if len(canonical_json(value)) > MAX_RECORD_BYTES:
        raise PackageError(
            "E_PACKAGE_SIZE: installation record exceeds its recovery bound"
        )
    return value


def _receipt(path):
    raw = _optional_read(path, limit=MAX_RECORD_BYTES)
    if raw is None:
        return None
    value = _json(raw)
    base = (
        "schema",
        "id",
        "publisher",
        "version",
        "package_sha256",
        "runtime",
        "state_version",
        "agents",
    )
    if isinstance(value, dict) and value.get("schema") == "rapp-install/1.0":
        _object(value, base)
    else:
        _object(
            value,
            (*base, "status", "sources", "directories", "loader_contract", "retained"),
        )
        if (
            value["schema"] != "rapp-install/2.0"
            or value["status"] not in ("installed", "detached")
            or not isinstance(value["sources"], dict)
            or value["loader_contract"] not in (None, LOADER_CONTRACT)
            or value["retained"] != (RETAINED if value["status"] == "detached" else [])
        ):
            raise PackageError("E_RECEIPT: invalid installation record")
        _strings(value["directories"], "receipt directories")
        for name in [*value["sources"], *value["directories"]]:
            relative_path(name)
        if any(not _sha(sha) for sha in value["sources"].values()):
            raise PackageError("E_RECEIPT: invalid owned source digest")
    if (
        value["runtime"] != GRAIL
        or not _sha(value["package_sha256"])
        or not isinstance(value["id"], str)
        or not ID_PATTERN.fullmatch(value["id"])
        or not isinstance(value["publisher"], str)
        or not PUBLISHER_PATTERN.fullmatch(value["publisher"])
        or not isinstance(value["version"], str)
        or not VERSION_PATTERN.fullmatch(value["version"])
        or not isinstance(value["state_version"], str)
        or not value["state_version"]
        or not isinstance(value["agents"], dict)
        or any(
            not isinstance(name, str)
            or "/" in name
            or not name.endswith("_agent.py")
            or name == "basic_agent.py"
            or not _sha(sha)
            for name, sha in value["agents"].items()
        )
    ):
        raise PackageError("E_RECEIPT: invalid installation record")
    return value


def _tree_inventory(root):
    """Bounded inventory that never follows links or silently skips hidden files."""
    root = _check_path(root, directory=True)
    files, directories = {}, []
    for directory, names, filenames in os.walk(root, followlinks=False):
        names.sort()
        for name in names:
            target = Path(directory) / name
            _check_path(target, directory=True)
            directories.append(target.relative_to(root).as_posix())
        for name in sorted(filenames):
            target = Path(directory) / name
            files[target.relative_to(root).as_posix()] = _read_regular(target)
        if (
            len(files) + len(directories) > MAX_FILES * 8
            or sum(map(len, files.values())) > MAX_EXPANDED_BYTES * 2
        ):
            raise PackageError("E_PATH: installed tree exceeds the inventory bound")
    return files, directories


def _verify_release(release, blob, m, files):
    if not release.exists():
        return False
    expected = {
        "application.egg": blob,
        "manifest.json": canonical_json(m),
        **{"files/" + name: content for name, content in files.items()},
    }
    actual, directories = _tree_inventory(release)
    if actual != expected or set(directories) != set(_source_directories(expected)):
        raise PackageError("E_IMMUTABLE_RELEASE: installed release closure differs")
    return True


def _owned_receipt(root, home, m):
    previous = _receipt(home / "installed.json")
    if previous is None:
        return None
    if any(previous[k] != m[k] for k in ("id", "publisher")):
        raise PackageError("E_RECEIPT_SCOPE: receipt belongs to another application")
    release = _safe_target(home, "releases/" + previous["package_sha256"])
    try:
        blob = _read_regular(release / "application.egg", limit=MAX_PACKAGE_BYTES)
        old, files = read_package(blob, previous["package_sha256"])
        require_supported(old)
        if any(old[key] != previous[key] for key in ("id", "publisher", "version")):
            raise PackageError("E_RECEIPT: release identity differs from receipt")
        if not _verify_release(release, blob, old, files):
            raise PackageError("E_RECEIPT: missing retained release")
        expected = _make_receipt(
            old,
            previous["package_sha256"],
            _source_layout(old, files),
            detached=previous.get("status") == "detached",
        )
        if previous["schema"] == "rapp-install/1.0":
            if _local(old) or any(
                previous[key] != expected[key] for key in previous if key != "schema"
            ):
                raise PackageError(
                    "E_RECEIPT: legacy receipt differs from the simple application"
                )
        elif previous != expected:
            raise PackageError("E_RECEIPT: receipt differs from its verified package")
    except FileNotFoundError as exc:
        raise PackageError("E_RECEIPT: retained release is incomplete") from exc
    return previous


def _ownership(previous):
    if previous is None or previous.get("status") == "detached":
        return {}, []
    return previous.get("sources", previous["agents"]), previous.get("directories", [])


def _pending(home):
    raw = _optional_read(home / "pending.json", limit=MAX_RECORD_BYTES)
    if raw is None:
        return None
    value = _json(raw)
    _object(
        value,
        (
            "schema",
            "operation",
            "id",
            "publisher",
            "package_sha256",
            "receipt_sha256",
            "previous_receipt_sha256",
            "sources",
            "directories",
            "hatcher",
        ),
    )
    if (
        value["schema"] != "rapp-install-pending/1"
        or value["operation"] not in ("install", "detach")
        or not _sha(value["receipt_sha256"])
        or value["previous_receipt_sha256"] is not None
        and not _sha(value["previous_receipt_sha256"])
    ):
        raise PackageError("E_RECOVERY_REQUIRED: invalid pending installation record")
    return value


def _transaction(m, sha, sources, receipt, previous_raw, *, operation, hatcher):
    value = {
        "schema": "rapp-install-pending/1",
        "operation": operation,
        "id": m["id"],
        "publisher": m["publisher"],
        "package_sha256": sha,
        "receipt_sha256": digest(canonical_json(receipt)),
        "previous_receipt_sha256": digest(previous_raw)
        if previous_raw is not None
        else None,
        "sources": {name: digest(blob) for name, blob in sorted(sources.items())},
        "directories": _source_directories(sources),
        "hatcher": hatcher,
    }
    if len(canonical_json(value)) > MAX_RECORD_BYTES:
        raise PackageError(
            "E_PACKAGE_SIZE: transaction record exceeds its recovery bound"
        )
    return value


def _check_pending(pending, desired, previous_raw):
    if pending is None:
        return
    if any(
        pending[key] != desired[key]
        for key in desired
        if key != "previous_receipt_sha256"
    ):
        raise PackageError(
            "E_RECOVERY_REQUIRED: complete the exact pending package and operation first"
        )
    current = digest(previous_raw) if previous_raw is not None else None
    if current not in (pending["previous_receipt_sha256"], pending["receipt_sha256"]):
        raise PackageError(
            "E_RECOVERY_REQUIRED: receipt changed during a pending transaction"
        )


def _check_case_collisions(path):
    path = _absolute(path)
    if not path.parent.exists():
        return
    with _directory(path.parent) as parent:
        if any(
            name != path.name and name.casefold() == path.name.casefold()
            for name in os.listdir(parent)
        ):
            raise PackageError(
                "E_COLLISION: case-insensitive installation path collision"
            )


def _check_sources(root, sources, previous, pending, *, local, complete=False):
    agents = root / "agents"
    owned, owned_directories = _ownership(previous)
    pending_sources = pending["sources"] if pending else {}
    pending_directories = pending["directories"] if pending else []
    directories = _source_directories(sources)
    for name in directories:
        target = _safe_target(agents, name)
        _check_case_collisions(target)
        if target.exists():
            _check_path(target, directory=True)
            if name not in owned_directories and name not in pending_directories:
                raise PackageError("E_SOURCE_CONFLICT: unowned support directory")
            if stat.S_IMODE(target.stat().st_mode) != 0o700:
                raise PackageError(
                    "E_SOURCE_DRIFT: support directories must remain 0700"
                )
        elif complete:
            raise PackageError("E_SOURCE_DRIFT: missing installed support directory")
    for directory in (name for name in directories if "/" not in name):
        target = agents / directory
        if target.exists():
            actual, nested = _tree_inventory(target)
            if any(directory + "/" + name not in sources for name in actual) or any(
                directory + "/" + name not in directories for name in nested
            ):
                raise PackageError(
                    "E_SOURCE_CONFLICT: undeclared files in support directory"
                )
    for name, blob in sources.items():
        target = _safe_target(agents, name)
        _check_case_collisions(target)
        contents = _optional_read(target)
        if contents is None:
            if complete:
                raise PackageError("E_SOURCE_DRIFT: missing installed source")
            continue
        sha = digest(contents)
        if sha not in {owned.get(name), pending_sources.get(name)}:
            raise PackageError(
                "E_AGENT_CONFLICT: refusing to replace unowned or modified source "
                + name
            )
        if local and (contents != blob or stat.S_IMODE(target.stat().st_mode) != 0o400):
            raise PackageError(
                "E_SCOTTY_CONFLICT: detach the existing Scotty before changing its selected revision"
            )
        if complete and contents != blob:
            raise PackageError("E_SOURCE_DRIFT: installed source differs")


def _check_other_scotty(root, hatcher=None):
    for path in sorted((root / "agents").glob("*_agent.py")):
        if path.name == "scotty_agent.py" or hatcher and path.name == hatcher["name"]:
            continue
        source = _read_regular(path, limit=MAX_EXPANDED_BYTES)
        try:
            tree = ast.parse(source)
        except (ValueError, SyntaxError, UnicodeError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "ScottyAgent"
                or isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and node.value.value == "Scotty"
                and any(
                    isinstance(target, ast.Attribute) and target.attr == "name"
                    for target in node.targets
                )
                or isinstance(node, ast.keyword)
                and node.arg == "name"
                and isinstance(node.value, ast.Constant)
                and node.value.value == "Scotty"
            ):
                raise PackageError(
                    "E_SCOTTY_CONFLICT: another top-level Scotty entrypoint already exists"
                )


def _check_scotty_cache(root, sources, previous, pending):
    cache = _check_path(root / "agents" / "__pycache__", directory=True, missing=True)
    if not cache.exists():
        return
    with _directory(cache) as fd:
        present = any(
            name.startswith("scotty_agent.") and name.endswith(".pyc")
            for name in os.listdir(fd)
        )
    if not present:
        return
    current = digest(sources["scotty_agent.py"])
    previous_sha = previous["agents"].get("scotty_agent.py") if previous else None
    pending_sha = pending["sources"].get("scotty_agent.py") if pending else None
    if current not in (previous_sha, pending_sha):
        raise PackageError(
            "E_AGENT_CONFLICT: unowned Scotty bytecode cache is retained; it cannot qualify a new bootstrap"
        )


def _check_version(previous, m, sha):
    if previous is None:
        return
    if previous["version"] == m["version"] and previous["package_sha256"] != sha:
        raise PackageError(
            "E_IMMUTABLE_VERSION: changed application bytes require a version bump"
        )
    if previous["state_version"] != m["state"]["version"]:
        raise PackageError(
            "E_STATE_MIGRATION_REQUIRED: preserve state and qualify migration before installing"
        )
    if (
        _local(m)
        and previous.get("loader_contract") == LOADER_CONTRACT
        and previous["agents"].get("scotty_agent.py") != m["files"][m["agent"]]
    ):
        raise PackageError(
            "E_LOADER_CONTRACT: stable bootstrap changes require a separately qualified loader migration"
        )

    def order(value):
        parts = [part.lstrip("0") or "0" for part in value.split(".")]
        return tuple((len(part), part) for part in parts)

    if order(m["version"]) < order(previous["version"]):
        raise PackageError(
            "E_ROLLBACK_REFUSED: old code needs a qualified state-compatible recovery"
        )


def _check_hatcher(root, hatcher, pending, home=None, previous=None):
    if hatcher is None:
        return
    _object(hatcher, ("name", "sha256"))
    name = hatcher["name"]
    if (
        not isinstance(name, str)
        or "/" in name
        or not name.endswith("_hatcher_agent.py")
        or not PurePosixPath(name).stem.isidentifier()
        or not _sha(hatcher["sha256"])
    ):
        raise PackageError(
            "E_HATCHER: retirement requires the exact transient hatcher name and hash"
        )
    source = _optional_read(_safe_target(root / "agents", name))
    if source is None and pending and pending["hatcher"] == hatcher:
        return
    if source is None and previous is not None and home is not None:
        archived = _optional_read(
            _safe_target(home, "installers/" + hatcher["sha256"] + ".py")
        )
        if archived is not None and digest(archived) == hatcher["sha256"]:
            return
    if source is None or digest(source) != hatcher["sha256"]:
        raise PackageError(
            "E_HATCHER: transient installer changed; it will not be removed"
        )


def _retire_hatcher(root, home, hatcher):
    if hatcher is None:
        return
    path = root / "agents" / hatcher["name"]
    contents = _optional_read(path)
    if contents is None:
        return
    if digest(contents) != hatcher["sha256"]:
        raise PackageError("E_HATCHER: transient installer changed during publication")
    archive = _safe_target(home, "installers/" + hatcher["sha256"] + ".py")
    saved = _optional_read(archive)
    if saved is None:
        _publish_file(archive, contents)
    elif saved != contents:
        raise PackageError("E_HATCHER: retained installer archive differs")
    _unlink_owned(path, hatcher["sha256"])


def _stage_tree(parent, files):
    _private_directory(parent)
    stage = parent / (".rapp-stage-" + uuid.uuid4().hex)
    with _directory(parent) as fd:
        try:
            os.mkdir(stage.name, mode=0o700, dir_fd=fd)
        except FileExistsError as exc:
            raise PackageError(
                "E_COLLISION: staging destination already exists"
            ) from exc
        os.fsync(fd)
    try:
        for name, blob in sorted(files.items()):
            relative_path(name)
            target = stage / name
            _private_directory(target.parent)
            _write_new(target, blob)
        with _directory(stage) as fd:
            os.fsync(fd)
        return stage
    except BaseException:
        shutil.rmtree(stage)
        raise


def _ensure_release(home, sha, blob, m, files):
    release = _safe_target(home, "releases/" + sha)
    if _verify_release(release, blob, m, files):
        return release
    staged_files = {
        "application.egg": blob,
        "manifest.json": canonical_json(m),
        **{"files/" + name: contents for name, contents in files.items()},
    }
    stage = _stage_tree(release.parent, staged_files)
    try:
        _rename_new(stage, release)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return release


def _ensure_sources(root, home, m, sources, previous, pending):
    agents = root / "agents"
    if _local(m):
        support = PurePosixPath(m["local_docker"]["loader"]["support"].rstrip("/")).name
        target = agents / support
        if not target.exists():
            nested = {
                name[len(support) + 1 :]: blob
                for name, blob in sources.items()
                if name.startswith(support + "/")
            }
            stage = _stage_tree(home / "staging", nested)
            try:
                _rename_new(stage, target)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
    primary = PurePosixPath(m["agent"]).name
    order = sorted(
        sources,
        key=lambda name: (
            name == primary,
            name == "scotty_revision.json",
            "/" not in name,
            name,
        ),
    )
    owned, _ = _ownership(previous)
    for name in order:
        target, blob = agents / name, sources[name]
        existing = _optional_read(target)
        if existing == blob:
            continue
        if existing is not None and (_local(m) or digest(existing) != owned.get(name)):
            raise PackageError("E_INSTALL_RACE: source changed during publication")
        _publish_file(
            target, blob, expected=digest(existing) if existing is not None else None
        )


def _verify_dependency(root, dep, ancestors=()):
    identity = dep["publisher"] + "/" + dep["id"]
    if identity in ancestors or len(ancestors) >= 64:
        raise PackageError("E_DEPENDENCY_CYCLE: dependency graph is cyclic or too deep")
    home = _home(root, dep)
    receipt = _owned_receipt(root, home, dep)
    if (
        receipt is None
        or receipt.get("status") == "detached"
        or any(
            receipt[k] != dep[k]
            for k in ("id", "publisher", "version", "package_sha256")
        )
        or _pending(home) is not None
    ):
        raise PackageError(
            "E_DEPENDENCY_REQUIRED: install the exact reviewed dependency first: "
            + identity
        )
    path = home / "releases" / dep["package_sha256"] / "application.egg"
    m, files = read_package(
        _read_regular(path, limit=MAX_PACKAGE_BYTES), dep["package_sha256"]
    )
    for child in m["dependencies"]:
        _verify_dependency(root, child, (*ancestors, identity))
    _check_sources(
        root, _source_layout(m, files), receipt, None, local=_local(m), complete=True
    )


def install_package(blob, expected_sha256, root, *, retire_hatcher=None):
    """Install a verified source closure; publish the discoverable entrypoint last.

    A durable, byte-bound pending record owns recoverable partial publication.
    It is not a success receipt. A retry must present the identical package.
    """
    m, files = read_package(blob, expected_sha256)
    require_supported(m)
    root = preflight_device(m, root, files)
    sources = _source_layout(m, files)
    home = _home(root, m)
    record = _safe_target(home, "installed.json")
    receipt = _make_receipt(m, expected_sha256, sources)

    def inspect():
        previous_raw = _optional_read(record)
        previous = _owned_receipt(root, home, m)
        _check_version(previous, m, expected_sha256)
        old_sources, _ = _ownership(previous)
        if set(old_sources) - set(sources):
            raise PackageError(
                "E_AGENT_MIGRATION_REQUIRED: detach old sources before changing the layout"
            )
        pending = _pending(home)
        plan = _transaction(
            m,
            expected_sha256,
            sources,
            receipt,
            previous_raw,
            operation="install",
            hatcher=retire_hatcher,
        )
        _check_pending(pending, plan, previous_raw)
        _check_hatcher(root, retire_hatcher, pending, home, previous)
        _check_sources(root, sources, previous, pending, local=_local(m))
        if _local(m):
            _check_other_scotty(root, retire_hatcher)
            _check_scotty_cache(root, sources, previous, pending)
        for dep in m["dependencies"]:
            _verify_dependency(root, dep)
        for target in m["state"]["seeds"]:
            _safe_target(home, "state/" + target)
        release = _safe_target(home, "releases/" + expected_sha256)
        _verify_release(release, blob, m, files)
        return previous_raw, previous, pending, plan

    inspect()
    with _install_lock(root):
        verify_grail(root)
        previous_raw, previous, pending, plan = inspect()
        if (
            previous == receipt
            and pending is None
            and (
                retire_hatcher is None
                or _optional_read(root / "agents" / retire_hatcher["name"]) is None
            )
            and all(
                _optional_read(root / "agents" / name) == contents
                for name, contents in sources.items()
            )
        ):
            _check_sources(
                root, sources, previous, None, local=_local(m), complete=True
            )
            if all((home / "state" / name).exists() for name in m["state"]["seeds"]):
                resumed = _resume_after_install(root, m)
                return {
                    "status": "already_installed",
                    "id": m["id"],
                    "package_sha256": expected_sha256,
                    "deployed": False,
                    "job_verified": False,
                    "runtime_resume": resumed,
                    "restart_required": resumed == "restart-Grail-required",
                }
        _private_directory(home)
        if pending is None:
            _publish_file(home / "pending.json", canonical_json(plan))
            pending = plan
        _ensure_release(home, expected_sha256, blob, m, files)
        for target, source in m["state"]["seeds"].items():
            path = _safe_target(home, "state/" + target)
            if not path.exists():
                _publish_file(path, files[source], mode=0o600)
        _ensure_sources(root, home, m, sources, previous, pending)
        _check_sources(root, sources, receipt, pending, local=_local(m), complete=True)
        _retire_hatcher(root, home, retire_hatcher)
        # No source, seed, or hatcher mutation is allowed after this commit point.
        new_record = canonical_json(receipt)
        current = _optional_read(record)
        if current not in (previous_raw, new_record):
            raise PackageError("E_INSTALL_RACE: receipt changed during publication")
        _publish_file(
            record,
            new_record,
            expected=digest(current) if current is not None else None,
        )
        _unlink_owned(home / "pending.json", digest(canonical_json(pending)))
    resumed = _resume_after_install(root, m)
    return {
        "status": "installed",
        "id": m["id"],
        "package_sha256": expected_sha256,
        "restart_required": resumed == "restart-Grail-required",
        "discovery": "next-Grail-agent-sweep",
        "deployed": False,
        "job_verified": False,
        "retired_hatcher": retire_hatcher["name"] if retire_hatcher else None,
        "runtime_resume": resumed,
        "note": "Complete source installed; images, authentication, app readiness and jobs are not qualified by installation.",
    }


def _fences():
    import types

    name = "_rapp_store_detach_fences"
    registry = sys.modules.get(name)
    if registry is None:
        registry = types.ModuleType(name)
        registry.entries = {}
        registry = sys.modules.setdefault(name, registry)
    return registry.entries


def _resume_after_install(root, m):
    registry = sys.modules.get("_rapp_store_detach_fences")
    key = (str(root), m["publisher"], m["id"])
    entry = registry.entries.get(key) if registry is not None else None
    if entry is None:
        return "not-needed"
    try:
        entry["resume"](home=entry["home"])
    except Exception:  # noqa: BLE001 - a controller failure must not roll back installed source.
        return "restart-Grail-required"
    registry.entries.pop(key, None)
    return "resumed-after-preserving-reinstall"


def _stop_local_docker(root, home, m, files, sha):
    """Explicit uninstall only: use the byte-verified controller, not shell hooks.

    The retained release permits safe recovery after partial source detachment.
    Its scoped controller shares the existing Dock admission/operation registry.
    No executable lifecycle path is accepted from package metadata.
    """
    import time
    import types

    loader = m["local_docker"]["loader"]
    release = home / "releases" / sha / "files"
    entrypoint = release / loader["entrypoint"]
    module = types.ModuleType("_rapp_store_detach_" + sha)
    module.__file__ = str(entrypoint)
    module.__package__ = ""
    try:
        exec(  # noqa: S102 - explicit uninstall executes only the verified installed bootstrap.
            compile(files[loader["entrypoint"]], str(entrypoint), "exec"),
            module.__dict__,
        )
        implementation = module._entry()
        controller_type = implementation.LocalDock
        controller_module = sys.modules[controller_type.__module__]
        expected_source = release / loader["support"] / "local_dock.py"
        if _absolute(controller_module.__file__) != _absolute(expected_source):
            raise PackageError(
                "E_LIFECYCLE: controller is not from the verified scoped support"
            )
        dock = controller_type.shared()
        fence = controller_module.quiesce(timeout=0, home=dock.home)
        if not isinstance(fence, dict) or fence.get("admission_paused") is not True:
            raise PackageError("E_DRAIN_STOP: controller did not pause admission")
        _fences()[(str(root), m["publisher"], m["id"])] = {
            "home": dock.home,
            "resume": controller_module.resume,
        }
        record = dock.lifecycle("stop", None, wait_seconds=10)
        deadline = time.monotonic() + 330
        while isinstance(record, dict) and record.get("status") in (
            "queued",
            "running",
        ):
            if time.monotonic() >= deadline:
                raise PackageError(
                    "E_DRAIN_STOP: stop deadline exceeded; all sources and layers retained"
                )
            record = dock.operation(record["id"], wait_seconds=10)
        if isinstance(record, dict) and isinstance(record.get("id"), str):
            # Grail-facing operation projections deliberately omit the scope.
            # Read the exact returned operation, not a guessed/all-history entry.
            record = dock.ops.get(record["id"])
        result = record.get("result") if isinstance(record, dict) else None
        if (
            not isinstance(result, dict)
            or record.get("status") != "succeeded"
            or record.get("kind") != "lifecycle"
            or record.get("name") != "stop"
            or record.get("application") is not None
            or result.get("stopped") is not True
            or result.get("data_deleted") is not False
            or result.get("unrelated_projects_changed") != []
            or not isinstance(record.get("scope"), list)
            or not record["scope"]
            or result.get("scope") != record["scope"]
        ):
            raise PackageError(
                "E_DRAIN_STOP: preserving stop was incomplete; all sources and layers retained"
            )
        fence = controller_module.quiesce(timeout=30, home=dock.home)
        if (
            not isinstance(fence, dict)
            or fence.get("quiesced") is not True
            or fence.get("admission_paused") is not True
            or fence.get("active_operations") != []
        ):
            raise PackageError(
                "E_DRAIN_STOP: operations did not drain; all sources and layers retained"
            )
    except PackageError:
        raise
    except Exception as exc:
        raise PackageError(
            "E_LIFECYCLE: verified installed controller cannot complete preserving stop"
        ) from exc
    return {
        "schema": "rapp-preserving-stop/1",
        "stopped": True,
        "drained": True,
        "admission_paused": True,
        "data_deleted": False,
        "retained": list(RETAINED),
        "operation_id": record.get("id"),
    }


def _remove_sources(root, m, sources, removed=None):
    agents = root / "agents"
    primary = PurePosixPath(m["agent"]).name
    order = sorted(
        sources,
        key=lambda name: (
            name != primary,
            name != "scotty_revision.json",
            -name.count("/"),
            name,
        ),
    )
    removed = [] if removed is None else removed
    for name in order:
        if _unlink_owned(agents / name, digest(sources[name])):
            removed.append(name)
    for name in reversed(_source_directories(sources)):
        path = agents / name
        if not path.exists():
            continue
        with _directory(path.parent) as parent:
            try:
                os.rmdir(path.name, dir_fd=parent)
            except OSError as exc:
                raise PackageError(
                    "E_SOURCE_CONFLICT: support directory is not empty; unexpected files retained"
                ) from exc
            os.fsync(parent)
    return removed


def uninstall_package(blob, expected_sha256, root, *, retire_hatcher=None):
    """Drain/stop through the installed controller, then detach only owned source.

    Data, custody, outputs, receipts, images, volumes and unqualified writable
    container layers are never removed. Failed/partial stop leaves source attached.
    """
    m, files = read_package(blob, expected_sha256)
    require_supported(m)
    root = preflight_device(m, root, files)
    home = _home(root, m)
    record = _safe_target(home, "installed.json")
    sources = _source_layout(m, files)
    receipt = _make_receipt(m, expected_sha256, sources, detached=True)

    def inspect():
        previous_raw = _optional_read(record)
        previous = _owned_receipt(root, home, m)
        if previous is None or previous["package_sha256"] != expected_sha256:
            raise PackageError(
                "E_RECEIPT_REQUIRED: detach requires the exact installed package and receipt"
            )
        pending = _pending(home)
        desired = _transaction(
            m,
            expected_sha256,
            sources,
            receipt,
            previous_raw,
            operation="detach",
            hatcher=retire_hatcher,
        )
        _check_pending(pending, desired, previous_raw)
        _check_hatcher(root, retire_hatcher, pending, home, previous)
        if previous == receipt and pending is None and retire_hatcher is None:
            if any((root / "agents" / name).exists() for name in sources):
                raise PackageError(
                    "E_SOURCE_CONFLICT: detached source paths have new occupants"
                )
            return previous_raw, previous, pending, desired
        _check_sources(root, sources, previous, pending, local=_local(m))
        return previous_raw, previous, pending, desired

    inspect()
    with _install_lock(root):
        verify_grail(root)
        previous_raw, previous, pending, desired = inspect()
        if previous == receipt and pending is None:
            return {
                "status": "already_detached",
                "id": m["id"],
                "retained": list(RETAINED),
                "data_deleted": False,
                "source_removed": [],
            }
        if pending is None:
            _publish_file(home / "pending.json", canonical_json(desired))
            pending = desired
        lifecycle = None
        if _local(m) and previous.get("status") != "detached":
            try:
                lifecycle = _stop_local_docker(root, home, m, files, expected_sha256)
                if (
                    not isinstance(lifecycle, dict)
                    or lifecycle.get("schema") != "rapp-preserving-stop/1"
                    or any(
                        lifecycle.get(name) is not True
                        for name in ("stopped", "drained", "admission_paused")
                    )
                    or lifecycle.get("data_deleted") is not False
                    or lifecycle.get("retained") != RETAINED
                ):
                    raise PackageError("E_DRAIN_STOP: preserving stop was not verified")
            except PackageError as exc:
                return {
                    "status": "retained",
                    "id": m["id"],
                    "detached": False,
                    "source_removed": [],
                    "data_deleted": False,
                    "retained": list(RETAINED),
                    "error": str(exc),
                    "recovery": "Retry uninstall with this exact package; no source was removed.",
                }
        _check_sources(root, sources, previous, pending, local=_local(m))
        removed = []
        try:
            _remove_sources(root, m, sources, removed)
            _retire_hatcher(root, home, retire_hatcher)
            new_record = canonical_json(receipt)
            current = _optional_read(record)
            if current not in (previous_raw, new_record):
                raise PackageError("E_INSTALL_RACE: receipt changed during detachment")
            _publish_file(
                record,
                new_record,
                expected=digest(current) if current is not None else None,
            )
            _unlink_owned(home / "pending.json", digest(canonical_json(pending)))
        except (OSError, PackageError) as exc:
            return {
                "status": "partial",
                "id": m["id"],
                "detached": False,
                "source_removed": removed,
                "data_deleted": False,
                "retained": list(RETAINED),
                "error": str(exc)
                if isinstance(exc, PackageError)
                else "E_DETACH_IO: owned source detachment was interrupted",
                "recovery": "Retry this exact package and operation. The pending record and installer archive are retained.",
            }
    return {
        "status": "detached",
        "id": m["id"],
        "package_sha256": expected_sha256,
        "source_removed": removed,
        "data_deleted": False,
        "retained": list(RETAINED),
        "lifecycle": lifecycle,
        "retired_hatcher": retire_hatcher["name"] if retire_hatcher else None,
        "note": "Only hash-owned discovery source was removed. Retained layers are not claimed absent, portable, or recreation-qualified.",
    }
