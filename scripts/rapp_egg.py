"""Unsigned rapplication packing from the accepted RAPP/1 rev-15 reference.

Narrow port of canonical, _egg_contents, pack_egg and the path checks in
kody-w/rapp-1@eb50008011447f5e69372ac22a1755f0978d15ed/rapp.py.
The exact checked-in reference is pinned by tests/test_producer_egg_contract.py.
Only the reference's exact-value JSON domain (no floats) is needed here.

MIT License

Copyright (c) 2025-2026 Kody Wildfeuer

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import io
import json
import re
import unicodedata
import zipfile


_RAPPID = re.compile(r"rappid:@([a-z0-9]+(?:-[a-z0-9]+)*)/([a-z0-9]+(?:-[a-z0-9]+)*):[0-9a-f]{64}")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)},
             *{f"LPT{i}" for i in range(1, 10)}}


def _canonical(value, depth=1):
    if depth > 64:
        raise ValueError("E_EGG_JSON: JSON nesting exceeds 64")
    if value is None or isinstance(value, bool):
        return json.dumps(value)
    if isinstance(value, int):
        if abs(value) > 2**53 - 1:
            raise ValueError("E_EGG_JSON: integer outside the interoperable range")
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item, depth + 1) for item in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False) + ":" + _canonical(value[key], depth + 1)
            for key in keys
        ) + "}"
    raise ValueError("E_EGG_JSON: expected exact-value JSON (no floats)")


def _check_paths(paths):
    keys = []
    for path in paths:
        if (not isinstance(path, str) or not path or path.startswith("/")
                or "\\" in path or path != unicodedata.normalize("NFC", path)):
            raise ValueError(f"E_EGG_PATH: invalid relative NFC POSIX path: {path!r}")
        parts = path.split("/")
        if any(part in ("", ".", "..") or part.endswith((" ", ".")) or ":" in part
               or any(ord(char) < 32 for char in part)
               or part.split(".", 1)[0].upper() in _RESERVED for part in parts):
            raise ValueError(f"E_EGG_PATH: nonportable path: {path!r}")
        keys.append(tuple(unicodedata.normalize("NFD", part).casefold() for part in parts))
    if len(keys) != len(set(keys)):
        raise ValueError("E_EGG_PATH: paths collide on common filesystems")
    ordered = sorted(keys)
    for key, following in zip(ordered, ordered[1:]):
        if len(key) < len(following) and following[:len(key)] == key:
            raise ValueError("E_EGG_PATH: file/directory path conflict")


class _Utf8ZipInfo(zipfile.ZipInfo):
    # zipfile otherwise clears the UTF-8 flag for ASCII names in both headers.
    def _encodeFilenameFlags(self):
        return self.filename.encode("utf-8"), self.flag_bits | 0x800


def pack_rapplication(rappid: str, created_utc: str, files: dict[str, bytes], payload: dict) -> bytes:
    """Pack the exact seven-member manifest and deterministic STORED ZIP."""
    match = _RAPPID.fullmatch(rappid)
    if not match or not 1 <= len(match[1]) <= 39 or not 1 <= len(match[2]) <= 100:
        raise ValueError("E_EGG_IDENTITY: rappid violates the section 6.1 grammar")
    if not _UTC.fullmatch(created_utc):
        raise ValueError("E_EGG_UTC: created_utc must use fixed UTC milliseconds")
    datetime.strptime(created_utc, "%Y-%m-%dT%H:%M:%S.%fZ")
    _check_paths(["manifest.json", *files])
    if "rappid.json" not in files or [
        path for path in files if "/" not in path and path.endswith(".py")
    ] != ["agent.py"]:
        raise ValueError("E_EGG_AGENT: rapplication requires rappid.json and exactly one root agent.py")
    contents = [
        {"path": path, "hash": hashlib.sha256(b"rapp/1:egg\n" + files[path]).hexdigest()}
        for path in sorted(files, key=lambda path: path.encode("utf-8"))
    ]
    manifest = {
        "schema": "rapp/1-egg", "variant": "rapplication", "rappid": rappid,
        "created_utc": created_utc, "contents": contents, "payload": payload, "sig": None,
    }
    manifest_bytes = _canonical(manifest).encode("utf-8")
    if len(manifest_bytes) > 1024 * 1024:
        raise ValueError("E_EGG_JSON: canonical manifest exceeds 1 MiB")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED, allowZip64=False) as archive:
        def write(name, data):
            info = _Utf8ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.flag_bits = 0x800
            # Fix the reference packer's Unix defaults even on Windows.
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)

        write("manifest.json", manifest_bytes)
        for item in contents:
            write(item["path"], files[item["path"]])
    return buf.getvalue()
