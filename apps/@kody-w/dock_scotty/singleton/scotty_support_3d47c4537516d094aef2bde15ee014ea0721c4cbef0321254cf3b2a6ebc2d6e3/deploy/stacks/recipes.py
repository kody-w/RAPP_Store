"""Offline recipe checks and Compose input rendering; not a deployment executor."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent
APPLICATIONS = ("scrapling", "dify", "open-seo", "openshorts", "presenton")
SDK_RUNTIME_GATE = (
    "No application recipe is qualified against the execution SDK yet. Its proposed "
    "strict subset excludes required private bind mounts, environment/custody files, "
    "reviewed startup commands and full upstream service wiring. Do not strip these "
    "inputs or bypass the SDK with raw Docker; reviewed SDK support and integration "
    "tests are required before any application apply."
)
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
IMAGE = re.compile(r"[a-z0-9][a-z0-9./_-]*@sha256:[0-9a-f]{64}")
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
SECRET_NAME = re.compile(r"(^|_)(PASSWORD|SECRET|TOKEN|API_KEY|ACCESS_KEY|SERVER_KEY|AUTH_KEY|FAL_KEY|DSN)(_|$)")
TOKEN = "@PRIVATE_ROOT@"
FORBIDDEN_SERVICE_KEYS = {
    "build", "extends", "include", "provider", "develop", "network_mode",
    "privileged", "devices", "device_cgroup_rules", "pid", "ipc", "uts",
    "userns_mode", "volumes_from", "external_links", "links", "cap_add",
    "credential_spec", "use_api_socket", "post_start", "pre_stop",
}
ALLOWED_SERVICE_KEYS = {
    "entrypoint", "command", "depends_on", "environment", "networks", "ports",
    "volumes", "shm_size", "healthcheck", "secrets", "image", "platform",
    "restart", "logging", "mem_limit", "cpus", "pids_limit", "security_opt",
    "env_file",
}
RESET_KEYS = {
    "build", "container_name", "ports", "volumes", "environment", "env_file",
    "profiles", "deploy", "healthcheck", "networks", "restart",
}


class Refused(ValueError):
    pass


# Public Store packages never vendor upstream default credential literals (names only, never values).
CREDENTIAL_DEFAULT_NAME = re.compile(
    r"(?i)(^|_)(PASSWORD|PASSWD|PWD|SECRET|TOKEN|API_KEY|APIKEY|ACCESS_KEY|SERVER_KEY|AUTH_KEY|DAEMON_KEY|"
    r"SITE_KEY|PRIVATE_KEY|SIGNING_KEY|ENCRYPTION_KEY|ENCRYPTIONKEY|FAL_KEY|DSN|CREDENTIALS|ALLOWED_KEYS)(_(ID|KEY|SECRET))?$"
)
REDACTION_KINDS = {"compose-default", "literal-assignment"}
# Digest of Dify's published example password: the renderer refuses it without shipping the value.
UPSTREAM_EXAMPLE_CREDENTIAL_SHA256 = frozenset({"b8ba9c61cc9ff699c426c75e748fcf200e8b47869d76fde8bb36ec2f7a34f038"})
_ASSIGNMENTS = (
    re.compile(r"""(?m)^(?P<lead>[ \t]*(?:-[ \t]+)?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<sep>:[ \t]+)(?P<q>["']?)"""
               r"""(?P<value>[^\s"'$&*|>{\[#][^"'#\n]*?)(?P=q)(?P<tail>[ \t]*(?:#[^\n]*)?)$"""),
    re.compile(r"""(?m)^(?P<lead>[ \t]*-[ \t]+)(?P<q>["']?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<sep>=)"""
               r"""(?P<value>[^\s"'$][^\s"']*)(?P=q)(?P<tail>[ \t]*)$"""),
    re.compile(r"""(?P<lead>")(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<sep>"[ \t]*:[ \t]*)(?P<q>")"""
               r"""(?P<value>[^"\\$][^"\\]*)(?P=q)(?P<tail>)"""),
    re.compile(r"""(?P<lead>")(?P<q>)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<sep>=)"""
               r"""(?P<value>[^"\\$\s][^"\\\s]*)(?P=q)(?P<tail>")"""),
)


def _compose_expressions(text: str):
    """Yield (start, end, name, operator, default_start, default_end) for ${...}, honoring $$ and nesting."""
    index = 0
    while True:
        start = text.find("${", index)
        if start < 0:
            return
        dollars = 0
        while start - dollars >= 0 and text[start - dollars] == "$":
            dollars += 1
        match = re.match(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:?[-?])?", text[start:])
        if dollars % 2 == 0 or not match:
            index = start + 2
            continue
        depth, cursor = 1, start + match.end()
        while cursor < len(text) and depth:
            if text.startswith("${", cursor):
                depth, cursor = depth + 1, cursor + 2
                continue
            if text[cursor] == "}":
                depth -= 1
            cursor += 1
        if depth:
            return
        yield start, cursor, match.group(1), match.group(2) or "", start + match.end(), cursor - 1
        index = start + match.end()


def _credential_spans(text: str):
    for start, _, name, operator, low, high in _compose_expressions(text):
        default = text[low:high]
        if operator in (":-", "-") and default and "${" not in default and CREDENTIAL_DEFAULT_NAME.search(name):
            yield name, "compose-default", start, low - len(operator), high, ""
    for pattern in _ASSIGNMENTS:
        for match in pattern.finditer(text):
            if CREDENTIAL_DEFAULT_NAME.search(match.group("key")) and match.group("value").strip():
                yield (match.group("key"), "literal-assignment", match.start(),
                       match.start("value"), match.end("value"), "${" + match.group("key") + "}")


def credential_literals(text: str) -> list[tuple[str, str, int]]:
    """Credential-named non-empty literal defaults or assignments: (name, kind, line), never values."""
    return sorted({(name, kind, text.count("\n", 0, start) + 1)
                   for name, kind, start, *_ in _credential_spans(text)}, key=lambda item: (item[2], item[0], item[1]))


def redact_credential_literals(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Replace ${NAME:-literal} with ${NAME} and literal credential values with ${NAME}; report keys/lines only."""
    spans = sorted({(low, high, replacement) for *_, low, high, replacement in _credential_spans(text)})
    if not spans:
        return text, []
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise Refused("overlapping credential redactions")
    findings = credential_literals(text)
    output, cursor = [], 0
    for low, high, replacement in spans:
        output.append(text[cursor:low])
        output.append(replacement)
        cursor = high
    output.append(text[cursor:])
    redacted = "".join(output)
    if credential_literals(redacted) or redacted.count("\n") != text.count("\n"):
        raise Refused("credential literal remains after redaction")
    grouped: dict[tuple[str, str], list[int]] = {}
    for name, kind, line in findings:
        grouped.setdefault((name, kind), []).append(line)
    return redacted, [{"variable": name, "kind": kind, "lines": sorted(lines)}
                      for (name, kind), lines in sorted(grouped.items())]


def _verify_redactions(item: dict[str, Any], data: bytes, reviewed: dict[str, str]) -> None:
    upstream = item.get("upstream_sha256")
    redactions = item.get("redactions")
    if (upstream is None) != (redactions is None):
        raise Refused("redacted upstream evidence needs both upstream_sha256 and redactions")
    if redactions is None:
        return
    if not isinstance(upstream, str) or not SHA256.fullmatch(upstream) or reviewed.get(item.get("upstream_path")) != upstream:
        raise Refused("redacted evidence does not identify its reviewed upstream blob")
    if not isinstance(redactions, list) or not redactions:
        raise Refused("invalid redaction list")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("redacted evidence is not text") from None
    lines = text.count("\n") + 1
    for entry in redactions:
        if (
            not isinstance(entry, dict) or set(entry) != {"variable", "kind", "lines"}
            or not isinstance(entry["variable"], str) or not CREDENTIAL_DEFAULT_NAME.search(entry["variable"])
            or entry["kind"] not in REDACTION_KINDS or not isinstance(entry["lines"], list) or not entry["lines"]
            or any(type(line) is not int or not 1 <= line <= lines for line in entry["lines"])
            or "${" + entry["variable"] + "}" not in text
        ):
            raise Refused("invalid credential redaction record")
    if credential_literals(text):
        raise Refused("redacted evidence still carries a credential literal")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def read_json(path: Path) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise Refused(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique_pairs)


def private_root(value: str) -> str:
    """Require the native volume path, not QNAP's share-name symlink."""
    if not isinstance(value, str):
        raise Refused("private root must be a string")
    path = PurePosixPath(value)
    if (
        not re.fullmatch(r"/share/[A-Za-z0-9_-]+/RAPP-Dock", value)
        or str(path) != value
        or path.parts[2].casefold() in {"public", "homes", "home", "container", "rapp-dock"}
        or "public" in (part.casefold() for part in path.parts)
    ):
        raise Refused("private root must be /share/<native-volume>/RAPP-Dock, never Public")
    for ancestor in reversed(Path(value).parents):
        if ancestor.is_symlink():
            raise Refused("private root has a symlinked ancestor")
    if Path(value).is_symlink():
        raise Refused("private root must not be a symlink")
    return value


def scoped_path(value: str, root: str, prefixes: tuple[str, ...]) -> str:
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise Refused("invalid scoped path")
    path = PurePosixPath(value)
    if str(path) != value or ".." in path.parts or "." in value.split("/"):
        raise Refused("noncanonical scoped path")
    if not any(value.startswith(root + "/" + prefix + "/") for prefix in prefixes):
        raise Refused("path escapes its application or release scope")
    if any(part.casefold() == "public" or part.endswith(".sock") for part in path.parts):
        raise Refused("public storage and sockets are forbidden")
    for candidate in (Path(value), *Path(value).parents):
        if candidate.is_symlink():
            raise Refused("symlink in scoped path")
    return value


def select_amd64_manifest(index: dict[str, Any]) -> str:
    """Select one exact OCI child; never fall back to another architecture or tag."""
    matches = [
        item for item in index.get("manifests", [])
        if item.get("platform", {}).get("os") == "linux"
        and item.get("platform", {}).get("architecture") == "amd64"
        and item.get("platform", {}).get("variant", "") in {"", "v1"}
    ]
    if len(matches) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", matches[0].get("digest", "")):
        raise Refused("registry index must contain exactly one linux/amd64 child")
    return matches[0]["digest"]


def load_recipe(application: str, directory: Path = ROOT) -> dict[str, Any]:
    if application not in APPLICATIONS:
        raise Refused("unknown application")
    recipe = read_json(directory / application / "recipe.json")
    lock = read_json(directory / application / "source.lock.json")
    if recipe.get("application") != application or lock.get("application") != application:
        raise Refused("application identity mismatch")
    if not COMMIT.fullmatch(lock.get("commit", "")):
        raise Refused("upstream commit is not an exact commit")
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", lock.get("repository", "")):
        raise Refused("upstream repository is not an explicit GitHub source")
    reviewed = {entry["path"]: entry["sha256"] for entry in lock.get("reviewed_source_files", [])}
    for item in lock["files"]:
        if not isinstance(item, dict) or not {"local", "sha256", "upstream_path"} <= set(item) <= {
                "local", "sha256", "upstream_path", "transform", "upstream_sha256", "redactions"}:
            raise Refused("invalid source lock entry")
        relative = PurePosixPath(item["local"])
        if relative.is_absolute() or ".." in relative.parts:
            raise Refused("invalid source lock path")
        path = directory / application / relative
        if path.is_symlink() or not SHA256.fullmatch(item["sha256"]):
            raise Refused("invalid source lock entry")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise Refused(f"upstream bytes changed: {application}/{relative}")
        _verify_redactions(item, data, reviewed)
    projection = lock.get("compose_projection")
    if projection:
        if projection not in {entry["local"] for entry in lock["files"]}:
            raise Refused("upstream projection is not locked")
        base = read_json(directory / application / projection)
    else:
        base = {"services": recipe["dockerfile_service"]}
    recipe["_source"] = lock
    recipe["_base"] = base
    evidence = read_json(directory / "registry-observation.json")
    for name, pin in recipe["images"].items():
        if pin["reference"] is None:
            continue
        matches = [
            observation for observation in evidence
            if observation.get("image") == pin["reference"]
            and observation.get("discovered_ref") == pin.get("discovery_reference")
            and observation.get("status") == "resolved"
            and observation.get("platform") == "linux/amd64"
        ]
        if len(matches) != 1:
            raise Refused(f"{name}: image is absent from the reviewed registry observation")
        revision = pin.get("source_revision")
        if revision and (revision != lock["commit"] or matches[0]["labels"].get("org.opencontainers.image.revision") != revision):
            raise Refused(f"{name}: image source revision does not match the reviewed source")
    return recipe


def _substitute(value: Any, root: str) -> Any:
    if isinstance(value, str):
        value = value.replace(TOKEN, root)
        if "@" in value and "ROOT@" in value:
            raise Refused("unknown path token")
        if re.search(r"\$(?:\{|[A-Za-z_])", value.replace("$$", "")):
            raise Refused("unresolved Compose interpolation")
        return value
    if isinstance(value, list):
        return [_substitute(item, root) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, root) for key, item in value.items()}
    return value


def compose_input(recipe: dict[str, Any], root: str, *, audit: bool = False) -> dict[str, Any]:
    """Materialize inert Compose data. Audit mode never emits a runnable image."""
    root = private_root(root)
    app = recipe["application"]
    selected = recipe["services"]
    base = recipe["_base"]
    if set(selected) != set(recipe["images"]) or set(selected) != set(recipe["limits"]):
        raise Refused("service/image/resource sets differ")
    if not set(selected).issubset(base["services"]):
        raise Refused("selected service is absent from official upstream")
    blockers = list(recipe.get("render_blockers", []))
    for name, image in recipe["images"].items():
        if image.get("reference") is None:
            blockers.append(f"{name}: {image.get('blocker', 'image digest unresolved')}")
        elif not IMAGE.fullmatch(image["reference"]) or image.get("platform") != "linux/amd64":
            raise Refused(f"{name}: image must be a linux/amd64 digest, never a tag")
        if name in recipe.get("source_image_services", []) and image["reference"] and not image.get("source_revision"):
            blockers.append(f"{name}: source/image revision relationship is unresolved")
    if blockers and not audit:
        raise Refused("; ".join(blockers))
    for group in recipe.get("environment_groups", []):
        if not set(group["services"]).issubset(selected):
            raise Refused("environment group names an unselected service")
    services: dict[str, Any] = {}
    for name in selected:
        original = copy.deepcopy(base["services"][name])
        dependencies = original.get("depends_on", {})
        if isinstance(dependencies, list):
            dependencies = {dep: {"condition": "service_started"} for dep in dependencies}
        kept = {}
        for dep, condition in dependencies.items():
            if dep in selected:
                kept[dep] = condition
            elif condition.get("required", True):
                raise Refused(f"{name}: required upstream dependency omitted: {dep}")
        for key in RESET_KEYS:
            original.pop(key, None)
        original["depends_on"] = kept
        original.update(copy.deepcopy(recipe["overrides"][name]))
        if kept != original.get("depends_on"):
            raise Refused("overlays may not discard official service dependencies")
        image = recipe["images"][name]["reference"]
        original["image"] = image if image and not blockers else "UNRESOLVED-NOT-A-RUNNABLE-IMAGE"
        original["platform"] = "linux/amd64"
        original["restart"] = "no"
        original["logging"] = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}
        original["mem_limit"] = str(recipe["limits"][name]["memory_mib"]) + "m"
        original["cpus"] = str(recipe["limits"][name]["cpus"])
        original["pids_limit"] = recipe["limits"][name].get("pids", 256)
        original["security_opt"] = ["no-new-privileges:true"]
        original.setdefault("ports", [])
        original.setdefault("volumes", [])
        original.setdefault("networks", ["default"])
        original.setdefault("environment", {})
        environment = {}
        for group in recipe.get("environment_groups", []):
            if name in group["services"]:
                environment.update(copy.deepcopy(group["values"]))
        environment.update(original["environment"])
        original["environment"] = environment
        required = recipe.get("credential_environment", {}).get(name, [])
        if required:
            if len(required) != len(set(required)) or any(not ENV_NAME.fullmatch(key) for key in required):
                raise Refused("invalid credential environment allowlist")
            if any(key in original["environment"] for key in required):
                raise Refused("a literal environment value would override custody")
            original["env_file"] = [{
                "path": f"{root}/custody/{app}/{name}.env",
                "required": True,
            }]
        services[name] = original
    document = {
        "name": "rapp-dock-" + app,
        "services": services,
        "networks": recipe["networks"],
    }
    if recipe.get("secrets"):
        document["secrets"] = recipe["secrets"]
    document = _substitute(document, root)
    validate_compose(document, recipe, root, audit=audit)
    return document


def validate_compose(document: dict[str, Any], recipe: dict[str, Any], root: str, *, audit: bool = False) -> None:
    app = recipe["application"]
    if _substitute(document, root) != document:
        raise Refused("unresolved private path token")
    if set(document) - {"name", "services", "networks", "secrets"}:
        raise Refused("unexpected top-level Compose effect")
    if not document["networks"] or any(
        value != {"driver": "bridge", "internal": True} for value in document["networks"].values()
    ):
        raise Refused("all application networks must be private internal bridges")
    if set(document["services"]) != set(recipe["services"]):
        raise Refused("unexpected service")
    for name, service in document["services"].items():
        if FORBIDDEN_SERVICE_KEYS.intersection(service):
            raise Refused(f"{name}: forbidden host authority or build directive")
        if set(service) - ALLOWED_SERVICE_KEYS:
            raise Refused(f"{name}: unreviewed service directive")
        if service.get("platform") != "linux/amd64":
            raise Refused("wrong runtime architecture")
        image = service.get("image", "")
        if not IMAGE.fullmatch(image) and not (audit and image == "UNRESOLVED-NOT-A-RUNNABLE-IMAGE"):
            raise Refused("mutable or unresolved runtime image")
        if image != recipe["images"][name]["reference"] and not (audit and image == "UNRESOLVED-NOT-A-RUNNABLE-IMAGE"):
            raise Refused("runtime image differs from its reviewed pin")
        if not set(service["networks"]).issubset(document["networks"]):
            raise Refused("service references an unreviewed network")
        if not set(service.get("depends_on", {})).issubset(document["services"]):
            raise Refused("unselected service dependency")
        for port in service.get("ports", []):
            if not isinstance(port, dict) or set(port) != {"host_ip", "published", "target", "protocol"}:
                raise Refused("ports must use explicit loopback long syntax")
            if port["host_ip"] != "127.0.0.1" or port["protocol"] != "tcp":
                raise Refused("a service would be exposed beyond loopback")
            if not str(port["published"]).isdigit() or not 1024 <= int(port["published"]) <= 65535:
                raise Refused("invalid published port")
            if not str(port["target"]).isdigit() or not 1 <= int(port["target"]) <= 65535:
                raise Refused("invalid target port")
        for mount in service.get("volumes", []):
            if not isinstance(mount, dict) or mount.get("type") != "bind":
                raise Refused("only explicitly scoped bind mounts are accepted")
            if set(mount) - {"type", "source", "target", "bind", "read_only"}:
                raise Refused("unreviewed mount directive")
            if mount.get("bind") != {"create_host_path": False}:
                raise Refused("bind mount may not create host paths")
            scoped_path(mount["source"], root, (f"workspaces/{app}", f"releases/{app}"))
            target = PurePosixPath(mount["target"])
            if not target.is_absolute() or str(target) != mount["target"] or ".." in target.parts:
                raise Refused("invalid container mount")
            if str(target) in {"/", "/proc", "/sys", "/dev", "/run", "/var/run"} or str(target).endswith(".sock"):
                raise Refused("host roots and Docker sockets must never be mounted")
            if "/releases/" in mount["source"] and mount.get("read_only") is not True:
                raise Refused("release inputs must be read-only")
        for env_file in service.get("env_file", []):
            if set(env_file) != {"path", "required"} or env_file["required"] is not True:
                raise Refused("credential custody files must be explicit and required")
            if env_file["path"] != f"{root}/custody/{app}/{name}.env":
                raise Refused("unscoped credential custody file")
            scoped_path(env_file["path"], root, (f"custody/{app}",))
        expected_env_files = (
            [{"path": f"{root}/custody/{app}/{name}.env", "required": True}]
            if recipe.get("credential_environment", {}).get(name) else []
        )
        if service.get("env_file", []) != expected_env_files:
            raise Refused("credential custody requirement was changed")
        environment = service["environment"]
        if not isinstance(environment, dict):
            raise Refused("environment must never inherit ambient values")
        if set(environment).intersection(recipe.get("credential_environment", {}).get(name, [])):
            raise Refused("environment would override required custody")
        for key, value in environment.items():
            if not ENV_NAME.fullmatch(key) or not isinstance(value, str):
                raise Refused("environment must contain explicit string literals")
            if SECRET_NAME.search(key) and value and key != "ENABLE_EMAIL_PASSWORD_LOGIN":
                raise Refused("credentials belong in protected custody, not templates")
            if (any(word in value.lower() for word in ("your-api-key", "changeme", "change_me"))
                    or any(hashlib.sha256(token.encode()).hexdigest() in UPSTREAM_EXAMPLE_CREDENTIAL_SHA256
                           for token in re.findall(r"[a-z0-9]+", value.lower()))):
                raise Refused("example credential is not a credential")
        health = service.get("healthcheck", {})
        if name not in recipe.get("completion_services", []):
            if not health.get("test") or health.get("disable") or health["test"][0] not in {"CMD", "CMD-SHELL"}:
                raise Refused(f"{name}: missing enabled health check")
            if not all(key in health for key in ("interval", "timeout", "retries", "start_period")):
                raise Refused("unbounded health check")
        limit = service.get("mem_limit", "")
        if not re.fullmatch(r"[1-9][0-9]*m", limit) or int(limit[:-1]) > 6144:
            raise Refused("missing or excessive memory limit")
        if not 0 < float(service.get("cpus", 0)) <= 3.5 or not 1 <= service.get("pids_limit", 0) <= 1024:
            raise Refused("missing or excessive CPU/process limit")
        if service.get("logging") != {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}:
            raise Refused("unbounded container logging")
        if service.get("restart") != "no" or service.get("security_opt") != ["no-new-privileges:true"]:
            raise Refused("unreviewed autonomous restart or privilege escalation")
    for secret in document.get("secrets", {}).values():
        if set(secret) != {"file"}:
            raise Refused("only protected file custody is permitted")
        scoped_path(secret["file"], root, (f"custody/{app}",))
    admission = recipe["admission"]
    if admission["max_active_heavy_stacks"] != 1 or admission["max_concurrent_jobs"] != 1:
        raise Refused("heavy work must be serialized by the SDK")
    if admission["start_mode"] != "on-demand" or admission["host_reserve_mib"] < 2048:
        raise Refused("unreviewed NAS admission policy")
    if sum(item["memory_mib"] for item in recipe["limits"].values()) != admission["memory_ceiling_mib"]:
        raise Refused("admission memory differs from container limits")
    if sum(float(item["cpus"]) for item in recipe["limits"].values()) > 3.5:
        raise Refused("application CPU limits leave insufficient control-plane headroom")


def _verify_qualification_inputs(root: Path, inputs: Any) -> None:
    if not isinstance(inputs, dict) or not 1 <= len(inputs) <= 32:
        raise Refused("invalid qualification input commitments")
    for name, digest in inputs.items():
        relative = PurePosixPath(name)
        if (
            relative.is_absolute() or str(relative) != name
            or "\\" in name or any(part in {"", ".", ".."} for part in name.split("/"))
            or not isinstance(digest, str) or not SHA256.fullmatch(digest)
        ):
            raise Refused("unsafe qualification input")
        selected = root / relative
        if any(candidate.is_symlink() for candidate in (selected, *selected.parents)):
            raise Refused("linked qualification input")
        if hashlib.sha256(selected.read_bytes()).hexdigest() != digest:
            raise Refused("qualification inputs changed after recorded execution")


def _dify_qualification_observation(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    _verify_qualification_inputs(root, record.get("inputs"))
    recipe = read_json(root / "recipe.json")
    source = read_json(root / "source.lock.json")
    services = record.get("service_evidence", [])
    expected = set(recipe["limits"])
    if (
        record.get("schema") != "dify-private-mac-qualification/1"
        or record.get("status") != "passed-bounded-local-qualification-stopped-volumes-retained"
        or record.get("source_commit") != source["commit"]
        or record.get("reviewed_service_count") != 15
        or record.get("healthy_long_running_roles") != 14
        or record.get("init_permissions_exit_code") != 0
        or len(services) != 15 or len(expected) != 15
        or {service["service"] for service in services} != expected
        or record.get("published_ports") != []
        or record.get("qualification_only") is not True
        or record.get("synthetic_credentials_only") is not True
        or record.get("raw_socket_capability_dropped") is not True
        or any(record.get(field) is not False for field in (
            "production_deployment_authorized", "canonical_rapp_owner_or_root_keys_created",
            "credentials_in_receipt", "existing_credentials_read_or_copied",
            "host_socket_or_root_mounts", "privileged_containers", "nas_actions",
        ))
    ):
        raise Refused("unreviewed Dify qualification or incomplete stack")
    for service in services:
        name = service["service"]
        if (
            service["image_reference"] != recipe["images"][name]["reference"]
            or service["port_bindings"] != {} or service["privileged"] is not False
            or service["oom_killed"] is not False
            or not 0 < service["memory_bytes"] <= 6144 * 1024 * 1024
            or not 0 < service["nano_cpus"] <= 3500000000
            or not 0 < service["pids_limit"] <= 1024
            or (name == "init_permissions" and service["exit_code"] != 0)
            or (name != "init_permissions" and (
                service["status"] != "running" or service["health"] != "healthy"
            ))
        ):
            raise Refused("Dify role did not satisfy recorded runtime qualification")
    if (
        sum(service["memory_bytes"] for service in services) != 8768 * 1024 * 1024
        or sum(service["nano_cpus"] for service in services) != 6625000000
        or len(record["network_evidence"]) != 4
        or any(
            network["internal"] is not True or network["ipv6"] is not False
            or network["driver_options"].get("com.docker.network.bridge.gateway_mode_ipv4") != "isolated"
            for network in record["network_evidence"]
        )
    ):
        raise Refused("Dify qualification resource or isolation contract changed")
    for workflow in (record["initial_workflow"], record["restart_workflow"]):
        operations = {(step["operation"], step["http_status"]) for step in workflow["steps"]}
        dataset = workflow["dataset_id"]
        required = {
            ("POST /login", 200), (f"GET /datasets/{dataset}", 200),
            (f"PATCH /datasets/{dataset}", 200), ("GET /datasets", 200),
        }
        if workflow is record["initial_workflow"]:
            required.add(("POST /datasets", 201))
        if (
            workflow["status"] != "passed"
            or not required.issubset(operations)
            or workflow["provider_calls_requested"] != 0
            or workflow["documents_ingested"] != 0
            or workflow["embedding_or_retrieval_tested"] is not False
            or workflow["user_content_used"] is not False
            or workflow["egress_probe"]["external_dns"] != "blocked"
            or workflow["egress_probe"]["tcp_public_endpoint"] != "blocked"
        ):
            raise Refused("Dify qualification workflow or egress evidence changed")
    persistence = record["restart_persistence"]
    if (
        persistence["status"] != "passed" or persistence["all15roles_restarted"] is not True
        or not record["initial_workflow"]["dataset_id"]
        or len({record["initial_workflow"]["dataset_id"], record["restart_workflow"]["dataset_id"],
                persistence["dataset_id"]}) != 1
    ):
        raise Refused("Dify dataset identity did not survive the recorded restart")
    return {
        "status": "recorded-real-qualification",
        "runtime_observed_now": False,
        "platform": "linux/amd64",
        "scope": "explicit-amd64-emulation-complete-private-mac-stack-not-nas-deployment",
        "source_assurance": "exact-pinned-images-and-source-lock-not-signed-builder-verification",
        "application_api": {
            "reviewed_roles": 15, "healthy_long_running_roles": 14,
            "initialization": "verified-successful-one-shot",
            "authenticated_synthetic_dataset_create_read_update_list": "verified",
            "complete_cold_restart_same_dataset": "verified",
            "embedding_or_retrieval": "not-tested",
            "provider_calls_requested": 0,
            "public_tcp_and_dns_egress": "denied",
        },
        "memory_ceiling_mib": 8768,
        "cpu_ceiling": 6.625,
        "production_authority": "not-established",
        "scotty_application_job_dispatch": "not-yet-wired",
    }


def _openshorts_qualification_observation(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    qualification = root / "qualification"
    observations = read_json(qualification / "offline-locks/observations.lock.json")
    entries = observations["files"]
    commitments = {entry["path"]: entry["sha256"] for entry in entries}
    if len(commitments) != len(entries):
        raise Refused("duplicate OpenShorts observation")
    _verify_qualification_inputs(qualification, commitments)
    source = read_json(root / "source.lock.json")["commit"]
    images = read_json(qualification / "offline-locks/application-image-lock.json")
    stack = read_json(qualification / "public-proof/stack-qualification-result.json")
    models = read_json(qualification / "public-proof/backend-model-proof.json")
    isolation = read_json(qualification / "public-proof/stack-isolation-observation.json")
    roles = {"backend", "frontend", "renderer"}
    if (
        record.get("application") != "openshorts"
        or record.get("status") != "qualified-provider-independent-local-runtime"
        or record.get("source_commit") != source
        or record.get("image_platform") != "linux/amd64"
        or record.get("emulation_explicit") is not True
        or record.get("registry_published") is not False
        or record.get("paid_provider_calls") != 0
        or record.get("nas_deployment_performed") is not False
        or record.get("private_user_inputs_used") is not False
        or set(images) != roles or set(isolation["containers"]) != roles
        or stack["status"] != "passed" or models["status"] != "passed"
        or stack["published_ports"] != [] or stack["direct_egress"] != "denied"
        or stack["paid_provider_calls"] != 0 or models["paid_provider_calls"] != 0
        or stack["provider_operation"]["status"] != "blocked"
        or stack["provider_operation"]["result"] is not None
        or isolation["network"]["internal"] is not True
    ):
        raise Refused("unreviewed OpenShorts application qualification")
    for role in roles:
        image, container = images[role], isolation["containers"][role]
        if (
            image["platform"] != "linux/amd64" or image["source_revision"] != source
            or image["all_layer_digests_verified"] is not True
            or image["image_manifest_digest"] != record["application_images"][role]
            or stack["images"][role] != image["oci_index_descriptor"]
            or container["cap_drop"] != ["ALL"] or container["port_bindings"] != {}
            or container["privileged"] is not False or container["running"] is not False
            or container["user"] not in {"1000:1000", "101:101"}
            or container["security_opt"] != ["no-new-privileges"]
            or container["network_names"] != [isolation["network"]["name"]]
            or any(mount["type"] != "volume" for mount in container["mounts"])
        ):
            raise Refused("OpenShorts image or isolation evidence differs")
    if (
        sum(item["memory"] for item in isolation["containers"].values()) != 7650410496
        or sum(item["nano_cpus"] for item in isolation["containers"].values()) != 4000000000
        or models["yolo_inference"] != "real-cpu"
        or models["mediapipe_inference"] != "real-cpu"
        or models["whisper_inference"] != "real-offline-int8"
        or models["scene_fallback_used"] is not False
        or models["transnetv2_scene_count"] < 1
    ):
        raise Refused("OpenShorts resource or model qualification differs")
    artifact = stack["real_render"]
    video = artifact["ffprobe"]["streams"][0]
    persistence = stack["restart_persistence"]
    if (
        artifact["sha256"] != record["actual_artifact"]["sha256"]
        or not SHA256.fullmatch(artifact["sha256"])
        or artifact["bytes"] <= 0 or artifact["unique_rgb_colors_in_sample"] <= 1
        or (video["codec_name"], video["width"], video["height"], video["nb_frames"])
            != ("h264", 180, 320, "30")
        or persistence["artifact_sha256_after_restart"] != artifact["sha256"]
        or persistence["matches_before"] is not True
        or persistence["all_three_processes_stopped_then_started"] is not True
        or persistence["container_recreation_tested"] is not False
        or persistence["upstream_in_memory_job_index_persistence_claimed"] is not False
    ):
        raise Refused("OpenShorts real output or persistence evidence differs")
    return {
        "status": "recorded-real-qualification",
        "runtime_observed_now": False,
        "platform": "linux/amd64",
        "scope": "explicit-amd64-emulation-local-source-builds-not-nas-deployment",
        "source_assurance": record["image_assurance"],
        "registry_published": False,
        "application_api": {
            "three_service_render": "verified-real-frontend-backend-renderer",
            "artifact": record["actual_artifact"],
            "real_offline_model_inference": ["YOLO", "MediaPipe", "TransNetV2", "Whisper"],
            "artifact_survives_process_restart": True,
            "container_recreation_tested": False,
            "in_memory_job_index_persistence": "not-claimed",
            "paid_provider_operation": "refused-without-credentials",
            "paid_provider_calls": 0,
        },
        "production_authority": "not-established",
        "scotty_application_job_dispatch": "not-yet-wired",
        "remaining_activation_gates": record["remaining_activation_gates"],
    }


def qualification_observation(application: str, directory: Path = ROOT) -> dict[str, Any]:
    """Expose recorded real execution separately from current installation or authority."""
    if application not in APPLICATIONS:
        raise Refused("unknown application")
    root = directory / application
    path = root / {
        "dify": "mac-qualification-record.json",
        "openshorts": "qualification/result.json",
    }.get(application, "native-mac.json")
    if not path.exists():
        return {"status": "not-recorded", "runtime_observed_now": False}
    if path.is_symlink():
        raise Refused("linked qualification record")
    record = read_json(path)
    if application == "dify":
        return _dify_qualification_observation(root, record)
    if application == "openshorts":
        return _openshorts_qualification_observation(root, record)
    if (
        record.get("schema") != "rapp-dock-application-qualification/1"
        or record.get("application") != application
        or record.get("production_authority") != "not-established"
        or record.get("scotty_application_job_dispatch") != "not-yet-wired"
        or record.get("image_published") is not False
        or record.get("platform") not in {"linux/amd64", "linux/arm64"}
    ):
        raise Refused("unreviewed qualification record")
    _verify_qualification_inputs(root, record.get("inputs"))
    runtime = record["runtime"]
    if (
        runtime["network_mode"] != "none" or runtime["published_ports"] != []
        or runtime["read_only_root"] is not True
        or runtime["user"] != "10001:10001"
        or runtime["no_new_privileges"] is not True
        or runtime["dropped_capabilities"] != ["ALL"]
    ):
        raise Refused("qualification isolation differs from reviewed contract")
    return {
        "status": "recorded-real-qualification",
        "runtime_observed_now": False,
        "platform": record["platform"],
        "scope": record["scope"],
        "upstream_image": record["upstream_image"],
        "derived_local_image": record["observed_local_image_id"],
        "application_api": record["application_api"],
        "source_assurance": record.get("assurance", record.get("source_assurance")),
        "production_authority": "not-established",
        "scotty_application_job_dispatch": "not-yet-wired",
    }


def inspect(application: str, directory: Path = ROOT) -> dict[str, Any]:
    recipe = load_recipe(application, directory)
    compose_input(recipe, "/share/CACHEDEV1_DATA/RAPP-Dock", audit=True)
    blockers = list(recipe.get("render_blockers", []))
    blockers += [f"{name}: {pin['blocker']}" for name, pin in recipe["images"].items() if pin["reference"] is None]
    blockers += [
        f"{name}: source/image revision relationship is unresolved"
        for name in recipe.get("source_image_services", [])
        if recipe["images"][name]["reference"] and not recipe["images"][name].get("source_revision")
    ]
    return {
        "application": application,
        "source_commit": recipe["_source"]["commit"],
        "static_validation": "passed",
        "renderable": not blockers,
        "sdk_executor_qualified": False,
        "render_blockers": blockers,
        "runtime_gates": [SDK_RUNTIME_GATE, *recipe["runtime_gates"]],
        "admission": recipe["admission"],
        "installation_state": "not_observed",
        "installation_performed": False,
        "recorded_qualification": qualification_observation(application, directory),
    }


def paid_call_inventory(application: str | None = None) -> dict[str, Any]:
    """Return only reviewed public metadata; never inspect credentials or make a call."""
    if application is not None and application not in APPLICATIONS:
        raise Refused("unknown application")
    catalog = read_json(ROOT / "paid-integrations.json")
    if set(catalog) != {"format_version", "coverage", "entries"} or catalog["format_version"] != 1:
        raise Refused("unreviewed integration inventory format")
    sources = {app: read_json(ROOT / app / "source.lock.json") for app in APPLICATIONS}
    seen = set()
    entries = []
    for item in catalog["entries"]:
        if set(item) != {"id", "application", "provider", "operation", "billing", "needed_credentials", "source_files"}:
            raise Refused("integration inventory may contain only reviewed metadata")
        app = item["application"]
        if app not in APPLICATIONS or not re.fullmatch(r"[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*", item["id"]) or item["id"] in seen:
            raise Refused("invalid or duplicate integration identifier")
        seen.add(item["id"])
        reviewed_paths = {entry["path"] for entry in sources[app]["reviewed_source_files"]}
        if not item["source_files"] or not set(item["source_files"]).issubset(reviewed_paths):
            raise Refused("integration lacks reviewed upstream evidence")
        for requirement in item["needed_credentials"]:
            if set(requirement) != {"name", "kind"} or requirement["kind"] not in {"environment-variable", "upstream-provider-setting"}:
                raise Refused("credential requirements are names only, never values")
            if requirement["kind"] == "environment-variable" and not ENV_NAME.fullmatch(requirement["name"]):
                raise Refused("invalid credential environment name")
        if application is not None and app != application:
            continue
        entries.append({
            **copy.deepcopy(item),
            "mode": "stub",
            "status": "blocked",
            "label": "STUB: no provider call made; no provider result generated",
            "llm_inferred": False,
            "credential_state": "not_checked",
            "estimated_cost": {"status": "unknown", "amount": None, "currency": None},
            "source_commit": sources[app]["commit"],
            "outbound_calls_performed": 0,
            "result": None,
            "generated_artifacts": [],
            "activation_requires": ["explicit provider/model selection", "credential custody", "owner-approved budget and data egress", "qualified SDK integration"],
        })
    return {
        "format_version": 1,
        "mode": "stub",
        "label": "STUB INVENTORY: deterministic local metadata, not LLM-inferred or provider-produced",
        "llm_inferred": False,
        "coverage": catalog["coverage"],
        "outbound_calls_performed": 0,
        "entries": sorted(entries, key=lambda item: item["id"]),
    }


def stub_paid_call(integration_id: str) -> dict[str, Any]:
    """Describe a blocked intended operation; do not accept or persist private inputs."""
    for entry in paid_call_inventory()["entries"]:
        if entry["id"] == integration_id:
            return entry
    raise Refused("unknown integration identifier")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    check = sub.add_parser("check", help="offline source, image, overlay and safety checks")
    check.add_argument("application", choices=APPLICATIONS, nargs="?")
    render = sub.add_parser("render", help="print inert Compose JSON; does not authorize any effect")
    render.add_argument("application", choices=APPLICATIONS)
    render.add_argument("--private-root", required=True)
    inventory = sub.add_parser("paid-inventory", help="print persistable, sanitized STUB metadata; no outbound calls")
    inventory.add_argument("application", choices=APPLICATIONS, nargs="?")
    stub = sub.add_parser("stub-paid-call", help="describe a blocked operation; never synthesize a provider result")
    stub.add_argument("integration_id")
    args = parser.parse_args()
    try:
        if args.operation == "check":
            result: Any = [inspect(app) for app in ((args.application,) if args.application else APPLICATIONS)]
        elif args.operation == "render":
            result = compose_input(load_recipe(args.application), args.private_root)
        elif args.operation == "paid-inventory":
            result = paid_call_inventory(args.application)
        else:
            result = stub_paid_call(args.integration_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2 if args.operation == "stub-paid-call" else 0
    except (Refused, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
