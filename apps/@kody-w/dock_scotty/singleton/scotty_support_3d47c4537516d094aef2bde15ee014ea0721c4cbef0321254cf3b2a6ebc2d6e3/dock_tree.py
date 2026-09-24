"""Compose the dedicated Dock tree using existing RAPP Work SDK operations.

This is use-case routing, not a second workspace implementation. Every write
is performed by the SDK against the complete explicitly approved plan.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rapp_work import Organization, ReleasePlan, Workspace, scaffold
from rapp_work._json import canonical_bytes, closed_object, strict_json_loads
from rapp_work._paths import absolute_path, private_directory, read_regular
from rapp_work.errors import Refusal, require

WORKSPACES = ("scotty", "scrapling", "dify", "open-seo", "openshorts", "presenton")


@dataclass(frozen=True)
class DockTree:
    root: Path
    owner_label: str
    world_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", absolute_path(self.root))
        # Provisioning a QNAP share is a separate approved host operation.
        private_directory(self.root)

    def _request(self, name: str) -> dict[str, str]:
        return {
            "kind": "organization" if name == "organization" else "workspace",
            "mode": "hive",
            "owner_label": self.owner_label,
            "root": str(self.root / name),
            "slug": "rapp-dock" if name == "organization" else name,
            "world_id": self.world_id,
        }

    def _load(self, name: str) -> Organization | Workspace:
        request = self._request(name)
        root = Path(request["root"])
        subject = Organization.load(root) if name == "organization" else Workspace.load(root)
        identity = subject.identity
        require(
            identity["world_id"] == self.world_id
            and identity["name"] == request["slug"]
            and identity["mode"] == "hive"
            and identity["rappid"].startswith(f"rappid:@{self.owner_label}/"),
            "REFUSE_DOCK_SUBJECT",
            "existing workspace does not match the selected Dock tree",
            name=name,
        )
        subject.verify()
        return subject

    def status(self) -> dict[str, Any]:
        entries = []
        for name in ("organization", *WORKSPACES):
            path = self.root / name
            if path.exists() or path.is_symlink():
                subject = self._load(name)
                entries.append(
                    {"name": name, "status": "verified", "rappid": subject.identity["rappid"]}
                )
            else:
                entries.append({"name": name, "status": "absent"})
        return {
            "root": str(self.root),
            "world_id": self.world_id,
            "entries": entries,
            "hive_authority": "requires-independent-authenticated-adoption",
            "deployment_authority": "not-granted-by-scaffolding",
        }

    def plan_next(self) -> dict[str, Any]:
        # Validate every existing object before planning even the first write.
        self.status()
        for name in ("organization", *WORKSPACES):
            if not (self.root / name).exists():
                request = self._request(name)
                result = scaffold(request)
                require(
                    result["status"] == "planned",
                    "REFUSE_DOCK_SCAFFOLD",
                    "SDK could not plan this workspace",
                    refusal=result.get("refusal"),
                )
                return {
                    "operation": "scaffold",
                    "name": name,
                    "sdk_request": request,
                    "plan": result["result"]["plan"],
                    "plan_sha256": result["result"]["plan_sha256"],
                }
        organization = Organization.load(self.root / "organization")
        pointers = organization.pointers()
        expected_paths = {str(self.root / name) for name in WORKSPACES}
        require(
            all(pointer["path"] in expected_paths for pointer in pointers),
            "REFUSE_DOCK_POINTER",
            "organization contains an unenrolled workspace",
        )
        for name in WORKSPACES:
            workspace = Workspace.load(self.root / name)
            identity = workspace.identity
            matching = [
                pointer for pointer in pointers
                if pointer["path"] == str(workspace.root) or pointer["rappid"] == identity["rappid"]
            ]
            expected = {
                "active": True,
                "mode": "hive",
                "name": name,
                "path": str(workspace.root),
                "rappid": identity["rappid"],
                "world_id": self.world_id,
            }
            if matching:
                require(
                    matching == [expected],
                    "REFUSE_DOCK_POINTER",
                    "registered workspace identity or world has changed",
                    name=name,
                )
                continue
            plan = organization.plan_register(workspace)
            return {
                "operation": "register",
                "name": name,
                "sdk_request": {"root": str(self.root), "world_id": self.world_id},
                "plan": plan.to_dict(),
                "plan_sha256": plan.sha256,
            }
        return {
            "operation": "none",
            "status": "tree-scaffolded",
            "hive_authority": "requires-independent-authenticated-adoption",
            "deployment_authority": "not-granted-by-scaffolding",
        }

    def apply(self, value: dict[str, Any], *, approved_sha256: str) -> dict[str, Any]:
        item = closed_object(
            value,
            required={"operation", "name", "sdk_request", "plan", "plan_sha256"},
            where="Dock SDK routing plan",
        )
        require(
            isinstance(item["name"], str)
            and item["name"] in ("organization", *WORKSPACES),
            "REFUSE_DOCK_SUBJECT",
            "unknown Dock workspace",
        )
        plan = ReleasePlan.from_dict(item["plan"])
        require(
            plan.sha256 == item["plan_sha256"] == approved_sha256,
            "REFUSE_PLAN_HASH",
            "complete plan and exact owner-approved SHA-256 are required",
        )
        self.status()
        if item["operation"] == "scaffold":
            request = self._request(item["name"])
            require(
                item["sdk_request"] == request,
                "REFUSE_DOCK_SUBJECT",
                "SDK request differs from selected Dock workspace",
            )
            return scaffold(
                {
                    **request,
                    "apply": True,
                    "plan": plan.to_dict(),
                    "plan_sha256": approved_sha256,
                }
            )
        require(
            item["operation"] == "register" and item["name"] in WORKSPACES,
            "REFUSE_DOCK_OPERATION",
            "only SDK scaffolding and pointer registration are supported",
        )
        current = self.plan_next()
        require(
            current == item,
            "REFUSE_PRECONDITION",
            "tree changed after pointer registration was planned",
        )
        return Organization.load(self.root / "organization").apply_register(
            Workspace.load(self.root / item["name"]),
            plan,
            plan_sha256=approved_sha256,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("status", "plan", "apply"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--owner-label", required=True)
    parser.add_argument("--world-id", required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--approved-sha256")
    args = parser.parse_args()
    try:
        tree = DockTree(args.root, args.owner_label, args.world_id)
        if args.operation == "apply":
            require(
                args.plan is not None and args.approved_sha256 is not None,
                "REFUSE_APPLY_REQUIRED",
                "apply requires the saved complete plan and approved hash",
            )
            value = strict_json_loads(read_regular(args.plan), where="saved Dock plan")
            result = tree.apply(value, approved_sha256=args.approved_sha256)
        else:
            require(
                args.plan is None and args.approved_sha256 is None,
                "REFUSE_INPUT_SHAPE",
                "approval arguments are only accepted by apply",
            )
            result = tree.status() if args.operation == "status" else tree.plan_next()
    except Refusal as error:
        print(json.dumps({"status": "refused", "error": str(error)}))
        return 1
    print(canonical_bytes(result).decode())
    return 1 if result.get("status") == "refused" else 0


if __name__ == "__main__":
    raise SystemExit(main())
