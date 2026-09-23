#!/usr/bin/env python3
"""Bind a separately reviewed public Dock closure to the Store contract, without executing it."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys


SAMPLE = Path(__file__).resolve().parents[1]
REPO = SAMPLE.parents[1]
sys.path.insert(0, str(REPO / "scripts"))


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode()


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def candidate_files(payload_root, *, publisher="@example", version=None):
    import rapp_package

    root = Path(payload_root)
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise ValueError("A reviewed distribution must not use symlink roots.")
    layout_path = root / "generated/source-layout.json"
    if not layout_path.is_file() or layout_path.is_symlink() or layout_path.stat().st_size > 256 * 1024:
        raise ValueError("Select the public template directory, never a coordinator/validation directory.")
    layout = json.loads(layout_path.read_bytes())
    if not isinstance(layout, dict) or layout.get("schema") != "scotty-store-template/1" or layout.get("component_lock") != "components.lock.json":
        raise ValueError("Unsupported public source layout.")
    if (root / "manifest.json").exists():
        raise ValueError("Input must be the manifest-free public distribution, not an installed application.")
    files = rapp_package.application_files(root)
    descriptor = json.loads(files["singleton/scotty_revision.json"])
    if not isinstance(descriptor, dict) or not isinstance(descriptor.get("support_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", descriptor["support_sha256"]):
        raise ValueError("The public descriptor must identify an exact support revision.")
    revision = descriptor["support_sha256"]
    if layout.get("capability_lock_sha256") != revision:
        raise ValueError("Public source layout and descriptor disagree.")
    entry = "singleton/scotty_agent.py"
    internal = None
    for node in ast.parse(files[entry]).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__manifest__" for target in node.targets):
            internal = ast.literal_eval(node.value)
    if not isinstance(internal, dict) or internal.get("schema") != "rapp-agent/1.0":
        raise ValueError("The public delegate must have a literal current agent manifest.")
    manifest = json.loads((SAMPLE / "manifest.json").read_text())
    manifest.update(
        name="RAPP Dock / Scotty public source candidate",
        version=internal["version"] if version is None else version, publisher=publisher,
        summary="Experimental chat-operated Dock candidate; source closure only, not a fresh-install or job qualification.",
        provenance={"status": "development", "source": "public-source-candidate:" + revision,
                    "deployed": False, "job_verified": False},
    )
    local = manifest["local_docker"]
    local["loader"]["support"] = "singleton/scotty_support_" + revision + "/"

    def put(name, blob):
        if name in files and files[name] != blob:
            raise ValueError("Refusing to overwrite a distribution member: " + name)
        files[name] = blob

    for key in ("requirements_file", "jobs_file", "state_lifecycle_file"):
        name = local[key]
        put(name, (SAMPLE / name).read_bytes())
    jobs = json.loads(files[local["jobs_file"]])["jobs"]
    manifest["capabilities"] = [job["id"] for job in jobs] + ["rapp/1-receipts", "rapp/1-capsules"]
    evidence_name = "generated/candidate-evidence.json"
    local["readiness"]["live_results"] = evidence_name
    lock = json.loads(files[local["component_lock"]])
    limitations = [
        "New exported source candidate; static package checks do not prove runtime outcomes.",
        "Fresh install, five journeys, preserving reinstall and recreation need candidate-specific acceptance.",
        "Cached image observations do not prove public-only rebuild or fresh-device qualification.",
    ]
    if lock.get("schema") == "rapp-dock-components/1":
        for component in lock["components"].values():
            limitations.extend(component["blockers"])
    else:
        raise ValueError("The real distribution must retain its typed public materializer lock.")
    put(evidence_name, canonical({
        "schema": "rapp-readiness-evidence/1", "synthetic": False,
        "scope": "candidate-verification", "candidate_digest": revision,
        "acceptance_suite_revision": None, "observed_at": None,
        "results": [{"job": job["id"], "mode": job["mode"], "status": "pending"} for job in jobs],
        "limitations": list(dict.fromkeys(limitations)),
    }))
    put("README.md", (
        "# RAPP Dock / Scotty — experimental public source candidate\n\n"
        "One chat-operated application with five declared journeys, running on unchanged current Grail.\n\n"
        "Local application execution; Copilot cloud inference; tested on Apple Silicon with some "
        "amd64 guests under emulation. This is a development reference, not fresh-candidate proof.\n\n"
        "Presenton is gateway-authored/Presenton-exported. Dify uses economy retrieval and gateway-grounded "
        "answers. OpenSEO paid metrics and other paid providers are disabled. Copilot uses adopter-owned "
        "entitlement/usage; unknown monetary cost and hard spend cap remain null.\n\n"
        "Fresh install, jobs, restart/recreation and preserving reinstall remain pending. Inspect "
        "generated/candidate-evidence.json and PUBLIC-INPUTS.md for public-input limitations. "
        "Cached images are not proof of public replay or current device health.\n\n"
        "Canonical RAPP/1 receipts are unsigned structural evidence. Capsules carry selected outputs "
        "and producing source, not full state, images or credentials. Store installation cartridges "
        "are separate. Stop/detach preserves data and unqualified container layers.\n\n"
        "This unlisted source candidate is not an admitted/featured release. Complete source submission "
        "uses commit-pinned public federation and normal maintainer review; no singleton-only fallback.\n"
    ).encode())
    manifest["files"] = {name: digest(blob) for name, blob in sorted(files.items())}
    return manifest, files


def write_candidate(payload_root, output, *, publisher="@example", version=None):
    import lib_rapp
    import rapp_package

    manifest, files = candidate_files(payload_root, publisher=publisher, version=version)
    rapp_package.require_installable(manifest, files)
    errors = lib_rapp._validate_manifest(manifest)
    for name in manifest["agents"]:
        errors.extend(lib_rapp._validate_singleton_bytes(files[name]))
    if errors:
        raise ValueError("; ".join(errors))
    target = Path(output)
    if target.name != manifest["id"]:
        raise ValueError("Output directory must match the application ID.")
    if target.exists() or target.is_symlink() or any(parent.is_symlink() for parent in target.parents):
        raise ValueError("Output must be a new directory with no symlink ancestors.")
    target.mkdir(parents=True, exist_ok=False)
    for name, blob in {**files, "manifest.json": canonical(manifest)}.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(blob)
    return {"files": len(files), "manifest_sha256": digest(canonical(manifest)),
            "support_sha256": manifest["local_docker"]["loader"]["support"].rstrip("/").rsplit("_", 1)[-1],
            "fresh_install": "pending", "job_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--publisher", default="@example")
    parser.add_argument("--version", help="Outer application release version; never rewrites the stable delegate.")
    args = parser.parse_args()
    print(json.dumps(write_candidate(args.payload, args.output, publisher=args.publisher, version=args.version), sort_keys=True))


if __name__ == "__main__":
    main()
