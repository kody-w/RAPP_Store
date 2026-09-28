"""Unsigned rapplication packing from the accepted RAPP/1 rev-17 reference.

Narrow port of canonical, _strict_json, utc_valid, _names_ok, _egg_contents,
_zip_pack, pack_egg, the path checks and the rapplication identity binding in
kody-w/rapp-1@f6bafe76735ba73510518810c8bc8cd133dcf527/rapp.py (rev-17).
The exact checked-in reference is pinned by tests/test_producer_egg_contract.py.

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

import decimal
import hashlib
import json
import re
import struct
import unicodedata
import zlib


_RAPPID = re.compile(r"rappid:@([a-z0-9]+(?:-[a-z0-9]+)*)/([a-z0-9]+(?:-[a-z0-9]+)*):[0-9a-f]{64}")
_UTC = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})\.[0-9]{3}Z", re.ASCII)
_RESERVED = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)},
             *{f"LPT{i}" for i in range(1, 10)}}
_MAX_JSON_INPUT = 64 * 1024 * 1024
_MAX_CANONICAL = 1024 * 1024
# Section 4 (b): surrogate code points and the 66 noncharacters are outside I-JSON.
_NOT_IJSON_CHAR = re.compile(
    "[\ud800-\udfff\ufdd0-\ufdef"
    + "".join(chr(plane << 16 | 0xFFFE) + chr(plane << 16 | 0xFFFF) for plane in range(17))
    + "]"
)


def _string(value):
    bad = _NOT_IJSON_CHAR.search(value)
    if bad:
        raise ValueError(f"E_EGG_JSON: string holds U+{ord(bad.group()):04X}, outside I-JSON")
    return json.dumps(value, ensure_ascii=False)


def _number_to_string(x):
    """ECMA-262 Number::toString of a finite binary64 value (RFC 8785 section 3.2.2.3)."""
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError("E_EGG_JSON: NaN and infinities are outside the section 4 domain")
    if x == 0:
        return "0"
    mantissa, _, exponent = repr(abs(x)).partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = (whole + fraction).lstrip("0")
    n = len(whole) + int(exponent or 0) - (len(whole) + len(fraction) - len(digits))
    digits = digits.rstrip("0")
    k = len(digits)
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * -n + digits
    else:
        text = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if n > 0 else "-") + str(abs(n - 1))
    return ("-" if x < 0 else "") + text


def _canonical(value, depth=1):
    if value is None or isinstance(value, bool):
        return json.dumps(value)
    if isinstance(value, int):
        if abs(value) <= 2**53 - 1:
            return json.dumps(value)
        try:
            as_binary64 = float(value)
        except OverflowError:
            as_binary64 = None
        if as_binary64 != value:
            raise ValueError("E_EGG_JSON: integer is not exactly a binary64 value")
        return _number_to_string(as_binary64)
    if isinstance(value, float):
        return _number_to_string(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, (list, dict)) and depth > 64:
        raise ValueError("E_EGG_JSON: JSON nesting exceeds 64")
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item, depth + 1) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("E_EGG_JSON: member names must be strings")
        keys = sorted(value, key=lambda key: key.encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(_string(key) + ":" + _canonical(value[key], depth + 1) for key in keys) + "}"
    raise ValueError("E_EGG_JSON: value outside the I-JSON domain")


def _json_number(token):
    number = float(token)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("E_EGG_JSON: number is not a finite binary64 value")
    try:
        same = decimal.Decimal(token) == decimal.Decimal(_number_to_string(number))
    except ArithmeticError:
        same = not any(char in "123456789" for char in token.lower().partition("e")[0])
    if not same:
        raise ValueError("E_EGG_JSON: number does not survive the binary64 round trip")
    return number


def _json_int(token):
    if token == "-0":
        return -0.0
    number = _json_number(token)
    value = int(token)
    return value if value == number else int(number)


def _json_constant(token):
    raise ValueError(f"E_EGG_JSON: {token} is not a JSON number")


def _strict_json(blob):
    """Parse one section 4 JSON text (octets or str) and return its value, or raise ValueError."""
    if isinstance(blob, (bytes, bytearray)):
        if len(blob) > _MAX_JSON_INPUT:
            raise ValueError("E_EGG_JSON: JSON text exceeds the 64 MiB input guard")
        if blob.startswith(b"\xef\xbb\xbf"):
            raise ValueError("E_EGG_JSON: JSON text starts with a byte-order mark")
        try:
            text = bytes(blob).decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"E_EGG_JSON: JSON text is not well-formed UTF-8: {error}") from None
    elif isinstance(blob, str):
        if len(blob) > _MAX_JSON_INPUT:
            raise ValueError("E_EGG_JSON: JSON text exceeds the 64 MiB input guard")
        text = blob
    else:
        raise ValueError("E_EGG_JSON: JSON text must be octets or a str")
    if text.startswith("\ufeff"):
        raise ValueError("E_EGG_JSON: JSON text starts with a byte-order mark")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"E_EGG_JSON: duplicate JSON member: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_float=_json_number,
                           parse_int=_json_int, parse_constant=_json_constant)
    except RecursionError:
        raise ValueError("E_EGG_JSON: JSON nesting exceeds 64") from None
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        children = current.values() if isinstance(current, dict) else current if isinstance(current, list) else ()
        for item in children:
            if isinstance(item, (dict, list)):
                if depth + 1 > 64:
                    raise ValueError("E_EGG_JSON: JSON nesting exceeds 64")
                stack.append((item, depth + 1))
    if len(_canonical(value).encode("utf-8")) > _MAX_CANONICAL:
        raise ValueError("E_EGG_JSON: canonical JSON exceeds 1 MiB")
    return value


def _names_ok(value):
    """Section 4 (rev-17 E-5, E-6): refuse, never normalize, a non-NFC or unassigned payload member name."""
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for name, item in current.items():
                if not isinstance(name, str):
                    raise ValueError("E_EGG_JSON: payload member names must be strings")
                if not unicodedata.is_normalized("NFC", name):
                    raise ValueError(f"E_EGG_JSON: payload member name is not NFC: {name!r}")
                if any(unicodedata.category(char) == "Cn" for char in name):
                    raise ValueError(f"E_EGG_JSON: payload member name holds an unassigned code point: {name!r}")
                stack.append(item)
        elif isinstance(current, list):
            stack.extend(current)


def _utc_valid(value):
    """Section 7.4 (rev-17 E-1): ASCII digits, proleptic Gregorian years 0000-9999."""
    if not isinstance(value, str) or len(value) != 24 or not value.isascii():
        return False
    match = _UTC.fullmatch(value)
    if not match:
        return False
    year, month, day, hour, minute, second = (int(group) for group in match.groups())
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return 1 <= month <= 12 and 1 <= day <= days[month - 1] and hour <= 23 and minute <= 59 and second <= 59


def _path_valid(path):
    if (not isinstance(path, str) or not path or path.startswith("/") or "\\" in path
            or path != unicodedata.normalize("NFC", path) or re.match(r"^[A-Za-z]:", path)):
        return False
    return not any(
        part in ("", ".", "..") or part.endswith((" ", ".")) or ":" in part
        or any(ord(char) < 32 for char in part)
        or part.split(".", 1)[0].upper() in _RESERVED
        for part in path.split("/")
    )


def _check_paths(paths):
    """Section 9.1: portable paths, equal only as code-point sequences (rev-17 E-14)."""
    paths = list(paths)
    for path in paths:
        if not _path_valid(path):
            raise ValueError(f"E_EGG_PATH: invalid relative NFC POSIX path: {path!r}")
    if len(paths) != len(set(paths)):
        raise ValueError("E_EGG_PATH: duplicate archive path or reserved root manifest.json")


def check_extractable(paths):
    """Extractor-side section 9.1 check: refuse paths that cannot coexist on common filesystems.

    A consumer that extracts refuses the extraction, not the egg; the Store applies it before
    packing because every catalog egg is hatched onto a host filesystem."""
    keys = [tuple(unicodedata.normalize("NFD", part).casefold() for part in path.split("/")) for path in paths]
    if len(keys) != len(set(keys)):
        raise ValueError("E_EGG_PATH: paths collide on common filesystems")
    ordered = sorted(keys)
    for key, following in zip(ordered, ordered[1:]):
        if len(key) < len(following) and following[:len(key)] == key:
            raise ValueError("E_EGG_PATH: file/directory path conflict")


_ZIP_LOCAL = struct.Struct("<IHHHHHIIIHH")
_ZIP_CENTRAL = struct.Struct("<IHHHHHHIIIHHHHHII")
_ZIP_END = struct.Struct("<IHHHHIIH")
_ZIP_VERSION = 0x0014   # section 9.1: version needed 20 and version made by 0x0014
_ZIP_FLAGS = 0x0800     # section 9.1: UTF-8 name; no data descriptor, no encryption
_ZIP_DOS_TIME, _ZIP_DOS_DATE = 0x0000, 0x0021
_ZIP_MAX_FIELD = 0xFFFFFFFE


def _zip_pack(entries):
    """Section 9.1 (rev-17 E-13): write every ZIP header field as pinned, so packers agree byte for byte."""
    if len(entries) > 0xFFFE:
        raise ValueError("E_EGG_ZIP: more than 65,534 entries needs ZIP64")
    local, central, offset = [], [], 0
    for name, data in entries:
        encoded = name.encode("utf-8")
        if len(encoded) > 0xFFFF:
            raise ValueError(f"E_EGG_ZIP: entry name exceeds 65,535 octets: {name!r}")
        if len(data) > _ZIP_MAX_FIELD or offset > _ZIP_MAX_FIELD:
            raise ValueError("E_EGG_ZIP: a size or offset above 0xFFFFFFFE needs ZIP64")
        crc = zlib.crc32(data) & 0xFFFFFFFF
        fields = (_ZIP_FLAGS, 0, _ZIP_DOS_TIME, _ZIP_DOS_DATE, crc, len(data), len(data), len(encoded), 0)
        header = _ZIP_LOCAL.pack(0x04034B50, _ZIP_VERSION, *fields) + encoded
        central.append(_ZIP_CENTRAL.pack(0x02014B50, _ZIP_VERSION, _ZIP_VERSION, *fields, 0, 0, 0, 0, offset)
                       + encoded)
        local += [header, data]
        offset += len(header) + len(data)
    directory = b"".join(central)
    if offset > _ZIP_MAX_FIELD or len(directory) > _ZIP_MAX_FIELD:
        raise ValueError("E_EGG_ZIP: a size or offset above 0xFFFFFFFE needs ZIP64")
    end = _ZIP_END.pack(0x06054B50, 0, 0, len(entries), len(entries), len(directory), offset, 0)
    return b"".join(local) + directory + end


def _identity_error(rappid, files):
    """Section 9.2 (rev-17 E-16): rappid.json binds the packed identity."""
    try:
        identity = _strict_json(files["rappid.json"])
    except ValueError as error:
        return f"rappid.json is invalid: {error}"
    if not isinstance(identity, dict):
        return "rappid.json MUST be an object"
    if "schema" in identity and identity["schema"] != "rapp/1":
        return "rappid.json schema, when present, MUST be rapp/1"
    if identity.get("rappid") != rappid:
        return "rappid.json identity MUST equal manifest.rappid"
    return None


def pack_rapplication(rappid: str, created_utc: str, files: dict[str, bytes], payload: dict) -> bytes:
    """Pack the exact seven-member manifest and the pinned STORED ZIP (section 9.3 producer)."""
    match = _RAPPID.fullmatch(rappid) if isinstance(rappid, str) else None
    if not match or not 1 <= len(match[1]) <= 39 or not 1 <= len(match[2]) <= 100:
        raise ValueError("E_EGG_IDENTITY: rappid violates the section 6.1 grammar")
    if not _utc_valid(created_utc):
        raise ValueError("E_EGG_UTC: created_utc must use fixed UTC milliseconds")
    if not isinstance(payload, dict):
        raise ValueError("E_EGG_JSON: egg payload MUST be an object")
    _names_ok(payload)
    for path, octets in files.items():
        if not isinstance(octets, bytes):
            raise ValueError(f"E_EGG_PATH: egg file octets MUST be bytes: {path!r}")
    _check_paths(["manifest.json", *files])
    if "rappid.json" not in files or [
        path for path in files if "/" not in path and path.endswith(".py")
    ] != ["agent.py"]:
        raise ValueError("E_EGG_AGENT: rapplication requires rappid.json and exactly one root agent.py")
    why = _identity_error(rappid, files)
    if why:
        raise ValueError("E_EGG_IDENTITY: " + why)
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
    return _zip_pack([("manifest.json", manifest_bytes)]
                     + [(item["path"], files[item["path"]]) for item in contents])
