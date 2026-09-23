"""Run only in an owned, byte-pinned Grail copy; no server or inference is started."""

import hashlib
import json
import os
import py_compile
import socket
import subprocess
import sys
from pathlib import Path


root, hatcher_name, state = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
assert root.is_absolute() and ".brainstem" not in root.parts
assert Path.home() == root.parent / "isolated-home"
sys.path.insert(0, str(root))
os.chdir(root)

import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: None


def no_network(*args, **kwargs):
    raise AssertionError("isolated loader must never contact a network service")


socket.socket.connect = no_network
import brainstem

assert hashlib.sha256((root / "brainstem.py").read_bytes()).hexdigest() == (
    "35618683ebc3d1c2bfaff47f60182fd756f3a8de53c53dd907ec1099d631930a"
)
assert hashlib.sha256((root / "agents/basic_agent.py").read_bytes()).hexdigest() == (
    "701488bc00d536a7b23295e7da99c62f24e9b00f233daa325886430c736b78eb"
)


def no_pip(*args, **kwargs):
    raise AssertionError("no scoped-load failure may reach Grail auto-pip")


brainstem._auto_install = no_pip
real_run = subprocess.run
commands = []


def versions_only(argv, **kwargs):
    assert Path(argv[0]).name == "docker", argv
    assert argv[1:] in (
        ["--version"],
        ["compose", "version", "--short"],
        ["buildx", "version"],
    ), argv
    commands.append(argv[1:])
    if argv[1:] == ["buildx", "version"]:
        return subprocess.CompletedProcess(
            argv, 0, b"synthetic Buildx version fixture\n", b""
        )
    return real_run(argv, **kwargs)


subprocess.run = versions_only
hatcher_path = root / "agents" / hatcher_name
hatcher_source = hatcher_path.read_bytes()
assert not (root / ".brainstem_data/rapplications").exists()
loaded = brainstem.load_agents()
assert list(loaded) == ["dock_fixture_install"], loaded
agent = loaded["dock_fixture_install"]
assert json.loads(agent.perform(action="inspect"))["device_checked"] is False
assert commands == [] and not (root / ".brainstem_data/rapplications").exists()

result = json.loads(agent.perform(action="install"))
assert result["status"] == "installed", result
assert not hatcher_path.exists(), (
    "only the exact hash-owned transient hatcher must retire"
)
assert commands == [
    ["--version"],
    ["compose", "version", "--short"],
    ["buildx", "version"],
], commands
assert json.loads(agent.perform(action="install"))["status"] == "already_installed"
py_compile.compile(str(root / "agents/scotty_agent.py"), doraise=True)
loaded = brainstem.load_agents()
assert list(loaded) == ["Scotty"], loaded
assert brainstem._quarantine_snapshot() == []
assert json.loads(loaded["Scotty"].perform()) == {
    "status": "fixture-only",
    "jobs_run": 0,
}

support = next((root / "agents").glob("scotty_support_*"))
assert not list(support.rglob("__pycache__"))
selected_asset = support / "assets/synthetic.txt"
original = selected_asset.read_bytes()
selected_asset.chmod(0o600)
selected_asset.write_bytes(b"tamper")
selected_asset.chmod(0o400)
assert brainstem.load_agents() == {}, (
    "changed scoped bytes must fail even with a cached support module"
)
selected_asset.chmod(0o600)
selected_asset.write_bytes(original)
selected_asset.chmod(0o400)
assert list(brainstem.load_agents()) == ["Scotty"]

runtime = agent.perform.__func__.__globals__
blob = runtime["base64"].b64decode(runtime["_PACKAGE_B64"])
sha = runtime["_PACKAGE_SHA256"]
preserved = {
    name: (state / name).read_bytes()
    for name in (
        "application-state.bin",
        "volume-state.bin",
        "identity.bin",
        "output.bin",
    )
}
hatcher_path.write_bytes(hatcher_source)
loaded = brainstem.load_agents()
assert set(loaded) == {"Scotty", "dock_fixture_install"}
detached = json.loads(loaded["dock_fixture_install"].perform(action="uninstall"))
assert detached["status"] == "detached", detached
assert detached["data_deleted"] is False
assert not hatcher_path.exists()
assert brainstem.load_agents() == {}
assert not support.exists()
assert list((root / "agents/__pycache__").glob("scotty_agent.*.pyc")), (
    "unowned framework cache must be retained"
)
assert json.loads((state / "synthetic-fence.json").read_text()) == {"paused": True}
assert all(
    (state / name).read_bytes() == contents for name, contents in preserved.items()
)

hatcher_path.write_bytes(hatcher_source)
loaded = brainstem.load_agents()
assert list(loaded) == ["dock_fixture_install"]
reinstalled = json.loads(loaded["dock_fixture_install"].perform(action="install"))
assert reinstalled["status"] == "installed", reinstalled
assert reinstalled["runtime_resume"] == "resumed-after-preserving-reinstall"
assert json.loads((state / "synthetic-fence.json").read_text()) == {"paused": False}
assert all(
    (state / name).read_bytes() == contents for name, contents in preserved.items()
)
assert list(brainstem.load_agents()) == ["Scotty"]
assert not hatcher_path.exists()
assert brainstem._quarantine_snapshot() == []

print(
    "STORE_GRAIL_PROOF="
    + json.dumps(
        {
            "runtime": "unchanged-Grail-0.6.16",
            "package_sha256": sha,
            "agents": ["Scotty"],
            "bootstrap": os.environ["S2_BOOTSTRAP_MODE"],
            "application": "synthetic-only",
            "jobs_verified": False,
            "import_effects": False,
            "support_tamper_refused": True,
            "preserving_detach_reinstall": True,
            "docker_commands": commands,
            "buildx_probe": "fixture-only-not-live",
        }
    )
)
