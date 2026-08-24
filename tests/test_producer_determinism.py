"""The catalog producer must be a pure function of apps/.

Wall-clock stamps (in egg manifests or zip member headers) once made every
build rewrite every egg's bytes — which silently broke every published
egg_sha256 pin on the next push. This guards the invariant: building twice
from the same tree yields byte-identical output.
"""
import hashlib
import pathlib
import shutil
import subprocess
import sys

_REPO = pathlib.Path(__file__).resolve().parent.parent


def _tree_digest(root: pathlib.Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            h.update(str(path.relative_to(root)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def test_two_builds_are_byte_identical(tmp_path):
    # Isolated copy: apps/ + the producer, no .git — exercises the
    # deterministic fallback stamp as well as the zip member stamps.
    work = tmp_path / "store"
    (work / "scripts").mkdir(parents=True)
    shutil.copytree(_REPO / "apps", work / "apps", symlinks=False)
    shutil.copy(_REPO / "scripts" / "build_pokedex_api.py", work / "scripts")

    digests = []
    for _ in range(2):
        subprocess.run(
            [sys.executable, "scripts/build_pokedex_api.py"],
            cwd=work, check=True, capture_output=True, timeout=300,
        )
        digests.append(_tree_digest(work / "api" / "v1"))
        shutil.rmtree(work / "api")
    assert digests[0] == digests[1], (
        "producer output drifted between two identical runs — a wall-clock "
        "or ordering dependency crept back in"
    )
