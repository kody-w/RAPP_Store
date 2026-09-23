#!/usr/bin/env python3
"""Build the synthetic, unlisted authoring fixture; never fetch or execute apps."""
import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GRAIL = {
    "repo": "microsoft/aibast-agents-library",
    "commit": "c60521e2cacbcbfa585a118c1275093d7bb15b74",
    "version": "0.6.16",
}
AUTHORED = (
    "README.md", "source/scotty_agent.py", "source/scotty_implementation.py",
    "generated/host-profiles.json", "generated/state-lifecycle.json",
    "generated/job-contracts.json", "tools/build_template.py",
)


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def component_lock():
    declarations = (
        ("intelligence", "https://github.com/github/copilot-cli", ["cli"], "linux/arm64", []),
        ("presenton", "https://github.com/presenton/presenton", ["application"], "linux/arm64", ["intelligence"]),
        ("scrapling", "https://github.com/D4Vinci/Scrapling", ["fetcher"], "linux/amd64", ["intelligence", "presenton"]),
        ("open-seo", "https://github.com/every-app/open-seo", ["application"], "linux/arm64", []),
        ("dify", "https://github.com/langgenius/dify", ["unqualified-full-stack"], "linux/amd64", ["intelligence"]),
        ("openshorts", "https://github.com/mutonby/openshorts", ["backend", "frontend", "renderer"], "linux/amd64", ["intelligence"]),
    )
    components = []
    for name, url, roles, platform, dependencies in declarations:
        images = [{
            "role": role, "platform": platform, "reference": None,
            "build_recipe": None, "observed_image_id": None,
        } for role in roles]
        if name == "scrapling":
            images.append({
                "role": "presenton-derived-ingress", "platform": "linux/arm64",
                "reference": None, "build_recipe": None, "observed_image_id": None,
            })
        components.append({
            "id": name,
            "source": {"url": url, "revision": None, "bytes": None, "sha256": None},
            "images": images, "inputs": [], "dependencies": dependencies,
            "licenses": {
                "status": "pending", "files": [],
                "note": "Template only: qualify the complete source, dependency, model and license closure before distribution.",
            },
        })
    return {"schema": "rapp-local-components/1", "mode": "template", "components": components}


def build():
    payload = {name: (ROOT / name).read_bytes() for name in AUTHORED}
    jobs = json.loads(payload["generated/job-contracts.json"])["jobs"]
    components = component_lock()
    payload["components.lock.json"] = canonical(components)
    payload["generated/synthetic-evidence.json"] = canonical({
        "schema": "rapp-readiness-evidence/1", "synthetic": True,
        "scope": "authoring-template", "candidate_digest": None,
        "acceptance_suite_revision": None, "observed_at": None,
        "results": [{"job": job["id"], "mode": job["mode"], "status": "pending"} for job in jobs],
        "limitations": [
            "Synthetic authoring fixture, not runtime acceptance evidence.",
            "No fresh installation, application execution or full recreation is claimed.",
            "No owner artifacts, receipts, capsules or credentials are included.",
        ],
    })
    support = payload["source/scotty_implementation.py"]
    inventory = canonical({
        "schema": "scotty-capability-files/1",
        "grail_commit": GRAIL["commit"],
        "files": [{"path": "agents/scotty_agent.py", "bytes": len(support), "sha256": digest(support)}],
    })
    revision = digest(inventory)
    prefix = "singleton/scotty_support_" + revision + "/"
    entrypoint = "singleton/scotty_agent.py"
    payload[entrypoint] = payload["source/scotty_agent.py"]
    payload[prefix + "agents/scotty_agent.py"] = support
    payload[prefix + "SCOTTY_CAPABILITY_LOCK.json"] = inventory
    payload["singleton/scotty_revision.json"] = canonical({
        "schema": "scotty-agent-revision/1", "loader_contract": "scotty-revision-loader/1",
        "entrypoint_sha256": digest(payload[entrypoint]), "support_sha256": revision,
    })
    statuses = {component["id"]: "pending" for component in components["components"]}
    manifest = {
        "schema": "rapp-application/2.0",
        "id": "dock_scotty", "name": "RAPP Dock / Scotty authoring template",
        "version": "0.1.0", "publisher": "@example",
        "summary": "Synthetic, experimental template for one chat-operated application with five local journeys; not an installable release.",
        "category": "platform",
        "tags": ["rapplication", "chat-operated", "local-docker", "template"],
        "quality_tier": "experimental", "license": "LicenseRef-Template-Review-Required",
        "agent": entrypoint, "agents": [entrypoint], "runtime": dict(GRAIL),
        "requires": ["portable-agents/1", "owned-files/1", "local-docker/1"],
        "profiles": [], "permissions": ["host-user"], "capabilities": ["template.describe"],
        "dependencies": [], "services": [],
        "state": {"version": "1", "preserve": True, "seeds": {}},
        "lifecycle": {
            "install": "copy-verified-files", "upgrade": "preserve-state",
            "uninstall": "preserve-state", "recovery": "reinstall-verified-package",
        },
        "providers": {"mode": "host", "spend_limit": None, "egress_allowlist": None},
        "provenance": {
            "status": "development", "source": "synthetic-authoring-template",
            "deployed": False, "job_verified": False,
        },
        "local_docker": {
            "schema": "rapp-local-docker/1",
            "component_lock": "components.lock.json",
            "loader": {
                "contract": "scotty-revision-loader/1", "entrypoint": entrypoint,
                "descriptor": "singleton/scotty_revision.json", "support": prefix,
            },
            "requirements_file": "generated/host-profiles.json",
            "jobs_file": "generated/job-contracts.json",
            "state_lifecycle_file": "generated/state-lifecycle.json",
            "intelligence": {
                "runtime": "official-copilot-cli-in-docker", "version": "1.0.88",
                "model": "gpt-5-mini", "concurrency": 2, "cloud_inference": True,
                "tools": [], "usage": "measured-when-available",
                "monetary_cost": None, "hard_spend_cap": None, "other_paid_providers": "disabled",
            },
            "exhaust": {
                "wire": "rapp/1", "frame_kind": "memory.tool-call",
                "receipt_variant": "session", "capsule_variant": "rapplication",
                "capsule_contains": "selected-outputs-and-producing-source-not-full-app-state",
                "verification": "unsigned-structural-only",
            },
            "readiness": {
                "candidate": "experimental", "package_verification": "pending",
                "fresh_install": "pending",
                "fresh_install_profiles": {"apple-silicon-development": "pending"},
                "jobs": {job["id"]: {"mode": job["mode"], "status": "pending"} for job in jobs},
                "current_health": {"status": "unknown", "observed_at": None},
                "restart": dict(statuses), "recreation": dict(statuses),
                "provider_blockers": [
                    "Adopter-owned Copilot entitlement and authentication required for AI jobs.",
                    "All other paid providers disabled; paid metrics are not available.",
                    "Native Dify model plugin is not installed in the described default mode.",
                ],
                "acceptance_suite": {"revision": None, "status": "pending"},
                "live_results": "generated/synthetic-evidence.json",
            },
        },
        "files": {name: digest(blob) for name, blob in sorted(payload.items())},
    }
    return {**payload, "manifest.json": canonical(manifest)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT)
    args = parser.parse_args()
    output = args.output
    expected = build()
    existing = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()} if output.exists() else set()
    if existing - expected.keys():
        parser.error("Unknown or stale files exist; use a new clean candidate directory, never delete owner state.")
    mismatches = []
    for name, blob in expected.items():
        target = output / name
        if target.is_symlink() or any(parent.is_symlink() for parent in target.parents):
            parser.error("Symlink destinations are forbidden.")
        if not target.is_file() or target.read_bytes() != blob:
            mismatches.append(name)
    if args.check:
        if mismatches:
            parser.exit(1, "Template differs: " + ", ".join(sorted(mismatches)) + "\n")
        print("Synthetic template is deterministic and current; this is not runtime qualification.")
        return
    for name in mismatches:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(expected[name])
    print("Generated synthetic authoring template; no Docker, provider or runtime effects.")


if __name__ == "__main__":
    main()
