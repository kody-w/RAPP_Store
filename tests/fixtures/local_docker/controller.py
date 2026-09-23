"""Synthetic lifecycle fixture only: never accesses Docker, apps or credentials."""

import json
import os
from pathlib import Path


class LocalDock:
    def __init__(self, home, namespace, port_base):
        self.home = Path(home)
        assert self.home == Path(os.environ["RAPP_INSTALL_TEST_STATE"])
        self.owner_home = Path.home()
        self.namespace = namespace
        self.port_base = port_base
        self.ops = self
        self.record = None

    @classmethod
    def for_installation(cls, *, home, namespace, port_base):
        return cls(home, namespace, port_base)

    def target(self):
        return {
            "home": str(self.home),
            "namespace": self.namespace,
            "port_base": self.port_base,
        }

    def pause_for_detach(self):
        (self.home / "synthetic-fence.json").write_text(json.dumps({"paused": True}))
        return self.detach_status()

    def detach_status(self, *, timeout=0):
        assert timeout in (0, 30)
        paused = json.loads((self.home / "synthetic-fence.json").read_text())["paused"]
        return {
            "schema": "rapp-dock-installation-fence/1",
            "target": self.target(),
            "durable": paused,
            "quiesced": True,
            "admission_paused": paused,
            "active_operations": [],
        }

    def resume_after_installation(self):
        (self.home / "synthetic-fence.json").write_text(json.dumps({"paused": False}))
        return {
            "schema": "rapp-dock-installation-fence/1",
            "target": self.target(),
            "durable": False,
            "admission_paused": False,
            "status": "reactivated",
        }

    def lifecycle(self, action, app, *, wait_seconds):
        assert (action, app, wait_seconds) == ("stop", None, 10)
        self.record = {
            "id": "op-0000000000-00000000",
            "kind": "lifecycle",
            "name": "stop",
            "application": None,
            "namespace": self.namespace,
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
