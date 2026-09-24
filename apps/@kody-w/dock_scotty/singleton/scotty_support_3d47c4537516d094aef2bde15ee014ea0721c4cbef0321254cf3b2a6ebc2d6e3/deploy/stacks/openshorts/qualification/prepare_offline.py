"""Stage hash-verified public build inputs; never download, build, deploy or read credentials."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from prepare_context import prepare


HERE = Path(__file__).resolve().parent
LOCKS = HERE / "offline-locks"


def copy_checked(source, target, expected, algorithm="sha256"):
    if source.is_symlink() or not source.is_file():
        raise ValueError("required artifact is missing or symlinked")
    with source.open("rb") as stream:
        actual = hashlib.file_digest(stream, algorithm).hexdigest()
    if actual != expected:
        raise ValueError("artifact digest mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o644)


def stage(source_archive, assets, output, role):
    if assets.is_symlink() or not assets.is_dir():
        raise ValueError("assets must be an explicit existing directory")
    result = prepare(source_archive, output)
    # Each output is new and contains only the exact public archive from prepare().
    (output / ".dockerignore").unlink()
    for script in ("offline-npm-lock.mjs", "frontend-build.sh"):
        shutil.copyfile(HERE / script, output / "qualification" / script)
    if role == "frontend":
        manifests = [json.loads((HERE / "frontend-artifacts.json").read_text())]
        shutil.copyfile(HERE / "frontend-artifacts.json", output / "frontend-artifacts.json")
    elif role == "renderer":
        manifests = []
        original = output / "source/render-service/src/render-worker.ts"
        if hashlib.sha256(original.read_bytes()).hexdigest() != "28b9a52a23458265c4678ce555c6ddd5a5f4c530f843f594fd03a9b9aaf28959":
            raise ValueError("unreviewed renderer source before browser overlay")
        subprocess.run(["git", "apply", "--check", str(HERE / "renderer-browser.patch")],
                       cwd=output / "source", check=True, capture_output=True)
        subprocess.run(["git", "apply", str(HERE / "renderer-browser.patch")],
                       cwd=output / "source", check=True, capture_output=True)
        for service in ("render-service", "remotion"):
            manifest = json.loads((LOCKS / service / "artifact-manifest.json").read_text())
            manifests.append(manifest)
            for filename in ("package.json", "package-lock.json", "artifact-manifest.json"):
                shutil.copyfile(LOCKS / service / filename, output / "source" / service / filename)
    else:
        manifests = []
    copied = set()
    for manifest in manifests:
        for artifact in manifest["artifacts"]:
            digest = artifact["sha512_hex"]
            if artifact["integrity"] != "sha512-" + base64.b64encode(bytes.fromhex(digest)).decode():
                raise ValueError("inconsistent npm artifact identity")
            if digest not in copied:
                copy_checked(assets / "locked-tarballs" / (digest + ".tgz"),
                             output / "tarballs" / (digest + ".tgz"), digest, "sha512")
                copied.add(digest)
    if role in ("backend", "renderer"):
        lock = json.loads((LOCKS / (role + "-system-packages.lock.json")).read_text())
        for artifact in lock["artifacts"]:
            copy_checked(assets / (role + "-system-packages") / artifact["filename"],
                         output / "system-packages" / artifact["filename"], artifact["sha256"])
        (output / "system-packages.sha256").write_text(
            "".join(item["sha256"] + "  " + item["filename"] + "\n" for item in lock["artifacts"])
        )
        shutil.copyfile(HERE / ("Dockerfile." + role + "-offline"), output / "Dockerfile")
    if role == "backend":
        for artifact in json.loads((LOCKS / "backend-artifacts.json").read_text())["artifacts"]:
            copy_checked(assets / "wheelhouse" / artifact["filename"],
                         output / "wheelhouse" / artifact["filename"], artifact["sha256"])
        shutil.copyfile(LOCKS / "backend-requirements.lock", output / "requirements.lock")
        models = json.loads((LOCKS / "backend-models.lock.json").read_text())["artifacts"]
        for artifact in models:
            copy_checked(assets / "backend-models" / artifact["path"],
                         output / "models" / artifact["path"], artifact["sha256"])
        (output / "models.sha256").write_text(
            "".join(item["sha256"] + "  " + item["path"] + "\n" for item in models)
        )
    return {**result, "role": role, "offline_artifacts_verified": True,
            "next_step": "Reviewed bounded compilation/image build; no effect is performed by preparation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--assets-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role", choices=("frontend", "backend", "renderer"), required=True)
    args = parser.parse_args()
    try:
        result = stage(args.source_archive, args.assets_root, args.output, args.role)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
