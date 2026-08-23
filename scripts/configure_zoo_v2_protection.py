#!/usr/bin/env python3
"""Additively configure and audit the Zoo v2 GitHub protection prerequisites."""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable


STATUS_CONTEXT = "Zoo v2 current-main"
TAG_RULESET_NAME = "Zoo v2 generation tags"
TAG_PATTERN = "refs/tags/zoo-v2-generation-*"
TAG_RULE_TYPES = frozenset({"update", "deletion", "non_fast_forward"})
AUDIT_SCHEMA = "rapp-zoo-v2-protection-audit/1.0"
AUDIT_PATH = Path(".github/zoo-v2-protection-audit.json")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ApiCall = Callable[[str, str, dict | None], object]


class ProtectionError(RuntimeError):
    """A repository-protection configuration or verification refusal."""


def _enabled(settings: dict, name: str, default: bool = False) -> bool:
    value = settings.get(name)
    if isinstance(value, dict):
        return value.get("enabled") is True
    if isinstance(value, bool):
        return value
    return default


def _configured_flag(settings: dict, name: str, default: bool = False) -> bool:
    if name not in settings or settings.get(name) is None:
        return default
    value = settings[name]
    if isinstance(value, bool):
        return value
    if (
        isinstance(value, dict)
        and isinstance(value.get("enabled"), bool)
    ):
        return value["enabled"]
    raise ProtectionError(f"E_PROTECTION_CONFIG: malformed {name} flag")


def _names(values: object, *keys: str) -> list[str]:
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        if isinstance(value, str):
            name = value
        elif isinstance(value, dict):
            name = next(
                (
                    value[key]
                    for key in keys
                    if isinstance(value.get(key), (str, int))
                ),
                None,
            )
        else:
            name = None
        if name is not None and str(name) not in result:
            result.append(str(name))
    return result


def _string_list(value: object, error: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProtectionError(error)
    return list(dict.fromkeys(value))


def _actor_restrictions(value: object) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProtectionError("E_PROTECTION_CONFIG: malformed actor restrictions")
    return {
        "users": _names(value.get("users"), "login", "name"),
        "teams": _names(value.get("teams"), "slug", "name"),
        "apps": _names(value.get("apps"), "slug", "name", "id"),
    }


def protection_payload(existing: object) -> dict:
    """Build a full PUT payload that preserves existing safeguards and adds minima."""
    if not isinstance(existing, dict):
        raise ProtectionError("E_PROTECTION_CONFIG: expected existing protection object")

    current_checks = existing.get("required_status_checks")
    if current_checks is not None and not isinstance(current_checks, dict):
        raise ProtectionError("E_PROTECTION_CONFIG: malformed required status checks")
    current_checks = current_checks or {}
    contexts = _string_list(
        current_checks.get("contexts"),
        "E_PROTECTION_CONFIG: malformed status contexts",
    )
    checks = []
    raw_checks = current_checks.get("checks", [])
    if raw_checks is not None and not isinstance(raw_checks, list):
        raise ProtectionError("E_PROTECTION_CONFIG: malformed status check records")
    for check in raw_checks or []:
        if not isinstance(check, dict) or not isinstance(check.get("context"), str):
            raise ProtectionError("E_PROTECTION_CONFIG: malformed status check record")
        item = {"context": check["context"]}
        if isinstance(check.get("app_id"), int):
            item["app_id"] = check["app_id"]
        if item not in checks:
            checks.append(item)
    if STATUS_CONTEXT not in contexts:
        contexts.append(STATUS_CONTEXT)

    current_reviews = existing.get("required_pull_request_reviews")
    if current_reviews is not None and not isinstance(current_reviews, dict):
        raise ProtectionError("E_PROTECTION_CONFIG: malformed pull-request reviews")
    current_reviews = current_reviews or {}
    review_count = current_reviews.get("required_approving_review_count", 0)
    if not isinstance(review_count, int) or isinstance(review_count, bool):
        raise ProtectionError("E_PROTECTION_CONFIG: malformed approving review count")
    reviews = {
        "dismiss_stale_reviews": True,
        "require_code_owner_reviews": (
            current_reviews.get("require_code_owner_reviews") is True
        ),
        "required_approving_review_count": max(1, review_count),
        "require_last_push_approval": True,
    }
    for name in ("dismissal_restrictions", "bypass_pull_request_allowances"):
        if name in current_reviews:
            reviews[name] = _actor_restrictions(current_reviews.get(name)) or {
                "users": [],
                "teams": [],
                "apps": [],
            }

    payload = {
        "required_status_checks": {
            "strict": True,
            "contexts": contexts,
            "checks": checks,
        },
        "enforce_admins": True,
        "required_pull_request_reviews": reviews,
        "restrictions": _actor_restrictions(existing.get("restrictions")),
        "required_conversation_resolution": True,
        "required_linear_history": _configured_flag(
            existing, "required_linear_history"
        ),
        "allow_force_pushes": False,
        "allow_deletions": False,
        "block_creations": _configured_flag(existing, "block_creations"),
        "lock_branch": _configured_flag(existing, "lock_branch"),
        "allow_fork_syncing": _configured_flag(existing, "allow_fork_syncing"),
    }
    return payload


def _status_contexts(settings: dict) -> set[str]:
    checks = settings.get("required_status_checks")
    if not isinstance(checks, dict):
        return set()
    contexts = set(_names(checks.get("contexts"), "context"))
    contexts.update(_names(checks.get("checks"), "context"))
    return contexts


def verify_settings(settings: object) -> None:
    """Verify required minima while accepting stricter/superset protection."""
    if not isinstance(settings, dict):
        raise ProtectionError("E_PROTECTION_VERIFY: expected a protection object")

    checks = settings.get("required_status_checks")
    if isinstance(checks, dict):
        contexts_value = checks.get("contexts")
        checks_value = checks.get("checks")
        if (
            contexts_value is not None
            and (
                not isinstance(contexts_value, list)
                or any(not isinstance(item, str) for item in contexts_value)
            )
        ) or (
            checks_value is not None
            and (
                not isinstance(checks_value, list)
                or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("context"), str)
                    for item in checks_value
                )
            )
        ):
            raise ProtectionError(
                "E_PROTECTION_VERIFY: malformed required status checks"
            )
    if (
        not isinstance(checks, dict)
        or checks.get("strict") is not True
        or STATUS_CONTEXT not in _status_contexts(settings)
    ):
        raise ProtectionError(
            "E_PROTECTION_VERIFY: strict Zoo v2 status context is missing"
        )

    reviews = settings.get("required_pull_request_reviews")
    count = reviews.get("required_approving_review_count") if isinstance(reviews, dict) else None
    if (
        not isinstance(reviews, dict)
        or reviews.get("dismiss_stale_reviews") is not True
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 1
        or reviews.get("require_last_push_approval") is not True
    ):
        raise ProtectionError(
            "E_PROTECTION_VERIFY: pull-request review minima are not enforced"
        )

    required_flags = {
        "enforce_admins": True,
        "required_conversation_resolution": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
    }
    for name, expected in required_flags.items():
        if _enabled(settings, name, default=not expected) is not expected:
            raise ProtectionError(
                f"E_PROTECTION_VERIFY: {name}.enabled is not {str(expected).lower()}"
            )


def _ruleset_payload(existing: object | None = None) -> dict:
    if existing is not None and not isinstance(existing, dict):
        raise ProtectionError("E_RULESET_CONFIG: expected a ruleset object")
    existing = existing or {}
    target = existing.get("target", "tag")
    if target != "tag":
        raise ProtectionError(
            f"E_RULESET_CONFIG: named ruleset target is {target!r}, expected 'tag'"
        )
    conditions = existing.get("conditions", {})
    if not isinstance(conditions, dict):
        raise ProtectionError("E_RULESET_CONFIG: malformed ruleset conditions")
    conditions = json.loads(json.dumps(conditions))
    ref_name = conditions.get("ref_name", {})
    if not isinstance(ref_name, dict):
        raise ProtectionError("E_RULESET_CONFIG: malformed ref-name condition")
    includes = _string_list(
        ref_name.get("include"),
        "E_RULESET_CONFIG: malformed ref-name includes",
    )
    excludes = [
        value
        for value in _string_list(
            ref_name.get("exclude"),
            "E_RULESET_CONFIG: malformed ref-name excludes",
        )
        if value != TAG_PATTERN
    ]
    if TAG_PATTERN not in includes:
        includes.append(TAG_PATTERN)
    conditions["ref_name"] = {"include": includes, "exclude": excludes}

    rules = existing.get("rules", [])
    if not isinstance(rules, list):
        raise ProtectionError("E_RULESET_CONFIG: malformed rules")
    if any(
        not isinstance(rule, dict) or not isinstance(rule.get("type"), str)
        for rule in rules
    ):
        raise ProtectionError("E_RULESET_CONFIG: malformed rule record")
    rules = json.loads(json.dumps(rules))
    present = {
        rule.get("type")
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("type"), str)
    }
    for rule_type in sorted(TAG_RULE_TYPES - present):
        rules.append({"type": rule_type})

    payload = {
        "name": TAG_RULESET_NAME,
        "target": "tag",
        "enforcement": "active",
        "conditions": conditions,
        "rules": rules,
    }
    bypass_actors = existing.get("bypass_actors")
    if bypass_actors is not None:
        if not isinstance(bypass_actors, list):
            raise ProtectionError("E_RULESET_CONFIG: malformed bypass actors")
        payload["bypass_actors"] = json.loads(json.dumps(bypass_actors))
    return payload


def verify_tag_ruleset(ruleset: object) -> None:
    if not isinstance(ruleset, dict):
        raise ProtectionError("E_RULESET_VERIFY: expected a ruleset object")
    if ruleset.get("name") != TAG_RULESET_NAME:
        raise ProtectionError("E_RULESET_VERIFY: named tag ruleset is missing")
    if not isinstance(ruleset.get("id"), int) or isinstance(ruleset.get("id"), bool):
        raise ProtectionError("E_RULESET_VERIFY: tag ruleset has no numeric id")
    if ruleset.get("target") != "tag" or ruleset.get("enforcement") != "active":
        raise ProtectionError("E_RULESET_VERIFY: tag ruleset is not active")
    conditions = ruleset.get("conditions")
    ref_name = conditions.get("ref_name") if isinstance(conditions, dict) else None
    includes = _string_list(
        ref_name.get("include") if isinstance(ref_name, dict) else None,
        "E_RULESET_VERIFY: malformed ref-name includes",
    )
    excludes = _string_list(
        ref_name.get("exclude") if isinstance(ref_name, dict) else None,
        "E_RULESET_VERIFY: malformed ref-name excludes",
    )
    probe = "refs/tags/zoo-v2-generation-verification-probe"
    conflicting_excludes = [
        value
        for value in excludes
        if value == "~ALL" or fnmatch.fnmatchcase(probe, value)
    ]
    if TAG_PATTERN not in includes or conflicting_excludes:
        raise ProtectionError(
            "E_RULESET_VERIFY: generation tag pattern is not unconditionally included"
        )
    rules = ruleset.get("rules")
    if not isinstance(rules, list) or any(
        not isinstance(rule, dict) or not isinstance(rule.get("type"), str)
        for rule in rules
    ):
        raise ProtectionError("E_RULESET_VERIFY: malformed tag rules")
    present = {
        rule.get("type")
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("type"), str)
    }
    missing = sorted(TAG_RULE_TYPES - present)
    if missing:
        raise ProtectionError(
            "E_RULESET_VERIFY: missing required tag rule(s): " + ", ".join(missing)
        )


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


def _named_ruleset(
    repository: str,
    api_call: ApiCall,
) -> dict | None:
    summaries = api_call(
        "GET",
        f"repos/{repository}/rulesets?includes_parents=false",
        None,
    )
    if not isinstance(summaries, list):
        raise ProtectionError("E_RULESET_API: expected a ruleset array")
    matches = [
        item
        for item in summaries
        if isinstance(item, dict) and item.get("name") == TAG_RULESET_NAME
    ]
    if len(matches) > 1:
        raise ProtectionError("E_RULESET_API: multiple named tag rulesets exist")
    if not matches:
        return None
    ruleset_id = matches[0].get("id")
    if not isinstance(ruleset_id, int) or isinstance(ruleset_id, bool):
        raise ProtectionError("E_RULESET_API: named ruleset has no numeric id")
    detail = api_call("GET", f"repos/{repository}/rulesets/{ruleset_id}", None)
    if not isinstance(detail, dict):
        raise ProtectionError("E_RULESET_API: expected a ruleset object")
    return detail


def _configure_ruleset(repository: str, api_call: ApiCall) -> dict:
    existing = _named_ruleset(repository, api_call)
    payload = _ruleset_payload(existing)
    if existing is None:
        created = api_call("POST", f"repos/{repository}/rulesets", payload)
        if (
            not isinstance(created, dict)
            or not isinstance(created.get("id"), int)
            or isinstance(created.get("id"), bool)
        ):
            raise ProtectionError("E_RULESET_API: create response has no numeric id")
        ruleset_id = created["id"]
    else:
        ruleset_id = existing.get("id")
        if not isinstance(ruleset_id, int) or isinstance(ruleset_id, bool):
            raise ProtectionError("E_RULESET_API: named ruleset has no numeric id")
        api_call("PUT", f"repos/{repository}/rulesets/{ruleset_id}", payload)
    verified = api_call("GET", f"repos/{repository}/rulesets/{ruleset_id}", None)
    verify_tag_ruleset(verified)
    return verified


def _audit_document(repository: str, settings: dict, ruleset: dict) -> dict:
    reviews = settings["required_pull_request_reviews"]
    return {
        "schema": AUDIT_SCHEMA,
        "repository": repository,
        "verified_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "branch": "main",
        "branch_protection": {
            "strict": True,
            "required_status_contexts": sorted(_status_contexts(settings)),
            "required_approving_review_count": reviews["required_approving_review_count"],
            "dismiss_stale_reviews": True,
            "require_last_push_approval": True,
            "enforce_admins": True,
            "required_conversation_resolution": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
        },
        "tag_ruleset": {
            "id": ruleset.get("id"),
            "name": TAG_RULESET_NAME,
            "target": "tag",
            "enforcement": "active",
            "include": TAG_PATTERN,
            "required_rules": sorted(TAG_RULE_TYPES),
        },
    }


def verify_audit(audit: object, repository: str) -> None:
    if not isinstance(audit, dict):
        raise ProtectionError("E_PROTECTION_AUDIT: expected an audit object")
    verified_at = audit.get("verified_at")
    if (
        audit.get("schema") != AUDIT_SCHEMA
        or audit.get("repository") != repository
        or audit.get("branch") != "main"
        or not isinstance(verified_at, str)
    ):
        raise ProtectionError("E_PROTECTION_AUDIT: identity fields are absent or malformed")
    try:
        timestamp = dt.datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtectionError(
            "E_PROTECTION_AUDIT: verified_at is not an ISO-8601 timestamp"
        ) from exc
    if timestamp.tzinfo is None:
        raise ProtectionError(
            "E_PROTECTION_AUDIT: verified_at must include a timezone"
        )
    branch = audit.get("branch_protection")
    if not isinstance(branch, dict):
        raise ProtectionError("E_PROTECTION_AUDIT: branch verification is absent")
    contexts = branch.get("required_status_contexts")
    count = branch.get("required_approving_review_count")
    required_branch = {
        "strict": True,
        "dismiss_stale_reviews": True,
        "require_last_push_approval": True,
        "enforce_admins": True,
        "required_conversation_resolution": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
    }
    if (
        not isinstance(contexts, list)
        or STATUS_CONTEXT not in contexts
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 1
        or any(branch.get(key) is not value for key, value in required_branch.items())
    ):
        raise ProtectionError("E_PROTECTION_AUDIT: branch minima are not verified")
    ruleset = audit.get("tag_ruleset")
    required_rules = ruleset.get("required_rules") if isinstance(ruleset, dict) else None
    if (
        not isinstance(ruleset, dict)
        or not isinstance(ruleset.get("id"), int)
        or isinstance(ruleset.get("id"), bool)
        or ruleset.get("name") != TAG_RULESET_NAME
        or ruleset.get("target") != "tag"
        or ruleset.get("enforcement") != "active"
        or ruleset.get("include") != TAG_PATTERN
        or not isinstance(required_rules, list)
        or any(not isinstance(rule, str) for rule in required_rules)
        or not TAG_RULE_TYPES.issubset(set(required_rules))
    ):
        raise ProtectionError("E_PROTECTION_AUDIT: tag ruleset minima are not verified")


def verify_audit_file(path: Path, repository: str) -> dict:
    try:
        audit = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ProtectionError(
            f"E_PROTECTION_AUDIT: missing {path}; an administrator must run "
            "configure-verify and commit its audit before release"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtectionError(f"E_PROTECTION_AUDIT: cannot read {path}: {exc}") from exc
    verify_audit(audit, repository)
    return audit


def _write_audit(path: Path, audit: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")


def configure_and_verify(repository: str, api_call: ApiCall = _gh_api) -> dict:
    _validate_repository(repository)
    endpoint = f"repos/{repository}/branches/main/protection"
    existing = api_call("GET", endpoint, None)
    api_call("PUT", endpoint, protection_payload(existing))
    settings = api_call("GET", endpoint, None)
    verify_settings(settings)
    ruleset = _configure_ruleset(repository, api_call)
    return _audit_document(repository, settings, ruleset)


def verify(repository: str, api_call: ApiCall = _gh_api) -> dict:
    _validate_repository(repository)
    endpoint = f"repos/{repository}/branches/main/protection"
    settings = api_call("GET", endpoint, None)
    verify_settings(settings)
    ruleset = _named_ruleset(repository, api_call)
    verify_tag_ruleset(ruleset)
    return _audit_document(repository, settings, ruleset)


def _validate_repository(repository: str) -> None:
    if not REPOSITORY_RE.fullmatch(repository):
        raise ProtectionError("E_REPOSITORY: expected owner/repo")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("verify", "configure-verify", "verify-audit"),
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH)
    args = parser.parse_args(argv)
    try:
        if args.command == "configure-verify":
            audit = configure_and_verify(args.repository)
        elif args.command == "verify":
            audit = verify(args.repository)
        else:
            audit = verify_audit_file(args.audit, args.repository)
        if args.audit_output:
            _write_audit(args.audit_output, audit)
    except ProtectionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
