"""RAPP Dock local lane: Scotty-operated Docker applications on this Mac.

Owner direction (2026-09-22): the NAS lacks the capacity for these stacks, so they
run in Docker Desktop on this Mac, and local Docker containment is the safety
boundary. There is no approval ceremony. Scotty operates only the compose
projects shipped with this capability, through validated structured actions; it
never receives arbitrary shell commands or Docker arguments.

Adapters live in ``deploy/local/<app>/adapter.py`` (see docs/LOCAL-DOCK.md).
Private state, secrets, operation records and outputs live under
``$RAPP_DOCK_HOME`` (default ``~/.rapp-dock``), never in this source tree.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib
import io
import ipaddress
import itertools
import json
import math
import os
import queue
import re
import secrets
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import uuid
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import partial, wraps
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit

from scotty_contract import (
    APPS, APP_INDEX, DEFAULT_AI_MODEL, DEFAULT_NAMESPACE, DEFAULT_PORT_BASE,
    NAMESPACE_PATTERN, ContractError, job_spec, validate_arguments as _contract_arguments,
)
from scotty_distribution import DistributionRefused, capability_manifest, read_regular

ROOT = Path(__file__).resolve().parent
LOCAL_ROOT = ROOT / "deploy" / "local"
AI_NETWORK = "rapp-dock-ai"
MAX_RESULT_BYTES = 128 * 1024
MAX_LOG_BYTES = 12 * 1024
MAX_OPERATION_BYTES = 1024 * 1024
MAX_DOCKER_BYTES = 8 * 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 4096
MAX_HTTP_BYTES = 64 * 1024 * 1024
MAX_HTTP_REDIRECTS = 3
MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_INPUT_CONFIG_BYTES = 16 * 1024
MAX_BIND_ALIAS_BYTES = 1024 * 1024
CONTENT_DIRECTORIES = ("Desktop", "Documents", "Downloads", "Movies", "Music", "Pictures")
MAX_OUTPUT_BYTES = 512 * 1024 * 1024
DEFAULT_WAIT_SECONDS = 8
MAX_WAIT_SECONDS = 10
MAX_WORKERS = 3
MAX_QUEUED = 16
STOP_PARALLELISM = 3
STOP_WAIT_SECONDS = 10
IDLE_SECONDS = 600
DEFAULT_NETWORK_POOL = "10.234.0.0/16"
NETWORK_PREFIX = 26
NETWORKS_PER_APP = 8
NETWORK_PLAN_BYTES = 64 * 1024
MAX_RESOURCE_CONTAINERS = 512
# Recovery window of one logical read-only observation, measured from its start. It only admits and caps
# the single timeout retry; clean reads keep their normal bounds under any caller deadline, and both
# attempts are min(normal, remaining) (Docker Desktop Resource Saver documents a wake of about 3-10 seconds).
DOCKER_READ_WAKE_SECONDS = 10
MAX_READ_OBSERVATIONS = 32
MAX_READ_ATTEMPTS = 32
MAX_READ_JOURNAL_BYTES = 128 * 1024
# Longest wait for the journal's in-process and interprocess lock; never past the observation's window.
READ_JOURNAL_LOCK_SECONDS = 1.0
READ_SCOPES = frozenset({
    "docker-read", "inventory", "network-inventory", "resource-snapshot", "dock-status",
    "image-resolution", "image-capture",
})
READ_COMMANDS = frozenset({
    "context-inspect", "ps", "info", "inspect-container", "inspect-image", "network-ls", "inspect-network",
})
# The local context lookup does not wake the Docker VM, so it is observed but never retried.
RETRYABLE_READS = READ_COMMANDS - {"context-inspect"}
READ_PHASES = frozenset({"spawn", "pipe-io", "process-exit", "completed", "unknown"})
READ_RECORD_FIELDS = frozenset({
    "id", "scope", "started_at", "finished_at", "state", "error", "wake_budget_seconds",
    "wake_seconds", "retry_used", "dropped_attempts", "attempts",
})
READ_ATTEMPT_FIELDS = frozenset({
    "command", "command_index", "attempt", "outcome", "phase", "timeout_seconds", "elapsed_ms",
    "spawn_ms", "pid", "exit_code", "open_streams", "stdin_bytes_written", "stdout_bytes",
    "stderr_bytes", "observed_at",
})
_READ_JOURNAL_LOCK = threading.Lock()


@contextmanager
def _read_journal_lock(root: Path, deadline: float):
    """Bounded exclusion across threads and processes for the private read journal's read-merge-write."""
    import fcntl

    if not _READ_JOURNAL_LOCK.acquire(timeout=max(0.0, deadline - time.monotonic())):
        raise ValueError
    try:
        descriptor = os.open(root / "docker-read.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != 0
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise ValueError
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError from None
                    time.sleep(min(0.02, remaining))
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
    finally:
        _READ_JOURNAL_LOCK.release()
RESOURCE_INFO_FORMAT = '{"id":{{json .ID}},"memory":{{json .MemTotal}},"cpus":{{json .NCPU}}}'
DESKTOP_INFO_FORMAT = '{"os":{{json .OperatingSystem}},"type":{{json .OSType}}}'
RESOURCE_INSPECT_FORMAT = (
    '{"id":{{json .Id}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},"state":{{json .State.Status}},'
    '"memory":{{json .HostConfig.Memory}},"nano_cpus":{{json .HostConfig.NanoCpus}},'
    '"quota":{{json .HostConfig.CpuQuota}},"period":{{json .HostConfig.CpuPeriod}}}'
)
IDENTITY_INSPECT_FORMAT = (
    '{"id":{{json .Id}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
    '"project":{{json (index .Config.Labels "com.docker.compose.project")}},"image_id":{{json .Image}}}'
)
CUSTODY_INSPECT_FORMAT = (
    '{"id":{{json .Id}},"labels":{{json .Config.Labels}},"read_only":{{json .HostConfig.ReadonlyRootfs}},'
    '"mounts":{{json .Mounts}}}'
)
IMAGE_INSPECT_FORMAT = (
    '[{"Id":{{json .Id}},"Os":{{json .Os}},"Architecture":{{json .Architecture}},'
    '"RepoDigests":{{json .RepoDigests}},"Config":{"Labels":'
    '{"rapp.dock.recipe.sha256":{{with (index . "Config")}}{{with (index . "Labels")}}'
    '{{json (index . "rapp.dock.recipe.sha256")}}{{else}}null{{end}}'
    '{{else}}null{{end}}}}}]'
)
_READ_OBSERVATION = ContextVar("rapp_dock_read_observation", default=None)
_READ_RETRY_DISABLED = ContextVar("rapp_dock_read_retry_disabled", default=False)
TERMINAL = ("succeeded", "partial", "failed", "interrupted", "cancelled")

_candidate = ModuleType("_rapp_dock_runtime_v1")
_candidate.lock = threading.RLock()
_candidate.boot_id = f"{os.getpid()}-{time.time_ns()}"
_candidate.runtimes = {}
_candidate.heavy = threading.BoundedSemaphore(1)
_candidate.heavy_owner = None
_candidate.network_lock = threading.RLock()
_candidate.docker_endpoints = {}
_REGISTRY = sys.modules.setdefault("_rapp_dock_runtime_v1", _candidate)
with _REGISTRY.lock:
    if not hasattr(_REGISTRY, "network_lock"):
        _REGISTRY.network_lock = threading.RLock()
    if not hasattr(_REGISTRY, "resource_lock"):
        _REGISTRY.resource_lock = threading.RLock()
        _REGISTRY.resource_reservations = {}
BOOT_ID = _REGISTRY.boot_id
_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_OP_ID = re.compile(r"op-[0-9]{10}-[0-9a-f]{8}")
_IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}")
_OPENER = None


def _secret_setting(name: str, value: str | None = None) -> bool:
    name = name.upper()
    if name.startswith("PUBLIC_") or name in {"MODEL", "PORT", "HOST", "URL", "URI", "PATH", "MODE", "TYPE"} or name.endswith(("_FILE", "_PATH", "_URL", "_URI", "_HOST", "_PORT", "_MODEL", "_MODE", "_NAME", "_TYPE")):
        return False
    if value is not None and value.strip().casefold() in ("", "true", "false", "none", "null", "disabled", "enabled"):
        return False
    return name in {"INTELLIGENCE_KEYS", "REDISCLI_AUTH", "APP_KEY", "SERVER_KEY", "PLUGIN_DAEMON_KEY", "INNER_API_KEY_FOR_PLUGIN"} or re.search(
        r"(?:^|_)(?:PASSWORD|PASSWD|TOKEN|SECRET|SECRET_KEY|API_KEY|ACCESS_KEY|PRIVATE_KEY|SIGNING_KEY|ENCRYPTION_KEY|MASTER_KEY|COOKIE|AUTHORIZATION)$",
        name,
    ) is not None


class LocalDockError(Exception):
    """An explicit, user-explainable refusal or failure."""

    def __init__(self, code: str, message: str = "", *, diagnostic: dict[str, Any] | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.diagnostic = diagnostic


def _observed_read(scope: str):
    def decorate(function):
        @wraps(function)
        def observed(self, *args, **kwargs):
            with self._read_observation(scope):
                return function(self, *args, **kwargs)
        return observed
    return decorate


def _single_attempt_reads(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        token = _READ_RETRY_DISABLED.set(True)
        try:
            return function(*args, **kwargs)
        finally:
            _READ_RETRY_DISABLED.reset(token)
    return guarded


def classify_docker_failure(text: str, fallback: str = "docker-compose-failed") -> str:
    patterns = (
        ("network-pool-exhausted", r"all predefined address pools have been fully subnetted|(?:could not|cannot) find (?:an? )?available.*(?:address|ipv4).*pool|address pools?.*exhausted"),
        ("network-subnet-overlap", r"pool overlaps with other one|pool overlaps with an existing|subnet.*overlaps"),
        ("port-in-use", r"port is already allocated|address already in use|port .* already in use"),
        ("image-missing", r"no such image|unable to find image|pull access denied|manifest unknown|manifest .*not found"),
        ("daemon-unavailable", r"cannot connect to the docker daemon|is the docker daemon running|error during connect:.*docker|docker.*connection refused"),
        ("out-of-memory", r"out of memory|cannot allocate memory|oom[- ]killed|oomkilled[\"']?\s*[:=]\s*true|memoryerror"),
    )
    for code, pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return code
    return fallback


def safe_error(code: str, *, no_speech: bool = False) -> dict[str, Any]:
    messages = {
        "invalid-arguments": "The supplied fields do not match this action or job.",
        "invalid-input": "The selected input is invalid or outside the permitted bounds.",
        "input-not-found": "The selected owner-home input file does not exist.",
        "input-not-enrolled": "That file is outside the enrolled input roots. Use a standard content folder, Dock inputs, a verified prior output, or a root in the private input-roots.json configuration.",
        "input-artifact-changed": "The selected prior output no longer matches its verified descriptor; it cannot be used as trusted input.",
        "invalid-input-roots": "Input roots must be configured outside chat as specific non-credential owner-home directories; the whole home cannot be enrolled.",
        "http-destination-refused": "Host HTTP is limited to this app's assigned loopback endpoint and its intelligence gateway.",
        "http-redirect-refused": "The application redirect was refused before contacting another endpoint or replaying a write.",
        "url-not-allowed": "That URL is outside the permitted public-source policy.",
        "not-installed": "This application's local adapter is not installed.",
        "docker-unavailable": "Local Docker Desktop is unavailable.",
        "docker-context-refused": "Docker Desktop did not resolve to an allowed local Unix socket.",
        "docker-state-unknown": "Docker state is unknown; no empty or stopped state is assumed.",
        "docker-timeout": "The bounded Docker operation timed out; native state may be uncertain.",
        "docker-output-too-large": "Docker output exceeded its byte limit.",
        "docker-compose-failed": "The enrolled application's Docker operation failed.",
        "network-pool-exhausted": "Docker's automatic network address pools are exhausted. Use the controller's explicit subnet plan; legacy idle Dock networks need scoped cleanup, not deletion of unrelated networks.",
        "port-in-use": "The assigned loopback port is already in use. Stop the conflicting Dock instance or select a free RAPP_DOCK_PORT_BASE before starting this app.",
        "image-missing": "A required locked local image is missing. Run the reviewed explicit materialization workflow for this application, then retry startup. Jobs never pull or build images.",
        "image-lock-mismatch": "The local image, platform, materialization receipt or component lock differs from the reviewed identity. Restore or explicitly materialize the locked public inputs; jobs never pull or substitute images.",
        "image-resolution-unavailable": "The complete locked image resolver is unavailable. Install the reviewed capability closure before starting this application.",
        "daemon-unavailable": "Docker Desktop is not reachable. Start Docker Desktop and inspect the operation's retained native state before retrying.",
        "out-of-memory": "Docker reported an out-of-memory failure. Stop idle heavy Dock apps or increase the Docker VM memory allowance before reconciling this operation.",
        "network-subnet-overlap": "The reserved Docker subnet overlaps an existing network. Select a disjoint private /16 with RAPP_DOCK_NETWORK_POOL; do not delete unrelated networks.",
        "network-budget-exceeded": "This application exhausted its reserved small-network slots. Retire unused networks belonging to this project or consolidate its reviewed Compose networks.",
        "network-plan-invalid": "The private network plan is invalid or unsafe. Restore the reviewed configuration before starting this app.",
        "invalid-network-pool": "Set RAPP_DOCK_NETWORK_POOL to a disjoint reserved RFC1918 IPv4 /16; it is only used for new Dock networks.",
        "network-ownership-mismatch": "A required network belongs to a different project. Resolve that scoped name conflict before starting this app.",
        "network-topology-changed": "An existing network differs from the reviewed isolation settings. Stop the affected project and recreate only its network after reviewing that change.",
        "app-not-ready": "The application did not become ready; no successful job is claimed.",
        "vm-capacity-exceeded": "Dock cannot fit the requested memory while protecting active work, required stacks and other Docker workloads. Eligible idle stacks are reclaimed automatically. Retry after current operations finish; if the requested stack alone exceeds the VM, use a smaller supported profile or increase VM memory.",
        "vm-capacity-unknown": "Docker VM memory or a running container's declared limits could not be verified. No stacks were assumed idle or unbounded memory assumed free.",
        "vm-state-changed": "The running container set changed during admission. Retry after that state settles; no new stack was started by this admission.",
        "invalid-resource-limits": "Every enrolled service must declare finite positive memory and CPU limits before startup.",
        "idle-stack-busy": "An idle-stack candidate acquired work or a protection fence before reclamation; it was not stopped.",
        "native-recovery-unavailable": "No qualified read-only collector and retained native identity are available. Native work was not resubmitted.",
        "recovery-read-only": "Recovery permits only the qualified native observations and private artifact collection; startup, input resealing and native work replay are refused.",
        "recovery-state-invalid": "The saved recovery link is inconsistent. Original native IDs and artifacts remain retained; no work was replayed.",
        "intelligence-unavailable": "The local intelligence provider is unavailable.",
        "intelligence-auth-unavailable": "The intelligence container's scoped authentication is unavailable.",
        "native-job-failed": "The native application job failed. Any retained outputs remain available.",
        "output-invalid": "The requested outputs did not pass validation; this is not a completed result.",
        "not-supported": "This request is outside the installed application's supported workflow.",
        "cancelled": "The operation was cancelled; no further native work will be submitted.",
        "quiescing": "Dock is draining accepted work for a reviewed revision; new work is paused.",
        "stopping": "A durable stop fence is active. Collect the stop operation before starting more work.",
        "detaching": "This installation is durably paused for preserving source detachment. Only a verified targeted reinstall may reactivate its admission.",
        "detach-incomplete": "Detachment still has active work or an unresolved stop fence. Retain source and state; do not reactivate this installation yet.",
        "installation-binding-invalid": "Installation lifecycle requires an explicit absolute Dock home, supported namespace and integer port base.",
        "installation-binding-mismatch": "The receipt's Dock home, namespace or port base does not match the retained runtime. No other installation was selected.",
        "stop-timeout": "Cancellation did not drain in time. The stop fence remains active.",
        "dependent-stop-incomplete": "A dependent application was not confirmed stopped, so this dependency remains running. Inspect the per-app stop results before retrying.",
        "queue-full": "Dock's bounded queue is full. Collect existing work before submitting more.",
        "unsafe-retry": "Native state may already contain this work. Reconcile the retained IDs; do not resubmit.",
        "provenance-unavailable": "The job receipt could not be accepted durably; no application work was submitted.",
        "unknown-operation": "That operation ID is not present in this Dock home.",
        "unknown-job": "That job is not installed. Use jobs to inspect the current catalog.",
        "unsupported-action": "That action is unavailable. Data deletion is not exposed.",
        "http-unavailable": "The application's HTTP endpoint is unavailable.",
        "response-too-large": "The application response exceeded its byte limit.",
        "docker-observation-budget-exhausted": "The bounded read-only Docker observation budget expired. Current state remains unknown; no work was replayed.",
        "docker-observation-audit-unavailable": "The private Docker observation record could not be safely retained. No successful observation is claimed.",
        "history-unavailable": "Verified local history is unavailable; no job or receipt repair was started.",
        "history-invalid-timezone": "Select an IANA timezone such as UTC or America/New_York.",
        "history-invalid-day": "Select a valid YYYY-MM-DD calendar day.",
        "history-invalid-range": "Select both start_day and end_day in YYYY-MM-DD order, at most 366 inclusive days; do not also supply day.",
        "history-invalid-limit": "History page limits must be integers from 1 to 20.",
        "history-invalid-operation": "Select a returned operation ID for lineage.",
        "history-invalid-cursor": "Use the exact returned history cursor with the same query fields.",
        "history-stale-cursor": "History changed or the query differs. Start a fresh query without a cursor.",
    }
    message = messages.get(code, "The local operation could not complete safely. Inspect its retained operation record.")
    if no_speech:
        message = "No usable speech was found. This workflow requires a video containing spoken content."
    recovery = {
        "network-pool-exhausted": "repair-network-budget", "port-in-use": "free-loopback-port",
        "image-missing": "materialize-locked-images", "daemon-unavailable": "start-docker-desktop",
        "image-lock-mismatch": "materialize-locked-images",
        "image-resolution-unavailable": "restore-reviewed-capability",
        "out-of-memory": "free-docker-memory",
        "network-subnet-overlap": "select-disjoint-network-pool",
        "network-budget-exceeded": "review-project-network-budget",
        "history-stale-cursor": "restart-history-query",
        "vm-capacity-exceeded": "submit-after-capacity",
        "vm-capacity-unknown": "verify-container-limits",
        "vm-state-changed": "refresh-resource-state",
        "invalid-resource-limits": "restore-reviewed-resource-limits",
        "detaching": "verified-targeted-reinstall",
        "detach-incomplete": "complete-targeted-stop",
        "installation-binding-mismatch": "verify-installation-receipt",
        "installation-binding-invalid": "verify-installation-receipt",
    }
    if code.startswith("history-invalid-"):
        recovery[code] = "correct-arguments"
    return {"code": code if isinstance(code, str) and _NAME.fullmatch(code) else "unexpected-error",
            "message": message, "retryable": code in ("queue-full", "quiescing", "vm-capacity-exceeded", "vm-state-changed"),
            "retry_scope": recovery.get(code, "submit-after-capacity" if code in ("queue-full", "quiescing") else "reconcile-native-state")}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _checked_wait(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= MAX_WAIT_SECONDS:
        raise LocalDockError("invalid-arguments", "wait_seconds must be between 0 and 10.")
    return value


def _memory_limit(value: Any) -> int:
    if type(value) is int and 0 < value <= 2 ** 60:
        return value
    if isinstance(value, str) and len(value) <= 32:
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([kmgt]?)(?:i?b)?", value.strip().lower())
        if match:
            amount = Decimal(match[1]) * (1024 ** ("kmgt".index(match[2]) + 1) if match[2] else 1)
            if amount == int(amount) and 0 < amount <= 2 ** 60:
                return int(amount)
    raise LocalDockError("invalid-resource-limits")


def _cpu_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)) or len(str(value)) > 32:
        raise LocalDockError("invalid-resource-limits")
    try:
        amount = Decimal(str(value)) * 1_000_000_000
        if amount.is_finite() and 0 < amount <= 65536 * 1_000_000_000 and amount == int(amount):
            return int(amount)
    except (InvalidOperation, ValueError, OverflowError):
        pass
    raise LocalDockError("invalid-resource-limits")


@contextmanager
def _directory_fd(path: Path):
    """Walk every component without following links, including intermediate ones."""
    path = Path(os.path.abspath(path))
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _regular_file(path: Path):
    with _directory_fd(path.parent) as parent:
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise LocalDockError("unsafe-file", "Expected an owner-controlled regular file without links.")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            yield stream
    finally:
        os.close(descriptor)


def _private_dir(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    try:
        if not path.parent.exists():
            _private_dir(path.parent)
        with _directory_fd(path.parent) as parent:
            try:
                os.mkdir(path.name, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            descriptor = os.open(
                path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
            )
            try:
                if os.fstat(descriptor).st_uid != os.geteuid():
                    raise LocalDockError("unsafe-state-directory", "State directories must belong to this owner.")
                os.fchmod(descriptor, 0o700)
            finally:
                os.close(descriptor)
        return path
    except OSError:
        raise LocalDockError("unsafe-state-directory", "State directories must not contain symbolic links.") from None


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        with _directory_fd(path.parent) as parent:
            os.fsync(parent)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def dock_home() -> Path:
    configured = os.environ.get("RAPP_DOCK_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".rapp-dock"


def docker_cli(override: str | None = None) -> str:
    override = os.environ.get("RAPP_DOCK_DOCKER") if override is None else override
    candidates = (override,) if override else (shutil.which("docker"),)
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise LocalDockError("docker-unavailable", "Docker CLI not found; is Docker Desktop installed and running?")


def docker_env(
    extra: dict[str, str] | None = None, *, executable: str | None = None,
    owner_home: Path | None = None,
) -> dict[str, str]:
    """A minimal environment: the caller's tokens and credentials are never inherited."""
    docker = executable or docker_cli()
    entries = [
        str(Path(docker).parent),
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "/Applications/Docker.app/Contents/Resources/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    env = {"PATH": os.pathsep.join(dict.fromkeys(entries)), "HOME": str(owner_home or Path.home()),
           "LANG": "C.UTF-8", "COMPOSE_DISABLE_ENV_FILE": "1"}
    for key in ("TMPDIR", "USER", "LOGNAME"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    env.update(extra or {})
    return env


def run_docker(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = 120,
    input_bytes: bytes | None = None,
    cwd: Path | None = None,
    executable: str | None = None,
    max_bytes: int = MAX_DOCKER_BYTES,
    check_cancelled: Callable[[], None] | None = None,
    hard_deadline: float | None = None,
) -> subprocess.CompletedProcess:
    argv = [executable or docker_cli(), *args]
    if not math.isfinite(timeout) or not 0 < timeout <= 1800 or not 0 < max_bytes <= MAX_HTTP_BYTES:
        raise LocalDockError("invalid-input", "Invalid Docker command bound.")
    if hard_deadline is not None and (isinstance(hard_deadline, bool) or not isinstance(hard_deadline, (int, float)) or not math.isfinite(hard_deadline)):
        raise LocalDockError("invalid-input", "Invalid Docker caller deadline.")
    process = None
    finished = False
    phase = "spawn"
    started = time.monotonic()
    spawned = None
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    read_counts = {"stdout": 0, "stderr": 0}
    open_streams: set[str] = set()
    offset = written = 0

    def diagnostic(code: str) -> dict[str, Any]:
        selected = args[2:] if args[:1] in (["--host"], ["--context"]) else args
        command = selected[0] if selected and selected[0] in {
            "compose", "context", "ps", "info", "inspect", "image", "network",
            "volume", "logs", "exec", "stop", "run", "update", "kill", "version",
        } else "docker"
        clock = time.monotonic()
        return {
            "kind": "docker-process", "command": command, "code": code, "phase": phase,
            "timeout_seconds": timeout, "elapsed_ms": round((clock - started) * 1000),
            "spawn_ms": round((spawned - started) * 1000) if spawned is not None else None,
            "pid": process.pid if process is not None else None,
            "exit_code": process.poll() if process is not None else None,
            "open_streams": sorted(open_streams), "stdin_bytes_written": written,
            "stdout_bytes": read_counts["stdout"], "stderr_bytes": read_counts["stderr"],
            "observed_at": _now(),
        }

    try:
        if hard_deadline is not None and time.monotonic() >= hard_deadline:
            raise LocalDockError("docker-observation-budget-exhausted")
        process = subprocess.Popen(
            argv, env=env or docker_env(), cwd=str(cwd) if cwd else None,
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        spawned = time.monotonic()
        phase = "pipe-io"
        deadline, total = spawned + timeout, 0
        if hard_deadline is not None:
            deadline = min(deadline, hard_deadline)
        with selectors.DefaultSelector() as selector:
            for name in ("stdout", "stderr"):
                stream = getattr(process, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
                open_streams.add(name)
            if process.stdin is not None:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
                open_streams.add("stdin")
            while selector.get_map():
                if check_cancelled:
                    check_cancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LocalDockError("docker-timeout", "The bounded Docker command timed out.")
                for key, _ in selector.select(min(remaining, 0.2)):
                    if key.data == "stdin":
                        if offset < len(input_bytes):
                            try:
                                count = os.write(key.fd, input_bytes[offset:offset + 65536])
                                offset += count
                                written += count
                            except BrokenPipeError:
                                offset = len(input_bytes)
                        if offset == len(input_bytes):
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            open_streams.discard("stdin")
                    else:
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            open_streams.discard(key.data)
                            continue
                        total += len(chunk)
                        read_counts[key.data] += len(chunk)
                        if total > max_bytes:
                            raise LocalDockError("docker-output-too-large", "Docker output exceeded its byte limit.")
                        buffers[key.data].extend(chunk)
        phase = "process-exit"
        try:
            remaining = deadline - time.monotonic()
            if hard_deadline is not None and remaining <= 0:
                raise LocalDockError("docker-timeout", "The bounded Docker command timed out.")
            code = process.wait(timeout=max(0.01, remaining) if hard_deadline is None else remaining)
        except subprocess.TimeoutExpired:
            raise LocalDockError("docker-timeout", "The bounded Docker command timed out.") from None
        finished = True
        return subprocess.CompletedProcess(argv, code, bytes(buffers["stdout"]), bytes(buffers["stderr"]))
    except LocalDockError as error:
        if error.code in {"docker-timeout", "docker-output-too-large"} and error.diagnostic is None:
            error.diagnostic = diagnostic(error.code)
        raise
    except OSError as error:
        details = {**diagnostic("docker-unavailable"), "os_error": error.errno}
        raise LocalDockError("docker-unavailable", "The local Docker command is unavailable.", diagnostic=details) from None
    finally:
        if process is not None:
            if not finished:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    grace = 1 if hard_deadline is None else max(0, min(1, hard_deadline - time.monotonic()))
                    process.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


@dataclass
class HttpResult:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8") or "null")

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


def _http_headers(headers: Any) -> dict[str, str]:
    """Keep repeat cookies separate: commas also occur inside cookie expiry dates."""
    result: dict[str, str] = {}
    names: dict[str, str] = {}
    for name, value in (headers.items() if headers is not None else ()):
        key = names.setdefault(name.lower(), name)
        if key in result:
            result[key] += ("\n" if name.lower() == "set-cookie" else ", ") + value
        else:
            result[key] = value
    return result


def multipart(
    fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]
) -> tuple[bytes, str]:
    """Encode a multipart/form-data body; returns (body, content-type)."""
    boundary = "rappdock" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            + str(value).encode()
            + b"\r\n"
        )
    for name, (filename, data, content_type) in files.items():
        safe = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
        chunks.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{safe}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
            + data
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class Operations:
    """Durable operation/job records; a restart marks unfinished work interrupted."""

    def __init__(self, home: Path, lock: Any = None) -> None:
        self.directory = home / "ops"
        self.events = home / "events.jsonl"
        self.lock = lock or threading.RLock()
        self.cache: dict[str, dict[str, Any]] = {}

    def _path(self, op_id: str) -> Path:
        if not isinstance(op_id, str) or _OP_ID.fullmatch(op_id) is None:
            raise LocalDockError("unknown-operation", "operation id is not valid")
        return self.directory / f"{op_id}.json"

    def create(self, kind: str, app: str | None, name: str, arguments: dict[str, Any], **fields: Any) -> dict[str, Any]:
        op_id = f"op-{int(time.time()):010d}-{secrets.token_hex(4)}"
        record = {
            "id": op_id,
            "kind": kind,
            "application": app,
            "name": name,
            "arguments": arguments,
            "status": "queued",
            "created": _now(),
            "started": None,
            "finished": None,
            "result": None,
            "error": None,
            "progress": [],
            "native": {},
            "diagnostic": None,
            "boot": BOOT_ID,
            **fields,
        }
        self._write(record)
        return record

    def _write(self, record: dict[str, Any]) -> None:
        with self.lock:
            encoded = json.dumps(record, sort_keys=True, allow_nan=False).encode()
            if len(encoded) > MAX_OPERATION_BYTES:
                raise LocalDockError("operation-too-large", "The operation record exceeds its byte limit.")
            _private_dir(self.directory)
            _atomic_write(self._path(record["id"]), encoded)
            self.cache[record["id"]] = json.loads(encoded)
            if len(self.cache) > 64:
                oldest = min(self.cache, key=lambda key: self.cache[key]["created"])
                self.cache.pop(oldest)

    def get(self, op_id: str) -> dict[str, Any]:
        path = self._path(op_id)
        with self.lock:
            try:
                with _regular_file(path) as stream:
                    if os.fstat(stream.fileno()).st_size > MAX_OPERATION_BYTES:
                        raise LocalDockError("operation-too-large", "The operation record exceeds its byte limit.")
                    raw = stream.read(MAX_OPERATION_BYTES + 1)
                if len(raw) > MAX_OPERATION_BYTES:
                    raise LocalDockError("operation-too-large", "The operation record exceeds its byte limit.")
                record = json.loads(raw)
            except FileNotFoundError:
                raise LocalDockError("unknown-operation", f"no operation {op_id}") from None
            except (OSError, ValueError):
                raise LocalDockError("invalid-operation", "The operation record is missing or unsafe.") from None
            if not isinstance(record, dict) or record.get("id") != op_id or not isinstance(record.get("status"), str):
                raise LocalDockError("invalid-operation", "The operation record has an invalid shape.")
            completion = record.get("pending_terminal")
            if completion is not None and (
                not isinstance(completion, dict) or completion.get("status") not in TERMINAL
                or completion.get("phase") != completion.get("status")
                or not isinstance(completion.get("finished"), str)
                or set(completion) != {"status", "finished", "phase", "updated_at", "error", "diagnostic"}
            ):
                raise LocalDockError("invalid-operation", "The staged terminal outcome is invalid.")
            if record["status"] not in TERMINAL and record.get("boot") != BOOT_ID and completion is None:
                record.update(
                    status="interrupted",
                    finished=_now(),
                    error={"code": "interrupted", "message": "The owning process ended. Native state is uncertain; no work is being retried automatically.", "retryable": False, "retry_scope": "reconcile-native-state"},
                )
                self._write(record)
            self.cache[op_id] = record
            if len(self.cache) > 64:
                self.cache.pop(min(self.cache, key=lambda key: self.cache[key]["created"]))
            return record

    def update(self, op_id: str, **fields: Any) -> dict[str, Any]:
        with self.lock:
            record = self.get(op_id)
            record.update(fields)
            self._write(record)
            return record

    def progress(self, op_id: str, message: str) -> None:
        with self.lock:
            record = self.get(op_id)
            record["progress"] = (record.get("progress") or [])[-19:] + [f"{_now()} {message[:300]}"]
            self._write(record)

    def record_native(self, op_id: str, key: str, value: Any) -> None:
        with self.lock:
            record = self.get(op_id)
            record.setdefault("native", {})[key] = value
            self._write(record)

    def recent(self, app: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        with self.lock:
            import heapq

            names = heapq.nlargest(256, itertools.islice(self.directory.glob("op-*.json"), 2048))
            records = []
            for path in names:
                if len(records) >= limit:
                    break
                try:
                    record = self.get(path.stem)
                except (LocalDockError, ValueError, OSError):
                    continue
                if app is None or record["application"] == app:
                    records.append(record)
            return sorted(records, key=lambda record: record["created"], reverse=True)

    def event(self, **fields: Any) -> None:
        line = json.dumps({"time": _now(), **fields}, sort_keys=True, default=str) + "\n"
        with self.lock:
            descriptor = os.open(self.events, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                stream.write(line)


def _runtime(home: Path, namespace: str, port_base: int, docker_override: str) -> Any:
    key = str(home)
    with _REGISTRY.lock:
        if key in _REGISTRY.runtimes:
            runtime = _REGISTRY.runtimes[key]
            if (runtime.namespace, runtime.port_base, runtime.docker_override) != (namespace, port_base, docker_override):
                raise LocalDockError("runtime-configuration-conflict", "An active Dock home cannot change namespace, ports, or Docker executable.")
            with runtime.lock:
                runtime.state.setdefault("last_used", {})
            return runtime
        state_path = home / "runtime.json"
        state = {"schema": "rapp-dock-runtime/1", "namespace": namespace, "generation": 0,
                 "app_generations": {app: 0 for app in APPS}, "stopping": [], "auto_started": {},
                 "boot": BOOT_ID, "idle_protected": [], "port_base": port_base, "detach_paused": False,
                 "last_used": {}}
        if state_path.exists() or state_path.is_symlink():
            try:
                with _regular_file(state_path) as stream:
                    raw = stream.read(16385)
                restored = json.loads(raw)
                if (
                    len(raw) > 16384 or restored["schema"] != state["schema"]
                    or restored["namespace"] != namespace
                    or type(restored["generation"]) is not int
                    or set(restored["app_generations"]) != set(APPS)
                    or any(type(value) is not int or value < 0 for value in restored["app_generations"].values())
                    or not isinstance(restored["stopping"], list)
                    or set(restored["stopping"]) - set(APPS)
                    or not isinstance(restored.get("auto_started", {}), dict)
                    or set(restored.get("auto_started", {})) - set(APPS)
                    or not isinstance(restored.get("idle_protected", []), list)
                    or set(restored.get("idle_protected", [])) - set(APPS)
                    or "port_base" in restored and (type(restored["port_base"]) is not int or restored["port_base"] != port_base)
                    or type(restored.get("detach_paused", False)) is not bool
                    or not isinstance(restored.get("last_used", {}), dict)
                    or set(restored.get("last_used", {})) - set(APPS)
                    or any(isinstance(value, bool) or not isinstance(value, (int, float))
                           or not math.isfinite(value) or value < 0 for value in restored.get("last_used", {}).values())
                ):
                    raise ValueError
                state.update(restored)
                if restored.get("boot") != BOOT_ID:
                    state["idle_protected"] = sorted(set(state["idle_protected"]) | set(state["auto_started"]))
                state["boot"] = BOOT_ID
            except (OSError, ValueError, KeyError, TypeError):
                raise LocalDockError("invalid-runtime-state", "The durable Dock cancellation fence is unsafe or invalid.") from None
        lock = threading.RLock()
        runtime = SimpleNamespace(
            home=home, namespace=namespace, port_base=port_base, docker_override=docker_override,
            lock=lock, state=state, ops=Operations(home, lock), pending={},
            queues={"work": queue.Queue(MAX_QUEUED), "control": queue.Queue(8)},
            threads={"work": [], "control": []}, app_locks={app: threading.RLock() for app in APPS},
            secret_lock=threading.RLock(), secret_values=set(), secret_material=set(), quiescing=False,
            expected_services={}, readiness={}, inventory=None, network_inventory=None, last_idle_check=0.0,
        )
        _REGISTRY.runtimes[key] = runtime
        return runtime


def _persist_runtime(runtime: Any) -> None:
    runtime.state["boot"] = BOOT_ID
    runtime.state["port_base"] = runtime.port_base
    _atomic_write(runtime.home / "runtime.json", json.dumps(runtime.state, sort_keys=True, allow_nan=False).encode())


def _stop_executor() -> tuple[ThreadPoolExecutor, Any]:
    with _REGISTRY.lock:
        if not hasattr(_REGISTRY, "stop_executor"):
            _REGISTRY.stop_executor = ThreadPoolExecutor(max_workers=STOP_PARALLELISM, thread_name_prefix="rapp-dock-stop")
            _REGISTRY.stop_pending = threading.BoundedSemaphore(STOP_PARALLELISM * 2)
        return _REGISTRY.stop_executor, _REGISTRY.stop_pending


def active_operations(home: Path | None = None) -> list[dict[str, Any]]:
    """Inspect all hot revisions' accepted work without importing their controllers."""
    selected = str(Path(home).expanduser().absolute()) if home is not None else None
    found = []
    with _REGISTRY.lock:
        runtimes = list(_REGISTRY.runtimes.values())
    for runtime in runtimes:
        if selected is not None and str(runtime.home) != selected:
            continue
        with runtime.lock:
            for op_id, pending in runtime.pending.items():
                record = runtime.ops.cache.get(op_id, {})
                found.append({
                    "id": op_id, "application": record.get("application"), "name": record.get("name"),
                    "status": record.get("status", "queued"), "phase": record.get("phase", "queued"),
                    "namespace": runtime.namespace,
                })
    return found


def quiesce(timeout: float = 30, home: Path | None = None) -> dict[str, Any]:
    """Pause new work and drain accepted work; call resume() after routing."""
    if not math.isfinite(timeout) or not 0 <= timeout <= 300:
        raise LocalDockError("invalid-input", "Quiescence timeout must be between 0 and 300 seconds.")
    selected = str(Path(home).expanduser().absolute()) if home is not None else None
    with _REGISTRY.lock:
        runtimes = list(_REGISTRY.runtimes.values())
    for runtime in runtimes:
        if selected is None or str(runtime.home) == selected:
            with runtime.lock:
                runtime.quiescing = True
    deadline = time.monotonic() + timeout
    while True:
        active = active_operations(home)
        if not active or time.monotonic() >= deadline:
            return {"quiesced": not active, "admission_paused": True, "active_operations": active}
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))


def resume(home: Path | None = None) -> None:
    selected = str(Path(home).expanduser().absolute()) if home is not None else None
    with _REGISTRY.lock:
        for runtime in _REGISTRY.runtimes.values():
            if selected is None or str(runtime.home) == selected:
                with runtime.lock:
                    if runtime.state.get("detach_paused"):
                        if selected is not None:
                            raise LocalDockError("detaching")
                        continue
                    runtime.quiescing = False


def context_hint(home: Path | None = None) -> str:
    """A disk-free hint; a hint never promotes a finished record to a verified reply."""
    selected = str(Path(home or dock_home()).expanduser().absolute())
    with _REGISTRY.lock:
        runtime = _REGISTRY.runtimes.get(selected)
    if runtime is None:
        return ""
    with runtime.lock:
        records = sorted(runtime.ops.cache.values(), key=lambda item: item["created"], reverse=True)[:3]
        return "; ".join(f"{r['id']} {r['name']} {r['status']} ({r.get('phase', r['status'])})" for r in records)


def historical_view(
    action: str, home: Path | None = None, *, timezone: str = "UTC",
    day: str | None = None, start_day: str | None = None, end_day: str | None = None,
    application: str | None = None, operation_id: str | None = None,
    limit: int = 10, cursor: str | None = None,
) -> dict[str, Any]:
    """Read verified evidence without initializing a controller or repairing receipts."""
    try:
        history = importlib.import_module("dock_history")
    except ImportError:
        raise LocalDockError("history-unavailable") from None
    try:
        reader_type = history.JobHistory
        if action == "history" and (start_day is not None or end_day is not None):
            if day is not None or start_day is None or end_day is None:
                raise history.HistoryError("history-invalid-range")
            try:
                if not 0 <= (date.fromisoformat(end_day) - date.fromisoformat(start_day)).days < 366:
                    raise ValueError
            except (ValueError, TypeError):
                raise history.HistoryError("history-invalid-range") from None

            class RangeHistory(history.JobHistory):
                def _query(self, view, **query):
                    selected, bounds = super()._query(view, **query)
                    if view != "history":
                        return selected, bounds
                    final, end = super()._query(view, **{**query, "day": end_day})
                    selected.update(day=None, start_day=start_day, end_day=final["day"])
                    bounds["end_utc"] = end["end_utc"]
                    return selected, bounds

                def _page(self, result, *args):
                    if result.get("view") == "history":
                        result["range"] = {"start_day": start_day, "end_day": end_day, "end_inclusive": True}
                    return super()._page(result, *args)

            reader_type, day = RangeHistory, start_day
        reader = reader_type(home if home is not None else dock_home())
        if action == "history":
            return reader.today(timezone=timezone, day=day, application=application, limit=limit, cursor=cursor)
        if action == "lineage":
            return reader.lineage(operation_id, limit=limit, cursor=cursor)
        raise LocalDockError("unsupported-action")
    except history.HistoryError as error:
        raise LocalDockError(error.code, safe_error(error.code)["message"]) from None


class AppContext:
    """What an adapter may do: operate its own compose project and private state."""

    def __init__(self, dock: "LocalDock", app: str, module: Any, op_id: str | None = None, *,
                 native_recovery: dict[str, Any] | None = None) -> None:
        self.dock = dock
        self.app = app
        self.module = module
        self.op_id = op_id
        self.root = Path(module.__file__).resolve().parent
        self.secrets_dir = dock.secrets_dir
        self.namespace = dock.namespace
        self.project = f"{self.namespace}-{app}"
        self.port = dock.port_base + APP_INDEX[app]
        self._input_commitments: dict[str, dict[str, Any]] = {}
        self._native_recovery = copy.deepcopy(native_recovery)
        self._resolved_images: dict[str, str] | None = None

    @property
    def state_dir(self) -> Path:
        return _private_dir(self.dock.home / "apps" / self.app)

    @property
    def outputs_dir(self) -> Path:
        """Stable app-wide mount, not the destination for an individual output."""
        return self.dock.home / "outputs" / self.app

    @property
    def output_dir(self) -> Path:
        if not self.op_id or _OP_ID.fullmatch(self.op_id) is None:
            raise LocalDockError("operation-required", "Saving outputs requires an operation id.")
        return _private_dir(self.outputs_dir / self.op_id)

    def host_url(self, path: str = "/") -> str:
        if not isinstance(path, str) or not path.startswith("/") or "\r" in path or "\n" in path:
            raise LocalDockError("invalid-input", "An application URL path must begin with '/'.")
        return f"http://127.0.0.1:{self.port}{path}"

    # -- secrets -----------------------------------------------------------------
    def secret_path(self, name: str) -> Path:
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise LocalDockError("invalid-secret-name", "Secret names must be simple file names.")
        return self.secrets_dir / name

    def secret(self, name: str, nbytes: int = 24, *, factory: Callable[[], str] | None = None) -> str:
        """Create-once private secret (0600); values are never returned in tool results."""
        with self.dock._secret_lock:
            return self._secret_value(name, nbytes, factory)

    def _secret_value(self, name: str, nbytes: int, factory: Callable[[], str] | None) -> str:
        path = self.secret_path(name)
        if self._native_recovery is not None and (
            factory is not None or name != {"openshorts": "openshorts-ingress-key", "dify": "dify-admin"}.get(self.app)
        ):
            raise LocalDockError("recovery-read-only")
        if path == self.dock.copilot_env or name == "copilot.env":
            raise LocalDockError("invalid-secret", "The Copilot env file is container-only, not an application secret.")
        if type(nbytes) is not int or not 16 <= nbytes <= 128:
            raise LocalDockError("invalid-secret", "Secret length must be between 16 and 128 bytes.")
        if not path.exists() and not path.is_symlink():
            if self._native_recovery is not None:
                raise LocalDockError("app-not-ready", "Recovery never creates missing app authentication.")
            value = factory() if factory else secrets.token_urlsafe(nbytes)
            if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
                raise LocalDockError("invalid-secret", "Secret values must be non-empty single-line text.")
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(value + "\n")
        try:
            with _regular_file(path) as stream:
                if stat.S_IMODE(os.fstat(stream.fileno()).st_mode) != 0o600:
                    raise LocalDockError("invalid-secret", "Secret files must have mode 0600.")
                data = stream.read(8193)
            if len(data) > 8192:
                raise LocalDockError("invalid-secret", "Secret file exceeds its size bound.")
            value = data.decode("utf-8").strip()
        except (OSError, UnicodeError):
            raise LocalDockError("invalid-secret", "Secret file is missing or unsafe.") from None
        if not value or "\n" in value or "\r" in value:
            raise LocalDockError("invalid-secret", "Secret file must contain one non-empty line.")
        self.dock._remember_secret(value)
        return value

    def write_env_file(self, name: str, mapping: dict[str, str]) -> Path:
        """Write a compose env_file (0600) whose values stay out of compose interpolation."""
        if self._native_recovery is not None:
            raise LocalDockError("recovery-read-only")
        path = self.secret_path(name)
        if path == self.dock.copilot_env or name == "copilot.env":
            raise LocalDockError("invalid-env-file", "The controller does not overwrite the Copilot env file.")
        lines = []
        for key, value in mapping.items():
            value = str(value)
            if re.fullmatch(r"[A-Z_][A-Z0-9_]*", key) is None or any(c in value for c in "\n\r\0'"):
                raise LocalDockError("invalid-env-file", "Invalid env-file field.")
            # Single quotes prevent Compose from expanding '$' or treating '#' as a comment.
            lines.append(f"{key}='{value}'\n")
            self.dock._remember_env_value(key, value)
        data = "".join(lines).encode()
        if path.is_symlink():
            raise LocalDockError("invalid-env-file", "Env files must not be symbolic links.")
        _atomic_write(path, data)
        return path

    # -- docker ------------------------------------------------------------------
    def compose_file(self) -> Path:
        return self.root / getattr(self.module, "COMPOSE", "compose.yaml")

    def compose_environment(self, *, resolve_images: bool = False) -> dict[str, str]:
        values = {
            "COMPOSE_PROJECT_NAME": self.project,
            "RAPP_DOCK_HOME": str(self.dock.home),
            "RAPP_DOCK_NAMESPACE": self.namespace,
            "RAPP_DOCK_PORT": str(self.port),
            "RAPP_DOCK_SECRETS": str(self.secrets_dir),
            "RAPP_DOCK_STATE": str(self.state_dir),
            "RAPP_DOCK_OUTPUTS": str(_private_dir(self.outputs_dir)),
            "RAPP_DOCK_AI_NETWORK": self.dock.ai_network,
            "RAPP_DOCK_COPILOT_ENV": str(self.dock.copilot_env),
            "RAPP_DOCK_AI_MODEL": self.dock.ai_model,
            "RAPP_DOCK_NETWORK_POOL": str(self.dock.network_pool),
            "RAPP_DOCK_AI_SUBNET": str(self.dock.ai_subnet),
        }
        extra = getattr(self.module, "compose_env", None)
        if extra is not None:
            for key, value in extra(self).items():
                if re.fullmatch(r"[A-Z_][A-Z0-9_]*", key) is None:
                    raise LocalDockError("invalid-compose-env", key)
                if key.startswith("RAPP_DOCK_IMAGE_") or key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "COMPOSE_ENV_FILES", "COMPOSE_DISABLE_ENV_FILE"):
                    raise LocalDockError("invalid-compose-env", "Adapters cannot replace the Docker execution environment.")
                if key in values and values[key] != str(value):
                    raise LocalDockError("invalid-compose-env", "Adapter cannot override controller-owned settings.")
                values[key] = str(value)
        if resolve_images and self._resolved_images is None:
            with self.dock._read_observation("image-resolution", check_cancelled=self.check_cancelled):
                self._resolved_images = self.dock.resolve_images(self.app)
        values.update(self._resolved_images or {})
        return values

    def _compose_argv(self, *args: str, overlay: Path | None = None) -> list[str]:
        return [
            "compose",
            "--ansi",
            "never",
            "--project-name",
            self.project,
            "--project-directory",
            str(self.root),
            "--file",
            str(self.compose_file()),
            *(["--file", str(overlay)] if overlay else []),
            *args,
        ]

    def compose(
        self,
        *args: str,
        timeout: float = 120,
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess:
        self.check_cancelled()
        if self._native_recovery is not None:
            self._recovery_compose(args)
        creating = bool(args and args[0] in ("up", "create"))
        if creating and self.dock.runtime.state.get("detach_paused"):
            raise LocalDockError("detaching")
        environment = self.compose_environment(resolve_images=True)
        with self.dock._resource_guard(self, self.dock._scope(self.app)) if creating else nullcontext(), (
            _REGISTRY.network_lock if creating else nullcontext()
        ):
            if creating:
                self.dock.ensure_network()
                overlay = self.dock._network_overlay(self, environment)
            else:
                overlay = self.dock._existing_network_overlay(self)
            if args and args[0] not in ("ps", "config", "logs", "images", "version"):
                self._effect()
            completed = self.dock._docker(
                self._compose_argv(*args, overlay=overlay),
                env=environment,
                timeout=timeout,
                input_bytes=input_bytes,
                cwd=self.root,
                check_cancelled=self.check_cancelled,
            )
            if creating:
                self.dock.runtime.network_inventory = None
        if completed.returncode != 0:
            error = self.dock._docker_failure("compose " + (args[0] if args else ""), completed)
            if self.op_id:
                self.dock.ops.update(self.op_id, diagnostic=error.diagnostic)
            if check:
                raise error
        return completed

    def _recovery_id(self, key: str) -> str:
        native = self._native_recovery.get("native")
        value = native.get(key) if isinstance(native, dict) else None
        if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", value) is None:
            raise LocalDockError("native-recovery-unavailable")
        return value

    def _recovery_compose(self, args: tuple[str, ...]) -> None:
        if args == ("config", "--services") or args[:1] == ("ps",):
            return
        if self.app != "openshorts":
            raise LocalDockError("recovery-read-only")
        job_id = self._recovery_id("job_id")
        if len(args) == 3 and args[0] == "cp":
            source, destination = args[1:]
            pattern = rf"backend:/app/output/{re.escape(job_id)}/[A-Za-z0-9_][A-Za-z0-9_.-]{{0,239}}"
            if (
                re.fullmatch(pattern, source) and source.endswith((".mp4", "_metadata.json"))
                and Path(destination).parent == self.output_dir and ".." not in Path(destination).parts
            ):
                return
        if len(args) == 8 and args[:5] == ("exec", "-T", "backend", "python", "-c"):
            operation, selected = args[6:]
            if not (
                operation == "metadata" and selected == job_id
                or operation == "clip" and re.fullmatch(
                    rf"/app/output/{re.escape(job_id)}/[A-Za-z0-9_][A-Za-z0-9_.-]{{0,239}}\.mp4", selected,
                )
            ):
                raise LocalDockError("recovery-read-only")
            path = self.root / "native_probe.py"
            try:
                relative = path.relative_to(ROOT).as_posix()
                entry = next(item for item in capability_manifest(ROOT)["files"] if item["path"] == relative)
                raw = read_regular(path)
                if (
                    len(raw) == entry["bytes"] <= MAX_BIND_ALIAS_BYTES
                    and hashlib.sha256(raw).hexdigest() == entry["sha256"] and args[5].encode() == raw
                ):
                    return
            except (OSError, ValueError, KeyError, TypeError, StopIteration, DistributionRefused):
                pass
        raise LocalDockError("recovery-read-only")

    def exec(
        self,
        service: str,
        argv: list[str],
        *,
        timeout: float = 120,
        user: str | None = None,
        input_bytes: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        args = ["exec", "-T"]
        if user:
            args += ["--user", user]
        return self.compose(*args, service, *argv, timeout=timeout, check=check, input_bytes=input_bytes)

    def services(self) -> list[str]:
        completed = self.compose("config", "--services", timeout=30)
        services = [line.strip() for line in _text(completed.stdout).splitlines() if line.strip()]
        with self.dock.runtime.lock:
            self.dock.runtime.expected_services[self.app] = set(services)
        return services

    def containers(self) -> list[dict[str, Any]]:
        with self.dock._read_observation("inventory", check_cancelled=self.check_cancelled):
            return self.dock._container_rows(self.app)

    def running(self) -> bool:
        rows = self.containers()
        return bool(rows) and any(row["state"] == "running" for row in rows)

    def copy_from(self, service: str, container_path: str, name: str, media_type: str) -> dict[str, Any]:
        """Copy a file out of a service container into this app's outputs."""
        self.check_cancelled()
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", service) or not container_path.startswith("/"):
            raise LocalDockError("invalid-input", "Expected an enrolled service and an absolute container path.")
        destination = self.output_path(name)
        try:
            completed = self.compose("cp", f"{service}:{container_path}", str(destination), timeout=300, check=False)
            if completed.returncode != 0:
                raise LocalDockError("copy-failed", "Could not collect the application's output file.")
            with _regular_file(destination) as stream:
                os.fchmod(stream.fileno(), 0o600)
            return self.describe_output(destination, media_type)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    # -- outputs -----------------------------------------------------------------
    def output_path(self, name: str) -> Path:
        if not isinstance(name, str) or not name or any(c in name for c in "/\\\0") or name in (".", ".."):
            raise LocalDockError("invalid-input", "Output names must be simple file names.")
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "output"
        path = self.output_dir / stem[:120]
        while True:
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                path = self.output_dir / f"{Path(stem[:100]).stem}-{uuid.uuid4().hex[:12]}{Path(stem).suffix[:16]}"
            else:
                os.close(descriptor)
                return path

    def save_output(self, name: str, data: bytes | str, media_type: str, verified: bool = False) -> dict[str, Any]:
        self.check_cancelled()
        if isinstance(data, str):
            data = data.encode("utf-8")
        if not isinstance(data, bytes) or len(data) > MAX_OUTPUT_BYTES or type(verified) is not bool:
            raise LocalDockError("output-invalid", "Output must be bounded bytes with an explicit verification flag.")
        path = self.output_path(name)
        try:
            _atomic_write(path, data)
            return self.describe_output(path, media_type, verified)
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def describe_output(path: Path, media_type: str = "application/octet-stream", verified: bool = False) -> dict[str, Any]:
        if not isinstance(media_type, str) or not media_type or len(media_type) > 200 or any(c in media_type for c in "\r\n\0"):
            raise LocalDockError("output-invalid", "Output media type is invalid.")
        digest = hashlib.sha256()
        size = 0
        with _regular_file(path) as stream:
            if os.fstat(stream.fileno()).st_size > MAX_OUTPUT_BYTES:
                raise LocalDockError("output-invalid", "Output exceeds the byte limit.")
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
                if size > MAX_OUTPUT_BYTES:
                    raise LocalDockError("output-invalid", "Output exceeds the byte limit.")
        return {
            "name": path.name, "path": str(path), "media_type": media_type,
            "bytes": size, "sha256": digest.hexdigest(), "verified": verified,
        }

    def mark_verified(self, artifact: dict[str, Any]) -> dict[str, Any]:
        path = Path(artifact.get("path", ""))
        if not path.is_absolute() or path.parent != self.output_dir:
            raise LocalDockError("output-invalid", "Verification requires this operation's output.")
        observed = self.describe_output(path, artifact.get("media_type"), True)
        if any(artifact.get(key) != observed[key] for key in ("name", "bytes", "sha256")):
            raise LocalDockError("output-invalid", "Output changed since collection.")
        artifact.update(observed)
        return artifact

    def _input_source(self, path: str | Path) -> Path:
        if not isinstance(path, (str, Path)) or "\0" in str(path):
            raise LocalDockError("invalid-input", "Select an owner-home file path.")
        source = Path(path).expanduser()
        owner = self.dock.owner_home
        if not source.is_absolute() or ".." in source.parts or not source.is_relative_to(owner):
            raise LocalDockError("invalid-input", "Select an absolute regular file inside the owner's home.")
        if self.dock._credential_input(source):
            raise LocalDockError("invalid-input", "Credential locations cannot be used as job input.")
        if source.is_relative_to(self.dock.home / "outputs"):
            artifact = self.dock._enrolled_artifact(source)
            self._input_commitments[str(source)] = artifact
        elif not any(source != root and source.is_relative_to(root) for root in self.dock.input_roots):
            raise LocalDockError("input-not-enrolled")
        return source

    def _check_input_commitment(self, source: Path, size: int, digest: str) -> None:
        expected = self._input_commitments.get(str(source))
        if expected is not None and (expected["bytes"] != size or expected["sha256"] != digest):
            raise LocalDockError("input-artifact-changed")

    def seal_input(self, path: str | Path) -> dict[str, Any]:
        """Take or reuse this operation's immutable private input snapshot."""
        if self._native_recovery is not None:
            raise LocalDockError("recovery-read-only")
        self.check_cancelled()
        if not self.op_id or _OP_ID.fullmatch(self.op_id) is None:
            raise LocalDockError("operation-required", "Input custody requires an operation id.")
        source = self._input_source(path)
        cached = self.dock.ops.get(self.op_id).get("sealed_inputs", {}).get(str(source))
        if cached:
            selected = Path(cached["path"])
            if selected.parent != self.state_dir / "inbox" / self.op_id:
                raise LocalDockError("invalid-input", "The private input snapshot is outside this operation.")
            with _regular_file(selected) as stream:
                info = os.fstat(stream.fileno())
                if info.st_size != cached["bytes"] or stat.S_IMODE(info.st_mode) != 0o600:
                    raise LocalDockError("invalid-input", "The private input snapshot changed.")
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
                if digest.hexdigest() != cached["sha256"] or (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise LocalDockError("invalid-input", "The private input snapshot changed.")
            self._check_input_commitment(source, cached["bytes"], cached["sha256"])
            return dict(cached)
        destination = None
        try:
            with _regular_file(source) as stream:
                before = os.fstat(stream.fileno())
                if before.st_size > MAX_INPUT_BYTES:
                    raise LocalDockError("invalid-input", "Input exceeds the 512 MiB limit.")
                inbox = _private_dir(self.state_dir / "inbox" / self.op_id)
                destination = inbox / f"{uuid.uuid4().hex}-{source.name[:120]}"
                descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                digest, size = hashlib.sha256(), 0
                with os.fdopen(descriptor, "wb") as output:
                    while chunk := stream.read(1024 * 1024):
                        self.check_cancelled()
                        size += len(chunk)
                        if size > MAX_INPUT_BYTES:
                            raise LocalDockError("invalid-input", "Input exceeds the 512 MiB limit.")
                        output.write(chunk)
                        digest.update(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                after = os.fstat(stream.fileno())
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns
                ):
                    raise LocalDockError("invalid-input", "Input changed while it was being copied.")
            sealed = {"name": source.name, "path": str(destination), "bytes": size, "sha256": digest.hexdigest()}
            self._check_input_commitment(source, size, sealed["sha256"])
            with self.dock.ops.lock:
                record = self.dock.ops.get(self.op_id)
                inputs = record.get("inputs", [])
                item = {key: sealed[key] for key in ("name", "bytes", "sha256")}
                if item not in inputs:
                    if len(inputs) >= 64:
                        raise LocalDockError("invalid-input", "An operation cannot seal more than 64 inputs.")
                    inputs = [*inputs, item]
                self.dock.ops.update(
                    self.op_id, inputs=inputs,
                    sealed_inputs={**record.get("sealed_inputs", {}), str(source): sealed},
                )
            return sealed
        except BaseException as error:
            if destination is not None:
                destination.unlink(missing_ok=True)
            if isinstance(error, FileNotFoundError):
                raise LocalDockError("input-not-found", "The selected input file does not exist.") from None
            if isinstance(error, OSError) or isinstance(error, LocalDockError) and error.code == "unsafe-file":
                raise LocalDockError("invalid-input", "Input must be a regular owner file without symbolic or hard links.") from None
            raise

    # -- http --------------------------------------------------------------------
    def http(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
        max_bytes: int = MAX_HTTP_BYTES,
    ) -> HttpResult:
        import urllib.request

        global _OPENER
        if _OPENER is None:
            class NoAutomaticRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, request, response, code, message, headers, newurl):
                    return None

            _OPENER = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), NoAutomaticRedirect(),
            )
        self.check_cancelled()
        method = method.upper() if isinstance(method, str) else ""
        if method not in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            raise LocalDockError("http-destination-refused")
        origin = self._http_origin(url)
        if self._native_recovery is not None:
            self._recovery_http(method, url, json_body, data)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 1800:
            raise LocalDockError("invalid-input", "HTTP timeout must be finite and bounded.")
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_OUTPUT_BYTES:
            raise LocalDockError("invalid-input", "HTTP response limit is outside the supported range.")
        body = data
        merged = dict(headers or {})
        if any(
            not isinstance(name, str) or not isinstance(value, str) or "\r" in name + value or "\n" in name + value
            or name.lower() == "host" and value != urlsplit(url).netloc
            for name, value in merged.items()
        ):
            raise LocalDockError("http-destination-refused")
        if json_body is not None:
            body = json.dumps(json_body, allow_nan=False).encode()
            merged.setdefault("Content-Type", "application/json")
        if method not in ("GET", "HEAD", "OPTIONS"):
            self._effect()
        def read(response, status: int) -> HttpResult:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise LocalDockError("response-too-large", "Application response exceeded its byte limit.")
            # Deliver accepted native IDs even if cancellation arrived during the request.
            headers = _http_headers(response.headers)
            for name, value in headers.items():
                if name.lower() == "set-cookie":
                    for cookie in value.split("\n"):
                        secret = cookie.split(";", 1)[0].partition("=")[2]
                        if len(secret) >= 8:
                            self.dock._remember_secret(secret)
            return HttpResult(status, headers, data)

        try:
            deadline = time.monotonic() + timeout
            for redirects in range(MAX_HTTP_REDIRECTS + 1):
                self.check_cancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LocalDockError("http-unavailable")
                request = urllib.request.Request(url, data=body, method=method, headers=merged)
                try:
                    response = _OPENER.open(request, timeout=remaining)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    status = response.status
                    if status not in (301, 302, 303, 307, 308):
                        return read(response, status)
                    headers = _http_headers(response.headers)
                    location = next((value for name, value in headers.items() if name.lower() == "location"), None)
                    if method not in ("GET", "HEAD") or not location or redirects == MAX_HTTP_REDIRECTS:
                        raise LocalDockError("http-redirect-refused")
                    target = urljoin(url, location)
                    try:
                        if self._http_origin(target) != origin:
                            raise LocalDockError("http-redirect-refused")
                        if self._native_recovery is not None:
                            self._recovery_http(method, target, json_body, data)
                    except LocalDockError:
                        raise LocalDockError("http-redirect-refused") from None
                    url = target
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise LocalDockError("http-unavailable", "Application HTTP endpoint is unavailable.") from None

    def _http_origin(self, url: str) -> tuple[str, str, int]:
        try:
            if not isinstance(url, str) or len(url) > 8192 or url != url.strip() or "\\" in url or any(ord(character) < 32 or ord(character) == 127 for character in url):
                raise ValueError
            parsed = urlsplit(url)
            if (
                parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.username is not None or parsed.password is not None or parsed.fragment
                or parsed.port not in (self.port, self.dock.port_base)
                or parsed.netloc != f"127.0.0.1:{parsed.port}"
            ):
                raise ValueError
            return parsed.scheme, parsed.hostname, parsed.port
        except (ValueError, TypeError):
            raise LocalDockError("http-destination-refused") from None

    def _recovery_http(self, method: str, url: str, json_body: Any, data: bytes | None) -> None:
        parsed = urlsplit(url)
        if parsed.port != self.port or data is not None:
            raise LocalDockError("recovery-read-only")
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        if self.app == "openshorts":
            if method == "GET" and json_body is None and path == "/api/status/" + self._recovery_id("job_id"):
                return
        elif self.app == "dify":
            dataset = "/console/api/datasets/" + self._recovery_id("dataset_id")
            if method == "GET" and json_body is None and path in (dataset, dataset + "/documents?limit=100&fetch=true"):
                return
            if (
                method == "POST" and path == "/console/api/login"
                and isinstance(json_body, dict) and set(json_body) == {"email", "password", "remember_me", "language"}
                and json_body["email"] == f"dock-{self.namespace}@dify.invalid"
                and isinstance(json_body["password"], str) and 1 <= len(json_body["password"]) <= 1024
                and json_body["remember_me"] is False and json_body["language"] == "en-US"
            ):
                password = base64.b64encode(("Q9" + self.secret("dify-admin")).encode()).decode()
                if json_body["password"] == password:
                    self.dock._remember_secret(password)
                    return
        raise LocalDockError("recovery-read-only")

    def wait_until(self, pred: Callable[[], bool], timeout: float, interval: float = 2.0) -> bool:
        if not math.isfinite(timeout) or not math.isfinite(interval) or not 0 <= timeout <= 86400 or not 0 < interval <= 60:
            raise LocalDockError("invalid-input", "Wait timeout and interval must be bounded positive values.")
        deadline = time.monotonic() + timeout
        while True:
            self.check_cancelled()
            # Polling already re-observes; an inner wake retry could only overrun this deadline.
            token = _READ_RETRY_DISABLED.set(True)
            try:
                if pred():
                    return True
            except LocalDockError as error:
                if error.code == "cancelled":
                    raise
            finally:
                _READ_RETRY_DISABLED.reset(token)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(interval, remaining))

    # -- cross-app -----------------------------------------------------------------
    def intelligence(self) -> dict[str, Any]:
        """Connection details for the Copilot-backed OpenAI-compatible endpoint."""
        if self._native_recovery is not None:
            raise LocalDockError("recovery-read-only")
        return {
            "internal_url": "http://intelligence:8080/v1",
            "host_url": f"http://127.0.0.1:{self.dock.port_base}/v1",
            "api_key": self.secret(f"intelligence-key-{self.app}"),
            "model": self.dock.ai_model,
        }

    def ensure_app(self, other: str) -> dict[str, Any]:
        """Start another enrolled application synchronously (dependency)."""
        if self._native_recovery is not None:
            raise LocalDockError("recovery-read-only")
        self.check_cancelled()
        record = self.dock.ops.get(self.op_id) if self.op_id else {}
        if record.get("scope") is not None and other not in record["scope"]:
            raise LocalDockError("invalid-adapter", "Dependencies must be declared in NEEDS before admission.")
        result = self.dock.start_sync(other, self.op_id, automatic=record.get("kind") == "job")
        self.check_cancelled()
        return result

    def check_cancelled(self) -> None:
        if self.op_id:
            record = self.dock.ops.get(self.op_id)
            if record.get("cancel_requested") or record.get("status") in ("cancelled", "interrupted"):
                raise LocalDockError("cancelled", "This operation was cancelled; no further work will be submitted.")
            if record.get("kind") == "lifecycle" and record.get("name") in ("stop", "restart", "idle-down"):
                return
            fence = record.get("fence")
            if fence is not None:
                with self.dock.runtime.lock:
                    current = self.dock.runtime.state
                    changed = fence["generation"] != current["generation"] or any(
                        current["app_generations"].get(app) != generation
                        for app, generation in fence["apps"].items()
                    )
                if changed:
                    raise LocalDockError("cancelled", "A stop fence cancelled this operation.")

    def _effect(self) -> None:
        if self._native_recovery is not None:
            return
        self.check_cancelled()
        if self.op_id:
            with self.dock.ops.lock:
                record = self.dock.ops.get(self.op_id)
                if not record.get("effects_started"):
                    self.dock.ops.update(self.op_id, effects_started=True)

    def record_native(self, key: str, value: Any) -> None:
        if not self.op_id:
            raise LocalDockError("operation-required", "Native state requires an operation id.")
        if not isinstance(key, str) or _NAME.fullmatch(key) is None:
            raise LocalDockError("invalid-input", "Invalid native record key.")
        try:
            encoded = json.dumps(value, allow_nan=False)
        except (TypeError, ValueError):
            raise LocalDockError("invalid-input", "Native records must contain bounded JSON.") from None
        if len(encoded.encode()) > 4096:
            raise LocalDockError("invalid-input", "Native record exceeds its byte limit.")
        if self.dock.redact(encoded) != encoded:
            raise LocalDockError("invalid-input", "Native records cannot contain secrets.")
        self.dock.ops.record_native(self.op_id, key, value)

    def phase(self, name: str, detail: Any = None) -> None:
        self.check_cancelled()
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise LocalDockError("invalid-input", "Invalid operation phase.")
        if self.op_id:
            detail = self.dock.redact(str(detail))[:300] if detail is not None else None
            record = self.dock.ops.get(self.op_id)
            if record.get("phase") == name and record.get("phase_detail") == detail:
                return
            self.dock.ops.update(self.op_id, phase=name, phase_detail=detail, updated_at=_now())
            self.log(name + (f": {detail}" if detail else ""))
            self.dock._exhaust_phase(self.op_id, name, {"detail": detail})

    def log(self, message: str) -> None:
        if self.op_id:
            self.dock.ops.progress(self.op_id, self.dock.redact(message))

    @staticmethod
    def preview(text: str, limit: int = 3000) -> str:
        return text if len(text) <= limit else text[:limit] + f"\n…[{len(text) - limit} more characters saved to the output file]"


def _validate_arguments(spec: dict[str, Any], arguments: Any, *, job: str | None = None) -> dict[str, Any]:
    try:
        return _contract_arguments(spec, {} if arguments is None else arguments, job=job)
    except ContractError as error:
        raise LocalDockError(error.code, error.message) from None


def load_adapter(app: str) -> Any:
    if app not in APPS:
        raise LocalDockError("unknown-application", "Select an enrolled application.")
    module_name = f"deploy.local.{app.replace('-', '_')}.adapter"
    expected = LOCAL_ROOT / app.replace("-", "_") / "adapter.py"
    if not expected.exists() and not expected.is_symlink():
        raise LocalDockError("not-installed", f"{app}'s local adapter is not installed.")
    try:
        selected = expected.relative_to(ROOT).as_posix()
        entry = next(item for item in capability_manifest(ROOT)["files"] if item["path"] == selected)
        raw = read_regular(expected)
        if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError
    except (DistributionRefused, StopIteration, OSError, ValueError, KeyError, TypeError):
        raise LocalDockError("adapter-not-reviewed", "Adapter bytes are not in the reviewed capability inventory.") from None
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name and (module_name == error.name or module_name.startswith(error.name + ".")):
            raise LocalDockError("not-installed", f"{app}'s local adapter is not installed.") from None
        raise LocalDockError("adapter-unavailable", "An adapter dependency is unavailable.") from None
    except Exception:
        raise LocalDockError("adapter-unavailable", "The reviewed adapter could not be loaded.") from None
    if Path(module.__file__).resolve() != expected.resolve():
        raise LocalDockError("adapter-not-reviewed", "Adapter is not part of this capability.")
    if getattr(module, "APP", None) != app or not isinstance(getattr(module, "TITLE", None), str) or not isinstance(getattr(module, "JOBS", None), dict):
        raise LocalDockError("invalid-adapter", "Adapter must declare its enrolled APP, TITLE and JOBS.")
    for name, spec in module.JOBS.items():
        if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name) is None or not isinstance(spec, dict) or not callable(spec.get("run")):
            raise LocalDockError("invalid-adapter", "Adapter jobs need reviewed names and handlers.")
    return module


def discover_jobs(app: str | None = None, query: str | None = None, *, loader: Callable = load_adapter) -> dict[str, Any]:
    if app is not None and app not in APPS:
        raise LocalDockError("unknown-application", "Select an enrolled application.")
    catalog, applications = [], []
    words = (query or "").casefold().split()
    for name in (app,) if app else APPS:
        try:
            module = loader(name)
        except LocalDockError as error:
            applications.append({"application": name, "state": "not-installed" if error.code == "not-installed" else "unknown", "error": error.code})
            continue
        applications.append({"application": name, "state": "installed"})
        for job, spec in module.JOBS.items():
            spec = job_spec(spec, f"{module.APP}.{job}")
            item = {
                "application": name, "job": f"{module.APP}.{job}",
                "description": spec.get("description", ""), "parameters": spec.get("parameters", {}),
                "required": list(spec.get("required", ())),
                "heavy": bool(spec.get("heavy") or getattr(module, "HEAVY", False)),
                "aliases": list(spec.get("aliases", ())),
            }
            searchable = " ".join((item["job"], item["description"], *item["aliases"])).casefold()
            if all(word in searchable for word in words):
                catalog.append(item)
    return {"jobs": catalog, "applications": applications}


class LocalDock:
    """The single controller Scotty uses for local application lifecycle and jobs."""

    _instances: dict[str, "LocalDock"] = {}
    _instances_lock = threading.Lock()

    @classmethod
    def shared(cls, home: Path | None = None) -> "LocalDock":
        home = Path(os.path.abspath(home or dock_home()))
        key = "|".join((str(home), *(os.environ.get(name, "") for name in (
            "RAPP_DOCK_NAMESPACE", "RAPP_DOCK_PORT_BASE", "RAPP_DOCK_AI_MODEL",
            "RAPP_DOCK_COPILOT_ENV", "RAPP_DOCK_DOCKER", "RAPP_DOCK_NETWORK_POOL",
            "RAPP_DOCK_INPUT_ROOTS",
        ))))
        with cls._instances_lock:
            if key not in cls._instances:
                cls._instances[key] = cls(home)
            return cls._instances[key]

    @classmethod
    def for_installation(cls, *, home: str | Path, namespace: str, port_base: int) -> "LocalDock":
        """Bind verified installer receipt fields; never select ambient home/scope."""
        if (
            not isinstance(home, (str, Path)) or not Path(home).is_absolute() or ".." in Path(home).parts
            or Path(home) in (Path(Path(home).anchor), Path.home())
            or not isinstance(namespace, str) or re.fullmatch(NAMESPACE_PATTERN, namespace) is None
            or type(port_base) is not int or not 1024 <= port_base <= 65535 - max(APP_INDEX.values())
        ):
            raise LocalDockError("installation-binding-invalid")
        with _REGISTRY.lock:
            prior = _REGISTRY.runtimes.get(str(Path(home).absolute()))
            if prior is not None and (prior.namespace, prior.port_base) != (namespace, port_base):
                raise LocalDockError("installation-binding-mismatch")
        return cls(Path(home), namespace=namespace, port_base=port_base)

    def __init__(self, home: Path, *, namespace: str | None = None, port_base: int | None = None) -> None:
        self.namespace = namespace if namespace is not None else os.environ.get("RAPP_DOCK_NAMESPACE", DEFAULT_NAMESPACE)
        if not isinstance(self.namespace, str) or re.fullmatch(NAMESPACE_PATTERN, self.namespace) is None:
            raise LocalDockError("invalid-namespace", "Use rapp-dock or an isolated rapp-dock-t[a-h] namespace.")
        if port_base is not None and type(port_base) is not int:
            raise LocalDockError("invalid-port-base")
        raw_port = str(port_base) if port_base is not None else os.environ.get("RAPP_DOCK_PORT_BASE", str(DEFAULT_PORT_BASE))
        if not re.fullmatch(r"[0-9]{1,5}", raw_port) or not 1024 <= int(raw_port) <= 65535 - max(APP_INDEX.values()):
            raise LocalDockError("invalid-port-base", "Port base must leave six unprivileged TCP ports available.")
        self.port_base = int(raw_port)
        self.ai_network = f"{self.namespace}-ai"
        self.ai_model = os.environ.get("RAPP_DOCK_AI_MODEL", DEFAULT_AI_MODEL)
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}", self.ai_model):
            raise LocalDockError("invalid-ai-model", "Invalid application intelligence model identifier.")
        self.owner_home = Path.home()
        try:
            self.network_pool = ipaddress.ip_network(os.environ.get("RAPP_DOCK_NETWORK_POOL", DEFAULT_NETWORK_POOL), strict=True)
            private_ranges = map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
            if self.network_pool.version != 4 or self.network_pool.prefixlen != 16 or not any(self.network_pool.subnet_of(pool) for pool in private_ranges):
                raise ValueError
        except (ValueError, TypeError):
            raise LocalDockError("invalid-network-pool", "RAPP_DOCK_NETWORK_POOL must be a reserved RFC1918 IPv4 /16.") from None
        namespace_index = 0 if self.namespace == DEFAULT_NAMESPACE else ord(self.namespace[-1]) - ord("a") + 1
        self.network_block = list(self.network_pool.subnets(new_prefix=20))[namespace_index]
        self.ai_subnet = next(self.network_block.subnets(new_prefix=NETWORK_PREFIX))
        self.home = Path(home).expanduser().absolute()
        self.copilot_env = Path(os.environ.get(
            "RAPP_DOCK_COPILOT_ENV", str(self.home / "secrets" / "copilot.env")
        )).expanduser().absolute()
        self.secrets_dir = self.home / "secrets"
        self._configured_input_roots()
        self.home = _private_dir(self.home)
        self.secrets_dir = _private_dir(self.home / "secrets")
        self.docker_override = os.environ.get("RAPP_DOCK_DOCKER", "")
        self.runtime = _runtime(self.home, self.namespace, self.port_base, self.docker_override)
        self._secret_values = self.runtime.secret_values
        self._secret_lock = self.runtime.secret_lock
        with self._secret_lock:
            if not hasattr(self.runtime, "secret_material"):
                self.runtime.secret_material = set()
            if not hasattr(self.runtime, "safe_configuration"):
                self.runtime.safe_configuration = set()
        previous_model = getattr(getattr(self.runtime, "current", None), "ai_model", None)
        for value in (
            self.ai_model, previous_model, "http://intelligence:8080/v1",
            f"http://127.0.0.1:{self.port_base}/v1",
            *(f"http://127.0.0.1:{self.port_base + index}/" for index in APP_INDEX.values()),
        ):
            if isinstance(value, str):
                self._remember_configuration(value)
        self.ops = self.runtime.ops
        self._app_locks = self.runtime.app_locks
        self._heavy = _REGISTRY.heavy
        self._exhaust_checked = False
        self._exhaust_client = None
        with self.runtime.lock:
            self.runtime.current = self

    # -- adapters ------------------------------------------------------------------
    def adapter(self, app: str) -> Any:
        return load_adapter(app)

    def context(self, app: str, op_id: str | None = None) -> AppContext:
        return AppContext(self, app, self.adapter(app), op_id)

    def _image_inspect(self, args: list[str], *, timeout: float = 20) -> subprocess.CompletedProcess:
        if (
            not isinstance(args, list) or len(args) != 3 or args[:2] != ["image", "inspect"]
            or not isinstance(args[2], str) or not (
                _IMAGE_ID.fullmatch(args[2]) or re.fullmatch(r"[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}", args[2])
            ) or "://" in args[2] or isinstance(timeout, bool)
            or not isinstance(timeout, (int, float)) or not 0 < timeout <= 20
        ):
            raise LocalDockError("image-lock-mismatch")
        return self._docker([
            "image", "inspect", "--format",
            IMAGE_INSPECT_FORMAT,
            args[2],
        ], timeout=timeout, max_bytes=64 * 1024)

    @_observed_read("image-resolution")
    def resolve_images(self, app: str) -> dict[str, str]:
        """Resolve installed locked components with a read-only Docker boundary."""
        selected = ROOT / "deploy/local/materialize.py"
        if not selected.exists() and not selected.is_symlink():
            raise LocalDockError("image-resolution-unavailable")
        try:
            entries = {item["path"]: item for item in capability_manifest(ROOT)["files"]}
            raw_lock = None
            for name in ("deploy/local/materialize.py", "deploy/local/components.lock.json"):
                raw = read_regular(ROOT / name)
                if len(raw) != entries[name]["bytes"] or hashlib.sha256(raw).hexdigest() != entries[name]["sha256"]:
                    raise ValueError
                if name.endswith(".json"):
                    raw_lock = raw
            lock = json.loads(raw_lock)
            expected = {lock["components"][name]["env"] for name in lock["applications"][app].values()}
            module = importlib.import_module("deploy.local.materialize")
            if Path(module.__file__).resolve() != selected.resolve() or selected.is_symlink():
                raise ValueError
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError, DistributionRefused):
            raise LocalDockError("image-lock-mismatch") from None
        observed = set()

        def inspect(args, *, timeout=20):
            result = self._image_inspect(args, timeout=timeout)
            if result.returncode == 0:
                for image in self._parse_rows(result.stdout):
                    identity = image.get("Id")
                    if isinstance(identity, str) and _IMAGE_ID.fullmatch(identity):
                        observed.add(identity)
            return result

        try:
            values = module.resolve_images(app, root=ROOT, state_dir=self.home / "materialize", run=inspect)
        except module.MaterializeRefused as error:
            code = "image-missing" if error.code == "image-not-materialized" else (
                "docker-state-unknown" if error.code == "docker-inspection-failed" else "image-lock-mismatch"
            )
            raise LocalDockError(code) from None
        if (
            not isinstance(values, dict) or set(values) != expected or not 1 <= len(values) <= 32
            or any(not isinstance(key, str) or re.fullmatch(r"RAPP_DOCK_IMAGE_[A-Z0-9_]+", key) is None for key in values)
            or any(not isinstance(value, str) or _IMAGE_ID.fullmatch(value) is None or value not in observed for value in values.values())
        ):
            raise LocalDockError("image-lock-mismatch")
        return values

    @_observed_read("image-capture")
    def _capture_images(self, ctx: AppContext, expected_ids: list[str] | None = None) -> None:
        observation = _READ_OBSERVATION.get()
        if observation is not None and ctx.check_cancelled not in observation.checks:
            observation.checks.append(ctx.check_cancelled)
        if not ctx.op_id or self.ops.get(ctx.op_id)["application"] != ctx.app:
            return
        rows = ctx.containers()
        ids = [row["id"] for row in rows]
        if expected_ids is not None and set(ids) != set(expected_ids):
            raise LocalDockError("app-not-ready")
        if not 1 <= len(ids) <= 32 or any(
            not isinstance(identifier, str) or re.fullmatch(r"[a-f0-9]{12,64}", identifier) is None for identifier in ids
        ):
            raise LocalDockError("docker-state-unknown")
        inspected = self._docker([
            "inspect", "--type", "container", "--format",
            IDENTITY_INSPECT_FORMAT,
            *ids,
        ], timeout=5, max_bytes=64 * 1024)
        if inspected.returncode:
            raise self._docker_failure("inspect image identities", inspected, "docker-state-unknown")
        containers = self._parse_rows(inspected.stdout)
        if len(containers) != len(rows) or len({item.get("id") for item in containers}) != len(rows):
            raise LocalDockError("docker-state-unknown")
        architectures = {}
        images = []
        for item in containers:
            identity, service = item.get("image_id"), item.get("service")
            if (
                not isinstance(identity, str) or _IMAGE_ID.fullmatch(identity) is None
                or item.get("project") != ctx.project or not isinstance(service, str) or _NAME.fullmatch(service) is None
                or not any(item.get("id", "").startswith(row["id"]) and service == row["service"] for row in rows)
            ):
                raise LocalDockError("docker-state-unknown")
            if ctx._resolved_images and identity not in ctx._resolved_images.values():
                raise LocalDockError("image-lock-mismatch")
            if identity not in architectures:
                inspected = self._image_inspect(["image", "inspect", identity])
                if inspected.returncode:
                    raise self._docker_failure("inspect image platform", inspected, "docker-state-unknown")
                facts = self._parse_rows(inspected.stdout)
                if len(facts) != 1 or facts[0].get("Id") != identity:
                    raise LocalDockError("image-lock-mismatch")
                platform = str(facts[0].get("Os")) + "/" + str(facts[0].get("Architecture"))
                architectures[identity] = platform if platform in ("linux/arm64", "linux/amd64") else None
            images.append({"service": service, "image_id": identity, "manifest_sha256": None,
                           "architecture": architectures[identity]})
        if expected_ids is not None:
            current = ctx.containers()
            if set(expected_ids) != {row["id"] for row in current} or not self._roles_ready(
                ctx.module, current, self.runtime.expected_services.get(ctx.app, set()),
            ):
                raise LocalDockError("app-not-ready")
        self.ops.update(ctx.op_id, images=sorted(images, key=lambda item: (item["service"], item["image_id"])))

    def _credential_input(self, source: Path) -> bool:
        if not source.is_relative_to(self.owner_home):
            return True
        full_parts = tuple(part.casefold() for part in source.relative_to(self.owner_home).parts)
        parts = full_parts
        for allowed in (self.home / "inputs", self.home / "outputs"):
            if source.is_relative_to(allowed):
                ancestors = self.home.relative_to(self.owner_home).parts[:-1]
                parts = tuple(part.casefold() for part in (*ancestors, *source.relative_to(allowed).parts))
                break
        credential_parts = {
            ".ssh", ".aws", ".azure", ".gnupg", ".kube", ".docker", ".copilot", ".brainstem",
            ".claude", ".codex", ".gemini", ".git", ".config", "keychains", "keyrings", "secrets", ".secrets", "credentials",
        }
        credential_names = {
            ".netrc", ".git-credentials", ".npmrc", ".pypirc", ".authinfo",
            "credentials", "credentials.json", "id_rsa", "id_ed25519", "copilot.env",
        }
        return (
            any(part in credential_parts for part in full_parts)
            or any(part.startswith(".") for part in parts)
            or source.name.casefold() in credential_names
            or source.name.casefold() == ".env" or source.name.casefold().startswith(".env.")
            or source.suffix.casefold() in (".key", ".pem", ".p12", ".pfx", ".keychain-db")
            or source == self.copilot_env or source.is_relative_to(self.secrets_dir)
        )

    @property
    def input_roots(self) -> tuple[Path, ...]:
        return self._configured_input_roots()

    def _input_roots_file(self) -> list[str]:
        try:
            with _directory_fd(self.home) as parent:
                present = os.stat("input-roots.json", dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISREG(present.st_mode) or present.st_uid != os.geteuid()
                or present.st_nlink != 1 or stat.S_IMODE(present.st_mode) != 0o600
                or present.st_size > MAX_INPUT_CONFIG_BYTES
            ):
                raise ValueError
            with _regular_file(self.home / "input-roots.json") as stream:
                before = os.fstat(stream.fileno())
                if stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > MAX_INPUT_CONFIG_BYTES:
                    raise ValueError
                raw = stream.read(MAX_INPUT_CONFIG_BYTES + 1)
                after = os.fstat(stream.fileno())
                if len(raw) > MAX_INPUT_CONFIG_BYTES or (
                    before.st_size, before.st_mtime_ns, before.st_ctime_ns
                ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise ValueError
            config = json.loads(raw)
            if not isinstance(config, dict) or set(config) != {"schema", "roots"} or config["schema"] != "rapp-dock-input-roots/1":
                raise ValueError
            return config["roots"]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, TypeError, LocalDockError):
            raise LocalDockError("invalid-input-roots", "The optional input-roots.json must be a private 0600 owner file with the closed input-roots schema.") from None

    def _configured_input_roots(self) -> tuple[Path, ...]:
        raw = os.environ.get("RAPP_DOCK_INPUT_ROOTS")
        try:
            if raw is not None and len(raw.encode("utf-8")) > MAX_INPUT_CONFIG_BYTES:
                raise ValueError
            values = json.loads(raw) if raw is not None else []
            configured = self._input_roots_file()
            if any(not isinstance(items, list) or len(items) > 8 for items in (values, configured)):
                raise ValueError
            roots = [self.home / "inputs", *(self.owner_home / name for name in CONTENT_DIRECTORIES)]
            extras = set()
            for value in [*values, *configured]:
                if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
                    raise ValueError
                root = Path(value).expanduser()
                if (
                    not root.is_absolute() or ".." in root.parts or root == self.owner_home
                    or self._credential_input(root) or root.is_symlink()
                    or root.is_relative_to(self.home) and not root.is_relative_to(self.home / "inputs")
                ):
                    raise ValueError
                try:
                    with _directory_fd(root):
                        pass
                except FileNotFoundError:
                    pass
                if root not in roots:
                    roots.append(root)
                    extras.add(root)
            if len(extras) > 8:
                raise ValueError
            return tuple(roots)
        except (ValueError, TypeError, OSError):
            raise LocalDockError("invalid-input-roots", "Input roots must be a JSON list of specific, non-credential owner-home directories.") from None

    def _enrolled_artifact(self, source: Path) -> dict[str, Any]:
        relative = source.relative_to(self.home / "outputs")
        if len(relative.parts) != 3 or relative.parts[0] not in APPS or _OP_ID.fullmatch(relative.parts[1]) is None:
            raise LocalDockError("input-not-enrolled")
        try:
            record = self.ops.get(relative.parts[1])
        except LocalDockError:
            raise LocalDockError("input-not-enrolled") from None
        if record["application"] != relative.parts[0] or record["status"] not in TERMINAL or (record.get("provenance") or {}).get("verification") != "structural-only":
            raise LocalDockError("input-not-enrolled")
        result = record.get("result") or {}
        artifacts = result.get("artifacts", []) if isinstance(result, dict) else []
        if not isinstance(artifacts, list) or len(artifacts) > 64:
            raise LocalDockError("input-not-enrolled")
        for artifact in artifacts:
            if (
                isinstance(artifact, dict) and artifact.get("path") == str(source) and artifact.get("verified") is True
                and type(artifact.get("bytes")) is int and artifact["bytes"] >= 0
                and re.fullmatch(r"[a-f0-9]{64}", str(artifact.get("sha256", "")))
            ):
                return {key: artifact[key] for key in ("path", "bytes", "sha256")}
        raise LocalDockError("input-not-enrolled")

    def _remember_secret(self, value: str) -> None:
        with self._secret_lock:
            self.runtime.secret_material.add(value)
            self._secret_values.add(value)

    def _remember_configuration(self, value: str) -> None:
        with self._secret_lock:
            if value not in self.runtime.secret_material:
                self._secret_values.discard(value)
                self.runtime.safe_configuration.add(value)

    def _remember_env_value(self, name: str, value: str) -> None:
        if _secret_setting(name, value):
            if len(value) >= 8:
                self._remember_secret(value)
            return
        # URLs are configuration; only embedded authentication material is secret.
        if "://" in value:
            try:
                parsed = urlsplit(value)
                if parsed.password and len(parsed.password) >= 8:
                    self._remember_secret(parsed.password)
                    self._remember_secret(unquote(parsed.password))
                for key, item in parse_qsl(parsed.query):
                    if (_secret_setting(key) or key.casefold() in ("sig", "signature", "x-amz-signature")) and len(item) >= 8:
                        self._remember_secret(item)
            except ValueError:
                pass
        self._remember_configuration(value)

    def redact(self, text: str) -> str:
        with self._secret_lock:
            for value in self.runtime.safe_configuration - self.runtime.secret_material:
                self._secret_values.discard(value)
            values = sorted(self._secret_values, key=len, reverse=True)
        for value in values:
            text = text.replace(value, "[redacted]")
        text = re.sub(r"\b(gh[opusr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b", "[redacted]", text)
        text = re.sub(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b", "[redacted]", text)
        text = re.sub(r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)", "[redacted private key]", text, flags=re.DOTALL)
        text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [redacted]", text)
        pattern = r'(?i)(?<![a-z0-9_-])((?P<field>[a-z0-9_-]{0,128}(?:api[_-]?key|token|password|authorization|cookie|secret|secret[_-]?access[_-]?key|secret[_-]?key|private[_-]?key))["\']?\s*[:=]\s*)("[^"]*"|\'[^\']*\'|[^\s,;]+)'
        return re.sub(pattern, lambda match: match.group(1) + '"[redacted]"' if _secret_setting(
            match.group("field").replace("-", "_"), match.group(3).strip("\"'")
        ) else match.group(0), text)

    def _docker_failure(
        self, command: str, completed: subprocess.CompletedProcess, fallback: str = "docker-compose-failed",
    ) -> LocalDockError:
        stderr = self.redact(_text(completed.stderr))
        stdout = self.redact(_text(completed.stdout))
        code = classify_docker_failure(stderr or stdout, fallback)
        tail = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", stderr).encode("utf-8")[-MAX_DIAGNOSTIC_BYTES:].decode("utf-8", "ignore")
        diagnostic = {
            "kind": "docker", "command": command[:80], "code": code,
            "exit_code": completed.returncode, "stderr_tail": tail,
            "stderr_truncated": len(stderr.encode("utf-8")) > MAX_DIAGNOSTIC_BYTES,
            "observed_at": _now(),
        }
        return LocalDockError(code, safe_error(code)["message"], diagnostic=diagnostic)

    def _observation_kind(self, args: list[str]) -> str | None:
        if not isinstance(args, list) or not args or any(not isinstance(item, str) or "\0" in item for item in args):
            return None
        if args[0] == "ps":
            index, seen, filters = 1, set(), []
            while index < len(args):
                flag = args[index]
                if flag in {"--all", "--no-trunc"} and flag not in seen:
                    seen.add(flag)
                    index += 1
                elif flag in {"--filter", "--format"} and index + 1 < len(args):
                    value = args[index + 1]
                    if flag == "--format":
                        if flag in seen or value != "json":
                            return None
                        seen.add(flag)
                    else:
                        filters.append(value)
                    index += 2
                else:
                    return None
            allowed = {"status=running", "status=paused", "status=restarting", "label=com.docker.compose.project"}
            allowed.update(f"label=com.docker.compose.project={self.namespace}-{app}" for app in APPS)
            return "ps" if "--format" in seen and 1 <= len(filters) <= 4 and set(filters) <= allowed else None
        if len(args) == 3 and args[:2] == ["info", "--format"] and args[2] in {RESOURCE_INFO_FORMAT, DESKTOP_INFO_FORMAT}:
            return "info"
        if (
            len(args) >= 6 and args[:4] == ["inspect", "--type", "container", "--format"]
            and args[4] in {RESOURCE_INSPECT_FORMAT, IDENTITY_INSPECT_FORMAT, CUSTODY_INSPECT_FORMAT}
            and 1 <= len(args[5:]) <= MAX_RESOURCE_CONTAINERS
            and all(re.fullmatch(r"[a-f0-9]{12,64}", item) for item in args[5:])
        ):
            return "inspect-container"
        if (
            len(args) == 5 and args[:3] == ["image", "inspect", "--format"] and args[3] == IMAGE_INSPECT_FORMAT
            and (_IMAGE_ID.fullmatch(args[4]) or re.fullmatch(r"[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}", args[4]))
            and "://" not in args[4]
        ):
            return "inspect-image"
        if args == ["network", "ls", "--format", "json"]:
            return "network-ls"
        if len(args) == 3 and args[:2] == ["network", "inspect"] and (
            args[2] == self.ai_network or any(
                args[2].startswith(f"{self.namespace}-{app}_") and _NAME.fullmatch(args[2]) for app in APPS
            )
        ):
            return "inspect-network"
        return None

    @staticmethod
    def _observation_error(code: str) -> str:
        allowed = {
            "cancelled", "docker-timeout", "docker-output-too-large", "docker-unavailable",
            "docker-state-unknown", "docker-context-refused", "daemon-unavailable",
            "vm-capacity-unknown", "vm-state-changed", "image-lock-mismatch", "image-missing",
            "image-resolution-unavailable", "docker-observation-budget-exhausted",
            "docker-observation-audit-unavailable",
        }
        return code if code in allowed else "observation-failed"

    @contextmanager
    def _read_observation(self, scope: str, *, deadline: float | None = None,
                          check_cancelled: Callable[[], None] | None = None):
        """Share one wake-aware retry and one private record across a logical read-only observation."""
        if scope not in READ_SCOPES:
            raise LocalDockError("invalid-input", "Invalid observation scope.")
        if deadline is not None and (
            isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline)
        ):
            raise LocalDockError("invalid-input", "Invalid observation deadline.")
        if _READ_RETRY_DISABLED.get():
            yield None
            return
        key = (str(self.home), self.namespace)
        existing = _READ_OBSERVATION.get()
        if existing is not None and existing.key == key:
            if deadline is not None:
                existing.deadline = min(existing.deadline, deadline)
                existing.window = min(existing.window, existing.deadline)
            if check_cancelled is not None and check_cancelled not in existing.checks:
                existing.checks.append(check_cancelled)
            try:
                yield existing
            except LocalDockError as error:
                if existing.record["error"] is None:
                    existing.record["error"] = self._observation_error(error.code)
                raise
            return
        started = time.monotonic()
        outer = deadline if deadline is not None else math.inf
        window = started + DOCKER_READ_WAKE_SECONDS
        observation = SimpleNamespace(
            key=key, started=started, deadline=outer, window=min(window, outer),
            command_index=0, journaled=False,
            checks=[check_cancelled] if check_cancelled is not None else [],
            record={
                "id": "read-" + uuid.uuid4().hex, "scope": scope, "started_at": _now(), "finished_at": None,
                "state": "running", "error": None, "wake_budget_seconds": DOCKER_READ_WAKE_SECONDS,
                "wake_seconds": None, "retry_used": False, "dropped_attempts": 0, "attempts": [],
            },
        )
        token = _READ_OBSERVATION.set(observation)
        try:
            yield observation
        except LocalDockError as error:
            if observation.record["error"] is None:
                observation.record["error"] = self._observation_error(error.code)
            raise
        except BaseException:
            if observation.record["error"] is None:
                observation.record["error"] = "observation-failed"
            raise
        finally:
            _READ_OBSERVATION.reset(token)
            record = observation.record
            record.update(finished_at=_now(), state="failed" if record["error"] else "completed")
            # Clean fast-path reads are not journaled; failures and every retry are (best effort here).
            if record["attempts"] and (record["retry_used"] or record["error"] or any(
                item["outcome"] != "exit-zero" for item in record["attempts"]
            )):
                self._write_read_observation(observation)

    @staticmethod
    def _check_read_cancellation(observation) -> None:
        for check in list(observation.checks):
            check()

    @staticmethod
    def _valid_read_record(record: Any) -> bool:
        def timestamp(value):
            return isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z", value) is not None

        def bounded(value, upper):
            return (not isinstance(value, bool) and isinstance(value, (int, float))
                    and math.isfinite(value) and 0 < value <= upper)

        def count(value):
            return value is None or type(value) is int and value >= 0

        if (
            not isinstance(record, dict) or set(record) != READ_RECORD_FIELDS
            or not isinstance(record["id"], str) or re.fullmatch(r"read-[a-f0-9]{32}", record["id"]) is None
            or record["scope"] not in READ_SCOPES or not timestamp(record["started_at"])
            or record["finished_at"] is not None and not timestamp(record["finished_at"])
            or record["state"] not in ("running", "completed", "failed")
            or record["error"] is not None and (
                not isinstance(record["error"], str) or LocalDock._observation_error(record["error"]) != record["error"]
            )
            or record["wake_budget_seconds"] != DOCKER_READ_WAKE_SECONDS
            or type(record["retry_used"]) is not bool
            or record["retry_used"] != (record["wake_seconds"] is not None)
            or record["wake_seconds"] is not None and not bounded(record["wake_seconds"], DOCKER_READ_WAKE_SECONDS)
            or type(record["dropped_attempts"]) is not int or record["dropped_attempts"] < 0
            or not isinstance(record["attempts"], list) or not 1 <= len(record["attempts"]) <= MAX_READ_ATTEMPTS
        ):
            return False
        retries = 0
        for attempt in record["attempts"]:
            if (
                not isinstance(attempt, dict) or set(attempt) != READ_ATTEMPT_FIELDS
                or attempt["command"] not in READ_COMMANDS
                or type(attempt["command_index"]) is not int or not 1 <= attempt["command_index"] <= 4096
                or type(attempt["attempt"]) is not int or attempt["attempt"] not in (1, 2)
                or attempt["attempt"] == 2 and attempt["command"] not in RETRYABLE_READS
                or attempt["phase"] not in READ_PHASES
                or not isinstance(attempt["outcome"], str)
                or attempt["outcome"] not in ("exit-zero", "nonzero-exit")
                and LocalDock._observation_error(attempt["outcome"]) != attempt["outcome"]
                or not bounded(attempt["timeout_seconds"], 1800) or not timestamp(attempt["observed_at"])
                or attempt["exit_code"] is not None and type(attempt["exit_code"]) is not int
                or not all(count(attempt[name]) for name in (
                    "elapsed_ms", "spawn_ms", "pid", "stdin_bytes_written", "stdout_bytes", "stderr_bytes",
                ))
            ):
                return False
            streams = attempt["open_streams"]
            if streams is not None and (
                not isinstance(streams, list) or len(set(streams)) != len(streams)
                or any(stream not in ("stdin", "stdout", "stderr") for stream in streams)
            ):
                return False
            retries += attempt["attempt"] == 2
        return retries <= 1 and (record["retry_used"] or not retries)

    def _write_read_observation(self, observation) -> bool:
        """Persist a bounded private record containing process facts only; never args, env or output."""
        record = observation.record
        try:
            if not self._valid_read_record(record):
                raise ValueError

            def unique(pairs):
                value = dict(pairs)
                if len(value) != len(pairs):
                    raise ValueError
                return value

            root = _private_dir(self.home / "observations")
            path = root / "docker-read.json"
            wait = max(0.0, min(READ_JOURNAL_LOCK_SECONDS, observation.deadline - time.monotonic()))
            # Concurrent writers merge under one bounded lock, so a returned observation ID is never silently lost.
            with _read_journal_lock(root, time.monotonic() + wait):
                records = []
                try:
                    with _regular_file(path) as stream:
                        info = os.fstat(stream.fileno())
                        if stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > MAX_READ_JOURNAL_BYTES:
                            raise ValueError
                        raw = stream.read(MAX_READ_JOURNAL_BYTES + 1)
                    previous = json.loads(raw, object_pairs_hook=unique)
                    if (
                        len(raw) > MAX_READ_JOURNAL_BYTES or not isinstance(previous, dict)
                        or set(previous) != {"schema", "namespace", "records"}
                        or previous["schema"] != "rapp-dock-read-observations/1"
                        or previous["namespace"] != self.namespace
                        or not isinstance(previous["records"], list) or len(previous["records"]) > MAX_READ_OBSERVATIONS
                        or any(not self._valid_read_record(item) for item in previous["records"])
                    ):
                        raise ValueError
                    records = [item for item in previous["records"] if item["id"] != record["id"]]
                except FileNotFoundError:
                    pass
                records = [*records, copy.deepcopy(record)][-MAX_READ_OBSERVATIONS:]
                while True:
                    data = json.dumps(
                        {"schema": "rapp-dock-read-observations/1", "namespace": self.namespace, "records": records},
                        sort_keys=True, separators=(",", ":"), allow_nan=False,
                    ).encode()
                    if len(data) <= MAX_READ_JOURNAL_BYTES:
                        break
                    if len(records) == 1:
                        raise ValueError
                    records.pop(0)
                _atomic_write(path, data)
        except (OSError, ValueError, TypeError, LocalDockError):
            return False
        observation.journaled = True
        return True

    @staticmethod
    def _ordinary_attempt(entry: dict[str, Any]) -> bool:
        return entry["outcome"] == "exit-zero" and entry["attempt"] == 1

    @staticmethod
    def _record_read_attempt(observation, *, kind: str, index: int, attempt: int, timeout: float, started: float,
                             result: subprocess.CompletedProcess | None = None,
                             error: LocalDockError | None = None) -> bool:
        """Retain one bounded attempt; a full record evicts an ordinary read to pin failure and retry evidence."""
        record = observation.record
        detail = error.diagnostic if error is not None and isinstance(error.diagnostic, dict) else {}

        def count(name):
            value = detail.get(name)
            return value if type(value) is int and value >= 0 else None

        streams = detail.get("open_streams")
        if not isinstance(streams, list) or len(set(streams)) != len(streams) or any(
            name not in ("stdin", "stdout", "stderr") for name in streams
        ):
            streams = None
        if result is not None:
            outcome = "exit-zero" if result.returncode == 0 else "nonzero-exit"
            phase, exit_code = "completed", result.returncode
            stdout = len(result.stdout) if isinstance(result.stdout, bytes) else None
            stderr = len(result.stderr) if isinstance(result.stderr, bytes) else None
        else:
            outcome = LocalDock._observation_error(error.code)
            phase = detail.get("phase") if detail.get("phase") in ("spawn", "pipe-io", "process-exit") else "unknown"
            exit_code, stdout, stderr = detail.get("exit_code"), count("stdout_bytes"), count("stderr_bytes")
        elapsed = count("elapsed_ms")
        entry = {
            "command": kind, "command_index": index, "attempt": attempt, "outcome": outcome, "phase": phase,
            "timeout_seconds": timeout,
            "elapsed_ms": elapsed if elapsed is not None else max(0, round((time.monotonic() - started) * 1000)),
            "spawn_ms": count("spawn_ms"), "pid": count("pid"),
            "exit_code": exit_code if type(exit_code) is int else None, "open_streams": streams,
            "stdin_bytes_written": count("stdin_bytes_written"), "stdout_bytes": stdout, "stderr_bytes": stderr,
            "observed_at": _now(),
        }
        attempts = record["attempts"]
        if len(attempts) >= MAX_READ_ATTEMPTS:
            # Every attempt not retained is counted; only the oldest ordinary success is ever evicted.
            record["dropped_attempts"] += 1
            evictable = None if LocalDock._ordinary_attempt(entry) else next(
                (position for position, item in enumerate(attempts) if LocalDock._ordinary_attempt(item)), None,
            )
            if evictable is None:
                return False
            del attempts[evictable]
        attempts.append(entry)
        return True

    @staticmethod
    def _annotate_read_error(error: LocalDockError, observation, attempt: int) -> None:
        if isinstance(error.diagnostic, dict):
            error.diagnostic = {**error.diagnostic, "observation_id": observation.record["id"], "attempt": attempt}

    def _observed_docker(self, args: list[str], *, kind: str, executable: str, environment: dict[str, str],
                         observation, **kwargs: Any) -> subprocess.CompletedProcess:
        """Run one allowlisted read; retry only its first timeout, once per logical observation."""
        normal = kwargs.get("timeout", 120)
        if isinstance(normal, bool) or not isinstance(normal, (int, float)) or not math.isfinite(normal) or not 0 < normal <= 1800:
            raise LocalDockError("invalid-input", "Invalid Docker command bound.")
        if kwargs.get("check_cancelled") is not None and kwargs["check_cancelled"] not in observation.checks:
            observation.checks.append(kwargs["check_cancelled"])
        observation.command_index += 1
        index, attempt = observation.command_index, 1
        while True:
            # Clean reads keep their bounds under any caller deadline; the window only admits and caps recovery.
            self._check_read_cancellation(observation)
            limit = observation.window if attempt == 2 else observation.deadline
            remaining = limit - time.monotonic()
            if remaining <= 0:
                raise LocalDockError(
                    "docker-observation-budget-exhausted",
                    safe_error("docker-observation-budget-exhausted")["message"],
                )
            call = {**kwargs, "timeout": min(normal, remaining), "hard_deadline": limit if math.isfinite(limit) else None,
                    "check_cancelled": partial(self._check_read_cancellation, observation)}
            started = time.monotonic()
            try:
                result = run_docker(args, executable=executable, env=environment, **call)
            except LocalDockError as error:
                recorded = self._record_read_attempt(observation, kind=kind, index=index, attempt=attempt,
                                                     timeout=call["timeout"], started=started, error=error)
                # A retry needs its timed-out attempt retained and room for its own entry (free or an ordinary read).
                room = len(observation.record["attempts"]) < MAX_READ_ATTEMPTS or any(
                    self._ordinary_attempt(item) for item in observation.record["attempts"]
                )
                if (
                    not (recorded and room)
                    or error.code != "docker-timeout" or attempt != 1 or kind not in RETRYABLE_READS
                    or observation.record["retry_used"] or observation.window <= time.monotonic()
                ):
                    self._annotate_read_error(error, observation, attempt)
                    raise
                self._check_read_cancellation(observation)
                observation.record.update(
                    retry_used=True, wake_seconds=max(0.001, round(observation.window - observation.started, 3)),
                )
                # A retry is admitted only after the timed-out attempt is durably retained.
                if not self._write_read_observation(observation):
                    observation.record.update(retry_used=False, wake_seconds=None)
                    self._annotate_read_error(error, observation, attempt)
                    raise
                attempt = 2
                continue
            self._record_read_attempt(observation, kind=kind, index=index, attempt=attempt,
                                      timeout=call["timeout"], started=started, result=result)
            if attempt == 2 and not self._write_read_observation(observation):
                raise LocalDockError(
                    "docker-observation-audit-unavailable",
                    safe_error("docker-observation-audit-unavailable")["message"],
                )
            return result

    def _docker(self, args: list[str], *, env: dict[str, str] | None = None, **kwargs: Any) -> subprocess.CompletedProcess:
        kind = self._observation_kind(args) if kwargs.get("input_bytes") is None else None
        if kind is not None and not _READ_RETRY_DISABLED.get():
            with self._read_observation("docker-read") as observation:
                return self._pinned_docker(args, env=env, observation=observation, kind=kind, **kwargs)
        return self._pinned_docker(args, env=env, **kwargs)

    def _pinned_docker(self, args: list[str], *, env: dict[str, str] | None = None,
                       observation=None, kind: str | None = None, **kwargs: Any) -> subprocess.CompletedProcess:
        executable = docker_cli(self.docker_override)
        environment = docker_env(env, executable=executable, owner_home=self.owner_home)
        key = (executable, str(self.owner_home))
        with _REGISTRY.lock:
            endpoint = _REGISTRY.docker_endpoints.get(key)
        if endpoint is None:
            arguments = ["--context", "desktop-linux", "context", "inspect", "desktop-linux",
                         "--format", "{{json .Endpoints.docker.Host}}"]
            observed = self._observed_docker(
                arguments, kind="context-inspect", executable=executable, environment=environment,
                observation=observation, timeout=1, max_bytes=4096,
            ) if observation is not None else run_docker(
                arguments, executable=executable, env=environment, timeout=1, max_bytes=4096,
            )
            if observed.returncode:
                raise self._docker_failure("context inspect", observed, "docker-context-refused")
            try:
                endpoint = json.loads(observed.stdout)
                path = endpoint.removeprefix("unix://") if isinstance(endpoint, str) else ""
                if observed.returncode or not endpoint.startswith("unix:///") or not path.startswith("/") or ".." in Path(path).parts or any(c in path for c in "\r\n\0?%#"):
                    raise ValueError
                if not self.docker_override and not Path(path).is_socket():
                    raise LocalDockError("daemon-unavailable", safe_error("daemon-unavailable")["message"])
            except (ValueError, TypeError, AttributeError):
                raise LocalDockError("docker-context-refused", "Docker Desktop must resolve to a local Unix socket.") from None
            with _REGISTRY.lock:
                _REGISTRY.docker_endpoints[key] = endpoint
        arguments = ["--host", endpoint, *args]
        if observation is not None:
            return self._observed_docker(
                arguments, kind=kind, executable=executable, environment=environment,
                observation=observation, **kwargs,
            )
        return run_docker(arguments, executable=executable, env=environment, **kwargs)

    @staticmethod
    def _parse_rows(raw: bytes) -> list[dict[str, Any]]:
        text = _text(raw).strip()
        if not text:
            return []
        try:
            value = json.loads(text)
            rows = value if isinstance(value, list) else [value]
        except ValueError:
            try:
                rows = [json.loads(line) for line in text.splitlines() if line.strip()]
            except ValueError:
                raise LocalDockError("docker-state-unknown", "Docker returned invalid state data.") from None
        if not all(isinstance(row, dict) for row in rows):
            raise LocalDockError("docker-state-unknown", "Docker returned invalid state data.")
        return rows

    @_observed_read("inventory")
    def _inventory(self, app: str | None = None, *, cached: bool = False, timeout: float = 1.5) -> dict[str, Any]:
        with self.runtime.lock:
            previous = self.runtime.inventory
            if cached and previous and previous["selection"] == app and time.monotonic() - previous["clock"] < 2:
                return previous
        selected = "label=com.docker.compose.project" + (f"={self.namespace}-{app}" if app else "")
        completed = self._docker(
            ["ps", "--all", "--filter", selected, "--format", "json"],
            timeout=timeout, max_bytes=512 * 1024,
        )
        if completed.returncode:
            raise self._docker_failure("ps", completed, "docker-state-unknown")
        rows = []
        projects = {f"{self.namespace}-{name}": name for name in APPS}
        for row in self._parse_rows(completed.stdout):
            labels = row.get("Labels", {})
            if isinstance(labels, str):
                labels = dict(item.split("=", 1) for item in labels.split(",") if "=" in item)
            if not isinstance(labels, dict):
                raise LocalDockError("docker-state-unknown", "Docker returned invalid project labels.")
            project = labels.get("com.docker.compose.project")
            if project not in projects:
                continue
            status = str(row.get("Status", ""))[:300]
            exit_match = re.search(r"Exited \((-?[0-9]+)\)", status)
            rows.append({
                "application": projects[project], "project": project,
                "service": labels.get("com.docker.compose.service"),
                "state": row.get("State"),
                "health": ("unhealthy" if "(unhealthy)" in status else "starting" if "(health: starting)" in status else "healthy" if "(healthy)" in status else row.get("Health") or None),
                "exit_code": int(exit_match.group(1)) if exit_match else row.get("ExitCode"),
                "status": status, "id": row.get("ID"),
            })
        result = {"rows": rows, "observed_at": _now(), "clock": time.monotonic(), "selection": app}
        with self.runtime.lock:
            self.runtime.inventory = result
        return result

    def _container_rows(self, app: str) -> list[dict[str, Any]]:
        return [row for row in self._inventory(app, timeout=5)["rows"] if row["application"] == app]

    def _resource_plan(self, scope: list[str], op_id: str | None) -> dict[tuple[str, str], tuple[int, int]]:
        planned = {}
        try:
            for app in scope:
                ctx = self.context(app, op_id)
                model = self._compose_model(ctx, {})
                if not 1 <= len(model["services"]) <= 64:
                    raise LocalDockError("invalid-resource-limits")
                for name, service in model["services"].items():
                    if not isinstance(name, str) or _NAME.fullmatch(name) is None or not isinstance(service, dict):
                        raise LocalDockError("invalid-resource-limits")
                    deployment = service.get("deploy") or {}
                    limits = (deployment.get("resources") or {}).get("limits") or {}
                    memories = [_memory_limit(source[key]) for source, key in (
                        (service, "mem_limit"), (limits, "memory"),
                    ) if key in source]
                    cpus = [_cpu_limit(source[key]) for source, key in (
                        (service, "cpus"), (limits, "cpus"),
                    ) if key in source]
                    replicas = service.get("scale", deployment.get("replicas", 1))
                    if (
                        not memories or len(set(memories)) != 1 or not cpus or len(set(cpus)) != 1
                        or type(replicas) is not int or not 1 <= replicas <= 32
                        or "scale" in service and "replicas" in deployment and service["scale"] != deployment["replicas"]
                    ):
                        raise LocalDockError("invalid-resource-limits")
                    planned[(ctx.project, name)] = (memories[0] * replicas, cpus[0] * replicas)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise LocalDockError("invalid-resource-limits") from None
        return planned

    @_observed_read("resource-snapshot")
    def _resource_snapshot(self) -> tuple[dict[str, Any], dict[tuple[str, str], tuple[int, int | None]]]:
        observed = self._docker([
            "info", "--format",
            RESOURCE_INFO_FORMAT,
        ], timeout=5, max_bytes=4096)
        if observed.returncode:
            raise self._docker_failure("info resource capacity", observed, "vm-capacity-unknown")
        try:
            info = json.loads(observed.stdout)
            if (
                not isinstance(info, dict) or not isinstance(info.get("id"), str) or not 1 <= len(info["id"]) <= 256
                or type(info.get("memory")) is not int or info["memory"] <= 0
                or type(info.get("cpus")) is not int or not 1 <= info["cpus"] <= 65536
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise LocalDockError("vm-capacity-unknown") from None

        def running_ids():
            inventory = self._docker([
                "ps", "--no-trunc", "--filter", "status=running", "--filter", "status=paused",
                "--filter", "status=restarting", "--format", "json",
            ], timeout=5, max_bytes=512 * 1024)
            if inventory.returncode:
                raise self._docker_failure("ps resource inventory", inventory, "vm-capacity-unknown")
            rows = self._parse_rows(inventory.stdout)
            ids = [row.get("ID", row.get("id")) for row in rows]
            if len(ids) > MAX_RESOURCE_CONTAINERS or any(
                not isinstance(identifier, str) or re.fullmatch(r"[a-f0-9]{64}", identifier) is None for identifier in ids
            ) or len(set(ids)) != len(ids):
                raise LocalDockError("vm-capacity-unknown")
            return ids

        ids = running_ids()
        if not ids:
            if running_ids():
                raise LocalDockError("vm-state-changed")
            return info, {}
        inspected = self._docker([
            "inspect", "--type", "container", "--format",
            RESOURCE_INSPECT_FORMAT,
            *ids,
        ], timeout=5, max_bytes=512 * 1024)
        if inspected.returncode:
            raise self._docker_failure("inspect resource limits", inspected, "vm-capacity-unknown")
        rows = self._parse_rows(inspected.stdout)
        if len(rows) != len(ids) or {row.get("id") for row in rows} != set(ids) or set(running_ids()) != set(ids):
            raise LocalDockError("vm-state-changed")
        budgets = {}
        for row in rows:
            if row.get("state") not in ("running", "paused", "restarting"):
                raise LocalDockError("vm-state-changed")
            memory, cpu = row.get("memory"), row.get("nano_cpus")
            if type(memory) is not int or memory <= 0 or type(cpu) is not int or cpu < 0:
                raise LocalDockError("vm-capacity-unknown")
            if not cpu:
                quota, period = row.get("quota"), row.get("period")
                if type(quota) is not int or type(period) is not int:
                    raise LocalDockError("vm-capacity-unknown")
                cpu = (quota * 1_000_000_000 + period - 1) // period if quota > 0 and period > 0 else None
            project, service = row.get("project"), row.get("service")
            key = (project, service) if all(isinstance(value, str) and value for value in (project, service)) else ("unowned", row["id"])
            prior = budgets.get(key, (0, 0))
            budgets[key] = (prior[0] + memory, prior[1] + cpu if prior[1] is not None and cpu is not None else None)
        return info, budgets

    @staticmethod
    def _cpu_total(budget: dict) -> int | None:
        return sum(value[1] for value in budget.values()) if all(value[1] is not None for value in budget.values()) else None

    def _reclaim_protected(self, requested_id: str) -> set[str]:
        """Called under the runtime lock, including immediately before fencing a stop."""
        requested = self.ops.get(requested_id)
        self.context(requested["application"], requested_id).check_cancelled()
        protected = set(requested.get("scope", [])) | set(self._scope(requested["application"]))
        protected.update(self.runtime.state["stopping"])
        protected.update(self.runtime.state.get("idle_protected", []))
        for pending in self.runtime.pending.values():
            protected.update(pending["scope"])
        if self.runtime.quiescing or self.runtime.state.get("detach_paused"):
            protected.update(APPS)
        return protected

    def _idle_reclaim_candidates(self, ctx: AppContext, scope: list[str], running: dict,
                                 reservations: list[dict], attempted: set[str]) -> list[str]:
        if not ctx.op_id:
            return []
        projects = {f"{self.namespace}-{app}": app for app in APPS}
        running_apps = {projects[project] for project, _ in running if project in projects}
        with self.runtime.lock:
            protected = self._reclaim_protected(ctx.op_id) | set(scope) | attempted
            for reservation in reservations:
                protected.update(projects[project] for project, _ in reservation if project in projects)
            for app in running_apps:
                try:
                    protected.update(set(self._scope(app)) - {app})
                except LocalDockError:
                    protected.update(running_apps)
            last_used = self.runtime.state.get("last_used", {})
            automatic = self.runtime.state["auto_started"]
            return sorted(running_apps - protected, key=lambda app: (
                last_used.get(app, automatic.get(app, 0)), APP_INDEX[app],
            ))

    @contextmanager
    def _resource_guard(self, ctx: AppContext, scope: list[str]):
        token = (str(self.home), ctx.op_id or threading.get_ident())
        waiting = False
        while not _REGISTRY.resource_lock.acquire(timeout=0.1):
            ctx.check_cancelled()
            if not waiting:
                ctx.phase("waiting_for_vm_admission", "Another startup is observing the shared Docker VM budget.")
                waiting = True
        owner = False
        try:
            ctx.check_cancelled()
            prior = _REGISTRY.resource_reservations.get(token)
            if prior is not None:
                if not set(scope) <= set(prior["scope"]):
                    raise LocalDockError("invalid-adapter", "Nested startup exceeds its admitted dependency scope.")
            else:
                planned = self._resource_plan(scope, ctx.op_id)
                reclaimed, attempted, daemon = [], set(), None
                while True:
                    ctx.check_cancelled()
                    with self._read_observation("resource-snapshot", check_cancelled=ctx.check_cancelled):
                        info, running = self._resource_snapshot()
                    if daemon is not None and info["id"] != daemon:
                        raise LocalDockError("vm-state-changed")
                    daemon = info["id"]
                    projected = dict(running)
                    reservations = [
                        item["planned"] for item in _REGISTRY.resource_reservations.values() if item["daemon"] == daemon
                    ]
                    for allocation in [*reservations, planned]:
                        for key, limits in allocation.items():
                            observed = projected.get(key, (0, 0))
                            cpu = max(observed[1], limits[1]) if observed[1] is not None and limits[1] is not None else None
                            projected[key] = (max(observed[0], limits[0]), cpu)
                    total_memory = sum(item[0] for item in projected.values())
                    total_cpu = self._cpu_total(projected)
                    allowed = total_memory <= info["memory"]
                    requested_fits = sum(item[0] for item in planned.values()) <= info["memory"]
                    candidates = self._idle_reclaim_candidates(ctx, scope, running, reservations, attempted) if not allowed and requested_fits else []
                    admission = {
                        "schema": "rapp-dock-admission/1", "observed_at": _now(),
                        "decision": "admitted" if allowed else "reclaiming" if candidates else "refused",
                        "capacity": {"memory_bytes": info["memory"], "cpu_nanos": info["cpus"] * 1_000_000_000},
                        "running_declared": {
                            "memory_bytes": sum(item[0] for item in running.values()), "cpu_nanos": self._cpu_total(running),
                        },
                        "projected_declared": {"memory_bytes": total_memory, "cpu_nanos": total_cpu},
                        "memory_policy": "hard-declared-limit", "cpu_policy": "compressible-caps-not-admission",
                        "cpu_oversubscription": round(total_cpu / (info["cpus"] * 1_000_000_000), 3) if total_cpu is not None else None,
                        "other_startups_reserved": len(reservations), "reclaimed_stacks": reclaimed,
                        "refusal_reason": None if allowed or candidates else (
                            "protected-or-unmanaged-memory" if requested_fits else "requested-memory-exceeds-vm"
                        ),
                    }
                    if ctx.op_id:
                        self.ops.update(ctx.op_id, admission=admission)
                    if allowed:
                        break
                    if not candidates:
                        raise LocalDockError("vm-capacity-exceeded")
                    app = candidates[0]
                    attempted.add(app)
                    ctx.phase("reclaiming_idle_memory", f"Stopping idle {app} to free memory; application data is retained.")
                    try:
                        # Stops may be draining workers that need the admission lock.
                        _REGISTRY.resource_lock.release()
                        try:
                            stopped = self._submit(
                                "lifecycle", app, "stop", {}, [app], self._stop_scope,
                                control=True, wait_seconds=0, reclaim_for=ctx.op_id,
                            )
                        finally:
                            _REGISTRY.resource_lock.acquire()
                    except LocalDockError as error:
                        if error.code != "idle-stack-busy":
                            raise
                        continue
                    reclaimed.append({
                        "application": app, "operation_id": stopped["id"], "status": stopped["status"],
                        "data_deleted": False, "stopped": (stopped.get("result") or {}).get("stopped") is True,
                    })
                    if ctx.op_id:
                        self.ops.update(ctx.op_id, admission={**admission, "reclaimed_stacks": list(reclaimed)})
                _REGISTRY.resource_reservations[token] = {
                    "daemon": info["id"], "scope": tuple(scope), "planned": planned,
                }
                owner = True
        finally:
            _REGISTRY.resource_lock.release()
        try:
            yield
        finally:
            if owner:
                with _REGISTRY.resource_lock:
                    _REGISTRY.resource_reservations.pop(token, None)

    @_observed_read("network-inventory")
    def _network_inventory(self, *, cached: bool = False, timeout: float = 1.5) -> dict[str, Any]:
        with self.runtime.lock:
            previous = getattr(self.runtime, "network_inventory", None)
            if cached and previous and time.monotonic() - previous["clock"] < 2:
                return previous["result"]
        completed = self._docker(["network", "ls", "--format", "json"], timeout=timeout, max_bytes=256 * 1024)
        if completed.returncode:
            raise self._docker_failure("network ls", completed, "docker-state-unknown")
        rows = self._parse_rows(completed.stdout)
        counts = {app: 0 for app in APPS}
        total, controlled, ai_present, unassigned = 0, 0, False, 0
        for row in rows:
            labels = row.get("Labels", {})
            if isinstance(labels, str):
                labels = dict(item.split("=", 1) for item in labels.split(",") if "=" in item)
            if not isinstance(labels, dict):
                raise LocalDockError("docker-state-unknown")
            project = labels.get("com.docker.compose.project")
            app = next((name for name in APPS if project == f"{self.namespace}-{name}"), None)
            if labels.get("rapp.dock.namespace") != self.namespace and app is None:
                continue
            total += 1
            controlled += labels.get("rapp.dock.ipam") == "controller-v1"
            if row.get("Name") == self.ai_network:
                ai_present = True
            elif app:
                counts[app] += 1
            else:
                unassigned += 1
        result = {
            "state": "observed", "observed_at": _now(), "docker_total": len(rows),
            "namespace_total": total, "controller_subnet_networks": controlled,
            "ai_present": ai_present, "by_application": {name: count for name, count in counts.items() if count},
            "other_owned": unassigned,
        }
        with self.runtime.lock:
            self.runtime.network_inventory = {"clock": time.monotonic(), "result": result}
        return result

    @staticmethod
    def _private_network_json(path: Path) -> dict[str, Any] | None:
        if not path.exists() and not path.is_symlink():
            return None
        try:
            with _regular_file(path) as stream:
                if stat.S_IMODE(os.fstat(stream.fileno()).st_mode) != 0o600:
                    raise ValueError
                raw = stream.read(NETWORK_PLAN_BYTES + 1)
            value = json.loads(raw)
            if len(raw) > NETWORK_PLAN_BYTES or not isinstance(value, dict):
                raise ValueError
            return value
        except (OSError, ValueError, LocalDockError):
            raise LocalDockError("network-plan-invalid") from None

    @staticmethod
    def _small_subnet(value: Any) -> ipaddress.IPv4Network:
        try:
            subnet = ipaddress.ip_network(value, strict=True)
            ranges = map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
            if subnet.version != 4 or subnet.prefixlen != NETWORK_PREFIX or not any(subnet.subnet_of(pool) for pool in ranges):
                raise ValueError
            return subnet
        except (ValueError, TypeError):
            raise LocalDockError("network-plan-invalid") from None

    def _existing_network_overlay(self, ctx: AppContext) -> Path | None:
        path = ctx.state_dir / "network-override.json"
        value = self._private_network_json(path)
        if value is None:
            return None
        if set(value) != {"networks"} or not isinstance(value["networks"], dict) or len(value["networks"]) > NETWORKS_PER_APP:
            raise LocalDockError("network-plan-invalid")
        for name, config in value["networks"].items():
            try:
                if (
                    not isinstance(name, str) or _NAME.fullmatch(name) is None
                    or set(config) != {"ipam", "labels"}
                    or config["labels"] != {"rapp.dock.namespace": self.namespace, "rapp.dock.ipam": "controller-v1"}
                    or set(config["ipam"]) != {"driver", "config"} or config["ipam"]["driver"] != "default"
                    or len(config["ipam"]["config"]) != 1 or set(config["ipam"]["config"][0]) != {"subnet"}
                ):
                    raise ValueError
                self._small_subnet(config["ipam"]["config"][0]["subnet"])
            except (TypeError, KeyError, ValueError):
                raise LocalDockError("network-plan-invalid") from None
        return path

    def _inspect_network(self, name: str) -> dict[str, Any] | None:
        observed = self._docker(["network", "inspect", name], timeout=5, max_bytes=512 * 1024)
        if observed.returncode:
            if re.search(r"not found|no such network", _text(observed.stderr), re.IGNORECASE):
                return None
            raise self._docker_failure("network inspect", observed, "docker-state-unknown")
        rows = self._parse_rows(observed.stdout)
        if len(rows) != 1 or rows[0].get("Name") != name:
            raise LocalDockError("docker-state-unknown")
        return rows[0]

    def _network_overlay(self, ctx: AppContext, environment: dict[str, str]) -> Path:
        """Assign small subnets without changing service attachments or isolation."""
        model = self._compose_model(ctx, environment)
        try:
            networks = model.get("networks", {})
            if not isinstance(networks, dict):
                raise ValueError
            managed = {name: value for name, value in networks.items() if not value.get("external")}
            if len(managed) > NETWORKS_PER_APP:
                raise LocalDockError("network-budget-exceeded")
            for name, definition in managed.items():
                definition.setdefault("name", ctx.project + "_" + name)
                if (
                    _NAME.fullmatch(name) is None or not isinstance(definition, dict)
                    or not isinstance(definition.get("name"), str)
                    or not definition["name"].startswith(ctx.project + "_")
                    or definition.get("driver", "bridge") != "bridge"
                    or definition.get("enable_ipv6", False)
                ):
                    raise ValueError
        except (ValueError, AttributeError, TypeError):
            raise LocalDockError("network-plan-invalid") from None

        return self._write_network_overlay(ctx, managed)

    def _compose_model(self, ctx: AppContext, environment: dict[str, str]) -> dict[str, Any]:
        rendered = self._docker(
            # The raw-model path avoids Compose's eager service env-file loader.
            ctx._compose_argv("config", "--format", "json", "--no-env-resolution", "--no-interpolate"),
            env=environment, timeout=30, max_bytes=MAX_DOCKER_BYTES, cwd=ctx.root,
            check_cancelled=ctx.check_cancelled,
        )
        if rendered.returncode:
            raise self._docker_failure("compose config", rendered)
        try:
            model = json.loads(rendered.stdout)
            if not isinstance(model, dict) or not isinstance(model.get("services"), dict):
                raise ValueError
        except (ValueError, AttributeError, TypeError):
            raise LocalDockError("network-plan-invalid") from None
        return model

    def _write_network_overlay(self, ctx: AppContext, managed: dict[str, Any]) -> Path:
        state_path = ctx.state_dir / "network-allocations.json"
        saved = self._private_network_json(state_path)
        allocations = {}
        if saved is not None:
            try:
                if (
                    set(saved) != {"schema", "namespace", "project", "allocations"}
                    or saved["schema"] != "rapp-dock-ipam/1" or saved["namespace"] != self.namespace
                    or saved["project"] != ctx.project or not isinstance(saved["allocations"], dict)
                    or len(saved["allocations"]) > NETWORKS_PER_APP
                ):
                    raise ValueError
                for logical, item in saved["allocations"].items():
                    if _NAME.fullmatch(logical) is None or set(item) != {"name", "subnet"} or not item["name"].startswith(ctx.project + "_"):
                        raise ValueError
                    self._small_subnet(item["subnet"])
                allocations = dict(saved["allocations"])
            except (ValueError, TypeError, AttributeError, KeyError):
                raise LocalDockError("network-plan-invalid") from None

        inspected: dict[str, dict[str, Any] | None] = {}

        def inspect(name):
            if name not in inspected:
                ctx.check_cancelled()
                inspected[name] = self._inspect_network(name)
            return inspected[name]

        for logical, item in list(allocations.items()):
            if logical not in managed:
                if inspect(item["name"]) is None:
                    allocations.pop(logical)
            elif item["name"] != managed[logical]["name"]:
                if inspect(item["name"]) is not None:
                    raise LocalDockError("network-topology-changed")
                allocations.pop(logical)

        overlay, pending, occupied = {}, [], []

        def entry(subnet):
            return {
                "ipam": {"driver": "default", "config": [{"subnet": str(subnet)}]},
                "labels": {"rapp.dock.namespace": self.namespace, "rapp.dock.ipam": "controller-v1"},
            }

        for logical, definition in sorted(managed.items()):
            name = definition["name"]
            existing = inspect(name)
            declared = (definition.get("ipam") or {}).get("config", [])
            if existing is not None:
                labels = existing.get("Labels") or {}
                if labels.get("com.docker.compose.project") != ctx.project or labels.get("com.docker.compose.network") != logical:
                    raise LocalDockError("network-ownership-mismatch")
                if existing.get("Driver") != "bridge" or bool(existing.get("Internal")) != bool(definition.get("internal", False)):
                    raise LocalDockError("network-topology-changed")
                config = (existing.get("IPAM") or {}).get("Config") or []
                if labels.get("rapp.dock.ipam") == "controller-v1":
                    if len(config) != 1:
                        raise LocalDockError("network-plan-invalid")
                    subnet = self._small_subnet(config[0].get("Subnet"))
                    if declared and any(item.get("subnet") != str(subnet) for item in declared):
                        raise LocalDockError("network-topology-changed")
                    allocations[logical] = {"name": name, "subnet": str(subnet)}
                    overlay[logical] = entry(subnet)
                else:
                    # Existing networks remain untouched, including legacy /16 allocations.
                    allocations.pop(logical, None)
                    for item in config:
                        if item.get("Subnet"):
                            occupied.append(ipaddress.ip_network(item["Subnet"], strict=True))
            elif declared:
                allocations.pop(logical, None)
                for item in declared:
                    if item.get("subnet"):
                        occupied.append(ipaddress.ip_network(item["subnet"], strict=True))
            else:
                pending.append((logical, name))

        candidates = self._network_candidates(ctx.app)
        for logical, name in pending:
            others = [self._small_subnet(item["subnet"]) for key, item in allocations.items() if key != logical]
            prior = allocations.get(logical)
            preferred = self._small_subnet(prior["subnet"]) if prior else None
            choices = ([preferred] if preferred in candidates else []) + candidates
            subnet = next((candidate for candidate in choices if not any(
                candidate.version == used.version and candidate.overlaps(used) for used in [*occupied, *others]
            )), None)
            if subnet is None or logical not in allocations and len(allocations) >= NETWORKS_PER_APP:
                raise LocalDockError("network-budget-exceeded")
            allocations[logical] = {"name": name, "subnet": str(subnet)}
            overlay[logical] = entry(subnet)

        _atomic_write(state_path, json.dumps({
            "schema": "rapp-dock-ipam/1", "namespace": self.namespace,
            "project": ctx.project, "allocations": allocations,
        }, sort_keys=True).encode())
        path = ctx.state_dir / "network-override.json"
        _atomic_write(path, json.dumps({"networks": overlay}, sort_keys=True).encode())
        self._existing_network_overlay(ctx)
        return path

    def _network_candidates(self, app: str) -> list[ipaddress.IPv4Network]:
        start = 1 + APP_INDEX[app] * NETWORKS_PER_APP
        return list(self.network_block.subnets(new_prefix=NETWORK_PREFIX))[start:start + NETWORKS_PER_APP]

    def ensure_network(self) -> None:
        with _REGISTRY.network_lock:
            self._ensure_network()

    def _ensure_network(self) -> None:
        def inspect():
            return self._docker(["network", "inspect", self.ai_network], timeout=30)

        observed = inspect()
        if observed.returncode != 0:
            if not re.search(r"not found|no such network", _text(observed.stderr), re.IGNORECASE):
                raise self._docker_failure("network inspect", observed, "docker-state-unknown")
            created = self._docker(
                ["network", "create", "--driver", "bridge", "--internal",
                 "--subnet", str(self.ai_subnet), "--label", f"rapp.dock.namespace={self.namespace}",
                 "--label", "rapp.dock.ipam=controller-v1", self.ai_network], timeout=60
            )
            if created.returncode != 0 and "already exists" not in _text(created.stderr):
                raise self._docker_failure("network create", created, "network-create-failed")
            observed = inspect()
        try:
            rows = json.loads(observed.stdout)
            network = rows[0] if isinstance(rows, list) and len(rows) == 1 else rows
            valid = (
                observed.returncode == 0 and isinstance(network, dict)
                and network.get("Name") == self.ai_network and network.get("Internal") is True
                and (network.get("Labels") or {}).get("rapp.dock.namespace") == self.namespace
            )
        except (ValueError, TypeError, IndexError):
            valid = False
        if not valid:
            raise LocalDockError("unsafe-ai-network", "The AI network must be internal and owned by this namespace.")

    # -- operation plumbing ----------------------------------------------------------
    def _scope(self, app: str) -> list[str]:
        ordered, visiting = [], set()

        def visit(name):
            if name in visiting:
                raise LocalDockError("invalid-adapter", "Adapter dependencies contain a cycle.")
            if name in ordered:
                return
            visiting.add(name)
            for dependency in getattr(self.adapter(name), "NEEDS", ()):
                visit(dependency)
            visiting.remove(name)
            ordered.append(name)

        visit(app)
        return ordered

    def _workers(self) -> None:
        runtime = self.runtime
        for kind, count in (("work", MAX_WORKERS), ("control", 1)):
            runtime.threads[kind] = [thread for thread in runtime.threads[kind] if thread.is_alive()]
            while len(runtime.threads[kind]) < count:
                def worker(selected=kind):
                    idle_since = time.monotonic()
                    while True:
                        try:
                            work = runtime.queues[selected].get(timeout=1)
                        except queue.Empty:
                            if selected == "control":
                                try:
                                    runtime.current.idle_down()
                                except Exception:
                                    pass
                            with runtime.lock:
                                if time.monotonic() - idle_since >= (1 if runtime.quiescing else 30) and not runtime.pending and (runtime.quiescing or not runtime.state["auto_started"]):
                                    runtime.threads[selected].remove(threading.current_thread())
                                    return
                            continue
                        try:
                            work()
                        except Exception:
                            # Record handling owns diagnostics; one failed persistence must not kill the pool.
                            pass
                        finally:
                            runtime.queues[selected].task_done()
                            idle_since = time.monotonic()

                thread = threading.Thread(target=worker, name=f"{self.namespace}-{kind}-worker", daemon=True)
                runtime.threads[kind].append(thread)
                thread.start()

    def _submit(
        self, kind: str, app: str | None, name: str, arguments: dict[str, Any],
        scope: list[str], work: Callable[[dict[str, Any]], Any], *,
        heavy: bool = False, control: bool = False, wait_seconds: float = DEFAULT_WAIT_SECONDS,
        retry_of: str | None = None,
        recovery_of: str | None = None,
        reclaim_for: str | None = None,
        input_identities: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        _checked_wait(wait_seconds)
        fingerprint = hashlib.sha256(json.dumps(
            {"kind": kind, "app": app, "name": name, "arguments": arguments, "model": self.ai_model,
             "inputs": input_identities or [], "scope": sorted(scope),
             **({"recovery_of": recovery_of} if recovery_of else {})},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()
        runtime = self.runtime
        with runtime.lock:
            if reclaim_for is not None:
                if not control or kind != "lifecycle" or name != "stop" or app not in APPS or scope != [app]:
                    raise LocalDockError("invalid-arguments")
                if app in self._reclaim_protected(reclaim_for):
                    raise LocalDockError("idle-stack-busy")
            for op_id, pending in runtime.pending.items():
                existing = self.ops.get(op_id)
                if existing.get("fingerprint") == fingerprint and existing["status"] not in TERMINAL:
                    return self.describe(existing)
            if runtime.quiescing and not (control and name == "stop"):
                raise LocalDockError("quiescing", "Dock is draining for a reviewed revision; new work is paused.")
            if runtime.state.get("detach_paused") and not (control and name == "stop"):
                raise LocalDockError("detaching")
            if not control and set(scope) & set(runtime.state["stopping"]):
                raise LocalDockError("stopping", "An application stop fence is active; collect the stop operation first.")
            selected = "control" if control else "work"
            if reclaim_for is None and runtime.queues[selected].full():
                raise LocalDockError("queue-full", "Dock's bounded work queue is full; collect existing work first.")
            if control:
                if app is None and name == "stop":
                    runtime.state["generation"] += 1
                for member in scope:
                    runtime.state["app_generations"][member] += 1
                runtime.state["stopping"] = sorted(set(runtime.state["stopping"]) | set(scope))
                _persist_runtime(runtime)
                for op_id, pending in list(runtime.pending.items()):
                    previous = self.ops.get(op_id)
                    if not previous.get("pending_terminal") and (not pending["control"] or previous["name"] == "restart") and set(pending["scope"]) & set(scope):
                        self.ops.update(op_id, cancel_requested=True)
                        self._cancel_queued(op_id)
            fence = {"generation": runtime.state["generation"],
                     "apps": {member: runtime.state["app_generations"][member] for member in scope}}
            record = self.ops.create(
                kind, app, name, arguments, namespace=self.namespace, scope=scope, fingerprint=fingerprint,
                fence=fence, cancel_requested=False, effects_started=False, phase="queued",
                updated_at=_now(), retry_of=retry_of, provenance={"verification": "unavailable"},
                output_dir=str(self.home / "outputs" / (app or "dock")),
                job=name if kind == "job" else None,
                **({"recovery_of": recovery_of, "execution_mode": "read-only-native-collection",
                    "native": {"original_operation_id": recovery_of}} if recovery_of else {}),
                **({"memory_reclaim_for": reclaim_for} if reclaim_for else {}),
            )
            if app:
                record = self.ops.update(record["id"], output_dir=str(self.home / "outputs" / app / record["id"]))
            if recovery_of:
                original = self.ops.get(recovery_of)
                self.ops.update(recovery_of, reconciliation={
                    **(original.get("reconciliation") or {}),
                    "observed_at": _now(), "strategy": "read-only-native-collection",
                    "recovery_operation_id": record["id"], "resubmission_safe": False,
                    "native_ids_retained": True, "original_outcome_unchanged": True,
                })
            try:
                for identity in input_identities or []:
                    sealed = self.context(app, record["id"]).seal_input(identity["source"])
                    if any(sealed[key] != identity[key] for key in ("bytes", "sha256")):
                        raise LocalDockError("invalid-input", "The selected input changed before acceptance.")
                record = self.ops.get(record["id"])
            except LocalDockError as error:
                record = self.ops.update(record["id"], status="failed", finished=_now(), phase="failed", error=safe_error(error.code))
                return self.describe(record)
            try:
                self._accepted(record)
            except Exception:
                failure = safe_error("provenance-unavailable")
                record = self.ops.update(record["id"], status="failed", finished=_now(), error=failure)
                return self.describe(record)
            runtime.pending[record["id"]] = {"scope": scope, "control": control, "executing": False}
            if reclaim_for is None:
                runtime.queues[selected].put_nowait(lambda: self._execute(record, work, heavy=heavy, control=control))
                self._workers()
        if reclaim_for is not None:
            # A restart can already own the sole control worker; execute its idle stop inline.
            self._execute(record, work, heavy=False, control=True)
        return self.wait(record["id"], wait_seconds)

    @contextmanager
    def _app_guard(self, app: str, ctx: AppContext):
        while not self._app_locks[app].acquire(timeout=0.1):
            ctx.check_cancelled()
        try:
            ctx.check_cancelled()
            yield
        finally:
            self._app_locks[app].release()

    @contextmanager
    def _heavy_guard(self, ctx: AppContext, needed: bool):
        if not needed:
            yield
            return
        token = (str(self.home), ctx.op_id or threading.get_ident())
        with _REGISTRY.lock:
            reentrant = _REGISTRY.heavy_owner == token
        if reentrant:
            yield
            return
        waiting = False
        while not self._heavy.acquire(timeout=0.1):
            ctx.check_cancelled()
            if not waiting:
                ctx.phase("waiting_for_heavy", "Another heavy operation is using the local resource slot.")
                waiting = True
        with _REGISTRY.lock:
            _REGISTRY.heavy_owner = token
        try:
            ctx.check_cancelled()
            yield
        finally:
            with _REGISTRY.lock:
                _REGISTRY.heavy_owner = None
            self._heavy.release()

    def _execute(self, record: dict[str, Any], work: Callable, *, heavy: bool, control: bool) -> None:
        op_id = record["id"]
        ctx = None
        status = "failed"
        failure = safe_error("unexpected-error")
        diagnostic = None
        with self.runtime.lock:
            if op_id not in self.runtime.pending:
                return
            self.runtime.pending[op_id]["executing"] = True
        try:
            if not control:
                ctx = self.context(record["application"], op_id)
            if ctx:
                ctx.check_cancelled()
            elif self.ops.get(op_id).get("cancel_requested"):
                raise LocalDockError("cancelled")
            if control:
                self.ops.update(op_id, status="running", started=_now(), phase="stopping", updated_at=_now())
                result = work(record)
            else:
                with self._heavy_guard(ctx, heavy):
                    with self._app_guard(record["application"], ctx):
                        self.ops.update(op_id, status="running", started=_now(), phase="starting", updated_at=_now())
                        result = work(record)
            if not isinstance(result, dict):
                raise LocalDockError("output-invalid")
            encoded = json.dumps(result, allow_nan=False)
            result = json.loads(self.redact(encoded))
            if len(encoded.encode()) > MAX_RESULT_BYTES:
                if ctx is None:
                    raise LocalDockError("output-invalid")
                detail = ctx.save_output("result.json", json.dumps(result, allow_nan=False).encode(), "application/json", verified=True)
                result = {**result, "result": {"details_path": detail["path"], "summary": "Large result retained in result.json."},
                          "artifacts": [*result.get("artifacts", []), detail]}
                if len(json.dumps(result).encode()) > MAX_RESULT_BYTES:
                    raise LocalDockError("output-invalid")
            self.ops.update(op_id, result=result, artifacts=result.get("artifacts", []), provider=result.get("provider"))
            if ctx:
                ctx.check_cancelled()
            elif record["name"] == "restart" and self.ops.get(op_id).get("cancel_requested"):
                raise LocalDockError("cancelled")
            if result.get("status") not in (None, "succeeded", "partial"):
                raise LocalDockError("output-invalid")
            outcome = "partial" if result.get("status") == "partial" else "succeeded"
            if record["kind"] == "job":
                artifacts = result.get("artifacts", [])
                if not isinstance(result.get("result", {}), dict) or not isinstance(artifacts, list) or len(artifacts) > 64:
                    raise LocalDockError("output-invalid")
                for artifact in artifacts:
                    if not isinstance(artifact, dict) or artifact.get("verified") is not True:
                        raise LocalDockError("output-invalid")
                    ctx.mark_verified(artifact)
            status, failure = outcome, None
        except LocalDockError as error:
            status = "cancelled" if error.code == "cancelled" else "failed"
            failure = safe_error(error.code, no_speech=error.code == "not-supported" and "no-usable-speech" in error.message)
            if record.get("recovery_of") and error.code != "cancelled":
                failure = {**failure, "retryable": error.code in ("app-not-ready", "http-unavailable", "native-job-failed"),
                           "retry_scope": "collect-retained-native",
                           "message": "Read-only recovery could not collect this native state. No application work was replayed. " + failure["message"]}
            diagnostic = error.diagnostic
        except Exception:
            status = "failed"
            failure = safe_error("unexpected-error")
        finally:
            try:
                finished = _now()
                fields = {"status": status, "finished": finished, "phase": status, "updated_at": finished, "error": failure}
                if record["kind"] == "job":
                    fields["diagnostic"] = diagnostic or self.ops.get(op_id).get("diagnostic")
                    self._finish_job(op_id, fields)
                else:
                    with self.runtime.lock:
                        if control and status in ("succeeded", "partial"):
                            held = {app for other, item in self.runtime.pending.items() if other != op_id and item["control"] for app in item["scope"]}
                            self.runtime.state["stopping"] = sorted((set(self.runtime.state["stopping"]) - set(record["scope"])) | held)
                            _persist_runtime(self.runtime)
                        if diagnostic:
                            fields["diagnostic"] = diagnostic
                        self.ops.update(op_id, **fields)
            finally:
                with self.runtime.lock:
                    self.runtime.pending.pop(op_id, None)
                    self.runtime.inventory = None
                    for app in record["scope"]:
                        self.runtime.state.setdefault("last_used", {})[app] = time.time()
                        if app in self.runtime.state["auto_started"]:
                            self.runtime.state["auto_started"][app] = time.time()
                    _persist_runtime(self.runtime)

    def wait(self, op_id: str, wait_seconds: float) -> dict[str, Any]:
        _checked_wait(wait_seconds)
        deadline = time.monotonic() + wait_seconds
        while True:
            record = self.ops.get(op_id)
            if record["status"] in TERMINAL or time.monotonic() >= deadline:
                return self.describe(record)
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))

    @staticmethod
    def describe(record: dict[str, Any]) -> dict[str, Any]:
        described = {
            key: record.get(key)
            for key in ("id", "kind", "application", "name", "status", "created", "started", "finished", "result", "error", "native", "phase", "phase_detail", "updated_at", "provenance", "reconciliation", "cancel_requested", "cancellation", "application_progress", "admission", "recovery_of")
        }
        described["progress"] = (record.get("progress") or [])[-6:]
        if record["status"] not in TERMINAL:
            described["hint"] = "Still running. Check later with action=operation and this id."
        return described

    # -- lifecycle -----------------------------------------------------------------------
    def start_sync(self, app: str, op_id: str | None = None, *, automatic: bool = False) -> dict[str, Any]:
        if op_id is None:
            submitted = self.lifecycle("start", app, wait_seconds=0)
            deadline = time.monotonic() + 1800
            while submitted["status"] not in TERMINAL and time.monotonic() < deadline:
                submitted = self.wait(submitted["id"], 10)
            if submitted["status"] == "succeeded":
                return submitted["result"]
            raise LocalDockError((submitted.get("error") or {}).get("code", "app-not-ready"))
        module = self.adapter(app)
        scope = self._scope(app)
        ctx = self.context(app, op_id)
        heavy = any(getattr(self.adapter(name), "HEAVY", False) for name in scope)
        with self._heavy_guard(ctx, heavy), self._resource_guard(ctx, scope):
            with self._app_guard(app, ctx):
                with self._read_observation("image-resolution", check_cancelled=ctx.check_cancelled):
                    ctx._resolved_images = self.resolve_images(app)
                for dependency in getattr(module, "NEEDS", ()):
                    self.start_sync(dependency, op_id, automatic=automatic)
                ctx.check_cancelled()
                before = ctx.containers()
                previous_ready = self.runtime.readiness.get(app)
                fresh = self._ready(module, ctx, timeout=0) if previous_ready else None
                if fresh and fresh.get("ready") is True:
                    self._capture_images(ctx, fresh["container_ids"])
                    with self.runtime.lock:
                        self.runtime.readiness[app] = fresh
                        self.runtime.state.setdefault("last_used", {})[app] = time.time()
                        if app in self.runtime.state["auto_started"]:
                            if automatic:
                                self.runtime.state["auto_started"][app] = time.time()
                            else:
                                self.runtime.state["auto_started"].pop(app)
                        if not automatic:
                            self.runtime.state["idle_protected"] = sorted(set(self.runtime.state.get("idle_protected", [])) - {app})
                        _persist_runtime(self.runtime)
                    return {"application": app, "ready": fresh, "urls": self._urls(module, ctx)}
                with self.runtime.lock:
                    self.runtime.readiness.pop(app, None)
                ctx.phase("starting_" + app.replace("-", "_"))
                ctx.check_cancelled()
                if hasattr(module, "prepare"):
                    module.prepare(ctx)
                ctx.check_cancelled()
                if automatic and not any(row["state"] == "running" for row in before):
                    with self.runtime.lock:
                        self.runtime.state["auto_started"][app] = time.time()
                        _persist_runtime(self.runtime)
                ctx.compose("up", "--detach", "--remove-orphans", timeout=getattr(module, "START_TIMEOUT", 900))
                ready = self._ready(module, ctx, timeout=getattr(module, "READY_TIMEOUT", 600))
                if not ready.get("ready"):
                    raise LocalDockError("app-not-ready")
                ctx.check_cancelled()
                setup = module.setup(ctx) if hasattr(module, "setup") else None
                ctx.check_cancelled()
                if hasattr(module, "setup"):
                    ready = self._ready(module, ctx, timeout=getattr(module, "READY_TIMEOUT", 600))
                    if ready.get("ready") is not True:
                        raise LocalDockError("app-not-ready")
                self._capture_images(ctx, ready["container_ids"])
                with self.runtime.lock:
                    self.runtime.readiness[app] = ready
                    self.runtime.state.setdefault("last_used", {})[app] = time.time()
                    if automatic and not any(row["state"] == "running" for row in before):
                        self.runtime.state["auto_started"][app] = time.time()
                    elif not automatic:
                        self.runtime.state["auto_started"].pop(app, None)
                        self.runtime.state["idle_protected"] = sorted(set(self.runtime.state.get("idle_protected", [])) - {app})
                    _persist_runtime(self.runtime)
                ctx.log(f"{app} ready")
                return {"application": app, "ready": ready, "setup": setup, "urls": self._urls(module, ctx)}

    @staticmethod
    def _urls(module: Any, ctx: AppContext) -> dict[str, str]:
        return module.urls(ctx) if hasattr(module, "urls") else {}

    @staticmethod
    def _roles_ready(module: Any, rows: list[dict[str, Any]], expected: set[str]) -> bool:
        one_shots = set(getattr(module, "ONE_SHOT_SERVICES", ()))
        return bool(expected) and expected == {row["service"] for row in rows} and all(
            (row["state"] == "exited" and row["exit_code"] == 0) if row["service"] in one_shots else
            (row["state"] == "running" and row["health"] in ("", "healthy", "none", None))
            for row in rows
        )

    def _ready(self, module: Any, ctx: AppContext, *, timeout: float) -> dict[str, Any]:
        last: dict[str, Any] = {"ready": False, "detail": "not probed"}
        expected = set(ctx.services())

        def probe() -> bool:
            nonlocal last
            rows = ctx.containers()
            if not self._roles_ready(module, rows, expected):
                last = {"ready": False, "detail": "Expected service roles have not become ready."}
            elif hasattr(module, "ready"):
                last = module.ready(ctx)
                if not isinstance(last, dict) or type(last.get("ready")) is not bool:
                    last = {"ready": False, "detail": "The native readiness probe did not return a boolean observation."}
            else:
                last = {"ready": True, "detail": "Expected container roles are ready."}
            if last.get("ready") is True:
                confirmed = ctx.containers()
                if (
                    {row["id"] for row in rows} != {row["id"] for row in confirmed}
                    or not self._roles_ready(module, confirmed, expected)
                ):
                    last = {"ready": False, "detail": "Container state changed during the native readiness probe."}
                else:
                    ctx.check_cancelled()
                    last = {**last, "observed_at": _now(), "container_ids": sorted(row["id"] for row in confirmed)}
            return last.get("ready") is True

        observed = ctx.wait_until(probe, timeout=timeout, interval=3.0)
        return last if observed else {**last, "ready": False}

    def _drain_scope(self, scope: list[str], op_id: str, timeout: float = 300) -> None:
        deadline = time.monotonic() + timeout
        while True:
            with self.runtime.lock:
                pending = [
                    other for other, item in self.runtime.pending.items()
                    if other != op_id and not item["control"] and set(item["scope"]) & set(scope)
                ]
            if not pending:
                return
            if time.monotonic() >= deadline:
                raise LocalDockError("stop-timeout", "Cancellation has not drained; the stop fence remains active.")
            time.sleep(0.05)

    @_single_attempt_reads
    def _teardown_custody(self, ctx: AppContext, rows: list[dict[str, Any]]) -> dict[str, Any]:
        model = self._compose_model(ctx, {})
        services = model["services"]
        writable = sorted(name for name, service in services.items() if service.get("read_only") is not True)
        if rows and writable:
            return {"qualified": False, "reason": "writable-container-layer", "retained_roles": writable}
        if not rows:
            return {"qualified": True, "reason": "no-containers-to-discard"}
        ids = [row["id"] for row in rows]
        if any(not isinstance(identifier, str) or re.fullmatch(r"[a-f0-9]{12,64}", identifier) is None for identifier in ids):
            raise LocalDockError("docker-state-unknown")
        observed = self._docker([
            "inspect", "--type", "container", "--format",
            CUSTODY_INSPECT_FORMAT,
            *ids,
        ], timeout=5, max_bytes=512 * 1024)
        if observed.returncode:
            raise self._docker_failure("inspect container custody", observed, "docker-state-unknown")
        containers = self._parse_rows(observed.stdout)
        if len(containers) != len(rows) or len({item.get("id") for item in containers}) != len(rows):
            raise LocalDockError("docker-state-unknown")
        named_volumes = set()
        for container in containers:
            labels = container.get("labels") or {}
            service_name = labels.get("com.docker.compose.service")
            if (
                labels.get("com.docker.compose.project") != ctx.project
                or service_name not in services
                or str(labels.get("com.docker.compose.oneoff", "False")).casefold() == "true"
                or not any(container.get("id", "").startswith(identifier) for identifier in ids)
            ):
                return {"qualified": False, "reason": "unreviewed-container-role"}
            if container.get("read_only") is not True:
                return {"qualified": False, "reason": "observed-writable-container-layer", "retained_roles": [service_name]}
            expected = {}
            for mount in services[service_name].get("volumes", []):
                if not isinstance(mount, dict) or mount.get("type") not in ("volume", "bind"):
                    return {"qualified": False, "reason": "unqualified-mount"}
                if mount["type"] == "volume":
                    source = mount.get("source")
                    declaration = model.get("volumes", {}).get(source)
                    if not isinstance(declaration, dict) or not source:
                        return {"qualified": False, "reason": "anonymous-or-unqualified-volume"}
                    name = declaration.get("name", f"{ctx.project}_{source}")
                    if not isinstance(name, str) or "$" in name:
                        return {"qualified": False, "reason": "unresolved-volume-name"}
                    expected[mount["target"]] = ("volume", name)
                else:
                    if mount.get("read_only") is not True:
                        return {"qualified": False, "reason": "writable-bind-not-qualified"}
                    expected[mount["target"]] = ("bind", mount.get("source"))
            actual = container.get("mounts")
            if not isinstance(actual, list):
                raise LocalDockError("docker-state-unknown")
            seen = set()
            for mount in actual:
                if mount.get("Type") == "tmpfs":
                    continue
                target = mount.get("Destination")
                if target not in expected:
                    return {"qualified": False, "reason": "anonymous-or-unqualified-volume"}
                kind, source = expected[target]
                actual_source = mount.get("Name") if kind == "volume" else mount.get("Source")
                if (
                    mount.get("Type") != kind
                    or kind == "volume" and actual_source != source
                    or kind == "bind" and (
                        mount.get("RW") is not False
                        or not self._bind_source_matches(ctx, container["id"], target, source, actual_source)
                    )
                ):
                    return {"qualified": False, "reason": "observed-mount-mismatch"}
                seen.add(target)
                if kind == "volume":
                    named_volumes.add(source)
            if seen != set(expected):
                return {"qualified": False, "reason": "required-persistent-mount-missing"}
        return {"qualified": True, "reason": "read-only-layers-with-named-volumes", "retained_volumes": sorted(named_volumes)}

    def _bind_source_matches(self, ctx: AppContext, container_id: str, target: str, source: Any, observed: Any) -> bool:
        if source == observed:
            return True
        if (
            sys.platform != "darwin" or not isinstance(source, str)
            or not source.startswith("/Users/") or observed != "/host_mnt" + source
            or str(Path(source)) != source or ".." in Path(source).parts
            or not Path(source).is_relative_to(ctx.root)
        ):
            return False
        try:
            selected = Path(source).relative_to(ROOT).as_posix()
            entry = next(item for item in capability_manifest(ROOT)["files"] if item["path"] == selected)
            if type(entry["bytes"]) is not int or not 0 < entry["bytes"] <= MAX_BIND_ALIAS_BYTES:
                return False
            raw = read_regular(Path(source))
            if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                return False
            info = self._docker(
                ["info", "--format", DESKTOP_INFO_FORMAT],
                timeout=5, max_bytes=4096,
            )
            if info.returncode or json.loads(info.stdout) != {"os": "Docker Desktop", "type": "linux"}:
                return False
            copied = self._docker(
                ["cp", f"{container_id}:{target}", "-"], timeout=10,
                max_bytes=MAX_BIND_ALIAS_BYTES + 64 * 1024,
            )
            if copied.returncode:
                return False
            # Only a locked small regular file qualifies; never extract a tar to disk.
            with tarfile.open(fileobj=io.BytesIO(copied.stdout), mode="r:") as archive:
                members = archive.getmembers()
                if len(members) != 1 or not members[0].isfile() or members[0].size != entry["bytes"]:
                    return False
                with archive.extractfile(members[0]) as stream:
                    actual = stream.read(MAX_BIND_ALIAS_BYTES + 1)
                return len(actual) == entry["bytes"] and hashlib.sha256(actual).hexdigest() == entry["sha256"]
        except (OSError, ValueError, TypeError, KeyError, StopIteration, tarfile.TarError, DistributionRefused, LocalDockError):
            return False

    def _release_project_networks(self, app: str, record: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        ctx = self.context(app, record["id"])
        custody = self._teardown_custody(ctx, rows)
        if not custody["qualified"]:
            return {"application": app, "status": "retained", **custody}
        current = self._container_rows(app)
        if {row["id"] for row in current} != {row["id"] for row in rows} or any(
            row["state"] in ("running", "restarting", "paused") for row in current
        ):
            return {"application": app, "status": "retained", "reason": "container-set-changed-after-stop"}
        ctx.compose("down", "--remove-orphans", "--timeout", "30", timeout=300)
        if self._container_rows(app):
            return {"application": app, "status": "retained", "reason": "containers-remain-after-down"}
        return {"application": app, "status": "released", "volumes_deleted": False, **custody}

    def _release_idle_ai_network(self, op_id: str) -> dict[str, Any]:
        with _REGISTRY.network_lock:
            with self.runtime.lock:
                if any(other != op_id for other in self.runtime.pending):
                    return {"status": "retained", "reason": "other-operations-pending"}
            if self._inventory(timeout=5)["rows"]:
                return {"status": "retained", "reason": "namespace-containers-retained"}
            network = self._inspect_network(self.ai_network)
            if network is None:
                return {"status": "absent"}
            if network.get("Internal") is not True or (network.get("Labels") or {}).get("rapp.dock.namespace") != self.namespace:
                return {"status": "retained", "reason": "network-ownership-mismatch"}
            if network.get("Containers"):
                return {"status": "retained", "reason": "network-still-attached"}
            identifier = network.get("Id")
            if not isinstance(identifier, str) or re.fullmatch(r"[a-f0-9]{12,64}", identifier) is None:
                raise LocalDockError("docker-state-unknown")
            removed = self._docker(["network", "rm", identifier], timeout=10, max_bytes=64 * 1024)
            if removed.returncode:
                return {"status": "retained", "reason": "network-busy-or-unavailable"}
            return {"status": "released"}

    def _stop_progress(self, op_id: str, app: str, phase: str, status: str, **fields: Any) -> None:
        with self.ops.lock:
            record = self.ops.get(op_id)
            progress = record.get("application_progress", {})
            progress[app] = {
                **progress.get(app, {}), "application": app, "phase": phase,
                "status": status, "updated_at": _now(), **fields,
            }
            self.ops.update(op_id, application_progress=progress, updated_at=_now())

    def _stop_dependencies(self, scope: list[str]) -> dict[str, set[str]]:
        dependencies = {}
        for app in scope:
            try:
                dependencies[app] = set(getattr(self.adapter(app), "NEEDS", ())) & set(scope)
            except LocalDockError:
                dependencies[app] = set()
            if app != "intelligence" and "intelligence" in scope:
                dependencies[app].add("intelligence")
        for _ in range(len(scope)):
            for app in scope:
                dependencies[app].update(
                    dependency for direct in list(dependencies[app]) for dependency in tuple(dependencies[direct])
                )
        if any(app in dependencies[app] for app in scope):
            raise LocalDockError("invalid-adapter", "Stop dependency order contains a cycle.")
        return dependencies

    def _stop_diagnostic(self, op_id: str, app: str, diagnostic: dict[str, Any]) -> None:
        with self.ops.lock:
            record = self.ops.get(op_id)
            detail = {"application": app, **diagnostic}
            observations = {**record.get("diagnostics_by_application", {}), app: detail}
            self.ops.update(op_id, diagnostic=detail, diagnostics_by_application=observations)

    @_single_attempt_reads
    def _stop_project(self, app: str, record: dict[str, Any]) -> dict[str, Any]:
        op_id = record["id"]
        try:
            self._stop_progress(op_id, app, "draining", "running", wait_reason="cancelling in-flight work")
            self._drain_scope([app], op_id)
            rows = self._container_rows(app)
            ids = [row["id"] for row in rows if row["state"] in ("running", "restarting", "paused")]
            if any(not isinstance(identifier, str) or re.fullmatch(r"[0-9a-f]{12,64}", identifier) is None for identifier in ids):
                raise LocalDockError("docker-state-unknown")
            self._stop_progress(op_id, app, "stopping", "running", containers_to_stop=len(ids), wait_reason=None)
            if ids:
                self.ops.update(op_id, effects_started=True)
                result = self._docker(["stop", "--time", "30", *ids], timeout=300, max_bytes=64 * 1024)
                if result.returncode:
                    raise self._docker_failure("stop " + app, result)
            after = self._container_rows(app)
            if any(row["state"] in ("running", "restarting", "paused") for row in after):
                raise LocalDockError("app-not-ready")
            self._stop_progress(op_id, app, "stopped", "running", stopped=True, containers_to_stop=0)
            cleanup = {"application": app, "status": "retained", "reason": "restart-keeps-networks"}
            if record["name"] in ("stop", "idle-down"):
                self._stop_progress(op_id, app, "releasing_networks", "running")
                try:
                    # Project networks are disjoint; only shared AI cleanup needs the global lock.
                    cleanup = self._release_project_networks(app, record, after)
                except LocalDockError as error:
                    if error.diagnostic:
                        self._stop_diagnostic(op_id, app, error.diagnostic)
                    cleanup = {"application": app, "status": "retained", "reason": error.code}
                except Exception:
                    cleanup = {"application": app, "status": "retained", "reason": "unexpected-error"}
            self._stop_progress(op_id, app, "finished", "succeeded", stopped=True, network_cleanup=cleanup)
            return {"application": app, "stopped": True, "network_cleanup": cleanup}
        except LocalDockError as error:
            failure = safe_error(error.code)
            if error.diagnostic:
                self._stop_diagnostic(op_id, app, error.diagnostic)
        except Exception:
            failure = safe_error("unexpected-error")
        self._stop_progress(op_id, app, "failed", "failed", stopped=False, error=failure)
        return {"application": app, "stopped": False, "error": failure}

    @_single_attempt_reads
    def _stop_scope(self, record: dict[str, Any]) -> dict[str, Any]:
        scope, op_id = record["scope"], record["id"]
        dependencies = self._stop_dependencies(scope)
        for app in scope:
            self._stop_progress(op_id, app, "queued", "queued", stopped=False, wait_reason="dependency order or bounded stop slot")
        self.ops.update(op_id, phase="stopping_applications", updated_at=_now())
        executor, pending_slots = _stop_executor()
        remaining, completed = set(scope), {}
        while remaining:
            layer = [app for app in scope if app in remaining and not any(
                app in dependencies[other] for other in remaining if other != app
            )]
            futures = {}
            for app in layer:
                if any(app in dependencies[other] and not result["stopped"] for other, result in completed.items()):
                    failure = safe_error("dependent-stop-incomplete")
                    self._stop_progress(op_id, app, "waiting_for_dependents", "blocked", error=failure)
                    completed[app] = {"application": app, "stopped": False, "error": failure}
                    continue
                pending_slots.acquire()
                try:
                    future = executor.submit(self._stop_project, app, record)
                except BaseException:
                    pending_slots.release()
                    raise
                future.add_done_callback(lambda unused, slots=pending_slots: slots.release())
                futures[future] = app
            for future in as_completed(futures):
                app = futures[future]
                try:
                    completed[app] = future.result()
                except Exception:
                    # Drain every submitted stop before ending the parent operation.
                    completed[app] = {"application": app, "stopped": False, "error": safe_error("unexpected-error")}
            remaining.difference_update(layer)

        after = self._inventory(timeout=5)
        for row in after["rows"]:
            if row["application"] in scope and row["state"] in ("running", "restarting", "paused") and completed[row["application"]]["stopped"]:
                app = row["application"]
                failure = safe_error("app-not-ready")
                completed[app] = {"application": app, "stopped": False, "error": failure}
                self._stop_progress(op_id, app, "failed", "failed", stopped=False, error=failure)
        succeeded = all(result["stopped"] for result in completed.values())
        ai_cleanup = {"status": "retained", "reason": "restart-keeps-networks"}
        if record["name"] in ("stop", "idle-down"):
            self.ops.update(op_id, phase="releasing_ai_network" if succeeded else "stop_incomplete", updated_at=_now())
            try:
                ai_cleanup = self._release_idle_ai_network(op_id) if succeeded else {"status": "retained", "reason": "dependent-stop-incomplete"}
            except LocalDockError as error:
                ai_cleanup = {"status": "retained", "reason": error.code}
        try:
            networks = self._network_inventory(timeout=5)
        except LocalDockError as error:
            networks = {"state": "unknown", "error": error.code}
        with self.runtime.lock:
            for app in scope:
                if completed[app]["stopped"]:
                    self.runtime.state["auto_started"].pop(app, None)
                    self.runtime.state["idle_protected"] = sorted(set(self.runtime.state.get("idle_protected", [])) - {app})
                    self.runtime.readiness.pop(app, None)
            _persist_runtime(self.runtime)
        result = {
            "scope": scope, "stopped": succeeded, "observed_at": after["observed_at"],
            "data_deleted": False, "data": "kept", "unrelated_projects_changed": [],
            "network_cleanup": [completed[app]["network_cleanup"] for app in scope if "network_cleanup" in completed[app]],
            "ai_network": ai_cleanup, "remaining_networks": networks,
        }
        self.ops.update(op_id, result=result)
        if not succeeded:
            failures = [completed[app] for app in scope if not completed[app]["stopped"]]
            failed = next((item for item in failures if item["error"]["code"] != "dependent-stop-incomplete"), failures[0])
            raise LocalDockError(failed["error"]["code"])
        return result

    def lifecycle(self, action: str, app: str | None = None, *, delete_data: bool = False, wait_seconds: float | None = None) -> dict[str, Any]:
        if wait_seconds is None:
            wait_seconds = STOP_WAIT_SECONDS if action == "stop" else DEFAULT_WAIT_SECONDS
        _checked_wait(wait_seconds)
        if action not in ("start", "stop", "restart") or delete_data:
            raise LocalDockError("unsupported-action", "Only scoped start, stop and restart are supported; data deletion is unavailable.")
        if app is not None and app not in APPS or action != "stop" and app is None:
            raise LocalDockError("unknown-application", "Select an enrolled application.")
        if action == "start":
            scope = self._scope(app)
            return self._submit(
                "lifecycle", app, action, {}, scope, lambda record: self.start_sync(app, record["id"]),
                heavy=any(getattr(self.adapter(name), "HEAVY", False) for name in scope), wait_seconds=wait_seconds,
            )
        scope = [app] if app else list(APPS)
        with self.runtime.lock:
            for op_id, pending in self.runtime.pending.items():
                if not pending["control"] and set(pending["scope"]) & set(scope):
                    target = self.ops.get(op_id)["application"]
                    if target not in scope:
                        scope.append(target)
            if action == "restart":
                self.adapter(app)

            def work(record):
                result = self._stop_scope(record)
                if action == "restart":
                    self.ops.update(record["id"], phase="restarting", updated_at=_now())
                    started = self.start_sync(app, record["id"])
                    return {"application": app, "restarted": True, "data_deleted": False, **started}
                return result

            # The durable fence and admission decision must be one critical section.
            result = self._submit("lifecycle", app, action, {}, scope, work, control=True, wait_seconds=0)
        return self.wait(result["id"], wait_seconds)

    # -- observation -------------------------------------------------------------------
    def status(self, app: str | None = None, *, deadline: float | None = None,
               check_cancelled: Callable[[], None] | None = None) -> dict[str, Any]:
        with self._read_observation("dock-status", deadline=deadline, check_cancelled=check_cancelled) as observation:
            result = self._status(app)
        # Links an unknown or recovered observation to its private record; clean fast reads have none.
        result["observation_id"] = observation.record["id"] if observation is not None and observation.journaled else None
        return result

    def _status(self, app: str | None = None) -> dict[str, Any]:
        if app is not None and app not in APPS:
            raise LocalDockError("unknown-application", "Select an enrolled application.")
        entries, modules = [], {}
        for name in (app,) if app else APPS:
            try:
                modules[name] = self.adapter(name)
            except LocalDockError as error:
                entries.append({"application": name, "state": "not-installed" if error.code == "not-installed" else "unknown", "error": error.code})
        inventory_error = None
        inventory = {"rows": [], "observed_at": _now()}
        if modules:
            try:
                inventory = self._inventory(app, cached=True)
            except LocalDockError as error:
                inventory_error = error.code
        for name, module in modules.items():
            if inventory_error:
                entries.append({"application": name, "state": "unknown", "error": inventory_error})
                continue
            ctx = self.context(name)
            rows = [row for row in inventory["rows"] if row["application"] == name]
            running = [row for row in rows if row["state"] == "running"]
            complete = [row for row in rows if row["service"] in getattr(module, "ONE_SHOT_SERVICES", ()) and row["state"] == "exited" and row["exit_code"] == 0]
            expected = self.runtime.expected_services.get(name, set())
            if not rows:
                state = "not-started"
            elif running and len(running) + len(complete) == len(rows) and (not expected or expected <= {row["service"] for row in rows}):
                state = "running"
            elif running:
                state = "partially-running"
            else:
                state = "stopped"
            entry: dict[str, Any] = {
                "application": name,
                "title": getattr(module, "TITLE", name),
                "state": state,
                "services": rows if app else len(rows),
                "urls": self._urls(module, ctx) if running else {},
                "readiness": "not-probed-by-status",
            }
            entries.append(entry)
        entries.sort(key=lambda item: APP_INDEX[item["application"]])
        capabilities = [
            {"job": item["job"], "description": " ".join(item["description"].split())[:160]}
            for item in self.jobs(app)["jobs"]
        ]
        networks = {"state": "not-needed", "docker_total": None, "namespace_total": None}
        if modules:
            try:
                networks = self._network_inventory(cached=True)
            except LocalDockError as error:
                networks = {"state": "unknown", "docker_total": None, "namespace_total": None, "error": error.code}
        return {"applications": entries, "capabilities": capabilities, "namespace": self.namespace,
                "observed_at": inventory["observed_at"], "active_operations": self.active_operations(),
                "docker_state": "unknown" if inventory_error else "observed" if modules else "not-needed",
                "docker_error": safe_error(inventory_error) if inventory_error else None,
                "networks": networks,
                "idle_protected_after_process_loss": sorted(self.runtime.state.get("idle_protected", [])),
                "detach_paused": bool(self.runtime.state.get("detach_paused")),
                "admission_paused": self.runtime.quiescing or bool(self.runtime.state["stopping"]) or bool(self.runtime.state.get("detach_paused"))}

    def logs(self, app: str, *, service: str | None = None, tail: int = 80) -> dict[str, Any]:
        self.adapter(app)
        rows = self._container_rows(app)
        if service is not None and service not in {row["service"] for row in rows}:
            raise LocalDockError("unknown-service", "Select an observed service.")
        tail = max(1, min(int(tail), 400))
        selected = [row for row in rows if service is None or row["service"] == service][:3]
        parts = []
        for row in selected:
            if not isinstance(row["id"], str) or re.fullmatch(r"[a-f0-9]{12,64}", row["id"]) is None:
                raise LocalDockError("docker-state-unknown")
            completed = self._docker(["logs", "--tail", str(tail), row["id"]], timeout=2, max_bytes=256 * 1024)
            if completed.returncode:
                raise self._docker_failure("logs", completed, "docker-state-unknown")
            parts.append(self.redact(_text(completed.stdout) + _text(completed.stderr)))
        text = "\n".join(parts)
        raw = text.encode("utf-8")
        return {"application": app, "service": service, "logs": raw[-4096:].decode("utf-8", "replace"),
                "truncated": len(raw) > 4096 or len(rows) > len(selected)}

    def jobs(self, app: str | None = None, query: str | None = None) -> dict[str, Any]:
        return discover_jobs(app, query, loader=self.adapter)

    def _input_identities(self, app: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        paths = ([arguments["source_path"]] if "source_path" in arguments else []) + arguments.get("input_paths", [])
        if not paths:
            return []
        ctx = self.context(app)
        identities, total = [], 0
        for selected in paths:
            source = ctx._input_source(selected)
            digest, size = hashlib.sha256(), 0
            try:
                with _regular_file(source) as stream:
                    before = os.fstat(stream.fileno())
                    if before.st_size + total > MAX_INPUT_BYTES:
                        raise LocalDockError("invalid-input", "The selected inputs exceed the aggregate byte limit.")
                    while chunk := stream.read(1024 * 1024):
                        size += len(chunk)
                        if size + total > MAX_INPUT_BYTES:
                            raise LocalDockError("invalid-input", "The selected inputs exceed the aggregate byte limit.")
                        digest.update(chunk)
                    after = os.fstat(stream.fileno())
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        raise LocalDockError("invalid-input", "A selected input changed during verification.")
            except FileNotFoundError:
                raise LocalDockError("input-not-found") from None
            except LocalDockError as error:
                if error.code == "unsafe-file":
                    raise LocalDockError("invalid-input") from None
                raise
            except OSError:
                raise LocalDockError("invalid-input") from None
            total += size
            ctx._check_input_commitment(source, size, digest.hexdigest())
            identities.append({"source": str(source), "name": source.name, "bytes": size, "sha256": digest.hexdigest()})
        return identities

    def run_job(self, app: str, job: str, arguments: Any = None, *, wait_seconds: float = DEFAULT_WAIT_SECONDS) -> dict[str, Any]:
        module = self.adapter(app)
        short_name = job.removeprefix(f"{app}.")
        spec = getattr(module, "JOBS", {}).get(short_name)
        if spec is None:
            raise LocalDockError("unknown-job", f"{app} has no job {job!r}; use action=jobs")
        checked = _validate_arguments(spec, arguments, job=f"{app}.{short_name}")
        scope = self._scope(app)
        inputs = self._input_identities(app, checked)

        def work(record) -> Any:
            ctx = self.context(app, record["id"])
            self.start_sync(app, record["id"], automatic=True)
            ctx.phase("running_job")
            self.ops.update(record["id"], dispatch_started=True)
            return spec["run"](ctx, **checked)

        return self._submit(
            "job", app, f"{app}.{short_name}", checked, scope, work,
            heavy=bool(spec.get("heavy")) or any(getattr(self.adapter(member), "HEAVY", False) for member in scope),
            wait_seconds=wait_seconds, input_identities=inputs,
        )

    def operation(self, op_id: str, *, wait_seconds: float = 0) -> dict[str, Any]:
        _checked_wait(wait_seconds)
        record = self.ops.get(op_id)
        if record.get("pending_terminal"):
            self._recover_finalization(record)
        elif record["status"] in TERMINAL:
            self._terminal(op_id)
            if record["status"] == "interrupted":
                recovered = self._recover_native(record, wait_seconds=wait_seconds)
                if recovered is not None:
                    return recovered
        return self.wait(op_id, wait_seconds)

    def _recover_native(self, record: dict[str, Any], *, wait_seconds: float, renew: bool = False) -> dict[str, Any] | None:
        if record.get("recovery_of"):
            original = self.ops.get(record["recovery_of"])
            if original["application"] != record["application"] or original.get("recovery_of"):
                raise LocalDockError("recovery-state-invalid")
            record = original
        if record["kind"] != "job" or record["status"] not in ("interrupted", "failed"):
            return None
        selected = None
        with self.runtime.lock:
            original = self.ops.get(record["id"])
            link = (original.get("reconciliation") or {}).get("recovery_operation_id")
            if link:
                prior = self.ops.get(link)
                if prior.get("recovery_of") != original["id"] or prior["application"] != original["application"]:
                    raise LocalDockError("recovery-state-invalid")
                if prior["status"] != "interrupted" and not (renew and prior["status"] in ("failed", "cancelled")):
                    selected = prior["id"]
                elif prior["status"] == "interrupted":
                    self._terminal(prior["id"])
            if selected is None:
                module = self.adapter(original["application"])
                collector = getattr(module, "reconcile", None)
                native = original.get("native")
                if not callable(collector) or not isinstance(native, dict) or not any(
                    key.endswith("_id") and isinstance(value, str) and value for key, value in native.items()
                ):
                    return None
                snapshot = copy.deepcopy(original)

                def collect(accepted):
                    ctx = AppContext(self, original["application"], module, accepted["id"], native_recovery=snapshot)
                    ctx.check_cancelled()
                    if not ctx.running():
                        raise LocalDockError("app-not-ready", "Recovery never starts a stopped native application.")
                    ctx.phase("reconciling_native", "Inspecting retained native IDs; no application work will be replayed.")
                    self.ops.update(accepted["id"], native_inspection_started=True)
                    self._capture_images(ctx)
                    result = collector(ctx, copy.deepcopy(snapshot))
                    if not isinstance(result, dict) or not isinstance(result.get("result", {}), dict):
                        raise LocalDockError("output-invalid")
                    provider = result.get("provider") or {}
                    if (
                        not isinstance(provider, dict) or provider.get("runtime", "none") != "none"
                        or type(provider.get("calls", 0)) is not int or provider.get("calls", 0) != 0
                        or provider.get("request_ids")
                    ):
                        raise LocalDockError("output-invalid", "A recovery cannot claim new provider work.")
                    return {
                        **result, "message": "Read-only recovery: " + str(result.get("message", "Retained native observations were collected.")),
                        "provider": {"runtime": "none", "model": None, "calls": 0, "request_ids": []},
                        "result": {**result.get("result", {}), "recovery": {
                            "original_operation_id": original["id"], "mode": "read-only-native-collection",
                            "native_submission_replayed": False, "inference_replayed": False,
                        }},
                    }

                submitted = self._submit(
                    "job", original["application"], original["application"] + ".collect",
                    {"original_operation_id": original["id"]}, [original["application"]], collect,
                    heavy=bool(getattr(module, "HEAVY", False)), wait_seconds=0, recovery_of=original["id"],
                )
                selected = submitted["id"]
        return self.operation(selected, wait_seconds=wait_seconds)

    def operations(self, app: str | None = None) -> dict[str, Any]:
        if app is not None and app not in APPS:
            raise LocalDockError("unknown-application")
        return {"operations": [self.describe(record) for record in self.ops.recent(app, 10)], "history_scan_limit": 2048}

    def active_operations(self) -> list[dict[str, Any]]:
        return active_operations(self.home)

    def quiesce(self, timeout: float = 30) -> dict[str, Any]:
        return quiesce(timeout, self.home)

    def resume(self) -> None:
        resume(self.home)

    def _installation_target(self) -> dict[str, Any]:
        if (self.runtime.home, self.runtime.namespace, self.runtime.port_base) != (self.home, self.namespace, self.port_base):
            raise LocalDockError("installation-binding-mismatch")
        return {"home": str(self.home), "namespace": self.namespace, "port_base": self.port_base}

    def pause_for_detach(self) -> dict[str, Any]:
        """Persist admission fencing only; source removal remains installer-owned."""
        self._installation_target()
        with self.runtime.lock:
            self.runtime.state["detach_paused"] = True
            _persist_runtime(self.runtime)
        return self.detach_status(timeout=0)

    def detach_status(self, *, timeout: float = 0) -> dict[str, Any]:
        """Bounded drain observation; never pause, resume, start, or repair work."""
        target = self._installation_target()
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 <= timeout <= 300:
            raise LocalDockError("invalid-input")
        deadline = time.monotonic() + timeout
        while True:
            active = self.active_operations()
            with self.runtime.lock:
                durable = bool(self.runtime.state.get("detach_paused"))
                paused = durable or self.runtime.quiescing or bool(self.runtime.state["stopping"])
            if not active or time.monotonic() >= deadline:
                return {"schema": "rapp-dock-installation-fence/1", "target": target,
                        "admission_paused": paused, "durable": durable,
                        "quiesced": not active, "active_operations": active}
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))

    def resume_after_installation(self) -> dict[str, Any]:
        """Explicit verified reinstall only; never clear a different pause reason."""
        target = self._installation_target()
        with self.runtime.lock:
            if self.runtime.pending or self.runtime.state["stopping"]:
                raise LocalDockError("detach-incomplete")
            if self.runtime.state.get("detach_paused"):
                self.runtime.state["detach_paused"] = False
                try:
                    _persist_runtime(self.runtime)
                except Exception:
                    self.runtime.state["detach_paused"] = True
                    raise
                status = "reactivated" if not self.runtime.quiescing else "paused-by-other-control"
            else:
                status = "not-detached"
            return {"schema": "rapp-dock-installation-fence/1", "target": target,
                    "status": status, "admission_paused": self.runtime.quiescing, "durable": False}

    def _cancel_queued(self, op_id: str) -> None:
        item = self.runtime.pending.get(op_id)
        if item is not None and not item["executing"]:
            self.ops.update(op_id, status="cancelled", phase="cancelled", cancel_requested=True,
                            finished=_now(), updated_at=_now(), error=safe_error("cancelled"))
            self.runtime.pending.pop(op_id, None)
            self._terminal(op_id)

    def cancel(self, op_id: str, *, wait_seconds: float = 0) -> dict[str, Any]:
        _checked_wait(wait_seconds)
        with self.runtime.lock:
            record = self.ops.get(op_id)
            if record["status"] in TERMINAL or record.get("pending_terminal"):
                return self.describe(record)
            if record["kind"] != "job" and not (record["kind"] == "lifecycle" and record["name"] in ("start", "restart")):
                raise LocalDockError("not-supported", "A stop fence cannot itself be cancelled.")
            self.ops.update(op_id, cancel_requested=True, phase="cancelling", updated_at=_now())
            self._cancel_queued(op_id)
            queued = op_id not in self.runtime.pending
        if record.get("recovery_of"):
            return self.wait(op_id, wait_seconds)
        if not queued or record["name"] == "restart":
            if record["kind"] == "lifecycle" and record["name"] == "restart":
                stop = self._submit("lifecycle", record["application"], "stop", {}, record["scope"],
                                    self._stop_scope, control=True, wait_seconds=0)
            else:
                stop = self.lifecycle("stop", record["application"], wait_seconds=0)
            self.ops.update(op_id, cancellation={"stop_operation_id": stop["id"], "native_cancellation": "scoped-app-stop"})
        return self.wait(op_id, wait_seconds)

    def _reconcile(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            rows = self._container_rows(record["application"]) if record["application"] else self._inventory()["rows"]
            app_state = "running" if any(row["state"] == "running" for row in rows) else "stopped"
        except LocalDockError:
            app_state = "unknown"
        return self.ops.update(record["id"], reconciliation={
            "observed_at": _now(), "application_state": app_state,
            "native_state": "unknown" if record.get("native") or record.get("dispatch_started") else "not-submitted",
            "native_ids_retained": bool(record.get("native")),
            "resubmission_safe": not (record.get("native") or record.get("effects_started") or record.get("dispatch_started")),
        })

    def retry(self, op_id: str, *, wait_seconds: float = DEFAULT_WAIT_SECONDS) -> dict[str, Any]:
        _checked_wait(wait_seconds)
        record = self.ops.get(op_id)
        if record["status"] not in TERMINAL:
            return self.describe(record)
        self._terminal(op_id)
        if record["status"] in ("failed", "interrupted") or record.get("recovery_of"):
            recovered = self._recover_native(record, wait_seconds=wait_seconds, renew=True)
            if recovered is not None:
                return recovered
        record = self._reconcile(record)
        if record["kind"] == "lifecycle" and record["name"] == "stop":
            return self._submit("lifecycle", record["application"], "stop", {}, record["scope"],
                                self._stop_scope, control=True, wait_seconds=wait_seconds)
        if record["status"] in ("succeeded", "partial") or not record["reconciliation"]["resubmission_safe"]:
            raise LocalDockError("unsafe-retry", "Native state is retained; uncertain or completed work must not be resubmitted.")
        if record["kind"] != "job":
            raise LocalDockError("not-supported")
        result = self.run_job(record["application"], record["name"], record["arguments"], wait_seconds=wait_seconds)
        if result["id"] != op_id:
            self.ops.update(result["id"], retry_of=op_id)
        return result

    def _exhaust(self) -> Any:
        with self.runtime.lock:
            if self._exhaust_checked:
                return self._exhaust_client
            selected = ROOT / "dock_exhaust.py"
            if not selected.exists():
                self._exhaust_checked = True
                return None
            module = importlib.import_module("dock_exhaust")
            if Path(module.__file__).resolve() != selected.resolve() or selected.is_symlink():
                raise LocalDockError("provenance-unavailable")
            self._exhaust_client = module.JobExhaust(self.home)
            self._exhaust_checked = True
            return self._exhaust_client

    def _accepted(self, record: dict[str, Any]) -> None:
        if record["kind"] != "job":
            return
        client = self._exhaust()
        if client is None:
            return
        try:
            from scotty_distribution import verify_capability

            verify_capability(ROOT)
            with _regular_file(ROOT / "SCOTTY_CAPABILITY_LOCK.json") as stream:
                raw = stream.read(MAX_OPERATION_BYTES + 1)
            revision = hashlib.sha256(raw).hexdigest() if len(raw) <= MAX_OPERATION_BYTES else None
        except (OSError, LocalDockError, DistributionRefused):
            if callable(getattr(client, "source_facts", None)):
                raise LocalDockError("provenance-unavailable") from None
            revision = None
        facts = {"capability_revision": revision}
        if callable(getattr(client, "source_facts", None)):
            facts = client.source_facts(record["application"], capability_root=ROOT)
            if set(facts) != {"capability_revision", "adapter_sha256", "compose_sha256"} or any(
                not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None for value in facts.values()
            ):
                raise LocalDockError("provenance-unavailable")
        record = self.ops.update(record["id"], **facts)
        _private_dir(Path(record["output_dir"]))
        client.accepted(record)
        self.ops.update(record["id"], provenance={"receipt_path": None, "frame_address": None, "verification": "pending"})

    def _exhaust_phase(self, op_id: str, phase: str, payload: dict[str, Any]) -> None:
        record = self.ops.get(op_id)
        if record["kind"] != "job":
            return
        try:
            client = self._exhaust()
            if client is not None:
                client.phase(op_id, phase, record)
        except Exception:
            self.ops.update(op_id, provenance={"verification": "pending", "receipt_path": None, "frame_address": None})

    def _receipt_provenance(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            client = self._exhaust()
            if client is None:
                return {"receipt_path": None, "frame_address": None, "verification": "unavailable"}
            provenance = client.terminal(record)
            if (
                not isinstance(provenance, dict) or provenance.get("verification") != "structural-only"
                or not isinstance(provenance.get("receipt_path"), str) or not provenance["receipt_path"]
                or not isinstance(provenance.get("frame_address"), dict)
                or not isinstance(provenance["frame_address"].get("space"), str)
                or re.fullmatch(r"[a-f0-9]{64}", str(provenance["frame_address"].get("hash", ""))) is None
            ):
                raise ValueError("Invalid receipt result.")
            return provenance
        except Exception:
            return {"receipt_path": None, "frame_address": None, "verification": "pending"}

    def _finish_job(self, op_id: str, fields: dict[str, Any] | None = None) -> None:
        with self.ops.lock:
            record = self.ops.get(op_id)
            if record["status"] in TERMINAL:
                return
            staged = record.get("pending_terminal")
            if staged is None:
                if fields is None:
                    return
                staged = dict(fields)
                if record.get("cancel_requested") and staged["status"] in ("succeeded", "partial"):
                    staged.update(status="cancelled", phase="cancelled", error=safe_error("cancelled"))
                record = self.ops.update(
                    op_id, pending_terminal=staged, status="running", phase="persisting_receipt",
                    phase_detail="Native work finished; saving its canonical receipt.", updated_at=_now(),
                )
            candidate = {key: value for key, value in record.items() if key != "pending_terminal"}
            candidate.update(staged)
        provenance = self._receipt_provenance(candidate)
        with self.ops.lock:
            current = self.ops.get(op_id)
            if current.get("pending_terminal") == staged:
                for app in current.get("scope", []):
                    self.runtime.state.setdefault("last_used", {})[app] = time.time()
                    if app in self.runtime.state["auto_started"]:
                        self.runtime.state["auto_started"][app] = time.time()
                self.ops.update(op_id, **staged, provenance=provenance, pending_terminal=None, phase_detail=None)

    def _recover_finalization(self, record: dict[str, Any]) -> None:
        """Resume only receipt/publication work after a lost worker or process."""
        op_id = record["id"]
        with self.runtime.lock:
            if op_id in self.runtime.pending or self.runtime.queues["work"].full():
                return
            self.runtime.pending[op_id] = {
                "scope": record.get("scope", [record["application"]]), "control": False, "executing": True,
            }

            def finish():
                try:
                    self._finish_job(op_id)
                finally:
                    with self.runtime.lock:
                        self.runtime.pending.pop(op_id, None)

            self.runtime.queues["work"].put_nowait(finish)
            self._workers()

    def _terminal(self, op_id: str) -> None:
        record = self.ops.get(op_id)
        if record["kind"] != "job" or record["status"] not in TERMINAL or record.get("provenance", {}).get("verification") == "structural-only":
            return
        provenance = self._receipt_provenance(record)
        with self.ops.lock:
            if self.ops.get(op_id).get("provenance", {}).get("verification") != "structural-only":
                self.ops.update(op_id, provenance=provenance)

    def bundle(self, op_id: str) -> dict[str, Any]:
        record = self.ops.get(op_id)
        if record["kind"] != "job" or record["status"] not in TERMINAL:
            raise LocalDockError("not-supported", "Collect the completed job before bundling its outputs.")
        self._terminal(op_id)
        record = self.ops.get(op_id)
        if record.get("provenance", {}).get("verification") != "structural-only":
            raise LocalDockError("provenance-unavailable", "The terminal receipt is not yet available.")
        try:
            capsule = self._exhaust().bundle(record, ROOT)
        except Exception:
            raise LocalDockError("bundle-unavailable", "A complete capsule could not be verified.") from None
        return {**self.describe(record), "capsule": capsule}

    def idle_down(self, now: float | None = None) -> list[dict[str, Any]]:
        runtime = self.runtime
        with runtime.lock:
            if runtime.quiescing or runtime.state["stopping"] or runtime.state.get("detach_paused"):
                return []
            if now is None and time.monotonic() - runtime.last_idle_check < 30:
                return []
            runtime.last_idle_check = time.monotonic()
            current = time.time() if now is None else now
            required = {app for pending in runtime.pending.values() for app in pending["scope"]}
            required.update(runtime.state.get("idle_protected", []))
            expired = [
                app for app, used in runtime.state["auto_started"].items()
                if app not in required and current - used >= IDLE_SECONDS
            ]
            if not expired:
                return []
            return [self._submit(
                "lifecycle", expired[0], "idle-down", {}, expired, self._stop_scope,
                control=True, wait_seconds=0,
            )]


def _outputs(result: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if {"path", "sha256", "bytes"} <= set(value):
                found.append({key: value[key] for key in ("path", "bytes", "sha256")})
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(result)
    return found[:20]
