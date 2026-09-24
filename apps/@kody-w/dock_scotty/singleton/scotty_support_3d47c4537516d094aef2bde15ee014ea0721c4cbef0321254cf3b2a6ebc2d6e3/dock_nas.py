"""Bounded NAS daemon observations, collected outside the Brainstem process."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from typing import Any

DOCKER = "/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker"
EMPTY_CONFIG = "/var/empty/rapp-dock-observer-client"
MAX_BYTES = 8192
SCHEMA = "rapp-dock-local-daemon-observation/1"
INFO_FIELDS = (
    ("architecture", "Architecture"),
    ("cpus", "NCPU"),
    ("memory_bytes", "MemTotal"),
    ("server_version", "ServerVersion"),
    ("containers", "Containers"),
    ("containers_running", "ContainersRunning"),
    ("containers_paused", "ContainersPaused"),
    ("containers_stopped", "ContainersStopped"),
)
INFO_FORMAT = "{" + ",".join(
    f'"{key}":{{{{json .{field}}}}}' for key, field in INFO_FIELDS
) + "}"
COMMAND = (
    DOCKER, "--config", EMPTY_CONFIG,
    "--host", "unix:///var/run/system-docker.sock",
    "info", "--format", INFO_FORMAT,
)
SNAPSHOT_FIELDS = {
    "schema", "observed_at", "scope", "read_only", "authority",
    "application_status", "daemon",
}


class ObservationError(ValueError):
    """Observation unavailable or invalid; never an empty healthy inventory."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ObservationError("duplicate observation member")
        result[key] = value
    return result


def decode(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_BYTES:
        raise ObservationError("observation exceeds byte limit")
    try:
        value = json.loads(data, object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ObservationError("invalid observation JSON") from exc
    if not isinstance(value, dict):
        raise ObservationError("observation must be an object")
    return value


def _daemon(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {key for key, _ in INFO_FIELDS}:
        raise ObservationError("unexpected daemon observation fields")
    if value["architecture"] not in ("amd64", "x86_64"):
        raise ObservationError("observed daemon is not linux/amd64 NAS architecture")
    version = value["server_version"]
    if not isinstance(version, str) or not re.fullmatch(
        r"\d{1,3}\.\d{1,3}\.\d{1,3}(?:[-+][A-Za-z0-9_.-]{1,32})?", version
    ):
        raise ObservationError("invalid daemon version")
    for key, limit in (("cpus", 4096), ("memory_bytes", 2**60)):
        if type(value[key]) is not int or not 1 <= value[key] <= limit:
            raise ObservationError("invalid daemon resource measurement")
    for key in ("containers", "containers_running", "containers_paused", "containers_stopped"):
        if type(value[key]) is not int or not 0 <= value[key] <= 1_000_000:
            raise ObservationError("invalid container count")
    # Paused containers are included in Docker's running count.
    if (
        value["containers_paused"] > value["containers_running"]
        or value["containers_running"] + value["containers_stopped"] > value["containers"]
    ):
        raise ObservationError("inconsistent daemon container counts")
    return dict(value)


def _timestamp(value: Any) -> float:
    if (
        type(value) not in (int, float) or not 0 <= value <= 2**53
        or not math.isfinite(value)
    ):
        raise ObservationError("invalid observation time")
    return float(value)


def snapshot_from_info(info: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "observed_at": _timestamp(time.time() if now is None else now),
        "scope": "daemon-aggregate-only",
        "read_only": True,
        "authority": "none",
        "application_status": "not_observed",
        "daemon": _daemon(info),
    }


def collect_snapshot() -> dict[str, Any]:
    """Run one fixed read-only command on the NAS, never from an agent tool."""
    if os.path.lexists(EMPTY_CONFIG):
        raise ObservationError("observer Docker client configuration path must be absent")
    try:
        result = subprocess.run(
            COMMAND, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=15, check=False,
            env={"PATH": str(Path(DOCKER).parent) + ":/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ObservationError("NAS daemon observation command unavailable") from exc
    if result.returncode:
        raise ObservationError("NAS daemon observation command failed")
    return snapshot_from_info(decode(result.stdout))


def read_snapshot(
    path: Path, *, now: float | None = None, max_age_seconds: int = 120,
) -> dict[str, Any]:
    """Read local diagnostic evidence, not signed enrollment or execution authority."""
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 300:
        raise ObservationError("observation freshness limit must be 1..300 seconds")
    path = Path(path).absolute()
    if any(parent.is_symlink() for parent in path.parents):
        raise ObservationError("observation path has a symlinked ancestor")
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > MAX_BYTES
        ):
            raise ObservationError("observation must be a bounded owner-only regular file")
        data = os.read(fd, MAX_BYTES + 1)
    except OSError as exc:
        raise ObservationError("NAS observation file unavailable") from exc
    finally:
        if fd is not None:
            os.close(fd)
    value = decode(data)
    if set(value) != SNAPSHOT_FIELDS:
        raise ObservationError("unexpected observation fields")
    expected = snapshot_from_info(value["daemon"], now=value["observed_at"])
    if value["read_only"] is not True or value != expected:
        raise ObservationError("invalid observation scope or claims")
    current = _timestamp(time.time() if now is None else now)
    age = current - expected["observed_at"]
    if not 0 <= age <= max_age_seconds:
        raise ObservationError("NAS observation is stale or future-dated")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read", type=Path, help="read an existing private snapshot; do not contact Docker")
    args = parser.parse_args()
    try:
        value = read_snapshot(args.read) if args.read else collect_snapshot()
    except ObservationError as exc:
        print(json.dumps({"status": "unavailable", "reason": str(exc), "read_only": True}))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
