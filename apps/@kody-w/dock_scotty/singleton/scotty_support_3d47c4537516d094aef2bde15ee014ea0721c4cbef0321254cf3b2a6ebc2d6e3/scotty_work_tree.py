"""Explicit optional Work adapter. Importing the standalone agent does not import Work."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from scotty_distribution import DistributionRefused, load_json


def from_scope_file(path: Path) -> Any:
    scope = load_json(path, private=True)
    if (
        not isinstance(scope, dict)
        or set(scope) != {"schema", "adapter", "root", "owner_label", "world_id"}
        or scope["schema"] != "scotty-work-tree-scope/1"
        or scope["adapter"] != "rapp-work"
        or not all(
            isinstance(scope[key], str) and scope[key]
            for key in ("root", "owner_label", "world_id")
        )
        or not Path(scope["root"]).is_absolute()
    ):
        raise DistributionRefused("invalid explicit Work tree scope")
    if importlib.util.find_spec("rapp_work") is None:
        raise DistributionRefused("optional Work adapter is not installed")
    from rapp_work.errors import Refusal

    from dock_tree import DockTree

    try:
        tree = DockTree(Path(scope["root"]), scope["owner_label"], scope["world_id"])
    except Refusal:
        raise DistributionRefused("explicit Work tree is unavailable") from None

    def selected_status() -> dict[str, Any]:
        try:
            return tree.status()
        except Refusal:
            raise DistributionRefused(
                "explicit Work tree scope could not be verified"
            ) from None

    return selected_status
