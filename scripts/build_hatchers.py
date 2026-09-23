"""Generate inert-on-import, explicit-install hatchers for verified current Grail.

The complete package and the shared stdlib installer are embedded. Native
desktop listings and historical cartridges are not given a fallback installer.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import rapp_package

ROOT = Path(__file__).resolve().parent.parent


def render_hatcher(blob):
    sha = rapp_package.digest(blob)
    manifest, _ = rapp_package.read_package(blob, sha)
    rapp_package.require_supported(manifest)
    class_name = (
        "".join(part.capitalize() for part in manifest["id"].split("_"))
        + "HatcherAgent"
    )
    metadata = {
        "schema": "rapp-agent/1.0",
        "name": manifest["publisher"] + "/" + manifest["id"] + "_hatcher",
        "version": manifest["version"],
        "description": "Explicit current-Grail application installer; import and inspect have no installation effects.",
    }
    implementation = Path(rapp_package.__file__).read_text()
    footer = f"""

import base64
try:
    from agents.basic_agent import BasicAgent
except ModuleNotFoundError:
    raise RuntimeError("This installer needs the current Grail BasicAgent; do not auto-install a substitute.") from None

__manifest__ = {metadata!r}
_PACKAGE_SHA256 = {sha!r}
_PACKAGE_B64 = {base64.b64encode(blob).decode("ascii")!r}
_HATCHER_PATH = _absolute(__file__)
_HATCHER_IMPORTED_SHA256 = digest(_read_regular(_HATCHER_PATH))


class {class_name}(BasicAgent):
    def __init__(self):
        super().__init__(name={manifest["id"] + "_install"!r}, metadata={{
            "name": {manifest["id"] + "_install"!r},
            "description": "Inspect, install, or preserving-uninstall the complete application on unchanged current Grail. Uninstall drains/stops through the verified controller and removes only owned source, never data or volumes. The exact unchanged transient hatcher retires after success. Local Docker apps need separate image materialization and adopter authentication.",
            "parameters": {{"type": "object", "properties": {{
                "action": {{"type": "string", "enum": ["inspect", "install", "uninstall"]}},
                "confirm": {{"type": "boolean", "description": "Optional explicit consent; install/uninstall already requests that operation."}},
            }}, "required": ["action"], "additionalProperties": False}},
        }})

    def perform(self, **kwargs):
        try:
            if set(kwargs) - {{"action", "confirm"}}:
                raise PackageError("E_ACTION: unsupported installer arguments; there is no force bypass")
            if "confirm" in kwargs and type(kwargs["confirm"]) is not bool:
                raise PackageError("E_ACTION: confirm must be boolean when present")
            action = kwargs.get("action", "inspect")
            blob = base64.b64decode(_PACKAGE_B64, validate=True)
            manifest, _ = read_package(blob, _PACKAGE_SHA256)
            require_supported(manifest)
            if action == "inspect":
                return json.dumps({{
                    "status": "package_verified", "installed": False,
                    "device_checked": False, "runtime": GRAIL, "application": manifest,
                    "note": "Static integrity and support only. Explicit install checks Python, current Grail, dependencies, collisions, and Docker/Compose when required. No credentials are requested or copied.",
                }})
            if action not in ("install", "uninstall"):
                raise PackageError("E_ACTION: use inspect, install, or preserving uninstall")
            if kwargs.get("confirm") is False:
                raise PackageError("E_CONFIRMATION_REQUIRED: the operation was explicitly declined")
            if _HATCHER_PATH.parent.name != "agents":
                raise PackageError("E_HATCHER: place the generated installer in the target Grail agents directory")
            operation = install_package if action == "install" else uninstall_package
            return json.dumps(operation(
                blob, _PACKAGE_SHA256, _HATCHER_PATH.parent.parent,
                retire_hatcher={{"name": _HATCHER_PATH.name, "sha256": _HATCHER_IMPORTED_SHA256}},
            ))
        except (PackageError, OSError, ValueError) as exc:
            return json.dumps({{"status": "refused", "error": str(exc)}})
"""
    source = implementation.rstrip() + "\n" + footer
    compile(source, manifest["id"] + "_hatcher_agent.py", "exec")
    return source.encode()


def write_immutable(path, blob):
    path = Path(path)
    existing = rapp_package._optional_read(path)
    if existing is not None:
        if existing != blob:
            raise rapp_package.PackageError(
                "E_IMMUTABLE_ARTIFACT: refusing to overwrite " + str(path)
            )
        return
    rapp_package._private_directory(path.parent)
    rapp_package._write_new(path, blob, mode=0o644)


def artifact_names(manifest, package, hatcher):
    stem = manifest["id"] + "-" + manifest["version"]
    return (
        stem + "-" + rapp_package.digest(package) + ".egg",
        manifest["id"]
        + "_"
        + manifest["version"].replace(".", "_")
        + "_"
        + rapp_package.digest(hatcher)
        + "_hatcher_agent.py",
    )


def write_artifacts(root, manifest, package):
    decoded, files = rapp_package.read_package(package, rapp_package.digest(package))
    if decoded != manifest:
        raise rapp_package.PackageError(
            "E_PACKAGE_IDENTITY: artifact metadata differs from the pinned package"
        )
    rapp_package.require_installable(manifest, files)
    hatcher = render_hatcher(package)
    egg_name, hatcher_name = artifact_names(manifest, package, hatcher)
    api = Path(root) / "api" / "v1"
    write_immutable(api / "egg" / egg_name, package)
    write_immutable(api / "hatcher" / hatcher_name, hatcher)
    return egg_name, hatcher_name


def main():
    catalog = json.loads((ROOT / "index.json").read_text())
    for entry in catalog["rapplications"]:
        if not entry.get("installable") or entry.get("desktop"):
            continue
        rapp_package.relative_path(entry["package_filename"])
        blob = (ROOT / "api" / "v1" / "egg" / entry["package_filename"]).read_bytes()
        manifest, _ = rapp_package.read_package(blob, entry["package_sha256"])
        write_artifacts(ROOT, manifest, blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
