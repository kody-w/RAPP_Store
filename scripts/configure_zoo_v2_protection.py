#!/usr/bin/env python3
"""Configure and fail-closed verify the Zoo v2 main-branch merge barrier."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Callable


STATUS_CONTEXT = "Zoo v2 current-main"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ApiCall = Callable[[str, str, dict | None], object]


class ProtectionError(RuntimeError):
    """A branch-protection configuration or verification refusal."""


def protection_payload() -> dict:
    return {
        "required_status_checks": {
            "strict": True,
            "contexts": [STATUS_CONTEXT],
        },
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "required_approving_review_count": 1,
            "require_last_push_approval": True,
        },
        "restrictions": None,
        "required_conversation_resolution": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "block_creations": False,
        "lock_branch": False,
        "allow_fork_syncing": True,
    }


def _gh_api(method: str, endpoint: str, payload: dict | None = None) -> object:
    command = [
        "gh",
        "api",
        "--method",
        method,
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2022-11-28",
        endpoint,
    ]
    input_text = None
    if payload is not None:
        command.extend(["--input", "-"])
        input_text = json.dumps(payload, sort_keys=True)
    result = subprocess.run(
        command,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ProtectionError(f"E_PROTECTION_API: {method} {endpoint}: {detail}")
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError as exc:
        raise ProtectionError(
            f"E_PROTECTION_API: invalid JSON from {method} {endpoint}: {exc}"
        ) from exc


def verify_settings(settings: object) -> None:
    if not isinstance(settings, dict):
        raise ProtectionError("E_PROTECTION_VERIFY: expected a protection object")

    checks = settings.get("required_status_checks")
    contexts = checks.get("contexts") if isinstance(checks, dict) else None
    if (
        not isinstance(checks, dict)
        or checks.get("strict") is not True
        or contexts != [STATUS_CONTEXT]
    ):
        raise ProtectionError(
            "E_PROTECTION_VERIFY: strict required status context is not exact"
        )

    reviews = settings.get("required_pull_request_reviews")
    if (
        not isinstance(reviews, dict)
        or reviews.get("dismiss_stale_reviews") is not True
        or reviews.get("require_code_owner_reviews") is not False
        or reviews.get("required_approving_review_count") != 1
        or reviews.get("require_last_push_approval") is not True
    ):
        raise ProtectionError(
            "E_PROTECTION_VERIFY: required pull-request review policy is not exact"
        )
    if settings.get("restrictions") is not None:
        raise ProtectionError(
            "E_PROTECTION_VERIFY: push restrictions are not the configured value"
        )

    required_flags = {
        "enforce_admins": True,
        "required_conversation_resolution": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "block_creations": False,
        "lock_branch": False,
        "allow_fork_syncing": True,
    }
    for name, expected in required_flags.items():
        value = settings.get(name)
        actual = value.get("enabled") if isinstance(value, dict) else None
        if actual is not expected:
            raise ProtectionError(
                f"E_PROTECTION_VERIFY: {name}.enabled is not {str(expected).lower()}"
            )


def configure_and_verify(repository: str, api_call: ApiCall = _gh_api) -> None:
    _validate_repository(repository)
    endpoint = f"repos/{repository}/branches/main/protection"
    api_call("PUT", endpoint, protection_payload())
    verify_settings(api_call("GET", endpoint, None))


def verify(repository: str, api_call: ApiCall = _gh_api) -> None:
    _validate_repository(repository)
    endpoint = f"repos/{repository}/branches/main/protection"
    verify_settings(api_call("GET", endpoint, None))


def _validate_repository(repository: str) -> None:
    if not REPOSITORY_RE.fullmatch(repository):
        raise ProtectionError("E_REPOSITORY: expected owner/repo")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("verify", "configure-verify"),
    )
    parser.add_argument("--repository", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "configure-verify":
            configure_and_verify(args.repository)
        else:
            verify(args.repository)
    except ProtectionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"main protection verified for {args.repository}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
