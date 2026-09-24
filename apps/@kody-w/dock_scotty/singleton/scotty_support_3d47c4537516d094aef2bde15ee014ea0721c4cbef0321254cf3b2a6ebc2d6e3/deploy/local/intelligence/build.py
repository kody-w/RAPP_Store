#!/usr/bin/env python3
"""Build a content-named local image without unpacking the CLI into the repository.

Use ``--public --cache ./materialized`` for anonymous, SHA-256-verified official
release retrieval and locked base-image materialization. ``--tarball`` remains
the original offline qualification interface; it never accepts an unpinned CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import importlib.util
import json
import os
import subprocess
import tarfile
from pathlib import Path


CLI_SHA256 = "e263f5f9eb0db5dddf5775ac98c437e27743857ce0ba310f08f2338aebd1107d"
BASE_IMAGE = "python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9"
BUILD_FILES = ("Dockerfile", "server.py", "schema.py")


def source_digest(root: Path | None = None) -> str:
    root = root or Path(__file__).resolve().parent
    digest = hashlib.sha256(CLI_SHA256.encode())
    for name in BUILD_FILES:
        digest.update(name.encode() + b"\0" + (root / name).read_bytes() + b"\0")
    return digest.hexdigest()


def image_tag(root: Path | None = None) -> str:
    return "rapp-dock/intelligence:" + source_digest(root)[:16]


def build(tarball: Path, docker: str = "docker") -> dict:
    root = Path(__file__).resolve().parent
    with tarball.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != CLI_SHA256:
        raise ValueError("Copilot release archive SHA-256 does not match the pinned release.")
    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    command = [docker, "--context", "desktop-linux"]
    subprocess.run(command + ["image", "inspect", BASE_IMAGE, "--format", "{{.Id}}"], check=True, env=env, stdout=subprocess.DEVNULL)
    tag = image_tag(root)
    args = command + [
        "build", "--pull=false", "--network=none", "--platform=linux/arm64",
        "--tag", tag, "--label", "rapp.dock.source.sha256=" + source_digest(root), "-",
    ]
    with tarfile.open(tarball, "r:gz") as archive:
        member = archive.getmember("copilot")
        if not member.isfile() or not 1 <= member.size <= 512 * 1024 * 1024:
            raise ValueError("Pinned archive does not contain a regular copilot executable.")
        binary = archive.extractfile(member)
        process = subprocess.Popen(args, stdin=subprocess.PIPE, env=env)
        try:
            with tarfile.open(fileobj=process.stdin, mode="w|") as context:
                for name in BUILD_FILES:
                    data = (root / name).read_bytes()
                    entry = tarfile.TarInfo(name)
                    entry.size, entry.mode = len(data), 0o644
                    context.addfile(entry, io.BytesIO(data))
                entry = tarfile.TarInfo("copilot")
                entry.size, entry.mode = member.size, 0o755
                context.addfile(entry, binary)
            process.stdin.close()
            if process.wait() != 0:
                raise RuntimeError("Intelligence image build failed.")
        finally:
            binary.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    image_id = subprocess.check_output(command + ["image", "inspect", tag, "--format", "{{.Id}}"], env=env, text=True).strip()
    return {"image": tag, "image_id": image_id, "source_sha256": source_digest(root), "cli_sha256": CLI_SHA256, "base": BASE_IMAGE}


def build_public(cache: Path, docker: str = "docker") -> dict:
    path = Path(__file__).resolve().parents[1] / "materialize.py"
    spec = importlib.util.spec_from_file_location("rapp_dock_public_materializer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.materialize(
        ["intelligence"], cache=cache, apply=True,
        run=module.docker_runner(cache=cache, executable=docker),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tarball", type=Path)
    parser.add_argument("--print-tag", action="store_true")
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args()
    if args.print_tag:
        print(image_tag())
        return
    if args.public:
        if args.tarball is not None or args.cache is None:
            parser.error("--public requires --cache and cannot be combined with --tarball")
        print(json.dumps(build_public(args.cache, args.docker), indent=2))
        return
    if args.tarball is None:
        parser.error("--tarball is required when building")
    print(json.dumps(build(args.tarball, args.docker), indent=2))


if __name__ == "__main__":
    main()
