"""All markers below are invented; no owner configuration or runtime is read."""
import base64
import gzip
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tarfile
from urllib.parse import quote
import zipfile

import pytest

import privacy_scan as privacy


FAKE_PATH = "/" + "Users" + "/synthetic-person/private-note"
FAKE_UUID = "12345678-1234-4567-89ab-123456789abc"
FAKE_OPERATION = "op-" + "1234567890" + "-abcdef12"
FAKE_TOKEN = "ghp_" + "SYNTHETIC_NOT_A_REAL_TOKEN"
POLICY = privacy.Policy(("obviously-fake-owner", "fake-workstation", "fake-private-org"))


def rules(blob, name="public.txt", **kwargs):
    return {row["rule"] for row in privacy.scan_files({name: blob}, **kwargs)["findings"]}


def zip_bytes(files, *, compression=zipfile.ZIP_DEFLATED):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression) as archive:
        for name, blob in files.items():
            archive.writestr(name, blob)
    return out.getvalue()


def tar_bytes(files, *, metadata=None):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        for name, blob in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(blob)
            if metadata:
                for key, value in metadata.items():
                    setattr(info, key, value)
            archive.addfile(info, io.BytesIO(blob))
    return out.getvalue()


def wrap(kind, contents, name="public.txt"):
    if kind in ("zip", "egg"):
        return zip_bytes({name: contents}), "public." + kind
    if kind == "tar":
        return tar_bytes({name: contents}), "public.tar"
    # GzipFile deliberately strips directories from FNAME; construct the header
    # to exercise hostile names received from other producers as well.
    blob = gzip.compress(contents, mtime=0)
    return blob[:3] + bytes([blob[3] | 8]) + blob[4:10] + name.encode() + b"\x00" + blob[10:], "public.gz"


def encoded(value, mode):
    if mode == "plain":
        return value
    if mode == "json":
        return "".join("\\u%04x" % ord(char) for char in value)
    if mode == "url":
        return "".join("%%%02X" % ord(char) for char in value)
    if mode == "double":
        return quote(encoded(value, "json"), safe="")
    if mode == "decimal":
        return "".join("&#%d;" % ord(char) for char in value)
    if mode == "hex":
        return "".join("&#x%X;" % ord(char) for char in value)
    if mode == "named":
        # Named references where HTML defines one; letters use the double-struck
        # names, which NFKC folds back to ASCII exactly as a reader sees them.
        return "".join(NAMED.get(char) or ("&" + char + "opf;" if char.isascii() and char.isalpha()
                                           else "&#x%x;" % ord(char)) for char in value)
    if mode == "nested":
        return encoded(value, "decimal").replace("&", "&amp;")
    if mode == "html-in-url":
        return quote(encoded(value, "hex"), safe="")
    if mode == "url-in-html":
        return encoded(value, "url").replace("%", "&#37;")
    if mode == "html-in-json":
        return encoded(value, "decimal").replace("&", "\\u0026")
    raise AssertionError(mode)


NAMED = {"/": "&sol;", ".": "&period;", ":": "&colon;", "_": "&lowbar;", "%": "&percnt;",
         "\\": "&bsol;", "@": "&commat;", " ": "&nbsp;"}
MODES = ["plain", "json", "url", "double"]
REFERENCES = ["decimal", "hex", "named", "nested", "html-in-url", "url-in-html", "html-in-json"]


CASES = [
    (FAKE_PATH, "P_HOME_PATH"),
    ("/home/synthetic-person/private-note", "P_HOME_PATH"),
    (r"C:\Users\synthetic-person\private-note", "P_HOME_PATH"),
    ("/root/private-note", "P_HOME_PATH"),
    ("10.255.255.254", "P_PRIVATE_ADDRESS"),
    ("172.16.0.1", "P_PRIVATE_ADDRESS"),
    ("172.31.255.254", "P_PRIVATE_ADDRESS"),
    ("192.168.100.2", "P_PRIVATE_ADDRESS"),
    ("169.254.42.1", "P_PRIVATE_ADDRESS"),
    ("fc00::1", "P_PRIVATE_ADDRESS"),
    ("fdff:ffff::1", "P_PRIVATE_ADDRESS"),
    ("fe80::1%en0", "P_PRIVATE_ADDRESS"),
    ("febf::1", "P_PRIVATE_ADDRESS"),
    ("::ffff:192.168.4.2", "P_PRIVATE_ADDRESS"),
    ("fixture-machine.local", "P_LAN_HOST"),
    ("fixture-machine.lan", "P_LAN_HOST"),
    ("fixture-machine.home.arpa", "P_LAN_HOST"),
    ("https://fixture-nas:8080/api", "P_LAN_HOST"),
    (FAKE_TOKEN, "P_TOKEN"),
    ("github_pat_" + "SYNTHETIC_NOT_A_TOKEN", "P_TOKEN"),
    ("glpat-" + "SYNTHETIC_NOT_A_TOKEN", "P_TOKEN"),
    ("xoxb-" + "SYNTHETIC_NOT_A_TOKEN", "P_TOKEN"),
    ("sk-proj-" + "SYNTHETIC_NOT_A_TOKEN", "P_TOKEN"),
    ("AKIA" + "A" * 16, "P_TOKEN"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----", "P_PRIVATE_KEY"),
    (FAKE_UUID, "P_SESSION_ID"),
    (FAKE_OPERATION, "P_OPERATION_ID"),
    ("operation_" + "a" * 24, "P_OPERATION_ID"),
    ("PRIVATE / NEVER PUBLISH", "P_PRIVATE_DOCUMENT"),
    ("obviously-fake-owner", "P_DENYLIST"),
    ("fake-workstation", "P_DENYLIST"),
    ("FAKE-PRIVATE-ORG", "P_DENYLIST"),
]


@pytest.mark.parametrize("value,rule", CASES)
@pytest.mark.parametrize("mode", MODES + REFERENCES)
def test_marker_matrix_in_contents_and_names(value, rule, mode):
    payload = encoded(value, mode)
    assert rule in rules(payload.encode(), policy=POLICY)
    assert rule in rules(b"Public fixture", name=payload + ".txt", policy=POLICY)


@pytest.mark.parametrize("value", [
    "127.0.0.1", "0.0.0.0", "::1", "localhost", "http://localhost:8000",
    "172.15.255.255", "172.32.0.0", "192.169.0.1", "169.253.2.3",
    "100.64.0.1", "192.0.2.1", "2001:db8::1", "fec0::1",
    "~/public-example", "$HOME/public-example", "Path.home()",
    "https://example.org/page", "https://public.example.com/page",
    "public.locality", "op-release-notes", "session_id = None",
    "github_pat_", "ghp_", "PUBLIC KEY", "public-owner",
])
def test_generic_defaults_and_near_misses_are_allowed(value):
    assert rules(value.encode(), policy=POLICY) == set()


@pytest.mark.parametrize("prefix", ["ghp_", "gho_", "ghu_", "ghs_", "ghr_",
                                   "sk_live_", "sk_test_", "rk_live_", "sk-ant-",
                                   "xoxa-", "xoxp-", "xoxr-", "xoxs-"])
def test_token_prefix_families(prefix):
    assert "P_TOKEN" in rules((prefix + "SYNTHETIC_NOT_A_TOKEN").encode())
    assert rules((prefix + " docs").encode()) == set()


@pytest.mark.parametrize("family", ["", "RSA ", "EC ", "DSA ", "ENCRYPTED ", "PGP "])
def test_private_key_families(family):
    suffix = " BLOCK" if family == "PGP " else ""
    assert "P_PRIVATE_KEY" in rules(("-----BEGIN " + family + "PRIVATE KEY" + suffix + "-----").encode())
    assert rules(("-----BEGIN " + family + "PUBLIC KEY-----").encode()) == set()


@pytest.mark.parametrize("outer", ["zip", "egg", "gzip", "tar"])
@pytest.mark.parametrize("inner", ["zip", "egg", "gzip", "tar"])
@pytest.mark.parametrize("mode", ["plain", "json", "url", "decimal", "hex", "named", "nested"])
def test_every_nested_container_pair_scans_names_and_contents(outer, inner, mode):
    hidden = encoded(FAKE_PATH, mode)
    for name, contents in ((hidden, b"Public fixture"), ("public.txt", hidden.encode())):
        blob, member = wrap(inner, contents, name)
        blob, root = wrap(outer, blob, member)
        assert "P_HOME_PATH" in rules(blob, root)
    clean, member = wrap(inner, b"Public fixture")
    clean, root = wrap(outer, clean, member)
    assert rules(clean, root) == set()


@pytest.mark.parametrize("suffix", ["zip", "egg", "gz", "tar"])
def test_content_magic_is_inspected_without_container_extension(suffix):
    payload, _ = wrap("gzip" if suffix == "gz" else suffix, FAKE_TOKEN.encode())
    assert "P_TOKEN" in rules(payload, "ordinary.txt")


@pytest.mark.parametrize("kind", ["zip", "egg", "gzip", "tar"])
@pytest.mark.parametrize("container", ["python", "json", "base64-file", "url-base64", "data-url"])
def test_literal_embedded_packages(kind, container):
    def document(body):
        package, _ = wrap(kind, body)
        value = base64.b64encode(package).decode()
        if container == "python":
            return ("PACKAGE = " + repr(value) + "\n").encode(), "hatcher.py"
        if container == "json":
            return json.dumps({"encoding": "base64", "data": value}).encode(), "package.json"
        if container == "url-base64":
            return quote(value, safe="").encode(), "public.txt"
        if container == "data-url":
            return ("data:application/octet-stream;base64," + value).encode(), "public.txt"
        return value.encode(), "package.b64"

    blob, name = document(FAKE_TOKEN.encode())
    assert "P_TOKEN" in rules(blob, name)
    blob, name = document(b"Public fixture")
    assert rules(blob, name) == set()


def test_python_hex_escaped_literal_is_inspected_without_execution():
    blob = ("raise RuntimeError('must not execute')\nVALUE = '" +
            "".join("\\x%02x" % ord(char) for char in FAKE_PATH) + "'\n").encode()
    assert "P_HOME_PATH" in rules(blob, "public.py")


def test_python_nontext_bytes_are_source_not_an_opaque_artifact():
    assert rules(b"MAGIC = b'\\x01\\xff\\x00'\n", "public.py") == set()


def test_json_base64_unsupported_encoding_and_malformed_data_refuse():
    for value, expected in [
        ({"encoding": "base85", "data": "abc"}, "E_UNSUPPORTED_ENCODING"),
        ({"encoding": "unreviewed-codec", "data": "abc"}, "E_UNSUPPORTED_ENCODING"),
        ({"encoding": "base64", "data": "!" * 40}, "E_BASE64"),
        ({"encoding": "base64", "data": 12}, "E_BASE64"),
        ({"encoding": "base64", "data": base64.b64encode(b"\x00\xff" * 20).decode()}, "E_OPAQUE_CONTENT"),
    ]:
        assert expected in rules(json.dumps(value).encode(), "public.json")


def test_recursively_encoded_packages_are_checked_and_depth_bounded():
    payload = zip_bytes({"public.txt": FAKE_TOKEN.encode()})
    for _ in range(3):
        payload = base64.b64encode(payload)
    assert "P_TOKEN" in rules(payload, "public.b64")
    assert "E_DEPTH_LIMIT" in rules(payload, "public.b64", limits=privacy.Limits(max_depth=2))


@pytest.mark.parametrize("name", ["state/data.json", "receipts/raw.egg", "transcripts/chat.txt",
                                  "prompts/input.txt", "registry.json", ".env", ".env.production",
                                  ".git/config", "ORGANIZATION.md", "raw-receipt.json",
                                  "frames.jsonl", "hive.json", "id_ed25519", "registry/world.json"])
def test_private_artifact_names_refuse_even_without_known_values(name):
    assert "P_PRIVATE_ARTIFACT" in rules(b"{}", name)


@pytest.mark.parametrize("name", ["generated/candidate-evidence.json", "generated/state-lifecycle.json",
                                  "source/receipts.py", "README.md", "LICENSE"])
def test_runtime_code_and_new_non_authoritative_summaries_are_not_raw_records(name):
    assert rules(b"{}", name) == set()


@pytest.mark.parametrize("bad_name", ["../escape.txt", "/absolute.txt", r"C:\drive.txt",
                                      "folder/../escape.txt", "a//b.txt", "./file.txt",
                                      "%2e%2e%2fescape.txt", "\\u002e\\u002e\\u002fescape.txt",
                                      "&#46;&#46;&#47;escape.txt", "&period;&period;&sol;escape.txt",
                                      "&amp;#x2e;&amp;#x2e;&amp;#x2f;escape.txt"])
@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_archive_path_attacks_are_refused_without_extraction(bad_name, kind):
    payload, name = wrap(kind, b"Public fixture", bad_name)
    assert "E_PATH" in rules(payload, name)


def test_zip_symlink_and_duplicate_members_are_refused():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        info = zipfile.ZipInfo("public.txt")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "elsewhere")
        archive.writestr("PUBLIC.TXT", "public")
    found = rules(out.getvalue(), "public.zip")
    assert {"E_LINK_OR_SPECIAL", "E_DUPLICATE_MEMBER"} <= found


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE])
def test_tar_links_and_special_files_refuse(kind):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        info = tarfile.TarInfo("public.txt")
        info.type = kind
        info.linkname = "elsewhere"
        archive.addfile(info)
    assert "E_LINK_OR_SPECIAL" in rules(out.getvalue(), "public.tar")


def test_archive_metadata_and_concatenated_gzip_are_inspected():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        info = zipfile.ZipInfo("public.txt")
        info.comment = encoded(FAKE_TOKEN, "url").encode()
        archive.comment = encoded(FAKE_UUID, "json").encode()
        archive.writestr(info, "Public fixture")
    assert {"P_TOKEN", "P_SESSION_ID"} <= rules(out.getvalue(), "public.zip")
    payload = tar_bytes({"public.txt": b"Public fixture"}, metadata={
        "pax_headers": {"comment": encoded(FAKE_TOKEN, "url")},
    })
    assert "P_TOKEN" in rules(payload, "public.tar")
    first = gzip.compress(b"Public fixture", mtime=0)
    second = gzip.compress(FAKE_TOKEN.encode(), mtime=0)
    assert "P_TOKEN" in rules(first + second, "public.gz")
    assert rules(first + first, "public.gz") == set()


def test_base64_in_archive_metadata_and_names_is_not_an_inspection_gap():
    encoded_path = base64.b64encode(FAKE_PATH.encode()).decode()
    assert "P_HOME_PATH" in rules(b"Public fixture", encoded_path + ".txt")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.comment = base64.b64encode(gzip.compress(FAKE_TOKEN.encode(), mtime=0))
        archive.writestr("public.txt", "Public fixture")
    assert "P_TOKEN" in rules(out.getvalue(), "public.zip")


def test_many_gzip_members_stop_at_the_shared_count_bound():
    member = gzip.compress(b"", mtime=0)
    blob = member * 2000
    assert "E_MEMBER_LIMIT" in rules(blob, "public.gz", limits=privacy.Limits(max_members=20))
    assert rules(member * 10, "public.gz", limits=privacy.Limits(max_members=11)) == set()


def test_concatenated_tar_cannot_hide_compressed_private_content_after_eof():
    first = tar_bytes({"public.txt": b"Public fixture"})
    second = tar_bytes({"hidden.gz": gzip.compress(FAKE_TOKEN.encode(), mtime=0)})
    assert "E_CONTAINER_FORMAT" in rules(first + second, "public.tar")


def test_tar_extended_metadata_counts_against_member_limit():
    blob = tar_bytes({"public.txt": b"Public fixture"}, metadata={"pax_headers": {"comment": "Public metadata"}})
    assert "E_MEMBER_LIMIT" in rules(blob, "public.tar", limits=privacy.Limits(max_members=2))
    assert rules(blob, "public.tar", limits=privacy.Limits(max_members=3)) == set()


HIDDEN = b"obviously-fake-owner " + FAKE_PATH.encode()


def formatted_tar(files, *, fmt=tarfile.USTAR_FORMAT, **options):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=fmt, **options) as archive:
        for name, blob in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(blob)
            archive.addfile(info, io.BytesIO(blob))
    return out.getvalue()


def patched(blob, start, edits):
    """Rewrite one header block, then restore a checksum every reader accepts."""
    blob, header = bytearray(blob), bytearray(blob[start:start + 512])
    for offset, data in edits.items():
        header[offset:offset + len(data)] = data
    header[148:156] = b" " * 8
    header[148:156] = b"%06o\x00 " % sum(header)
    blob[start:start + 512] = header
    return bytes(blob)


def readable(blob, name="public.txt"):
    with tarfile.open(fileobj=io.BytesIO(blob)) as archive:
        return archive.extractfile(name).read()


def padded_tar(hidden=HIDDEN):
    clean = formatted_tar({"public.txt": b"P"})
    return clean[:513] + hidden + clean[513 + len(hidden):]


def tar_findings(blob):
    report = privacy.scan_files({"public.tar": blob}, policy=POLICY)
    rendered = json.dumps(report)
    assert "fake" not in rendered and FAKE_PATH not in rendered
    return {(row["rule"], row["location"]) for row in report["findings"]}


@pytest.mark.parametrize("fmt", [tarfile.USTAR_FORMAT, tarfile.GNU_FORMAT, tarfile.PAX_FORMAT])
@pytest.mark.parametrize("hidden", [HIDDEN, b"\x01"])
def test_tar_member_padding_is_accounted_not_skipped(fmt, hidden):
    clean = formatted_tar({"public.txt": b"P"}, fmt=fmt)
    blob = clean[:513] + hidden + clean[513 + len(hidden):]
    assert readable(blob) == b"P"
    assert tar_findings(blob) == {("E_CONTAINER_FORMAT", "file[0]/tar-header[0]/padding")}
    assert tar_findings(clean) == set()


@pytest.mark.parametrize("wrapper", ["zip", "egg", "gzip", "tar", "base64", "json-base64"])
def test_tar_padding_counterexample_refuses_inside_every_wrapper(wrapper):
    def outer(blob):
        if wrapper == "base64":
            return base64.b64encode(blob), "package.b64"
        if wrapper == "json-base64":
            return json.dumps({"encoding": "base64", "data": base64.b64encode(blob).decode()}).encode(), "package.json"
        return wrap(wrapper, blob, "inner.tar")

    assert "E_CONTAINER_FORMAT" in rules(*outer(padded_tar()), policy=POLICY)
    assert rules(*outer(formatted_tar({"public.txt": b"P"})), policy=POLICY) == set()


@pytest.mark.parametrize("edits", [
    {11: b"obviously-fake-owner"},          # name after its terminator
    {158: b"fake-workstation"},             # linkname
    {266: b"fake-workstation"},             # uname
    {298: b"fake-workstation"},             # gname
    {346: HIDDEN[:40]},                     # prefix
    {500: b"hidden-bytes"},                 # trailing header pad
    {124: b"1\x00hidden!!!!"},              # numeric field after its terminator
    {100: b"644\x00abc\x00"},               # mode slack
    {108: b"\x80\x00\x00\x00\x00\x00\x01\xf5"},  # unsupported base-256 number
    {257: b"\x00" * 8},                     # pre-POSIX header without magic
    {263: b"01"},                           # unknown version
])
def test_tar_header_slack_and_unknown_forms_refuse(edits):
    blob = patched(formatted_tar({"public.txt": b"P"}), 0, edits)
    assert readable(blob) == b"P"
    assert ("E_CONTAINER_FORMAT", "file[0]/tar-header[0]") in tar_findings(blob)


def test_tar_extension_payload_bytes_are_all_inspected():
    clean = tar_bytes({"public.txt": b"P"}, metadata={"pax_headers": {"comment": "Public"}})
    size = tarfile.TarInfo.frombuf(clean[:512], "utf-8", "surrogateescape").size
    hidden = b"\x00obviously-fake-owner"
    blob = patched(clean[:512 + size] + hidden + clean[512 + size + len(hidden):], 0,
                   {124: b"%011o\x00" % (size + len(hidden))})
    assert readable(blob) == b"P"
    assert ("P_DENYLIST", "file[0]/tar-header[0]/extension") in tar_findings(blob)
    blob = clean[:512 + size + 3] + HIDDEN + clean[512 + size + 3 + len(HIDDEN):]
    assert readable(blob) == b"P"
    assert ("E_CONTAINER_FORMAT", "file[0]/tar-header[0]/padding") in tar_findings(blob)
    name = "public/" + "n" * 120 + ".txt"
    clean = formatted_tar({name: b"P"}, fmt=tarfile.GNU_FORMAT)
    size = tarfile.TarInfo.frombuf(clean[:512], "utf-8", "surrogateescape").size
    blob = patched(clean[:512 + size] + hidden + clean[512 + size + len(hidden):], 0,
                   {124: b"%011o\x00" % (size + len(hidden))})
    assert readable(blob, name) == b"P"
    assert ("P_DENYLIST", "file[0]/tar-header[0]/extension") in tar_findings(blob)


@pytest.mark.parametrize("legacy,rule", [("../escape.txt", "E_PATH"), (".env", "P_PRIVATE_ARTIFACT"),
                                         ("state/raw.json", "P_PRIVATE_ARTIFACT")])
def test_tar_legacy_names_behind_pax_paths_are_checked_as_names(legacy, rule):
    blob = tar_bytes({legacy: b"P"}, metadata={"pax_headers": {"path": "public.txt"}})
    assert readable(blob) == b"P"
    assert (rule, "file[0]/tar-header[1]/name") in tar_findings(blob)
    assert tar_findings(tar_bytes({"public.txt": b"P"}, metadata={"pax_headers": {"path": "public.txt"}})) == set()


def test_tar_framing_ambiguity_and_incomplete_end_refuse():
    clean = formatted_tar({"public.txt": b"P"})
    extended = tar_bytes({"public.txt": b"P"}, metadata={"pax_headers": {"comment": "Public"}})
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for kind in (tarfile.DIRTYPE, tarfile.SYMTYPE):
            info = tarfile.TarInfo("entry-" + kind.decode())
            info.type, info.size = kind, 5
            archive.addfile(info, io.BytesIO(b"bytes"))
    for blob in (
        tar_bytes({"public.txt": b"P"}, metadata={"pax_headers": {"size": "513"}}),
        extended[:1024] + b"\x00" * 1024,
        clean[:1024] + b"\x00" * 512,
        clean[:-1] + b"\x01",
        patched(clean, 0, {124: b"%011o\x00" % 99999}),
        out.getvalue(),
    ):
        assert "E_CONTAINER_FORMAT" in {rule for rule, _ in tar_findings(blob)}


@pytest.mark.parametrize("fmt", [tarfile.USTAR_FORMAT, tarfile.GNU_FORMAT, tarfile.PAX_FORMAT])
def test_ordinary_tar_layouts_remain_supported(fmt):
    options = {"pax_headers": {"comment": "Public archive"}} if fmt == tarfile.PAX_FORMAT else {}
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=fmt, **options) as archive:
        folder = tarfile.TarInfo("folder")
        folder.type = tarfile.DIRTYPE
        archive.addfile(folder)
        for name, blob in {"folder/empty.txt": b"", "one.txt": b"P", "block.txt": b"B" * 512,
                           "l" * 60 + "/" + "n" * 60 + ".txt": b"Long public name"}.items():
            info = tarfile.TarInfo(name)
            info.size, info.mtime = len(blob), 1_700_000_000.5
            archive.addfile(info, io.BytesIO(blob))
    blob = out.getvalue()
    assert tar_findings(blob) == set()
    assert rules(gzip.compress(blob, mtime=0), "public.tgz", policy=POLICY) == set()
    assert rules(zip_bytes({"public.tar": blob}), "public.zip", policy=POLICY) == set()


def test_zip_local_only_metadata_is_inspected():
    blob = bytearray(zip_bytes({"public.txt": b"Public fixture"}))
    name_length = struct.unpack_from("<H", blob, 26)[0]
    extra = encoded(FAKE_PATH, "url").encode()
    extra = struct.pack("<HH", 0xcafe, len(extra)) + extra
    struct.pack_into("<H", blob, 28, len(extra))
    blob[30 + name_length:30 + name_length] = extra
    end = blob.rfind(b"PK\x05\x06")
    start = struct.unpack_from("<I", blob, end + 16)[0]
    struct.pack_into("<I", blob, end + 16, start + len(extra))
    assert "P_HOME_PATH" in rules(bytes(blob), "public.zip")


def test_zip_gap_and_deflate_trailer_cannot_hide_private_content():
    original = zip_bytes({"public.txt": b"Public fixture"})
    for inside_stream in (False, True):
        blob = bytearray(original)
        start = blob.find(b"PK\x01\x02")
        hidden = gzip.compress(FAKE_TOKEN.encode(), mtime=0)
        blob[start:start] = hidden
        central = start + len(hidden)
        end = blob.rfind(b"PK\x05\x06")
        struct.pack_into("<I", blob, end + 16, central)
        if inside_stream:
            compressed = struct.unpack_from("<I", blob, 18)[0] + len(hidden)
            struct.pack_into("<I", blob, 18, compressed)
            struct.pack_into("<I", blob, central + 20, compressed)
        assert "E_CONTAINER_FORMAT" in rules(bytes(blob), "public.zip")


def test_streamed_zip_with_data_descriptor_is_supported():
    class Streaming(io.BytesIO):
        def seekable(self):
            return False

        def seek(self, *args):
            raise OSError("synthetic nonseekable stream")

    output = Streaming()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("public.txt", "Public fixture")
    assert rules(output.getvalue(), "public.zip") == set()


def test_malformed_embedded_package_is_not_silently_ignored():
    value = base64.b64encode(zip_bytes({"public.txt": b"Public fixture"})).decode()
    assert "E_BASE64" in rules(("DATA = " + repr(value[:-1])).encode(), "public.py")


@pytest.mark.parametrize("name", ["public.zip", "public.egg", "public.gz", "public.tar"])
def test_declared_but_malformed_container_refuses(name):
    assert "E_CONTAINER_FORMAT" in rules(b"Not a container", name)


@pytest.mark.parametrize("kind", ["zip", "gzip", "tar"])
def test_truncated_container_refuses(kind):
    blob, name = wrap(kind, b"Public fixture")
    assert "E_CONTAINER_FORMAT" in rules(blob[:-17], name)


def test_encryption_unsupported_compression_and_trailing_zip_data_refuse():
    blob = bytearray(zip_bytes({"public.txt": b"Public fixture"}))
    local = blob.find(b"PK\x03\x04")
    central = blob.find(b"PK\x01\x02")
    struct.pack_into("<H", blob, local + 6, 1)
    struct.pack_into("<H", blob, central + 8, 1)
    assert "E_UNSUPPORTED_CONTAINER" in rules(bytes(blob), "public.zip")
    blob = zip_bytes({"public.txt": b"Public fixture"}, compression=zipfile.ZIP_BZIP2)
    assert "E_UNSUPPORTED_CONTAINER" in rules(blob, "public.zip")
    blob = zip_bytes({"public.txt": b"Public fixture"}) + b"trailing-unreviewed-content"
    assert "E_CONTAINER_FORMAT" in rules(blob, "public.zip")


@pytest.mark.parametrize("blob,name", [
    (b"Rar!\x1a\x07\x00", "public.dat"), (b"7z\xbc\xaf\x27\x1c", "public.dat"),
    (b"BZh91", "public.dat"), (b"\xfd7zXZ\x00", "public.dat"),
    (b"\x28\xb5\x2f\xfd", "public.dat"), (b"unknown", "public.rar"),
    (b"\x00\xff\x01\x02", "public.dat"), (b"image", "public.png"),
])
def test_opaque_or_unsupported_content_never_passes(blob, name):
    assert rules(blob, name) & {"E_UNSUPPORTED_CONTAINER", "E_OPAQUE_CONTENT"}


def test_cumulative_member_depth_byte_and_decode_limits():
    blob = zip_bytes({"first.txt": b"Public", "second.txt": b"Public"})
    assert "E_MEMBER_LIMIT" in rules(blob, "public.zip", limits=privacy.Limits(max_members=2))
    nested = blob
    for _ in range(4):
        nested = zip_bytes({"inner.egg": nested})
    assert "E_DEPTH_LIMIT" in rules(nested, "public.zip", limits=privacy.Limits(max_depth=2))
    report = privacy.scan_files({"a.txt": b"a" * 50, "b.txt": b"b" * 50},
                                limits=privacy.Limits(max_total_bytes=99))
    assert any(row["rule"] == "E_BYTE_LIMIT" for row in report["findings"])
    bomb = gzip.compress(b"A" * 200_000, mtime=0)
    assert "E_BYTE_LIMIT" in rules(bomb, "public.gz", limits=privacy.Limits(max_file_bytes=4096))
    value = "%25252525252525252F"
    assert "E_ENCODING_LIMIT" in rules(value.encode(), limits=privacy.Limits(max_decode_rounds=2))
    assert "E_BYTE_LIMIT" in rules(b"A" * 20, limits=privacy.Limits(max_file_bytes=10))


def test_cumulative_expansion_is_shared_across_separate_archives():
    package = gzip.compress(b"Public\n" * 500, mtime=0)
    assert rules(package, "public.gz", limits=privacy.Limits(max_total_bytes=4000)) == set()
    result = privacy.scan_files({"a.gz": package, "b.gz": package}, limits=privacy.Limits(max_total_bytes=4000))
    assert any(row["rule"] == "E_BYTE_LIMIT" for row in result["findings"])


def test_refusal_diagnostics_are_deterministic_and_never_echo_matches():
    files = {FAKE_PATH + ".txt": (FAKE_UUID + "\n" + FAKE_TOKEN).encode()}
    first = privacy.scan_files(files, policy=POLICY)
    assert first == privacy.scan_files(dict(reversed(list(files.items()))), policy=POLICY)
    with pytest.raises(privacy.PrivacyRefusal) as caught:
        privacy.require_clean(files)
    rendered = json.dumps(first) + str(caught.value) + json.dumps(caught.value.report())
    for marker in (FAKE_PATH, FAKE_UUID, FAKE_TOKEN):
        assert marker not in rendered
    assert "P_TOKEN" in rendered and "file[0]" in rendered


def test_runtime_config_is_strict_literal_private_and_not_copied(tmp_path):
    config = tmp_path / "private-config.json"
    config.write_text(json.dumps({"version": 1, "deny": list(POLICY.deny)}))
    loaded = privacy.load_policy(config)
    assert loaded == POLICY
    assert all(value not in repr(loaded) for value in loaded.deny)
    assert "P_DENYLIST" in rules(b"fake-workstation", policy=loaded)
    for bad in [
        {"version": True, "deny": []}, {"version": 1, "deny": "name"},
        {"version": 1, "deny": ["x"]}, {"version": 1, "deny": [1]},
        {"version": 1, "deny": ["\ud800invalid"]},
        {"version": 1, "deny": [], "unknown": "not accepted"},
    ]:
        config.write_text(json.dumps(bad))
        with pytest.raises(privacy.PrivacyRefusal, match="E_DENYLIST"):
            privacy.load_policy(config)
    config.write_text('{"version":1,"version":1,"deny":[]}')
    with pytest.raises(privacy.PrivacyRefusal, match="E_DENYLIST"):
        privacy.load_policy(config)


def test_unicode_private_markers_survive_json_surrogates_and_url_encoding():
    marker = "synthetic-\U0001f600-owner"
    policy = privacy.Policy((marker,))
    for encoded_marker in (json.dumps(marker, ensure_ascii=True), quote(marker, safe=""),
                           encoded(marker, "decimal"), encoded(marker, "hex")):
        assert "P_DENYLIST" in rules(encoded_marker.encode(), policy=policy)
    assert rules(b"synthetic-public-owner", policy=policy) == set()


@pytest.mark.parametrize("text", [
    "Tom &amp; Jerry &lt;b&gt;bold&lt;/b&gt; &copy; 2026 &mdash; caf&eacute;",
    "&#169; &#x2014; &nbsp; &quot;quoted&quot; &apos;single&apos; &hellip;",
    '<a href="https://example.org/?a=1&amp;b=2&copy=3">Docs &raquo;</a>',
    "AT&T R&D &unknown; & ; &#; &#x; &#xZZ;", "&#x2F;docs&#x2F;index.html",
    "Unicode &#x1F600; and &#8364; are public", "public&#45;owner &lt;fake&gt;",
])
def test_ordinary_character_references_remain_public(text):
    assert rules(text.encode(), "public.html", policy=POLICY) == set()


@pytest.mark.parametrize("name", ["Tom &amp; Jerry.md", "caf&eacute;.md", "notes&#x2d;2026.txt",
                                  "R&D.md", "docs/&lt;index&gt;.html"])
def test_ordinary_character_references_in_names_remain_public(name):
    assert rules(b"Public fixture", name, policy=POLICY) == set()


def test_character_references_hide_nothing_in_every_supported_location():
    marker = encoded("obviously-fake-owner", "hex")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        info = zipfile.ZipInfo("public.txt")
        info.comment = marker.encode()
        archive.writestr(info, "Public fixture")
    assert "P_DENYLIST" in rules(out.getvalue(), "public.zip", policy=POLICY)
    blob = tar_bytes({"public.txt": b"Public fixture"}, metadata={"pax_headers": {"comment": marker}})
    assert "P_DENYLIST" in rules(blob, "public.tar", policy=POLICY)
    blob = tar_bytes({"public.txt": b"Public fixture"}, metadata={"uname": encoded("fake-workstation", "decimal")})
    assert "P_DENYLIST" in rules(blob, "public.tar", policy=POLICY)
    blob, name = wrap("gzip", b"Public fixture", marker)
    assert "P_DENYLIST" in rules(blob, name, policy=POLICY)
    for body in (json.dumps({"description": marker}), "VALUE = " + repr(marker) + "\n"):
        for name in ("public.json", "public.py"):
            assert "P_DENYLIST" in rules(body.encode(), name, policy=POLICY)


@pytest.mark.parametrize("kind", ["zip", "egg", "gzip", "tar"])
@pytest.mark.parametrize("container", ["python", "json", "base64-file", "data-url"])
def test_character_referenced_markers_inside_wrappers_refuse(kind, container):
    for mode in ("decimal", "hex", "named", "nested"):
        package, _ = wrap(kind, encoded(FAKE_PATH, mode).encode())
        value = base64.b64encode(package).decode()
        blob, name = {
            "python": (("PACKAGE = " + repr(value) + "\n").encode(), "hatcher.py"),
            "json": (json.dumps({"encoding": "base64", "data": value}).encode(), "package.json"),
            "base64-file": (value.encode(), "package.b64"),
            "data-url": (("data:application/octet-stream;base64," + value).encode(), "public.txt"),
        }[container]
        assert "P_HOME_PATH" in rules(blob, name)
    plain = base64.b64encode(encoded(FAKE_TOKEN, "decimal").encode()).decode()
    assert "P_TOKEN" in rules(("TEXT = " + repr(plain)).encode(), "public.py")


def test_character_reference_decoding_is_bounded_and_fails_closed():
    layered = encoded(FAKE_PATH, "decimal")
    for _ in range(7):
        layered = layered.replace("&", "&amp;")
    assert rules(layered.encode()) == {"P_HOME_PATH"}
    assert "E_ENCODING_LIMIT" in rules(layered.replace("&", "&amp;").encode())
    assert "E_ENCODING_LIMIT" in rules(encoded(FAKE_PATH, "nested").encode(),
                                       limits=privacy.Limits(max_decode_rounds=1))
    assert "E_TEXT_ENCODING" in rules(("&#" + "9" * 5000 + ";").encode())
    report = privacy.scan_files({"public.txt": encoded(FAKE_PATH, "named").encode()})
    assert FAKE_PATH not in json.dumps(report) and "&sol;" not in json.dumps(report)


@pytest.mark.parametrize("blob,name,expected", [
    (b'{"same":1,"same":2}', "public.json", "E_DOCUMENT_FORMAT"),
    (b'{"bad":NaN}', "public.json", "E_DOCUMENT_FORMAT"),
    (b'{"unfinished":', "public.json", "E_DOCUMENT_FORMAT"),
    (b'def missing(', "public.py", "E_DOCUMENT_FORMAT"),
    (b'bad percent %FF', "public.txt", "E_TEXT_ENCODING"),
    (b'{"unpaired":"\\ud800"}', "public.json", "E_TEXT_ENCODING"),
])
def test_malformed_supported_text_never_becomes_a_clean_result(blob, name, expected):
    assert expected in rules(blob, name)


def test_tree_snapshot_rejects_links_ignored_private_roots_and_empty_dirs(tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    (root / "public.txt").write_text("Public fixture")
    assert privacy.read_tree(root) == {"public.txt": b"Public fixture"}
    for link in ("symlink", "hardlink"):
        target = root / "link.txt"
        if link == "symlink":
            target.symlink_to("public.txt")
        else:
            os.link(root / "public.txt", target)
        with pytest.raises(privacy.PrivacyRefusal, match="E_LINK_OR_SPECIAL|E_INPUT_FILE"):
            privacy.read_tree(root)
        target.unlink()
    (root / ".git").mkdir()
    with pytest.raises(privacy.PrivacyRefusal, match="P_PRIVATE_ARTIFACT"):
        privacy.read_tree(root)
    (root / ".git").rmdir()
    (root / "empty").mkdir()
    with pytest.raises(privacy.PrivacyRefusal, match="E_EMPTY_DIRECTORY"):
        privacy.read_tree(root)


def test_root_and_ancestor_symlinks_are_not_followed(tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    (root / "file.txt").write_text("public")
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(privacy.PrivacyRefusal, match="E_INPUT_TREE"):
        privacy.read_tree(link)


def test_writer_refuses_before_any_directory_creation(tmp_path):
    output = tmp_path / "not-created" / "public"
    with pytest.raises(privacy.PrivacyRefusal, match="P_TOKEN"):
        privacy.write_tree({"public.txt": FAKE_TOKEN.encode()}, output)
    assert not output.parent.exists()


def test_writer_is_create_only_and_produces_exact_bytes(tmp_path):
    files = {"a.txt": b"Public fixture", "nested/b.txt": b"Public second fixture"}
    output = tmp_path / "export" / "public"
    result = privacy.write_tree(files, output)
    assert result["status"] == "clean"
    assert privacy.read_tree(output) == files
    assert not list(output.parent.glob(".public-build-*"))
    with pytest.raises(ValueError, match="new directory"):
        privacy.write_tree(files, output)
    assert privacy.read_tree(output) == files


def test_writer_cleans_failed_build_without_publishing(tmp_path, monkeypatch):
    output = tmp_path / "new-parent" / "public"

    def fail(_):
        raise OSError("synthetic disk refusal")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(privacy.PrivacyRefusal, match="E_OUTPUT_IO"):
        privacy.write_tree({"public.txt": b"Public fixture"}, output)
    assert not output.exists() and not output.parent.exists()


def test_writer_never_clobbers_a_destination_created_at_commit_time(tmp_path, monkeypatch):
    output = tmp_path / "public"
    rename = privacy._rename_new
    competitor = {}

    def race(parent, source, target):
        output.mkdir()
        competitor["inode"] = output.stat().st_ino
        rename(parent, source, target)

    monkeypatch.setattr(privacy, "_rename_new", race)
    with pytest.raises(privacy.PrivacyRefusal, match="E_OUTPUT_IO"):
        privacy.write_tree({"public.txt": b"Public fixture"}, output)
    assert output.stat().st_ino == competitor["inode"]
    assert list(output.iterdir()) == []
    assert not list(tmp_path.glob(".public-build-*"))


@pytest.mark.parametrize("files", [
    {"public.html": encoded("obviously-fake-owner", "decimal").encode()},
    {encoded(FAKE_PATH, "hex") + ".txt": b"Public fixture"},
    {"public.tar": padded_tar()},
], ids=["encoded-content", "encoded-name", "tar-padding"])
def test_writer_refuses_encoded_and_padded_inputs_and_preserves_destinations(tmp_path, files):
    fresh = tmp_path / "not-created" / "public"
    with pytest.raises(privacy.PrivacyRefusal) as caught:
        privacy.write_tree(files, fresh, policy=POLICY)
    assert not fresh.parent.exists()
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "kept.txt").write_bytes(b"Existing public bytes")
    with pytest.raises(privacy.PrivacyRefusal):
        privacy.write_tree(files, existing, policy=POLICY)
    assert privacy.read_tree(existing) == {"kept.txt": b"Existing public bytes"}
    assert not list(tmp_path.glob(".public-build-*"))
    rendered = str(caught.value) + json.dumps(caught.value.report())
    for secret in ("fake", "&#", FAKE_PATH, encoded(FAKE_PATH, "hex")):
        assert secret not in rendered


@pytest.mark.parametrize("files", [{"a": b"Public", "a/b": b"Public"},
                                  {"a/b": b"Public", "a/b/c": b"Public"},
                                  {"a/": b"Public"}])
def test_path_shape_collisions_refuse_before_output(tmp_path, files):
    output = tmp_path / "not-created" / "public"
    with pytest.raises(privacy.PrivacyRefusal, match="E_PATH"):
        privacy.write_tree(files, output)
    assert not output.parent.exists()


def test_unrelated_basename_does_not_conflict_with_a_parent_directory():
    assert privacy.scan_files({"b": b"Public", "a/b/c": b"Public"})["status"] == "clean"


def test_cli_has_safe_machine_readable_refusal_and_no_writes(tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    (root / "file.txt").write_text(FAKE_TOKEN)
    config = tmp_path / "config.json"
    config.write_text('{"version":1,"deny":[]}')
    result = subprocess.run([sys.executable, "-B", str(Path(privacy.__file__)),
                             str(root), "--denylist", str(config)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1 and result.stderr == ""
    assert json.loads(result.stdout)["status"] == "refused"
    assert FAKE_TOKEN not in result.stdout
    assert sorted(p.name for p in root.iterdir()) == ["file.txt"]


def test_cli_refuses_encoded_and_padded_counterexamples_without_echoing_them(tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    (root / "notes.html").write_text(encoded(FAKE_TOKEN, "hex"))
    (root / "bundle.tar").write_bytes(padded_tar())
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"version": 1, "deny": list(POLICY.deny)}))
    result = subprocess.run([sys.executable, "-B", str(Path(privacy.__file__)),
                             str(root), "--denylist", str(config)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1 and result.stderr == ""
    found = {(row["rule"], row["location"]) for row in json.loads(result.stdout)["findings"]}
    assert found == {("E_CONTAINER_FORMAT", "file[0]/tar-header[0]/padding"),
                     ("P_TOKEN", "file[1]/content")}
    for secret in (FAKE_TOKEN, encoded(FAKE_TOKEN, "hex"), "fake", FAKE_PATH):
        assert secret not in result.stdout
    assert sorted(p.name for p in root.iterdir()) == ["bundle.tar", "notes.html"]
