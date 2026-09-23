#!/usr/bin/env python3
"""Bounded, offline inspection of public source distributions; never a publish grant.

Supported containers are ZIP/egg, gzip (including concatenated members), tar,
and literal base64 packages in Python/JSON or .b64 files. Archives are inspected
in memory, never extracted or executed. Unknown binary formats fail closed.
Every TAR byte is a checked header field, inspected extension/member data,
or required zero padding and end-of-archive; anything else refuses.
Names, comments and contents receive the same rules on every view produced by
bounded JSON-escape, URL and HTML/XML character-reference decoding.

Private names belong in a runtime JSON file, not in this module:
    {"version": 1, "deny": ["obviously-fake-owner", "fake-workstation"]}
Values are literal, case-insensitive substrings, not executable regexes.
Loopback, wildcard listeners, localhost, $HOME and ~/ are generic defaults, not
owner locators. Bare LAN names must be supplied in the deny-list; .local/.lan
and other private DNS suffixes and single-label URL hosts are detected here.
This is a bounded source-format gate, not universal DLP or license/ship approval.

CLI: python scripts/privacy_scan.py PUBLIC_TREE --denylist PRIVATE_CONFIG
Diagnostics use ordinal locations, never source names or matched values.
"""
import argparse
import ast
import base64
import binascii
from contextlib import contextmanager
import ctypes
from dataclasses import asdict, dataclass, field
import html
import io
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import struct
import sys
import tarfile
import unicodedata
from urllib.parse import unquote, urlsplit
import zipfile
import zlib


@dataclass(frozen=True)
class Limits:
    max_depth: int = 8
    max_members: int = 4096
    max_file_bytes: int = 20 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024
    max_decode_rounds: int = 8

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ValueError("E_LIMIT_CONFIG: inspection limits must be positive integers")


@dataclass(frozen=True)
class Policy:
    deny: tuple = field(default=(), repr=False)

    def __post_init__(self):
        if (not isinstance(self.deny, tuple) or len(self.deny) > 1024
                or any(not isinstance(value, str) or not 3 <= len(value) <= 4096
                       or not value.strip() or "\x00" in value for value in self.deny)):
            raise ValueError("E_DENYLIST: expected bounded, nonempty literal markers")
        try:
            for value in self.deny:
                value.encode("utf-8")
        except UnicodeError:
            raise ValueError("E_DENYLIST: markers must be Unicode text") from None


class PrivacyRefusal(ValueError):
    def __init__(self, findings):
        self.findings = sorted(
            { (row["rule"], row["location"]) for row in findings }
        )
        super().__init__("Public projection refused: " + "; ".join(
            rule + " at " + location for rule, location in self.findings
        ))

    def report(self):
        return {"status": "refused", "findings": [
            {"rule": rule, "location": location} for rule, location in self.findings
        ]}


def refuse(rule, location="input"):
    raise PrivacyRefusal([{"rule": rule, "location": location}])


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True,
                       allow_nan=False) + "\n").encode("utf-8")


def strict_json(blob):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("non-finite JSON number")

    return json.loads(blob, object_pairs_hook=pairs, parse_constant=invalid)


@contextmanager
def directory_fd(path):
    """Pin each ancestor without following links, including the selected root."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(os.path.abspath(path)).parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def read_regular(path, *, limit=256 * 1024):
    try:
        path = Path(os.path.abspath(path))
        with directory_fd(path.parent) as parent:
            return _read_at(parent, path.name, limit)
    except PrivacyRefusal:
        raise
    except (OSError, ValueError):
        refuse("E_INPUT_FILE")


def _read_at(parent, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size > limit):
            refuse("E_INPUT_FILE")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            blob = stream.read(limit + 1)
        after = os.fstat(fd)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(blob) > limit or any(getattr(before, key) != getattr(after, key) for key in fields):
            refuse("E_INPUT_CHANGED")
        return blob
    finally:
        os.close(fd)


def load_policy(path):
    try:
        value = strict_json(read_regular(path))
        if not isinstance(value, dict) or set(value) != {"version", "deny"}:
            refuse("E_DENYLIST")
        if type(value["version"]) is not int or value["version"] != 1 or not isinstance(value["deny"], list):
            refuse("E_DENYLIST")
        return Policy(tuple(value["deny"]))
    except (ValueError, TypeError, RecursionError):
        refuse("E_DENYLIST")


_RULES = (
    ("P_HOME_PATH", re.compile(
        r"(?:/(?:Users|home)/[^/\s\"'<>]+|/root(?:/|\b)|"
        r"\b[A-Z]:[\\/](?:Users|Documents and Settings)[\\/][^\\/\s\"'<>]+)", re.I)),
    ("P_LAN_HOST", re.compile(
        r"(?<![\w.-])[a-z0-9_-]+(?:\.[a-z0-9_-]+)*"
        r"\.(?:local|lan|internal|localdomain|home(?:\.arpa)?)(?![\w-]|\s*\()", re.I)),
    ("P_TOKEN", re.compile(
        r"\b(?:(?:gh[pousr]_|github_pat_|glpat-|xox[baprs]-|"
        r"sk_(?:live|test)_|rk_live_|sk-(?:proj-|ant-)?)[A-Za-z0-9_-]{6,}"
        r"|(?:AKIA|ASIA)[A-Z0-9]{16})\b")),
    ("P_PRIVATE_KEY", re.compile(
        r"-----BEGIN (?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED|PGP) )?"
        r"PRIVATE KEY(?: BLOCK)?-----", re.I)),
    ("P_SESSION_ID", re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)),
    ("P_OPERATION_ID", re.compile(
        r"\b(?:op-\d{10,}-[0-9a-f]{8,}|(?:session|operation)[-_][0-9a-f]{16,})\b", re.I)),
    ("P_PRIVATE_DOCUMENT", re.compile(r"\bPRIVATE\s*/\s*NEVER\s+PUBLISH\b", re.I)),
)
_V4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_V6 = re.compile(r"(?<![\w:])(?:[0-9a-f]{0,4}:){2,}[0-9a-f:.]*(?:%[\w.-]+)?(?![\w:])", re.I)
_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "fc00::/7", "fe80::/10",
))
_URL = re.compile(r"\b(?:https?|wss?|ftp|smb)://[^\s\"'<>`]+", re.I)
_ESCAPE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|["\\/bfnrt])')
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
            "n": "\n", "r": "\r", "t": "\t"}
_B64 = re.compile(r"(?<![\w+/=-])[A-Za-z0-9+/_-]{24,}={0,2}(?![\w+/=-])")
_PRIVATE_PARTS = frozenset({
    ".git", ".ssh", ".aws", ".azure", ".gnupg", ".rapp", ".brainstem_data",
    ".copilot", "state", "receipts", "transcripts", "prompts", "credentials",
    "registry", "registry.json", "organization.md", "organization.json", "private-stores.md",
    "frames", "frames.jsonl", "hive.json", "id_ed25519", "id_rsa",
})
_UNSUPPORTED_SUFFIXES = (
    ".7z", ".rar", ".bz2", ".xz", ".zst", ".zstd", ".lz4", ".br",
    ".whl", ".jar", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".dmg",
    ".sqlite", ".db", ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib",
)
_UNSUPPORTED_MAGIC = (
    b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07", b"BZh", b"\xfd7zXZ\x00",
    b"\x28\xb5\x2f\xfd", b"\x04\x22\x4d\x18", b"%PDF-", b"\x89PNG",
    b"\xff\xd8\xff", b"GIF8", b"SQLite format 3\x00", b"\x7fELF",
)


def _unescape(match):
    token = match.group()[1:]
    return chr(int(token[1:], 16)) if token.startswith("u") else _ESCAPES[token]


def _json_escapes(text):
    decoded = _ESCAPE.sub(_unescape, text)
    if re.search("[\ud800-\udfff]", decoded):
        decoded = decoded.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le")
    return decoded


def _url_escapes(text):
    return unquote(text, errors="strict")


# Each round peels one layer per decoder. html.unescape applies the HTML5 rules
# browsers use: decimal, hex and named references, with or without the final
# semicolon. XML character and predefined entity references are a subset.
_DECODERS = (_json_escapes, _url_escapes, html.unescape)

# USTAR/GNU header layout: terminated text fields, octal numbers, a fixed magic,
# the type byte and zero padding. Nothing else may carry header bytes.
_TAR_EXTENSIONS = (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE,
                   tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK)
_TAR_MAGIC = (b"ustar\x0000", b"ustar  \x00")
_TAR_TEXT = ((0, 100), (157, 257), (265, 297), (297, 329), (345, 500))
_TAR_NUMBERS = ((100, 108), (108, 116), (116, 124), (124, 136), (136, 148),
                (148, 156), (329, 337), (337, 345))
_TAR_OCTAL = re.compile(rb" *[0-7]*[ \x00]*")


def _safe_name(name):
    if (not isinstance(name, str) or not name or len(name) > 4096
            or "\\" in name or ":" in name or name.startswith("/")
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        return False
    parts = name.rstrip("/").split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _private_name(name):
    parts = name.casefold().replace("\\", "/").rstrip("/").split("/")
    return any(part in _PRIVATE_PARTS or part == ".env" or part.startswith(".env.")
               or re.fullmatch(r"(?:raw[-_])?(?:receipt|transcript|prompt|session|operation)s?"
                               r"(?:[-_][^.]+)?\.(?:jsonl?|txt|log|egg)", part)
               for part in parts)


def _kind(blob):
    if blob.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    if blob.startswith(b"\x1f\x8b"):
        return "gzip"
    if len(blob) >= 512 and blob[257:263] in (b"ustar\x00", b"ustar "):
        return "tar"
    if blob.startswith(_UNSUPPORTED_MAGIC):
        return "unsupported"
    return None


class _Scanner:
    def __init__(self, policy, limits):
        self.policy, self.limits = policy, limits
        self.deny = tuple(unicodedata.normalize("NFKC", value).casefold() for value in policy.deny)
        self.findings = set()
        self.members = self.total = 0

    def add(self, rule, location):
        self.findings.add((rule, location))

    def charge(self, size, location, *, member=True):
        self.members += int(member)
        self.total += size
        if self.members > self.limits.max_members:
            refuse("E_MEMBER_LIMIT", location)
        if size > self.limits.max_file_bytes or self.total > self.limits.max_total_bytes:
            refuse("E_BYTE_LIMIT", location)

    def allowance(self):
        return min(self.limits.max_file_bytes, self.limits.max_total_bytes - self.total)

    def patterns(self, text, location):
        for rule, pattern in _RULES:
            if pattern.search(text):
                self.add(rule, location)
        folded = text.casefold()
        if any(value in folded for value in self.deny):
            self.add("P_DENYLIST", location)
        for pattern in (_V4, _V6):
            for match in pattern.finditer(text):
                try:
                    address = ipaddress.ip_address(match.group().split("%", 1)[0])
                except ValueError:
                    continue
                if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                    address = address.ipv4_mapped
                if any(address.version == network.version and address in network for network in _NETWORKS):
                    self.add("P_PRIVATE_ADDRESS", location)
        for match in _URL.finditer(text):
            try:
                host = urlsplit(match.group()).hostname
            except ValueError:
                continue
            if (host and re.fullmatch(r"[a-z][a-z0-9-]*", host, re.I)
                    and host.lower() != "localhost"):
                self.add("P_LAN_HOST", location)

    def view(self, text, location, name):
        text = unicodedata.normalize("NFKC", text)
        self.patterns(text, location)
        if name:
            if not _safe_name(text):
                self.add("E_PATH", location)
            if _private_name(text):
                self.add("P_PRIVATE_ARTIFACT", location)
        return text

    def text(self, text, location, *, name=False):
        """Inspect the text and each successive decoded view until a fixed point.

        A round peels one JSON-escape, URL and HTML-reference layer, in that
        order, inspecting every intermediate view; exhausting the round budget
        refuses. This is a bounded canonicalization chain, not a search of
        every possible decoding order.
        """
        text = self.view(text, location, name)
        for step in range(self.limits.max_decode_rounds + 1):
            start = text
            for decode in _DECODERS:
                try:
                    decoded = decode(text)
                except (UnicodeError, ValueError):
                    self.add("E_TEXT_ENCODING", location)
                    return text
                if decoded != text:
                    if step == self.limits.max_decode_rounds:
                        self.add("E_ENCODING_LIMIT", location)
                        return text
                    text = self.view(decoded, location, name)
            if text == start:
                break
        return text

    def embedded(self, value, location, depth, *, required=False):
        if isinstance(value, bytes):
            try:
                value = value.decode("ascii")
            except UnicodeError:
                if required:
                    self.add("E_BASE64", location)
                return
        candidates = ["".join(value.split())] if required else [m.group() for m in _B64.finditer(value)]
        for number, candidate in enumerate(candidates):
            if not required and re.fullmatch("[0-9a-fA-F]+", candidate):
                continue
            try:
                blob = base64.b64decode(candidate, altchars=b"-_", validate=True)
            except (ValueError, binascii.Error):
                if required or candidate.startswith(("UEsDB", "UEsFB", "H4sI", "UmFyIR", "N3q8")):
                    self.add("E_BASE64", location)
                continue
            if not blob:
                if required:
                    self.add("E_BASE64", location)
                continue
            kind = _kind(blob)
            if required or kind:
                self.blob(blob, "embedded", location + "/base64[" + str(number) + "]", depth + 1)
            else:
                try:
                    text = blob.decode("utf-8")
                except UnicodeError:
                    continue
                if all(char.isprintable() or char in "\t\r\n" for char in text):
                    self.blob(blob, "embedded", location + "/base64[" + str(number) + "]", depth + 1)

    def metadata(self, value, location, depth, *, name=False):
        decoded = self.text(value, location, name=name)
        self.embedded(decoded, location, depth)

    def document(self, blob, name, location, depth):
        try:
            text = blob.decode("utf-8-sig")
        except UnicodeError:
            self.add("E_OPAQUE_CONTENT", location)
            return
        if any(ord(char) < 32 and char not in "\t\r\n\f" for char in text):
            self.add("E_OPAQUE_CONTENT", location)
            return
        decoded = self.text(text, location + "/content")
        if name.lower().endswith((".b64", ".base64")):
            self.embedded(decoded, location, depth, required=True)
            return
        self.embedded(decoded, location, depth)
        try:
            if name.lower().endswith(".py"):
                tree = ast.parse(blob)
                for number, node in enumerate(ast.walk(tree)):
                    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
                        value = node.value
                        if isinstance(value, bytes):
                            value = value.decode("utf-8", errors="replace")
                        self.charge(len(value.encode("utf-8")), location, member=False)
                        self.text(value, location + "/literal[" + str(number) + "]")
                        self.embedded(value, location + "/literal[" + str(number) + "]", depth)
            elif name.lower().endswith(".json"):
                value = strict_json(blob)
                stack = [value]
                while stack:
                    item = stack.pop()
                    if isinstance(item, dict):
                        if item.get("encoding") in ("base64", "base64url"):
                            if not isinstance(item.get("data"), str):
                                self.add("E_BASE64", location)
                            else:
                                self.embedded(item["data"], location + "/encoded-data", depth, required=True)
                        elif ("encoding" in item and "data" in item
                              and item["encoding"] not in ("utf-8", "utf8", "plain")):
                            self.add("E_UNSUPPORTED_ENCODING", location)
                        stack.extend(item.values())
                    elif isinstance(item, list):
                        stack.extend(item)
        except PrivacyRefusal:
            raise
        except (SyntaxError, ValueError, TypeError, UnicodeError, RecursionError):
            self.add("E_DOCUMENT_FORMAT", location)

    def blob(self, blob, name, location, depth):
        if depth > self.limits.max_depth:
            refuse("E_DEPTH_LIMIT", location)
        self.charge(len(blob), location)
        self.metadata(name, location + "/name", depth, name=True)
        kind = _kind(blob)
        suffix = name.lower()
        if suffix.endswith(_UNSUPPORTED_SUFFIXES) or kind == "unsupported":
            self.add("E_UNSUPPORTED_CONTAINER", location)
            return
        expected = ("zip" if suffix.endswith((".zip", ".egg")) else
                    "gzip" if suffix.endswith((".gz", ".gzip", ".tgz")) else
                    "tar" if suffix.endswith(".tar") else None)
        if expected and kind not in (expected, None):
            self.add("E_CONTAINER_FORMAT", location)
            return
        kind = kind or expected
        try:
            if kind == "zip":
                self.zip(blob, location, depth)
            elif kind == "gzip":
                self.gzip(blob, name, location, depth)
            elif kind == "tar":
                self.tar(blob, location, depth)
            else:
                self.document(blob, name, location, depth)
        except PrivacyRefusal:
            raise
        except (ValueError, OSError, EOFError, RuntimeError, NotImplementedError,
                zipfile.BadZipFile, zlib.error, struct.error):
            self.add("E_CONTAINER_FORMAT", location)

    def zip(self, blob, location, depth):
        if not blob.startswith((b"PK\x03\x04", b"PK\x05\x06")):
            self.add("E_CONTAINER_FORMAT", location)
            return
        offset = blob.rfind(b"PK\x05\x06", max(0, len(blob) - 65557))
        if offset < 0:
            self.add("E_CONTAINER_FORMAT", location)
            return
        _, disk, start_disk, count_disk, count, size, start, comment = struct.unpack_from("<4s4H2IH", blob, offset)
        if (disk or start_disk or count_disk != count or count == 65535
                or start + size != offset or offset + 22 + comment != len(blob)):
            self.add("E_CONTAINER_FORMAT", location)
            return
        if self.members + count > self.limits.max_members:
            refuse("E_MEMBER_LIMIT", location)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            entries = archive.infolist()
            if len(entries) != count:
                self.add("E_CONTAINER_FORMAT", location)
                return
            self.metadata(archive.comment.decode("utf-8", errors="replace"), location + "/comment", depth)
            spans, cursor = {}, 0
            for number, info in enumerate(sorted(entries, key=lambda item: item.header_offset)):
                member = location + "/zip-local[" + str(number) + "]"
                if info.header_offset != cursor or blob[cursor:cursor + 4] != b"PK\x03\x04":
                    self.add("E_CONTAINER_FORMAT", member)
                    return
                flags, method = struct.unpack_from("<HH", blob, cursor + 6)
                crc, compressed, expanded = struct.unpack_from("<III", blob, cursor + 14)
                namesize, extrasize = struct.unpack_from("<HH", blob, cursor + 26)
                begin = cursor + 30
                end = begin + namesize + extrasize
                data_end = end + info.compress_size
                if flags != info.flag_bits or method != info.compress_type or data_end > start:
                    self.add("E_CONTAINER_FORMAT", member)
                    return
                self.metadata(blob[begin:begin + namesize].decode(
                    "utf-8" if flags & 2048 else "cp437"), member + "/name", depth, name=True)
                self.metadata(blob[begin + namesize:end].decode("utf-8", errors="replace"),
                              member + "/extra", depth)
                cursor = data_end
                if flags & 8:
                    if blob[cursor:cursor + 4] == b"PK\x07\x08":
                        cursor += 4
                    crc, compressed, expanded = struct.unpack_from("<III", blob, cursor)
                    cursor += 12
                if (crc, compressed, expanded) != (info.CRC, info.compress_size, info.file_size):
                    self.add("E_CONTAINER_FORMAT", member)
                    return
                spans[info.header_offset] = (end, data_end)
            if cursor != start:
                self.add("E_CONTAINER_FORMAT", location)
                return
            seen = set()
            for number, info in enumerate(entries):
                member = location + "/zip[" + str(number) + "]"
                self.metadata(info.orig_filename, member + "/name", depth, name=True)
                self.metadata(info.comment.decode("utf-8", errors="replace"), member + "/comment", depth)
                self.metadata(info.extra.decode("utf-8", errors="replace"), member + "/extra", depth)
                key = unicodedata.normalize("NFKC", info.filename).casefold().rstrip("/")
                if key in seen:
                    self.add("E_DUPLICATE_MEMBER", member)
                seen.add(key)
                mode = stat.S_IFMT(info.external_attr >> 16)
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    self.add("E_LINK_OR_SPECIAL", member)
                    continue
                if info.flag_bits & (1 | 64) or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    self.add("E_UNSUPPORTED_CONTAINER", member)
                    continue
                if info.file_size > self.allowance():
                    refuse("E_BYTE_LIMIT", member)
                begin, end = spans[info.header_offset]
                contents = blob[begin:end]
                if info.compress_type == zipfile.ZIP_DEFLATED:
                    decoder = zlib.decompressobj(-zlib.MAX_WBITS)
                    contents = decoder.decompress(contents, self.allowance() + 1)
                    if len(contents) > self.allowance():
                        refuse("E_BYTE_LIMIT", member)
                    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                        self.add("E_CONTAINER_FORMAT", member)
                        continue
                if len(contents) != info.file_size or zlib.crc32(contents) != info.CRC:
                    self.add("E_CONTAINER_FORMAT", member)
                    continue
                if info.is_dir():
                    self.charge(0, member)
                    if contents:
                        self.add("E_CONTAINER_FORMAT", member)
                    continue
                self.blob(contents, info.filename, member, depth + 1)

    def gzip(self, blob, name, location, depth):
        start, number = 0, 0
        while start < len(blob):
            member = location + "/gzip[" + str(number) + "]"
            if len(blob) - start < 18 or blob[start:start + 3] != b"\x1f\x8b\x08" or blob[start + 3] & 0xe0:
                self.add("E_CONTAINER_FORMAT", member)
                return
            flags, offset = blob[start + 3], start + 10
            if flags & 4:
                length = struct.unpack_from("<H", blob, offset)[0]
                offset += 2
                self.metadata(blob[offset:offset + length].decode("utf-8", errors="replace"),
                              member + "/extra", depth)
                offset += length
            member_name = name[:-4] + ".tar" if name.lower().endswith(".tgz") else re.sub(r"\.(?:gz|gzip)$", "", name, flags=re.I)
            for flag, label in ((8, "name"), (16, "comment")):
                if flags & flag:
                    end = blob.find(b"\x00", offset, offset + 4097)
                    if end < 0:
                        self.add("E_CONTAINER_FORMAT", member)
                        return
                    value = blob[offset:end].decode("latin-1")
                    self.metadata(value, member + "/" + label, depth, name=label == "name")
                    if label == "name":
                        member_name = value
                    offset = end + 1
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            chunks, expanded, cursor = [], 0, start
            while cursor < len(blob) and not decoder.eof:
                chunk = blob[cursor:cursor + 65536]
                cursor += len(chunk)
                part = decoder.decompress(chunk, self.allowance() - expanded + 1)
                expanded += len(part)
                if expanded > self.allowance() or decoder.unconsumed_tail:
                    refuse("E_BYTE_LIMIT", member)
                chunks.append(part)
            if not decoder.eof:
                self.add("E_CONTAINER_FORMAT", member)
                return
            start = cursor - len(decoder.unused_data)
            self.blob(b"".join(chunks), member_name or "contents", member, depth + 1)
            number += 1

    def tar_header(self, header, location, depth):
        """Inspect each text field; every other header byte has one fixed form."""
        canonical = header[257:265] in _TAR_MAGIC and not any(header[500:])
        for begin, end in _TAR_NUMBERS:
            canonical = canonical and _TAR_OCTAL.fullmatch(header[begin:end]) is not None
        for begin, end in _TAR_TEXT:
            value, _, slack = header[begin:end].partition(b"\x00")
            canonical = canonical and not any(slack)
            if value:
                self.metadata(value.decode("utf-8", errors="replace"), location, depth)
        if not canonical:
            self.add("E_CONTAINER_FORMAT", location)

    def tar_layout(self, blob, location, depth):
        """Account for every block; return each member's (data offset, size)."""
        members, cursor, headers = [], 0, 0
        awaiting_member, initial_members = False, self.members
        while True:
            header = blob[cursor:cursor + 512]
            if not any(header):
                if (len(header) < 512 or awaiting_member or len(blob) - cursor < 1024
                        or any(blob[cursor:])):
                    self.add("E_CONTAINER_FORMAT", location + "/end")
                    return None
                return members
            where = location + "/tar-header[" + str(headers) + "]"
            headers += 1
            if initial_members + headers > self.limits.max_members:
                refuse("E_MEMBER_LIMIT", location)
            raw = tarfile.TarInfo.frombuf(header, "utf-8", "surrogateescape")
            self.tar_header(header, where, depth)
            if raw.size < 0 or raw.size > self.allowance():
                refuse("E_BYTE_LIMIT", location)
            begin = cursor + 512
            end = begin + raw.size
            cursor = begin + (raw.size + 511) // 512 * 512
            if cursor > len(blob):
                self.add("E_CONTAINER_FORMAT", where)
                return None
            if raw.type in _TAR_EXTENSIONS:
                self.charge(0, location + "/extended-header")
                self.metadata(blob[begin:end].decode("utf-8", errors="replace"),
                              where + "/extension", depth)
            elif raw.type == tarfile.GNUTYPE_SPARSE:
                # Old GNU sparse maps continue beyond the header; never guess their framing.
                self.add("E_LINK_OR_SPECIAL", where)
                return None
            elif raw.isreg() or raw.type not in tarfile.SUPPORTED_TYPES:
                members.append((begin, raw.size))
            elif raw.size:
                # Readers resume at the next block for this type: declared data would be read as headers.
                self.add("E_CONTAINER_FORMAT", where)
                return None
            else:
                members.append((begin, 0))
            awaiting_member = raw.type in _TAR_EXTENSIONS
            if any(blob[end:cursor]):
                self.add("E_CONTAINER_FORMAT", where + "/padding")

    def tar(self, blob, location, depth):
        """Inspect members only when the byte walk and tarfile frame them identically."""
        if len(blob) % 512:
            self.add("E_CONTAINER_FORMAT", location)
            return
        try:
            layout = self.tar_layout(blob, location, depth)
            if layout is None:
                return
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as archive:
                entries = list(archive)
        except (tarfile.TarError, RecursionError):
            self.add("E_CONTAINER_FORMAT", location)
            return
        # The byte walk and the reader must frame identical members.
        if [(info.offset_data, info.size) for info in entries] != layout:
            self.add("E_CONTAINER_FORMAT", location)
            return
        seen = set()
        for number, info in enumerate(entries):
            member = location + "/tar[" + str(number) + "]"
            self.metadata(info.name, member + "/name", depth, name=True)
            self.metadata(info.uname + "\n" + info.gname, member + "/owner", depth)
            for key, value in info.pax_headers.items():
                self.metadata(key + "\n" + value, member + "/metadata", depth)
            key = unicodedata.normalize("NFKC", info.name).casefold().rstrip("/")
            if key in seen:
                self.add("E_DUPLICATE_MEMBER", member)
            seen.add(key)
            if info.issparse() or not (info.isfile() or info.isdir()):
                self.add("E_LINK_OR_SPECIAL", member)
                self.charge(0, member)
                continue
            if info.isdir():
                self.charge(0, member)
                continue
            self.blob(blob[info.offset_data:info.offset_data + info.size], info.name,
                      member, depth + 1)


def scan_files(files, *, policy=None, limits=None):
    """Inspect an exact byte snapshot. The result has no paths, values or clocks."""
    policy, limits = policy or Policy(), limits or Limits()
    scanner = _Scanner(policy, limits)
    try:
        if not isinstance(files, dict) or not files:
            refuse("E_EMPTY_PROJECTION")
        if any(not isinstance(name, str) or not isinstance(blob, bytes) for name, blob in files.items()):
            refuse("E_INPUT_TYPE")
        if len(files) > limits.max_members:
            refuse("E_MEMBER_LIMIT")
        seen = set()
        for number, (name, blob) in enumerate(sorted(files.items())):
            location = "file[" + str(number) + "]"
            key = unicodedata.normalize("NFKC", name).casefold()
            if key in seen:
                scanner.add("E_DUPLICATE_MEMBER", location)
            if name.endswith("/") or any(str(parent) in seen for parent in PurePosixPath(key).parents):
                scanner.add("E_PATH", location)
            seen.add(key)
            scanner.blob(blob, name, location, 0)
    except PrivacyRefusal as exc:
        scanner.findings.update(exc.findings)
    findings = [{"rule": rule, "location": location} for rule, location in sorted(scanner.findings)]
    return {
        "version": 1, "status": "refused" if findings else "clean",
        "scope": "bounded-content-inspection-only",
        "findings": findings, "objects_inspected": scanner.members,
        "bytes_inspected": scanner.total, "limits": asdict(limits),
        "runtime_denylist_applied": policy is not None and bool(policy.deny),
    }


def require_clean(files, *, policy=None, limits=None):
    report = scan_files(files, policy=policy, limits=limits)
    if report["findings"]:
        raise PrivacyRefusal(report["findings"])
    return report


def read_tree(root, *, limits=None):
    """Read every regular member, including dotfiles; no ignore rules or links."""
    limits = limits or Limits()
    files, members, total = {}, 0, 0

    def visit(fd, prefix):
        nonlocal members, total
        before = os.fstat(fd)
        names = []
        with os.scandir(fd) as entries:
            for entry in entries:
                members += 1
                if members > limits.max_members:
                    refuse("E_MEMBER_LIMIT")
                names.append(entry.name)
        if not names:
            refuse("E_EMPTY_DIRECTORY")
        for number, name in enumerate(sorted(names)):
            relative = prefix + name
            location = "tree[" + str(len(files)) + "]/member[" + str(number) + "]"
            if not _safe_name(relative):
                refuse("E_PATH", location)
            if _private_name(relative):
                refuse("P_PRIVATE_ARTIFACT", location)
            item = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(item.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    visit(child, relative + "/")
                finally:
                    os.close(child)
            elif stat.S_ISREG(item.st_mode) and item.st_nlink == 1:
                blob = _read_at(fd, name, min(limits.max_file_bytes, limits.max_total_bytes - total))
                total += len(blob)
                files[relative] = blob
            else:
                refuse("E_LINK_OR_SPECIAL", location)
        after = os.fstat(fd)
        if before.st_mtime_ns != after.st_mtime_ns or before.st_ctime_ns != after.st_ctime_ns:
            refuse("E_INPUT_CHANGED")

    try:
        with directory_fd(root) as fd:
            visit(fd, "")
    except PrivacyRefusal:
        raise
    except (OSError, ValueError):
        refuse("E_INPUT_TREE")
    return files


def _rename_new(parent, source, target):
    """Atomic no-replace publication on the supported POSIX authoring hosts."""
    libc = ctypes.CDLL(None, use_errno=True)
    function, flags = ("renameatx_np", 4) if sys.platform == "darwin" else ("renameat2", 1)
    rename = getattr(libc, function, None)
    if rename is None:
        refuse("E_ATOMIC_PUBLICATION_UNAVAILABLE")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(source), parent, os.fsencode(target), flags):
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def _write_member(root, name, blob):
    current = os.dup(root)
    try:
        parts = PurePosixPath(name).parts
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o755, dir_fd=current)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o644, dir_fd=current)
        with os.fdopen(fd, "wb") as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644)
    finally:
        os.close(current)


def write_tree(files, output, *, policy=None, limits=None):
    """Scan before any write; publish a complete create-only directory or nothing."""
    report = require_clean(files, policy=policy, limits=limits)
    target = Path(os.path.abspath(output))
    created = []
    try:
        if target.exists() or target.is_symlink():
            raise ValueError("E_OUTPUT_EXISTS: output must be a new directory")
        missing, parent = [], target.parent
        while not parent.exists():
            if parent.is_symlink():
                refuse("E_OUTPUT_PATH")
            missing.append(parent)
            parent = parent.parent
        with directory_fd(parent):
            pass
        for path in reversed(missing):
            path.mkdir(mode=0o755)
            created.append(path)
        with directory_fd(target.parent) as parent_fd:
            stage = ".public-build-" + secrets.token_hex(12)
            os.mkdir(stage, 0o700, dir_fd=parent_fd)
            try:
                fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                try:
                    for name, blob in sorted(files.items()):
                        _write_member(fd, name, blob)
                    os.fchmod(fd, 0o755)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                _rename_new(parent_fd, stage, target.name)
            except BaseException:
                shutil.rmtree(stage, dir_fd=parent_fd)
                raise
    except BaseException as exc:
        for parent in reversed(created):
            try:
                parent.rmdir()
            except OSError:
                pass
        if isinstance(exc, OSError):
            refuse("E_OUTPUT_IO")
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--denylist", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.denylist)
        result = scan_files(read_tree(args.root), policy=policy)
    except PrivacyRefusal as exc:
        result = exc.report()
    print(canonical(result).decode(), end="")
    return 1 if result["status"] == "refused" else 0


if __name__ == "__main__":
    raise SystemExit(main())
