"""Materialize only the exact public OpenShorts source and reviewed frontend inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def checked_members(archive: tarfile.TarFile, commit: str) -> list[tarfile.TarInfo]:
    prefix = f"openshorts-{commit}/"
    if archive.pax_headers.get("comment") != commit:
        raise ValueError("source archive lacks the exact Git commit comment")
    members = archive.getmembers()
    seen: set[str] = set()
    size = 0
    for member in members:
        if not (member.isfile() or member.isdir()):
            raise ValueError("source archive contains a non-file/directory member")
        if member.size < 0:
            raise ValueError("source archive contains a negative size")
        if member.name.rstrip("/") == prefix.rstrip("/"):
            continue
        if not member.name.startswith(prefix):
            raise ValueError("source archive member escapes its commit prefix")
        relative = member.name[len(prefix):].rstrip("/")
        path = PurePosixPath(relative)
        if not relative or str(path) != relative or path.is_absolute() or ".." in path.parts:
            raise ValueError("source archive contains a noncanonical path")
        if relative.casefold() in seen:
            raise ValueError("source archive contains duplicate/case-colliding paths")
        seen.add(relative.casefold())
        size += member.size
    if size > 512 * 1024 * 1024:
        raise ValueError("source archive exceeds its 512MiB materialization bound")
    return members


def prepare(source: Path, output: Path) -> dict[str, object]:
    lock = json.loads((HERE / "inputs.lock.json").read_text())
    if source.is_symlink() or digest(source) != lock["source"]["archive_sha256"]:
        raise ValueError("source archive SHA-256 does not match the reviewed lock")
    if source.stat().st_size != lock["source"]["archive_bytes"]:
        raise ValueError("source archive size does not match the reviewed lock")
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("output must be a new directory beneath an existing parent")
    if any(path.is_symlink() for path in output.parents):
        raise ValueError("output has a symlinked ancestor")
    for item in lock["candidate_files"]:
        path = HERE.parent / item["path"]
        if path.is_symlink() or digest(path) != item["sha256"]:
            raise ValueError("qualification candidate bytes differ from the reviewed lock")
    with tarfile.open(source, "r:gz") as archive:
        members = checked_members(archive, lock["source"]["commit"])
        prefix = f"openshorts-{lock['source']['commit']}/"
        for item in lock["source_files"]:
            stream = archive.extractfile(prefix + item["path"])
            if stream is None or hashlib.sha256(stream.read()).hexdigest() != item["sha256"]:
                raise ValueError("upstream dependency manifest differs from its exact source pin")
        output.mkdir(mode=0o700)
        archive.extractall(output, members=members, filter="data")
    (output / prefix.rstrip("/")).rename(output / "source")
    qualification = output / "qualification"
    qualification.mkdir()
    for name in ("Dockerfile.frontend", "npmrc"):
        shutil.copyfile(HERE / name, qualification / name)
    shutil.copyfile(HERE.parent / "private-nginx.conf", qualification / "private-nginx.conf")
    shutil.copyfile(HERE / "frontend.dockerignore", output / ".dockerignore")
    return {
        "status": "prepared-public-source-only",
        "source_commit": lock["source"]["commit"],
        "source_archive_sha256": lock["source"]["archive_sha256"],
        "source_date_epoch": lock["source"]["source_date_epoch"],
        "build_performed": False,
        "deployment_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.source_archive, args.output)
    except (OSError, ValueError, tarfile.TarError) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
