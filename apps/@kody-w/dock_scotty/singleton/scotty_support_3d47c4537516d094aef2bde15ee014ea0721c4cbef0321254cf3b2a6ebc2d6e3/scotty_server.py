"""Verify and exec the unchanged CURRENT Grail. This module implements no server."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scotty_distribution import (
    DistributionRefused,
    canonical,
    read_regular,
    verify_capability,
    verify_grail,
)

GRAIL_IMPORTS = ("flask", "flask_cors", "requests", "dotenv", "pyzipper")


def launch_configuration(
    grail_root: Path,
    *,
    port: int = 7071,
    lan: bool = False,
    allowed_hosts: Sequence[str] = (),
    work_scope_file: Path | None = None,
    native_auth_approved: bool = False,
    nas_snapshot_file: Path | None = None,
) -> tuple[list[str], dict[str, str], dict[str, Any]]:
    root = Path(os.path.abspath(grail_root))
    info = os.stat(root, follow_symlinks=False)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
        or type(port) is not int
        or not 1 <= port <= 65535
    ):
        raise DistributionRefused(
            "an existing owner-only private Grail root and valid port are required"
        )
    verified = verify_grail(root)
    capability = verify_capability(root)
    missing = [name for name in GRAIL_IMPORTS if importlib.util.find_spec(name) is None]
    if missing:
        raise DistributionRefused(
            "install the declared Grail dependency closure before launch"
        )
    try:
        dotenv_version = importlib.metadata.version("python-dotenv").split(".")
    except importlib.metadata.PackageNotFoundError:
        raise DistributionRefused(
            "python-dotenv distribution metadata is missing"
        ) from None
    if tuple(int(part) for part in dotenv_version[:2]) < (1, 2):
        raise DistributionRefused(
            "dedicated launch requires python-dotenv >=1.2 for explicit dotenv disablement"
        )
    agent_files = {path.name for path in (root / "agents").glob("*_agent.py")}
    if agent_files != {"basic_agent.py", "scotty_agent.py"}:
        raise DistributionRefused(
            "dedicated Scotty launch requires only its reviewed flat agent set"
        )
    if (root / ".env").exists():
        raise DistributionRefused(
            "dedicated launch uses explicit environment, not an inherited .env"
        )
    if not native_auth_approved and any(
        (root / name).exists() or (root / name).is_symlink()
        for name in (".copilot_token", ".copilot_session", ".copilot_pending")
    ):
        raise DistributionRefused(
            "native authenticated launch requires a separately approved Grail credential/network workflow"
        )
    if lan:
        secret = read_regular(root / ".brainstem_secret", private=True).strip()
        if not 16 <= len(secret) <= 8192:
            raise DistributionRefused(
                "provision the dedicated native Grail LAN secret privately"
            )
    if work_scope_file is not None:
        from scotty_work_tree import from_scope_file

        from_scope_file(work_scope_file)
    if nas_snapshot_file is not None and not nas_snapshot_file.is_absolute():
        raise DistributionRefused(
            "NAS snapshot selection requires an explicit absolute file path"
        )
    hosts = []
    for host in allowed_hosts:
        if (
            not isinstance(host, str)
            or not host
            or len(host) > 253
            or any(character.isspace() for character in host)
            or any(character in host for character in "/@?#,")
        ):
            raise DistributionRefused("invalid explicit native Grail allowed host")
        hosts.append(host)
    env = {
        "PATH": "/nonexistent",
        "HOME": str(root),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHON_DOTENV_DISABLED": "1",
        "GITHUB_TOKEN": "",
        "GH_TOKEN": "",
        "GITHUB_MODEL": "auto",
        "AGENTS_PATH": str(root / "agents"),
        "SOUL_PATH": str(root / "soul.md"),
        "PORT": str(port),
        "BRAINSTEM_LAN_MODE": "true" if lan else "false",
        "BRAINSTEM_ALLOWED_HOSTS": ",".join(hosts),
        "VOICE_MODE": "false",
        "VOICE_ZIP_PASSWORD": "",
        "SCOTTY_WORK_SCOPE_FILE": str(work_scope_file) if work_scope_file else "",
        "SCOTTY_NAS_SNAPSHOT_FILE": str(nas_snapshot_file) if nas_snapshot_file else "",
    }
    report = {
        "status": "verified",
        "engine": "current-grail",
        "grail": verified,
        "capability": capability,
        "launch": "unchanged-brainstem.py",
        "provider": "github-copilot-api",
        "inference": (
            "native-auth-state-explicitly-acknowledged-not-a-budget-grant"
            if native_auth_approved
            else "unavailable-without-separately-approved-native-authentication"
        ),
        "application_provider_calls": "disabled-by-capability",
        "work_tree_adapter": "explicit" if work_scope_file else "not_configured",
        "nas_snapshot": "explicit-file-consumer"
        if nas_snapshot_file
        else "not_configured",
        "experimental_worker_state": "not-opened-or-migrated",
        "bind": "0.0.0.0" if lan else "127.0.0.1",
        "port": port,
    }
    return [sys.executable, "-I", "-B", "-u", str(root / "brainstem.py")], env, report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--grail-root", required=True, type=Path)
    parser.add_argument("--port", type=int, default=7071)
    parser.add_argument("--lan", action="store_true")
    parser.add_argument("--allowed-host", action="append", default=[])
    parser.add_argument("--work-scope-file", type=Path)
    parser.add_argument("--nas-snapshot-file", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--native-auth-approved",
        action="store_true",
        help="Existing Grail-owned auth/network use was approved externally; not a spend grant.",
    )
    args = parser.parse_args(argv)
    try:
        command, env, report = launch_configuration(
            args.grail_root,
            port=args.port,
            lan=args.lan,
            allowed_hosts=args.allowed_host,
            work_scope_file=args.work_scope_file,
            native_auth_approved=args.native_auth_approved,
            nas_snapshot_file=args.nas_snapshot_file,
        )
        if args.check:
            print(canonical(report).decode(), end="")
            return 0
        os.chdir(Path(os.path.abspath(args.grail_root)))
        os.execve(command[0], command, env)
    except (DistributionRefused, OSError, ValueError):
        print('{"status":"refused","code":"current-grail-launch-preflight-failed"}')
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
