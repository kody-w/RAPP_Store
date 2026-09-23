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
    "generated/job-contracts.json", "tools/build_template.py", "tools/assemble_candidate.py",
)


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def component_lock():
    declarations = (
        ("intelligence", "https://github.com/github/copilot-cli", "linux/arm64"),
        ("presenton", "https://github.com/presenton/presenton", "linux/arm64"),
        ("scrapling", "https://github.com/D4Vinci/Scrapling", "linux/amd64"),
        ("open-seo", "https://github.com/every-app/open-seo", "linux/arm64"),
        ("dify", "https://github.com/langgenius/dify", "linux/amd64"),
        ("openshorts", "https://github.com/mutonby/openshorts", "linux/amd64"),
    )
    components = {
        name: {
            "kind": "blocked-build", "platform": platform,
            "env": "RAPP_DOCK_IMAGE_" + name.upper().replace("-", "_"),
            "reference": None, "recipe": None, "observed_image_ids": [],
            "source": url,
            "license": "Template only; review the complete source, dependency, model and license closure.",
            "blockers": ["Synthetic authoring fixture: no qualified image or complete public build recipe is supplied."],
        } for name, url, platform in declarations
    }
    applications = {name: {"application": name} for name in components}
    applications["scrapling"] = {"scrapling": "scrapling", "browser": "presenton", "egress": "scrapling"}
    return {
        "schema": "rapp-dock-components/1",
        "profile": {
            "host": "darwin/arm64", "docker_context": "desktop-linux",
            "guest_platforms": ["linux/arm64", "linux/amd64"], "amd64_emulation_required": True,
            "assurance": "locked-public-inputs-and-local-image-observations-not-signed-builds",
            "fresh_machine_acceptance": "pending", "bit_identical_rebuilds_claimed": False,
        },
        "artifacts": {}, "input_sets": {}, "components": components, "applications": applications,
    }


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
    support = {
        "agents/scotty_agent.py": payload["source/scotty_implementation.py"],
        "deploy/local/components.lock.json": payload["components.lock.json"],
    }
    inventory = canonical({
        "schema": "scotty-capability-files/1",
        "grail_commit": GRAIL["commit"],
        "files": [{"path": name, "bytes": len(blob), "sha256": digest(blob)}
                  for name, blob in sorted(support.items())],
    })
    revision = digest(inventory)
    prefix = "singleton/scotty_support_" + revision + "/"
    entrypoint = "singleton/scotty_agent.py"
    payload[entrypoint] = payload["source/scotty_agent.py"]
    payload.update({prefix + name: blob for name, blob in support.items()})
    payload[prefix + "SCOTTY_CAPABILITY_LOCK.json"] = inventory
    payload["singleton/scotty_revision.json"] = canonical({
        "schema": "scotty-agent-revision/1", "loader_contract": "scotty-revision-loader/1",
        "entrypoint_sha256": digest(payload[entrypoint]), "support_sha256": revision,
    })
    statuses = {name: "pending" for name in components["applications"]}
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
                "descriptor": "singleton/scotty_revision.json", "support": prefix.rstrip("/"),
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
