"""Synthetic lifecycle fixture only: never accesses Docker, apps or credentials."""

import json
import os
from pathlib import Path


class LocalDock:
    def __init__(self, home):
        self.home = Path(home)
        assert self.home == Path(os.environ["RAPP_INSTALL_TEST_STATE"])
        self.owner_home = Path.home()
        self.namespace = os.environ["RAPP_DOCK_NAMESPACE"]
        self.port_base = int(os.environ.get("RAPP_DOCK_PORT_BASE", "18080"))
        self.ops = self
        self.record = None

    @classmethod
    def shared(cls, home=None):
        assert home is not None, "ambient runtime target must never be selected"
        return cls(home)

    def lifecycle(self, action, app, *, wait_seconds):
        assert (action, app, wait_seconds) == ("stop", None, 10)
        self.record = {
            "id": "op-0000000000-00000000",
            "kind": "lifecycle",
            "name": "stop",
            "application": None,
            "scope": ["synthetic"],
            "status": "succeeded",
            "result": {
                "scope": ["synthetic"],
                "stopped": True,
                "data_deleted": False,
                "unrelated_projects_changed": [],
            },
        }
        return {name: value for name, value in self.record.items() if name != "scope"}

    def get(self, operation_id):
        assert self.record["id"] == operation_id
        return self.record


def quiesce(*, timeout, home):
    assert home.is_dir() and timeout in (0, 30)
    (home / "synthetic-fence.json").write_text(json.dumps({"paused": True}))
    return {"quiesced": True, "admission_paused": True, "active_operations": []}


def resume(*, home):
    (home / "synthetic-fence.json").write_text(json.dumps({"paused": False}))
