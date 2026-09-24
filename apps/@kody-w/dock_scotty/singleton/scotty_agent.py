"""Generated user-agent entrypoint template: private, byte-bound support imports.

The packager binds an immutable support revision through a separately routed
descriptor. Stable bootstrap bytes avoid timestamp/size bytecode-cache aliases.
This file is not an engine, installer, or mutable global import shim.
"""

from __future__ import annotations

import builtins as _builtins
import hashlib as _hashlib
import importlib as _importlib
import json as _json
import os as _os
import re as _re
import stat as _stat
import sys as _sys
import threading as _threading
import types as _types
from pathlib import Path as _Path

_LOADER_CONTRACT = "scotty-revision-loader/1"
_MAX_FILE = 4 * 1024 * 1024
_MAX_TOTAL = 32 * 1024 * 1024
_REGISTRY_NAME = "_rapp_scotty_revision_registry"


def _refuse():
    raise RuntimeError(
        "Scotty revision support is incomplete, changed, unsafe, or incompatible."
    )


def _read(path):
    descriptor = None
    file_fd = None
    try:
        path = _Path(_os.path.abspath(path))
        descriptor = _os.open(
            path.anchor, _os.O_RDONLY | _os.O_DIRECTORY | _os.O_NOFOLLOW
        )
        for component in path.parts[1:-1]:
            child = _os.open(
                component,
                _os.O_RDONLY | _os.O_DIRECTORY | _os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            _os.close(descriptor)
            descriptor = child
        file_fd = _os.open(
            path.name,
            _os.O_RDONLY | _os.O_NOFOLLOW | _os.O_NONBLOCK,
            dir_fd=descriptor,
        )
        before = _os.fstat(file_fd)
        if (
            not _stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > _MAX_FILE
            or before.st_mode & 0o022
        ):
            _refuse()
        with _os.fdopen(file_fd, "rb", closefd=False) as stream:
            data = stream.read(_MAX_FILE + 1)
        after = _os.fstat(file_fd)
        if len(data) > _MAX_FILE or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            _refuse()
        return data
    except (OSError, ValueError, AttributeError):
        _refuse()
    finally:
        if file_fd is not None:
            _os.close(file_fd)
        if descriptor is not None:
            _os.close(descriptor)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _refuse()
        value[key] = item
    return value


def _verified(root, revision):
    raw = _read(root / "SCOTTY_CAPABILITY_LOCK.json")
    if _hashlib.sha256(raw).hexdigest() != revision:
        _refuse()
    try:
        manifest = _json.loads(raw, object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError):
        _refuse()
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema", "grail_commit", "files"}
        or manifest["schema"] != "scotty-capability-files/1"
        or manifest["grail_commit"] != "c60521e2cacbcbfa585a118c1275093d7bb15b74"
        or not isinstance(manifest["files"], list)
        or not 1 <= len(manifest["files"]) <= 512
    ):
        _refuse()
    files = {}
    total = 0
    for item in manifest["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
            _refuse()
        name = item["path"]
        if (
            not isinstance(name, str)
            or len(name) > 512
            or name.startswith("/")
            or "\\" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or name in files
            or type(item["bytes"]) is not int
            or not 0 <= item["bytes"] <= _MAX_FILE
            or not isinstance(item["sha256"], str)
            or _re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
            or name == "brainstem.py"
            or any(
                part.startswith((".copilot", ".brainstem")) for part in name.split("/")
            )
        ):
            _refuse()
        data = _read(root / name)
        total += len(data)
        if (
            len(data) != item["bytes"]
            or _hashlib.sha256(data).hexdigest() != item["sha256"]
            or total > _MAX_TOTAL
        ):
            _refuse()
        files[name] = data
    if "agents/scotty_agent.py" not in files:
        _refuse()
    return files


class _SupportScope:
    def __init__(self, root, prefix, files):
        self.root = root
        self.prefix = prefix
        self.files = files
        self.lock = _threading.RLock()
        self.modules = {}
        self.code = {"_entry": "agents/scotty_agent.py"}
        self.packages = {""}
        for path in files:
            if not path.endswith(".py") or path.startswith("agents/"):
                continue
            components = path[:-3].split("/")
            package = components[-1] == "__init__"
            if package:
                components.pop()
            if not components or not all(part.isidentifier() for part in components):
                continue
            name = ".".join(components)
            self.code[name] = path
            for length in range(1, len(components) + (1 if package else 0)):
                self.packages.add(".".join(components[:length]))
        self.importlib = _types.ModuleType("importlib")
        self.importlib.__dict__.update(vars(_importlib))
        self.importlib.import_module = self.import_module

    def local(self, name):
        return name in self.code or name in self.packages

    def import_module(self, name, package=None):
        absolute = (
            _importlib.util.resolve_name(name, package)
            if name.startswith(".")
            else name
        )
        if absolute.startswith(self.prefix + "."):
            absolute = absolute[len(self.prefix) + 1 :]
        if self.local(absolute):
            return self.load(absolute)
        return _importlib.import_module(name, package)

    def import_hook(self, name, globals=None, locals=None, fromlist=(), level=0):
        absolute = name
        if level:
            package = (globals or {}).get("__package__", "")
            absolute = _importlib.util.resolve_name("." * level + name, package)
            if absolute.startswith(self.prefix + "."):
                absolute = absolute[len(self.prefix) + 1 :]
        if absolute == "importlib":
            return self.importlib
        if self.local(absolute):
            module = self.load(absolute)
            if fromlist:
                for child in fromlist:
                    selected = absolute + "." + child
                    if child != "*" and self.local(selected):
                        self.load(selected)
                return module
            return self.load(absolute.split(".")[0])
        return _builtins.__import__(name, globals, locals, fromlist, level)

    def load(self, name):
        with self.lock:
            return self._load(name)

    def _load(self, name):
        if name in self.modules:
            return self.modules[name]
        full_name = self.prefix + ("." + name if name else "")
        path = self.code.get(name)
        module = _types.ModuleType(full_name)
        module.__package__ = (
            full_name if name in self.packages else full_name.rpartition(".")[0]
        )
        if name in self.packages:
            module.__path__ = [str(self.root.joinpath(*name.split(".")))]
        if path is not None:
            module.__file__ = str(self.root / path)
        module.__dict__["__builtins__"] = {
            **vars(_builtins),
            "__import__": self.import_hook,
        }
        self.modules[name] = module
        _sys.modules[full_name] = module
        if name:
            parent_name, _, child = name.rpartition(".")
            setattr(self.load(parent_name), child, module)
        try:
            if path is not None:
                exec(
                    compile(self.files[path], module.__file__, "exec"), module.__dict__
                )
            return module
        except BaseException:
            self.modules.pop(name, None)
            _sys.modules.pop(full_name, None)
            raise


def _entry():
    agent_path = _Path(_os.path.abspath(__file__))
    try:
        selected = _json.loads(
            _read(agent_path.parent / "scotty_revision.json"), object_pairs_hook=_unique
        )
    except (ValueError, UnicodeError, RecursionError):
        _refuse()
    if (
        not isinstance(selected, dict)
        or set(selected)
        != {"schema", "loader_contract", "entrypoint_sha256", "support_sha256"}
        or selected["schema"] != "scotty-agent-revision/1"
        or selected["loader_contract"] != _LOADER_CONTRACT
        or not isinstance(selected["support_sha256"], str)
        or _re.fullmatch(r"[0-9a-f]{64}", selected["support_sha256"]) is None
        or _hashlib.sha256(_read(agent_path)).hexdigest()
        != selected["entrypoint_sha256"]
    ):
        _refuse()
    revision = selected["support_sha256"]
    root = agent_path.parent / ("scotty_support_" + revision)
    files = _verified(root, revision)
    key = (revision, str(root))
    candidate = _types.ModuleType(_REGISTRY_NAME)
    candidate.lock = _threading.RLock()
    candidate.scopes = {}
    registry = _sys.modules.setdefault(_REGISTRY_NAME, candidate)
    with registry.lock:
        if key not in registry.scopes:
            if len(registry.scopes) >= 32:
                _refuse()
            location = _hashlib.sha256(str(root).encode()).hexdigest()[:16]
            prefix = "_rapp_scotty_" + revision + "_" + location
            registry.scopes[key] = _SupportScope(root, prefix, files)
        scope = registry.scopes[key]
        try:
            return scope.load("_entry")
        except (Exception, SystemExit):
            # Never let a missing scoped helper trigger the native loader's auto-pip.
            _refuse()



from agents.basic_agent import BasicAgent

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/dock_scotty",
    "version": "1.0.0",
    "description": "Scotty: operate verified local applications through current Grail.",
}


class ScottyAgent(BasicAgent):
    def __init__(self):
        self._delegate = _entry().ScottyAgent()
        super().__init__(name="Scotty", metadata=self._delegate.metadata)

    def perform(self, **kwargs):
        return self._delegate.perform(**kwargs)

    def system_context(self):
        return self._delegate.system_context()
