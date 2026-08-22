#!/usr/bin/env python3
"""Deterministic control plane for the RAPP Zoo v2 prototype store.

GitHub Issues are parsed as inert JSON data. This module never imports,
executes, or shells out to submitted artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Callable


DISCOVERY_SCHEMA = "rapp-zoo-store-discovery/2.0"
GENERATION_SCHEMA = "rapp-zoo-store-generation/2.0"
COMMAND_SCHEMA = "rapp-zoo-store-command/2.0"
SUMMON_SCHEMA = "rapp-zoo-prototype-summon/2.0"

RAW_URL_RE = re.compile(
    r"^https://raw\.githubusercontent\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/"
    r"(?P<commit>[0-9a-f]{40})/(?P<path>[^?#]+)$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
RAPPID_RE = re.compile(r"^rappid:@[a-z0-9](?:[a-z0-9-]{0,38})/[a-z][a-z0-9-]{2,63}:[0-9a-f]{64}$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
TITLE_RE = re.compile(r"^\[ZOO V2 (CREATE|UPDATE|DEPRECATE)\]\s+([a-z][a-z0-9-]{2,63})\s*$")

Fetch = Callable[[str], bytes]


class StoreError(ValueError):
    """A stable, user-facing validation error."""


def canonical_json(data: object) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "RAPP-Store-Zoo-v2-validator/2.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise StoreError(f"E_FETCH: could not fetch {url}: {exc}") from exc


def parse_allowlist(value: str) -> set[str]:
    actors = {part.strip().lower() for part in value.split(",") if part.strip()}
    if not actors:
        raise StoreError("E_EMPTY_ALLOWLIST: at least one eligible GitHub actor is required")
    return actors


def validate_actor(actor: str, allowlist: set[str]) -> None:
    if actor.lower() not in allowlist:
        raise StoreError(f"E_ACTOR_NOT_ALLOWED: @{actor} is not eligible for Zoo v2 catalog CRUD")


def validate_pinned_raw_url(url: object, field: str) -> re.Match[str]:
    if not isinstance(url, str):
        raise StoreError(f"E_PINNED_URL: {field} must be a string")
    match = RAW_URL_RE.fullmatch(url)
    if not match:
        raise StoreError(
            f"E_PINNED_URL: {field} must be a raw.githubusercontent.com URL "
            "with an exact lowercase 40-character commit SHA"
        )
    parts = match.group("path").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise StoreError(f"E_PINNED_URL: {field} contains an unsafe path segment")
    return match


def validate_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise StoreError(f"E_SHA256: {field} must be exactly 64 lowercase hexadecimal characters")
    return value


def verified_fetch(url: str, expected_sha256: str, field: str, fetcher: Fetch) -> bytes:
    blob = fetcher(url)
    actual = sha256_bytes(blob)
    if actual != expected_sha256:
        raise StoreError(
            f"E_HASH_DRIFT: {field} expected {expected_sha256}, fetched {actual}"
        )
    return blob


def _require_exact_keys(value: dict, required: set[str], optional: set[str], field: str) -> None:
    missing = sorted(required - value.keys())
    extra = sorted(value.keys() - required - optional)
    if missing:
        raise StoreError(f"E_SCHEMA: {field} is missing {', '.join(missing)}")
    if extra:
        raise StoreError(f"E_SCHEMA: {field} has unknown fields: {', '.join(extra)}")


def validate_license(license_data: object, fetcher: Fetch, *, network: bool = True) -> None:
    if not isinstance(license_data, dict):
        raise StoreError("E_LICENSE_REQUIRED: license must include SPDX and pinned evidence")
    _require_exact_keys(
        license_data,
        {"spdx", "evidence_url", "evidence_sha256"},
        set(),
        "license",
    )
    spdx = license_data["spdx"]
    if not isinstance(spdx, str) or not re.match(r"^MIT(?:\s+(?:OR|AND)\s+[A-Za-z0-9.+-]+)*$", spdx):
        raise StoreError("E_LICENSE_NOT_MIT_FIRST: SPDX expression must begin with MIT")
    url = license_data["evidence_url"]
    expected = validate_hash(license_data["evidence_sha256"], "license.evidence_sha256")
    validate_pinned_raw_url(url, "license.evidence_url")
    if network:
        evidence = verified_fetch(url, expected, "license evidence", fetcher)
        text = evidence.decode("utf-8", errors="replace")
        markers = ("MIT License", "Permission is hereby granted", "THE SOFTWARE IS PROVIDED")
        if not all(marker in text for marker in markers):
            raise StoreError("E_LICENSE_EVIDENCE: pinned evidence is not recognizable MIT license text")


def validate_prototype(
    prototype: object,
    fetcher: Fetch = fetch_bytes,
    *,
    network: bool = True,
) -> dict:
    if not isinstance(prototype, dict):
        raise StoreError("E_SCHEMA: prototype must be an object")
    _require_exact_keys(
        prototype,
        {
            "id", "name", "version", "summary", "status", "artifact",
            "license", "wire_contract", "identity", "ecosystem_acceptance",
            "external_blockers",
        },
        set(),
        "prototype",
    )
    prototype_id = prototype["id"]
    if not isinstance(prototype_id, str) or not ID_RE.fullmatch(prototype_id):
        raise StoreError("E_ID: prototype.id must match ^[a-z][a-z0-9-]{2,63}$")
    if not isinstance(prototype["name"], str) or not (1 <= len(prototype["name"]) <= 100):
        raise StoreError("E_SCHEMA: prototype.name must be 1-100 characters")
    if not isinstance(prototype["summary"], str) or not (1 <= len(prototype["summary"]) <= 500):
        raise StoreError("E_SCHEMA: prototype.summary must be 1-500 characters")
    if not isinstance(prototype["version"], str) or not SEMVER_RE.fullmatch(prototype["version"]):
        raise StoreError("E_VERSION: prototype.version must be strict MAJOR.MINOR.PATCH")
    if prototype["status"] != "prototype":
        raise StoreError("E_PROTOTYPE_ONLY: live Zoo v2 entries must have status 'prototype'")
    if prototype["wire_contract"] != "RAPP/1":
        raise StoreError("E_WIRE: wire_contract must be exactly 'RAPP/1'")
    if not isinstance(prototype["identity"], str) or not RAPPID_RE.fullmatch(prototype["identity"]):
        raise StoreError("E_IDENTITY: identity must be a full rappid content identity")
    if prototype["ecosystem_acceptance"] != "not-asserted":
        raise StoreError(
            "E_ACCEPTANCE_CLAIM: ecosystem_acceptance must be exactly 'not-asserted'"
        )
    blockers = prototype["external_blockers"]
    if not isinstance(blockers, list) or not blockers or not all(
        isinstance(item, str) and 1 <= len(item) <= 300 for item in blockers
    ):
        raise StoreError("E_EXTERNAL_BLOCKERS: provide at least one preserved external blocker")

    artifact = prototype["artifact"]
    if not isinstance(artifact, dict):
        raise StoreError("E_SCHEMA: artifact must be an object")
    _require_exact_keys(artifact, {"url", "sha256", "media_type"}, set(), "artifact")
    validate_pinned_raw_url(artifact["url"], "artifact.url")
    expected = validate_hash(artifact["sha256"], "artifact.sha256")
    if prototype["identity"].rsplit(":", 1)[-1] != expected:
        raise StoreError("E_IDENTITY_HASH: rappid content hash must equal artifact.sha256")
    if artifact["media_type"] not in {
        "text/x-python", "application/json", "application/zip", "application/octet-stream"
    }:
        raise StoreError("E_MEDIA_TYPE: artifact.media_type is not allowed")
    if network:
        verified_fetch(artifact["url"], expected, "artifact", fetcher)

    validate_license(prototype["license"], fetcher, network=network)
    return deepcopy(prototype)


def parse_issue_command(body: str) -> dict:
    blocks = JSON_BLOCK_RE.findall(body or "")
    if len(blocks) != 1:
        raise StoreError("E_ISSUE_JSON: issue body must contain exactly one fenced JSON block")
    try:
        payload = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        raise StoreError(f"E_ISSUE_JSON: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise StoreError("E_ISSUE_JSON: command must be a JSON object")
    return payload


def validate_command(command: object, title: str) -> dict:
    if not isinstance(command, dict):
        raise StoreError("E_SCHEMA: command must be an object")
    _require_exact_keys(
        command,
        {"schema", "operation", "id"},
        {"prototype", "reason"},
        "command",
    )
    if command["schema"] != COMMAND_SCHEMA:
        raise StoreError(f"E_SCHEMA: command.schema must be {COMMAND_SCHEMA}")
    operation = command["operation"]
    if operation not in {"create", "update", "deprecate"}:
        raise StoreError("E_OPERATION: only create, update, and deprecate are supported")
    prototype_id = command["id"]
    if not isinstance(prototype_id, str) or not ID_RE.fullmatch(prototype_id):
        raise StoreError("E_ID: command.id is invalid")

    title_match = TITLE_RE.fullmatch(title)
    if not title_match:
        raise StoreError(
            "E_TITLE: title must be '[ZOO V2 CREATE|UPDATE|DEPRECATE] <prototype-id>'"
        )
    if title_match.group(1).lower() != operation or title_match.group(2) != prototype_id:
        raise StoreError("E_TITLE_MISMATCH: title operation/id must exactly match command JSON")

    if operation in {"create", "update"}:
        if "reason" in command:
            raise StoreError("E_SCHEMA: reason is only valid for deprecate")
        if not isinstance(command.get("prototype"), dict):
            raise StoreError("E_SCHEMA: create/update requires prototype")
        if command["prototype"].get("id") != prototype_id:
            raise StoreError("E_ID_MISMATCH: command.id must equal prototype.id")
    else:
        if "prototype" in command:
            raise StoreError("E_DESTRUCTIVE_DELETE: deprecate accepts a reason, never replacement data")
        if not isinstance(command.get("reason"), str) or not (1 <= len(command["reason"]) <= 500):
            raise StoreError("E_SCHEMA: deprecate.reason must be 1-500 characters")
    return deepcopy(command)


def validate_discovery(discovery: object) -> str:
    if not isinstance(discovery, dict):
        raise StoreError("E_DISCOVERY: discovery document must be an object")
    _require_exact_keys(discovery, {"schema", "generation_url"}, set(), "discovery")
    if discovery["schema"] != DISCOVERY_SCHEMA:
        raise StoreError(f"E_DISCOVERY: schema must be {DISCOVERY_SCHEMA}")
    validate_pinned_raw_url(discovery["generation_url"], "discovery.generation_url")
    if "/api/v2/generations/" not in discovery["generation_url"]:
        raise StoreError("E_DISCOVERY: generation_url must name api/v2/generations/<file>.json")
    if not discovery["generation_url"].endswith(".json"):
        raise StoreError("E_DISCOVERY: generation_url must name a JSON generation")
    return discovery["generation_url"]


def validate_tombstone(tombstone: object) -> dict:
    if not isinstance(tombstone, dict):
        raise StoreError("E_TOMBSTONE: tombstone must be an object")
    _require_exact_keys(
        tombstone,
        {
            "id", "status", "reason", "deprecated_at", "source_issue",
            "last_version", "last_artifact_sha256",
        },
        set(),
        "tombstone",
    )
    if not isinstance(tombstone["id"], str) or not ID_RE.fullmatch(tombstone["id"]):
        raise StoreError("E_TOMBSTONE: invalid id")
    if tombstone["status"] != "deprecated":
        raise StoreError("E_TOMBSTONE: status must be 'deprecated'")
    if not isinstance(tombstone["reason"], str) or not tombstone["reason"]:
        raise StoreError("E_TOMBSTONE: reason is required")
    if not isinstance(tombstone["deprecated_at"], str) or not UTC_TIMESTAMP_RE.fullmatch(
        tombstone["deprecated_at"]
    ):
        raise StoreError("E_TOMBSTONE: deprecated_at must be a UTC second timestamp")
    if not isinstance(tombstone["source_issue"], int) or tombstone["source_issue"] <= 0:
        raise StoreError("E_TOMBSTONE: source_issue must be a positive integer")
    if not isinstance(tombstone["last_version"], str) or not SEMVER_RE.fullmatch(
        tombstone["last_version"]
    ):
        raise StoreError("E_TOMBSTONE: last_version must be strict semver")
    validate_hash(tombstone["last_artifact_sha256"], "tombstone.last_artifact_sha256")
    return deepcopy(tombstone)


def validate_generation(
    generation: object,
    fetcher: Fetch = fetch_bytes,
    *,
    network: bool = True,
    previous: dict | None = None,
) -> dict:
    if not isinstance(generation, dict):
        raise StoreError("E_GENERATION: generation document must be an object")
    _require_exact_keys(
        generation,
        {
            "schema", "generation_id", "created_at", "source_issue",
            "previous_generation_url", "prototypes", "tombstones",
        },
        set(),
        "generation",
    )
    if generation["schema"] != GENERATION_SCHEMA:
        raise StoreError(f"E_GENERATION: schema must be {GENERATION_SCHEMA}")
    if not isinstance(generation["generation_id"], str) or not re.fullmatch(
        r"(?:issue-[1-9]\d*|bootstrap-\d{8})", generation["generation_id"]
    ):
        raise StoreError(
            "E_GENERATION: generation_id must be issue-<positive integer> "
            "or bootstrap-<YYYYMMDD>"
        )
    if not isinstance(generation["created_at"], str) or not UTC_TIMESTAMP_RE.fullmatch(
        generation["created_at"]
    ):
        raise StoreError("E_GENERATION: created_at must be a UTC second timestamp")
    source_issue = generation["source_issue"]
    if source_issue is not None and (
        not isinstance(source_issue, int) or isinstance(source_issue, bool) or source_issue <= 0
    ):
        raise StoreError("E_GENERATION: source_issue must be null or a positive integer")
    if generation["generation_id"].startswith("issue-") and source_issue is None:
        raise StoreError("E_GENERATION: issue generations require source_issue")
    if generation["generation_id"].startswith("bootstrap-") and source_issue is not None:
        raise StoreError("E_GENERATION: bootstrap generations must use source_issue null")
    previous_url = generation["previous_generation_url"]
    if previous_url is not None:
        validate_pinned_raw_url(previous_url, "generation.previous_generation_url")

    if not isinstance(generation["prototypes"], list):
        raise StoreError("E_GENERATION: prototypes must be an array")
    prototypes = [
        validate_prototype(item, fetcher, network=network)
        for item in generation["prototypes"]
    ]
    ids = [item["id"] for item in prototypes]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise StoreError("E_GENERATION: prototypes must be unique and sorted by id")

    if not isinstance(generation["tombstones"], list):
        raise StoreError("E_GENERATION: tombstones must be an array")
    tombstones = [validate_tombstone(item) for item in generation["tombstones"]]
    tombstone_ids = [item["id"] for item in tombstones]
    if len(tombstone_ids) != len(set(tombstone_ids)):
        raise StoreError("E_TOMBSTONE: each id may be tombstoned only once")
    if set(ids) & set(tombstone_ids):
        raise StoreError("E_TOMBSTONE: a tombstoned id cannot remain live")

    if previous is not None:
        previous_tombstones = previous.get("tombstones", [])
        if tombstones[:len(previous_tombstones)] != previous_tombstones:
            raise StoreError("E_TOMBSTONE_APPEND_ONLY: prior tombstones changed or disappeared")
        if len(tombstones) < len(previous_tombstones):
            raise StoreError("E_TOMBSTONE_APPEND_ONLY: tombstones cannot be removed")
        previous_live = {item["id"]: item for item in previous.get("prototypes", [])}
        current_live = {item["id"]: item for item in prototypes}
        appended = tombstones[len(previous_tombstones):]
        appended_by_id = {item["id"]: item for item in appended}
        removed_ids = set(previous_live) - set(current_live)
        if removed_ids != set(appended_by_id):
            raise StoreError(
                "E_DESTRUCTIVE_DELETE: every removed live id must become exactly one new tombstone"
            )
        for removed_id, tombstone in appended_by_id.items():
            old = previous_live[removed_id]
            if (
                tombstone["last_version"] != old["version"]
                or tombstone["last_artifact_sha256"] != old["artifact"]["sha256"]
            ):
                raise StoreError(
                    "E_TOMBSTONE_PROVENANCE: tombstone must preserve the last version and artifact hash"
                )
    return deepcopy(generation)


def load_current_generation(discovery_path: Path, fetcher: Fetch = fetch_bytes) -> tuple[dict, str]:
    try:
        discovery = json.loads(discovery_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError(f"E_DISCOVERY: cannot read {discovery_path}: {exc}") from exc
    generation_url = validate_discovery(discovery)
    try:
        generation = json.loads(fetcher(generation_url))
    except json.JSONDecodeError as exc:
        raise StoreError(f"E_GENERATION: current generation is invalid JSON: {exc}") from exc
    validate_generation(generation, fetcher, network=True)
    return generation, generation_url


def _semver_tuple(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value)
    if not match:
        raise StoreError(f"E_VERSION: invalid semver {value!r}")
    return tuple(map(int, match.groups()))


def apply_command(
    current: dict,
    current_url: str,
    command: dict,
    *,
    issue_number: int,
    timestamp: str,
    fetcher: Fetch = fetch_bytes,
    network: bool = True,
) -> dict:
    validate_generation(current, fetcher, network=network)
    prototypes = {item["id"]: deepcopy(item) for item in current["prototypes"]}
    tombstones = deepcopy(current["tombstones"])
    tombstoned_ids = {item["id"] for item in tombstones}
    prototype_id = command["id"]
    operation = command["operation"]

    if operation == "create":
        if prototype_id in prototypes or prototype_id in tombstoned_ids:
            raise StoreError("E_ALREADY_EXISTS: ids are never recreated after admission or tombstone")
        prototypes[prototype_id] = validate_prototype(
            command["prototype"], fetcher, network=network
        )
    elif operation == "update":
        if prototype_id not in prototypes:
            raise StoreError("E_NOT_FOUND: update requires a live prototype")
        replacement = validate_prototype(command["prototype"], fetcher, network=network)
        if _semver_tuple(replacement["version"]) <= _semver_tuple(prototypes[prototype_id]["version"]):
            raise StoreError("E_VERSION_NOT_BUMPED: update version must increase")
        prototypes[prototype_id] = replacement
    elif operation == "deprecate":
        if prototype_id not in prototypes:
            raise StoreError("E_NOT_FOUND: deprecate requires a live prototype")
        old = prototypes.pop(prototype_id)
        tombstones.append({
            "id": prototype_id,
            "status": "deprecated",
            "reason": command["reason"],
            "deprecated_at": timestamp,
            "source_issue": issue_number,
            "last_version": old["version"],
            "last_artifact_sha256": old["artifact"]["sha256"],
        })
    else:  # guarded by validate_command; retained as a fail-closed boundary.
        raise StoreError("E_DESTRUCTIVE_DELETE: delete is unsupported; use a tombstone")

    result = {
        "schema": GENERATION_SCHEMA,
        "generation_id": f"issue-{issue_number}",
        "created_at": timestamp,
        "source_issue": issue_number,
        "previous_generation_url": current_url,
        "prototypes": sorted(prototypes.values(), key=lambda item: item["id"]),
        "tombstones": tombstones,
    }
    return validate_generation(
        result,
        fetcher,
        network=network,
        previous=current,
    )


def process_event(
    event: dict,
    discovery_path: Path,
    output_dir: Path,
    allowlist: set[str],
    fetcher: Fetch = fetch_bytes,
) -> Path:
    issue = event.get("issue")
    if not isinstance(issue, dict):
        raise StoreError("E_EVENT: event has no issue object")
    actor = issue.get("user", {}).get("login")
    if not isinstance(actor, str) or not actor:
        raise StoreError("E_EVENT: issue actor is missing")
    validate_actor(actor, allowlist)
    number = issue.get("number")
    if not isinstance(number, int) or number <= 0:
        raise StoreError("E_EVENT: issue number must be a positive integer")
    timestamp = issue.get("updated_at") or issue.get("created_at")
    if not isinstance(timestamp, str) or not timestamp:
        raise StoreError("E_EVENT: issue timestamp is missing")

    command = validate_command(
        parse_issue_command(issue.get("body") or ""),
        issue.get("title") or "",
    )
    current, current_url = load_current_generation(discovery_path, fetcher)
    generation = apply_command(
        current,
        current_url,
        command,
        issue_number=number,
        timestamp=timestamp,
        fetcher=fetcher,
        network=True,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"issue-{number}.json"
    if output.exists():
        raise StoreError(f"E_IMMUTABLE_GENERATION: {output} already exists")
    output.write_bytes(canonical_json(generation))
    return output


def pin_discovery(repository: str, commit: str, generation_path: str, output: Path) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise StoreError("E_REPOSITORY: expected owner/repo")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise StoreError("E_COMMIT: generation commit must be exactly 40 lowercase hex characters")
    path = Path(generation_path)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".json":
        raise StoreError("E_GENERATION_PATH: path must be a safe repository-relative JSON path")
    if path.parts[:3] != ("api", "v2", "generations"):
        raise StoreError("E_GENERATION_PATH: generation must live under api/v2/generations/")
    generation_url = f"https://raw.githubusercontent.com/{repository}/{commit}/{path.as_posix()}"
    discovery = {"schema": DISCOVERY_SCHEMA, "generation_url": generation_url}
    validate_discovery(discovery)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(discovery))


def validate_tree(root: Path, fetcher: Fetch = fetch_bytes, *, network: bool = False) -> None:
    discovery_path = root / "api" / "v2" / "discovery.json"
    discovery = json.loads(discovery_path.read_text())
    current_url = validate_discovery(discovery)
    current_name = current_url.rsplit("/", 1)[-1]
    current_path = root / "api" / "v2" / "generations" / current_name
    if not current_path.is_file():
        raise StoreError(f"E_DISCOVERY_TARGET: local generation is missing: {current_path}")

    generations = []
    by_name = {}
    for path in sorted((root / "api" / "v2" / "generations").glob("*.json")):
        generation = json.loads(path.read_text())
        validate_generation(generation, fetcher, network=network)
        if canonical_json(generation) != path.read_bytes():
            raise StoreError(f"E_NON_CANONICAL_JSON: {path}")
        generations.append(generation)
        by_name[path.name] = generation
    if not generations:
        raise StoreError("E_GENERATION: at least one immutable generation is required")
    for generation in generations:
        previous_url = generation["previous_generation_url"]
        if previous_url is None:
            continue
        previous_name = previous_url.rsplit("/", 1)[-1]
        if previous_name not in by_name:
            raise StoreError(
                f"E_GENERATION_CHAIN: local previous generation is missing: {previous_name}"
            )
        validate_generation(
            generation,
            fetcher,
            network=network,
            previous=by_name[previous_name],
        )

    if canonical_json(discovery) != discovery_path.read_bytes():
        raise StoreError(f"E_NON_CANONICAL_JSON: {discovery_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    apply_parser = sub.add_parser("apply-issue")
    apply_parser.add_argument("--event-path", required=True)
    apply_parser.add_argument("--discovery", default="api/v2/discovery.json")
    apply_parser.add_argument("--output-dir", default="api/v2/generations")
    apply_parser.add_argument("--allow-actors", required=True)

    pin_parser = sub.add_parser("pin-discovery")
    pin_parser.add_argument("--repository", required=True)
    pin_parser.add_argument("--commit", required=True)
    pin_parser.add_argument("--generation-path", required=True)
    pin_parser.add_argument("--output", default="api/v2/discovery.json")

    tree_parser = sub.add_parser("validate-tree")
    tree_parser.add_argument("--root", default=".")
    tree_parser.add_argument("--network", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "apply-issue":
            event = json.loads(Path(args.event_path).read_text())
            output = process_event(
                event,
                Path(args.discovery),
                Path(args.output_dir),
                parse_allowlist(args.allow_actors),
            )
            print(output.as_posix())
        elif args.command == "pin-discovery":
            pin_discovery(
                args.repository,
                args.commit,
                args.generation_path,
                Path(args.output),
            )
        else:
            validate_tree(Path(args.root), network=args.network)
            print("Zoo v2 catalog is valid.")
    except (StoreError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
