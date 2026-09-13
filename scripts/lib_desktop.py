"""Optional native-release metadata and anonymous, bounded byte verification.

These checks bind publisher evidence to public release bytes. They do not
authenticate Apple reports or confer RAPP/1 identity, signing, or acceptance.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request


SCHEMA_DESKTOP = "rapp-desktop/1.0"
SCHEMA_EVIDENCE = "rapp-desktop-evidence/1.0"
MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024
MAX_EVIDENCE_BYTES = 256 * 1024
MAX_METADATA_BYTES = 5 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
MAX_DOWNLOAD_SECONDS = 900
ARCHITECTURES = ("arm64", "x86_64")
ARTIFACT_FORMATS = ("dmg", "zip")
MAX_ARTIFACTS = len(ARCHITECTURES) * len(ARTIFACT_FORMATS)

COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
VERSION_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
OS_RE = re.compile(r"(1[0-9]|[2-9][0-9])\.(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?\Z")
BUNDLE_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z][A-Za-z0-9-]*){2,}\Z")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
APP_PATH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()-]*\.app\Z")

DESKTOP_FIELDS = {
    "schema", "platform", "minimum_os", "bundle_id", "source", "release_tag",
    "artifacts", "prerequisites", "privacy", "setup", "agent_integration",
}
ARTIFACT_FIELDS = {"arch", "format", "url", "bytes", "sha256", "evidence"}
REFERENCE_FIELDS = {"url", "bytes", "sha256"}
SOURCE_FIELDS = {"repo", "commit_sha"}
UNSUPPORTED_CLAIMS = {
    "rappid", "parent_rappid", "identity", "wire_contract", "ecosystem_acceptance",
    "egg_url", "hatcher_url", "notarized", "signed", "trust",
}


class DesktopError(ValueError):
    pass


def _matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _text(value, limit=4000):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and not any(ord(c) < 32 and c not in "\n\t" for c in value))


def _exact_fields(value, fields):
    return isinstance(value, dict) and set(value) == fields


def release_url(repo, tag, filename):
    return f"https://github.com/{repo}/releases/download/{tag}/{filename}"


def artifact_filename(entry, arch, artifact_format="dmg"):
    return f"{entry['id']}-{entry['version']}-{arch}.{artifact_format}"


def evidence_filename(entry, arch, artifact_format="dmg", *, sha256=None):
    filename = artifact_filename(entry, arch, artifact_format)
    # Preserve existing DMG references while allowing both formats per arch.
    stem = filename[:-4] if artifact_format == "dmg" else filename
    digest = f".{sha256}" if sha256 is not None else ""
    return stem + ".evidence" + digest + ".json"


def _reference_errors(value, expected_url, cap, label):
    errors = []
    if not isinstance(value, dict):
        return [f"E_DESKTOP_REFERENCE: {label} must be an object"]
    expected_urls = expected_url if isinstance(expected_url, tuple) else (expected_url,)
    if value.get("url") not in expected_urls:
        errors.append(f"E_DESKTOP_URL: {label}.url must be the exact same-repo versioned release asset URL")
    size = value.get("bytes")
    if type(size) is not int or not 0 < size <= cap:
        errors.append(f"E_DESKTOP_SIZE: {label}.bytes must be an integer in 1..{cap}")
    if not _matches(SHA256_RE, value.get("sha256")):
        errors.append(f"E_DESKTOP_SHA256: {label}.sha256 must be 64 lowercase hex characters")
    return errors


def validate_metadata(entry, *, repo=None, previous=None):
    """Validate shape/bindings without fetching anything (also used by v1 projection)."""
    if not isinstance(entry, dict):
        return ["E_DESKTOP_SCHEMA: manifest/catalog entry must be an object"]
    errors = []
    desktop = entry.get("desktop")
    prior_desktop = (previous or {}).get("desktop")
    if "desktop" not in entry:
        return (["E_DESKTOP_REQUIRED: an existing native listing cannot silently drop desktop metadata"]
                if prior_desktop else [])
    if not _exact_fields(desktop, DESKTOP_FIELDS):
        return ["E_DESKTOP_SCHEMA: desktop must contain exactly the documented rapp-desktop/1.0 fields"]
    if desktop["schema"] != SCHEMA_DESKTOP or desktop["platform"] != "macos":
        errors.append("E_DESKTOP_SCHEMA: only rapp-desktop/1.0 platform macos is supported")
    if entry.get("access", "public") != "public":
        errors.append("E_DESKTOP_PUBLIC_ONLY: native releases require anonymous public federation")
    if not _matches(VERSION_RE, entry.get("version")):
        errors.append("E_DESKTOP_VERSION: native version must be canonical MAJOR.MINOR.PATCH")
    if not _matches(ID_RE, entry.get("id")):
        errors.append("E_DESKTOP_ID: native catalog id must be snake_case")
    if errors:
        return errors
    if not _matches(OS_RE, desktop["minimum_os"]):
        errors.append("E_DESKTOP_OS: minimum_os must be a macOS version such as 14.0")
    if not _matches(BUNDLE_ID_RE, desktop["bundle_id"]):
        errors.append("E_DESKTOP_BUNDLE_ID: bundle_id must be a stable reverse-DNS identifier")
    for key in ("privacy", "agent_integration"):
        if not _text(desktop[key]):
            errors.append(f"E_DESKTOP_DISCLOSURE: {key} must be nonempty plain text (at most 4000 characters)")
    for key in ("prerequisites", "setup"):
        values = desktop[key]
        if (not isinstance(values, list) or not 1 <= len(values) <= 20
                or not all(_text(value, 1000) for value in values)):
            errors.append(f"E_DESKTOP_DISCLOSURE: {key} must contain 1..20 nonempty text items")
    source = desktop["source"]
    if (not _exact_fields(source, SOURCE_FIELDS)
            or not _matches(REPO_RE, source.get("repo"))
            or not _matches(COMMIT_RE, source.get("commit_sha"))):
        errors.append("E_DESKTOP_SOURCE: source requires repo and a full lowercase 40-hex native-build commit_sha")
        return errors
    if repo is not None and source["repo"] != repo:
        errors.append("E_DESKTOP_REPO: native build and federation must use the same owner/repo")
    if previous:
        old_repo = (previous.get("source") or {}).get("repo")
        if old_repo and source["repo"] != old_repo:
            errors.append("E_DESKTOP_REPO: existing listing cannot change source owner/repo")
        if previous.get("publisher") and entry.get("publisher") != previous["publisher"]:
            errors.append("E_DESKTOP_PUBLISHER: existing native listing cannot change publisher")
    if prior_desktop and desktop["bundle_id"] != prior_desktop.get("bundle_id"):
        errors.append("E_DESKTOP_BUNDLE_ID: existing native listing cannot change bundle_id")
    if desktop["release_tag"] != f"v{entry.get('version')}":
        errors.append("E_DESKTOP_TAG: release_tag must be v<manifest.version>")
    forbidden = sorted(UNSUPPORTED_CLAIMS.intersection(entry))
    if forbidden:
        errors.append("E_DESKTOP_UNSUPPORTED_CLAIM: native metadata cannot supply " + ", ".join(forbidden))

    artifacts = desktop["artifacts"]
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= MAX_ARTIFACTS:
        return errors + ["E_DESKTOP_ARTIFACTS: provide 1..4 architecture-specific DMG/ZIP releases"]
    seen = set()
    for artifact in artifacts:
        if not _exact_fields(artifact, ARTIFACT_FIELDS):
            errors.append("E_DESKTOP_ARTIFACT: each artifact must contain exactly arch, format, url, bytes, sha256, evidence")
            continue
        arch = artifact["arch"]
        if not isinstance(arch, str) or arch not in ARCHITECTURES:
            errors.append("E_DESKTOP_ARCH: arch must be arm64 or x86_64 (no universal artifacts)")
            continue
        artifact_format = artifact["format"]
        if artifact_format not in ARTIFACT_FORMATS:
            errors.append("E_DESKTOP_FORMAT: only DMG and ZIP release assets are supported")
            continue
        pair = (arch, artifact_format)
        if pair in seen:
            errors.append("E_DESKTOP_ARCH: each architecture/format pair must be unique")
            continue
        seen.add(pair)
        filename = artifact_filename(entry, arch, artifact_format)
        url = release_url(source["repo"], desktop["release_tag"], filename)
        errors.extend(_reference_errors(artifact, url, MAX_ARTIFACT_BYTES, arch))
        evidence = artifact["evidence"]
        if not _exact_fields(evidence, REFERENCE_FIELDS):
            errors.append("E_DESKTOP_EVIDENCE: evidence requires exactly url, bytes, sha256")
        evidence_urls = [release_url(source["repo"], desktop["release_tag"],
                                      evidence_filename(entry, arch, artifact_format))]
        if isinstance(evidence, dict) and _matches(SHA256_RE, evidence.get("sha256")):
            evidence_urls.append(release_url(
                source["repo"], desktop["release_tag"],
                evidence_filename(entry, arch, artifact_format, sha256=evidence["sha256"])))
        errors.extend(_reference_errors(evidence, tuple(evidence_urls), MAX_EVIDENCE_BYTES, f"{arch}.evidence"))
    return errors


def _safe_transport_url(url, *, redirect=False):
    try:
        parsed = urllib.parse.urlsplit(url)
        hosts = {"github.com", "raw.githubusercontent.com", "api.github.com"}
        if redirect:
            hosts |= {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}
        return (parsed.scheme == "https" and parsed.hostname in hosts
                and parsed.port is None and parsed.username is None
                and parsed.password is None and not parsed.fragment
                and (redirect or not parsed.query))
    except (TypeError, ValueError):
        return False


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _safe_transport_url(newurl, redirect=True):
            raise DesktopError("E_DESKTOP_REDIRECT: unsupported release redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def anonymous_chunks(url):
    """No credential lookup/forwarding; bounded chunks, timeout and redirect hosts."""
    if not _safe_transport_url(url):
        raise DesktopError("E_DESKTOP_URL: only anonymous HTTPS GitHub URLs are fetched")
    opener = urllib.request.build_opener(_SafeRedirect())
    request = urllib.request.Request(url, headers={
        "User-Agent": "rapp-store-validator/1.0", "Accept": "*/*",
    })
    started = time.monotonic()
    try:
        with opener.open(request, timeout=30) as response:
            while True:
                if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                    raise DesktopError("E_DESKTOP_TIMEOUT: download exceeded time budget")
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk
    except (urllib.error.URLError, OSError) as exc:
        # Never include CDN query strings, headers or credentials in a report.
        raise DesktopError("E_DESKTOP_FETCH: anonymous GitHub fetch failed") from exc


def anonymous_bytes(url, max_bytes=MAX_METADATA_BYTES):
    chunks = anonymous_chunks(url)
    data = bytearray()
    try:
        for chunk in chunks:
            data.extend(chunk)
            if len(data) > max_bytes:
                raise DesktopError("E_DESKTOP_METADATA_SIZE: metadata fetch exceeded its byte cap")
    finally:
        chunks.close()
    return bytes(data)


def _fetch_bytes(fetcher, url, cap):
    try:
        blob = fetcher(url, max_bytes=cap) if fetcher is anonymous_bytes else fetcher(url)
    except Exception as exc:
        raise DesktopError("E_DESKTOP_FETCH: required public release metadata is unavailable") from exc
    if not isinstance(blob, bytes) or len(blob) > cap:
        raise DesktopError("E_DESKTOP_METADATA_SIZE: fetched metadata exceeded its byte cap")
    return blob


def load_json_object(blob):
    """Reject duplicate keys and non-JSON constants in native provenance."""
    def unique_object(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out

    def reject_constant(value):
        raise ValueError("non-JSON constant")

    try:
        value = json.loads(blob, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, UnicodeDecodeError) as exc:
        raise DesktopError("E_DESKTOP_JSON: evidence/API response must be UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise DesktopError("E_DESKTOP_JSON: evidence/API response must be an object")
    return value


def _fetch_json(fetcher, url):
    return load_json_object(_fetch_bytes(fetcher, url, MAX_METADATA_BYTES))


def _verify_blob(blob, ref):
    if len(blob) != ref["bytes"]:
        raise DesktopError("E_DESKTOP_BYTES_MISMATCH: fetched evidence size differs from its pin")
    if hashlib.sha256(blob).hexdigest() != ref["sha256"]:
        raise DesktopError("E_DESKTOP_HASH_MISMATCH: fetched evidence SHA256 differs from its pin")


def verify_artifact(artifact, artifact_fetcher):
    """Hash a native archive without buffering/saving it; stop on excess bytes."""
    stream = None
    total = 0
    digest = hashlib.sha256()
    started = time.monotonic()
    try:
        stream = iter(artifact_fetcher(artifact["url"]))
        for chunk in stream:
            if not isinstance(chunk, bytes) or len(chunk) > CHUNK_BYTES:
                raise DesktopError("E_DESKTOP_STREAM: artifact fetcher must yield bounded byte chunks")
            if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                raise DesktopError("E_DESKTOP_TIMEOUT: artifact verification exceeded time budget")
            total += len(chunk)
            if total > artifact["bytes"] or total > MAX_ARTIFACT_BYTES:
                raise DesktopError("E_DESKTOP_BYTES_MISMATCH: artifact exceeded its exact byte pin")
            digest.update(chunk)
    except DesktopError:
        raise
    except Exception as exc:
        raise DesktopError("E_DESKTOP_FETCH: native artifact stream failed") from exc
    finally:
        if stream is not None and hasattr(stream, "close"):
            stream.close()
    if total != artifact["bytes"]:
        raise DesktopError("E_DESKTOP_BYTES_MISMATCH: artifact was truncated")
    if digest.hexdigest() != artifact["sha256"]:
        raise DesktopError("E_DESKTOP_HASH_MISMATCH: artifact SHA256 differs from its pin")


def _successful_report(report, *required):
    return (isinstance(report, dict) and set(report) == {"exit_code", "output"}
            and type(report["exit_code"]) is int and report["exit_code"] == 0
            and _text(report["output"], MAX_EVIDENCE_BYTES)
            and all(part in report["output"] for part in required))


def _verify_evidence(report, entry, artifact, fetcher):
    expected_keys = {"schema", "subject", "source", "workflow_run", "signing",
                     "notarization", "gatekeeper", "stapler"}
    if not _exact_fields(report, expected_keys) or report["schema"] != SCHEMA_EVIDENCE:
        raise DesktopError("E_DESKTOP_EVIDENCE: unsupported or incomplete release evidence")
    desktop = entry["desktop"]
    subject = {key: artifact[key] for key in ("arch", "url", "bytes", "sha256")}
    subject.update(id=entry["id"], version=entry["version"], bundle_id=desktop["bundle_id"])
    if (report["subject"] != subject or report["source"] != desktop["source"]
            or type(report["subject"].get("bytes")) is not int):
        raise DesktopError("E_DESKTOP_EVIDENCE_BINDING: evidence does not bind this artifact, version and build source")
    repo = desktop["source"]["repo"]
    run_pattern = re.compile(rf"https://github\.com/{re.escape(repo)}/actions/runs/([1-9][0-9]*)\Z")
    run_match = run_pattern.fullmatch(report["workflow_run"]) if isinstance(report["workflow_run"], str) else None
    if run_match is None:
        raise DesktopError("E_DESKTOP_WORKFLOW: evidence must reference a same-repo GitHub Actions run")
    run = _fetch_json(fetcher, f"https://api.github.com/repos/{repo}/actions/runs/{run_match[1]}")
    repository = run.get("repository")
    if (run.get("html_url") != report["workflow_run"]
            or not isinstance(repository, dict) or repository.get("full_name") != repo
            or run.get("head_sha") != desktop["source"]["commit_sha"]
            or run.get("status") != "completed" or run.get("conclusion") != "success"):
        raise DesktopError("E_DESKTOP_WORKFLOW: successful public run must bind the native-build commit and repository")
    signing = report["signing"]
    signing_fields = {"team_id", "authority", "codesign_details", "codesign_verify", "architectures"}
    if not _exact_fields(signing, signing_fields) or not _matches(re.compile(r"[A-Z0-9]{10}\Z"), signing.get("team_id")):
        raise DesktopError("E_DESKTOP_SIGNING: complete Developer ID signing reports are required")
    authority = signing["authority"]
    if (not _text(authority, 300) or not authority.startswith("Developer ID Application: ")
            or not authority.endswith(f" ({signing['team_id']})")
            or signing["architectures"] != [artifact["arch"]]):
        raise DesktopError("E_DESKTOP_SIGNING: Developer ID authority or architecture mismatch")
    details = signing["codesign_details"]
    if (not _text(details, MAX_EVIDENCE_BYTES)
            or f"Identifier={desktop['bundle_id']}" not in details.splitlines()
            or f"TeamIdentifier={signing['team_id']}" not in details.splitlines()
            or f"Authority={authority}" not in details.splitlines()
            or not _hardened_runtime_details(details)
            or not _successful_report(signing["codesign_verify"],
                                      "valid on disk", "satisfies its Designated Requirement")):
        raise DesktopError("E_DESKTOP_SIGNING: codesign verification/details do not match the signed application")
    notarization = report["notarization"]
    if artifact["format"] == "zip":
        _verify_stapled_app(report, entry)
        return
    if not _exact_fields(notarization, {"submission_id", "submitted_sha256", "log"}):
        raise DesktopError("E_DESKTOP_NOTARIZATION: notarytool submission and log are required")
    log = notarization["log"]
    if (not _matches(UUID_RE, notarization["submission_id"])
            or not _matches(SHA256_RE, notarization["submitted_sha256"])
            or not isinstance(log, dict)
            or log.get("jobId") != notarization["submission_id"]
            or log.get("status") != "Accepted" or type(log.get("statusCode")) is not int
            or log["statusCode"] != 0
            or log.get("archiveFilename") != artifact_filename(entry, artifact["arch"])
            or log.get("sha256") != notarization["submitted_sha256"]
            or "issues" not in log or log["issues"] not in (None, [])):
        raise DesktopError("E_DESKTOP_NOTARIZATION: accepted Apple notarytool log must bind the pre-staple DMG upload")
    if not _gatekeeper_report(report["gatekeeper"], authority):
        raise DesktopError("E_DESKTOP_GATEKEEPER: an accepted Notarized Developer ID assessment is required")
    if not _successful_report(report["stapler"], "The validate action worked!"):
        raise DesktopError("E_DESKTOP_STAPLER: final DMG stapler validation is required")


def _verify_stapled_app(report, entry):
    """ZIPs have no staple/ticket; verify reports about the enclosed application."""
    notarization = report["notarization"]
    fields = {"method", "app_path", "bundle_id", "version", "minimum_os"}
    if (not _exact_fields(notarization, fields)
            or notarization["method"] != "stapled-app"
            or not _matches(APP_PATH_RE, notarization["app_path"])
            or len(notarization["app_path"]) > 200
            or notarization["bundle_id"] != entry["desktop"]["bundle_id"]
            or notarization["version"] != entry["version"]
            or notarization["minimum_os"] != entry["desktop"]["minimum_os"]):
        raise DesktopError("E_DESKTOP_APP_NOTARIZATION: ZIP evidence must identify the enclosed stapled app, not a container ticket")
    app = notarization["app_path"]
    signing = report["signing"]
    executable = re.compile(rf"^Executable=(?:.*/)?{re.escape(app)}/Contents/MacOS/[^\r\n]+$", re.MULTILINE)
    if (not executable.search(signing["codesign_details"])
            or not _successful_report(signing["codesign_verify"],
                                      f"{app}: valid on disk",
                                      f"{app}: satisfies its Designated Requirement")
            or not _app_report_line(signing["codesign_verify"]["output"], app, ": valid on disk")
            or not _app_report_line(signing["codesign_verify"]["output"], app, ": satisfies its Designated Requirement")):
        raise DesktopError("E_DESKTOP_SIGNING: ZIP signing reports must identify the enclosed application")
    if (not _gatekeeper_report(report["gatekeeper"], signing["authority"])
            or not _app_report_line(report["gatekeeper"].get("output", ""), app, ": accepted")):
        raise DesktopError("E_DESKTOP_GATEKEEPER: ZIP evidence requires the enclosed app's Notarized Developer ID assessment")
    if not _successful_report(report["stapler"], app, "The validate action worked!"):
        raise DesktopError("E_DESKTOP_STAPLER: ZIP evidence requires app stapler validation, never a ZIP staple")
    targets = [line[len("Processing:"):].strip()
               for line in report["stapler"]["output"].splitlines() if line.startswith("Processing:")]
    if len(targets) != 1 or targets[0].rsplit("/", 1)[-1] != app:
        raise DesktopError("E_DESKTOP_STAPLER: stapler must process the exact .app, not a similarly named ZIP/container")


def _app_report_line(output, app, suffix):
    return re.search(rf"^(?:.*/)?{re.escape(app)}{re.escape(suffix)}$", output, re.MULTILINE) is not None


def _gatekeeper_report(report, authority):
    if not _successful_report(report, ": accepted", "source=Notarized Developer ID"):
        return False
    lines = report["output"].splitlines()
    sources = [line for line in lines if line.startswith("source=")]
    origins = [line for line in lines if line.startswith("origin=")]
    # Some genuine spctl versions omit origin; codesign remains authoritative.
    return sources == ["source=Notarized Developer ID"] and (
        not origins or origins == [f"origin={authority}"])


def _hardened_runtime_details(details):
    match = re.search(r"^CodeDirectory\b[^\r\n]*\bflags=0x([0-9a-fA-F]+)\(([^)\r\n]*)\)",
                      details, re.MULTILINE)
    return bool(match and int(match[1], 16) & 0x10000
                and "runtime" in [flag.strip() for flag in match[2].split(",")])


def verify_release(entry, *, fetcher=None, artifact_fetcher=None):
    """Verify public release/tag/run references, evidence pins and native archives."""
    errors = validate_metadata(entry)
    if errors:
        return errors
    if "desktop" not in entry:
        return []
    fetcher = fetcher or anonymous_bytes
    artifact_fetcher = artifact_fetcher or anonymous_chunks
    desktop = entry["desktop"]
    repo = desktop["source"]["repo"]
    tag = desktop["release_tag"]
    try:
        commit = _fetch_json(fetcher, f"https://api.github.com/repos/{repo}/commits/{tag}")
        if commit.get("sha") != desktop["source"]["commit_sha"]:
            raise DesktopError("E_DESKTOP_TAG_COMMIT: release tag does not resolve to the native-build commit")
        release = _fetch_json(fetcher, f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
        if (release.get("tag_name") != tag or release.get("draft") is not False
                or release.get("prerelease") is not False
                or release.get("html_url") != f"https://github.com/{repo}/releases/tag/{tag}"):
            raise DesktopError("E_DESKTOP_RELEASE: a published stable same-repo versioned release is required")
        assets = release.get("assets")
        if not isinstance(assets, list) or any(not isinstance(asset, dict) for asset in assets):
            raise DesktopError("E_DESKTOP_RELEASE: release assets are missing")
        # Check all cheap evidence before streaming any potentially large binary.
        for artifact in desktop["artifacts"]:
            for ref in (artifact, artifact["evidence"]):
                matches = [a for a in assets if a.get("browser_download_url") == ref["url"]]
                if (len(matches) != 1 or matches[0].get("state") != "uploaded"
                        or matches[0].get("name") != ref["url"].rsplit("/", 1)[1]
                        or type(matches[0].get("size")) is not int
                        or matches[0]["size"] != ref["bytes"]
                        or matches[0].get("digest") != f"sha256:{ref['sha256']}"):
                    raise DesktopError("E_DESKTOP_RELEASE_ASSET: GitHub release asset name/size/digest differs from its pin")
            blob = _fetch_bytes(fetcher, artifact["evidence"]["url"], MAX_EVIDENCE_BYTES)
            _verify_blob(blob, artifact["evidence"])
            _verify_evidence(load_json_object(blob), entry, artifact, fetcher)
        for artifact in desktop["artifacts"]:
            verify_artifact(artifact, artifact_fetcher)
    except DesktopError as exc:
        return [str(exc)]
    return []
