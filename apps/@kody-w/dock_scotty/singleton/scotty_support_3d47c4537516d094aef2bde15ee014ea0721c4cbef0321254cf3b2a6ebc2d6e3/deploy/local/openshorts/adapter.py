"""Native spoken-video jobs through OpenShorts' existing OpenAI-compatible backend."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
import re
import time
from urllib.parse import unquote, urlencode, urlsplit

from local_dock import LocalDockError

APP = "openshorts"
TITLE = "OpenShorts"
COMPOSE = "compose.yaml"
NEEDS = ("intelligence",)
HEAVY = True
START_TIMEOUT = 240
READY_TIMEOUT = 240
MAX_INPUT_BYTES = 256 * 1024 * 1024
MIN_SOURCE_SECONDS = 45
MAX_SOURCE_SECONDS = 600
JOB_TIMEOUT = 1800
POLL_INTERVAL = 3
INTERNAL_AI_URL = "http://intelligence:8080/v1"
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
FILENAME = re.compile(r"[A-Za-z0-9_.-]{1,240}")
PROBE = Path(__file__).with_name("native_probe.py")
REQUEST_ID = re.compile(r"[a-f0-9]{32}")
GATEWAY_FIELDS = ("request_id", "cursor", "app", "model", "status", "started", "duration_ms", "usage", "error_code")
WINDOW_NOTE = "App-scoped time window; may include concurrent or earlier in-flight app requests. Not an exact native-job binding."


def urls(ctx):
    return {"application": ctx.host_url("/")}


def prepare(ctx):
    connection = ctx.intelligence()
    if connection.get("internal_url") != INTERNAL_AI_URL:
        raise LocalDockError("intelligence-unavailable", "OpenShorts requires the enrolled local intelligence gateway.")
    key, model = connection.get("api_key"), connection.get("model")
    if not isinstance(key, str) or not key or not isinstance(model, str) or not model:
        raise LocalDockError("intelligence-auth-unavailable", "The app-scoped intelligence connection is unavailable.")
    ctx.write_env_file("openshorts-backend.env", {
        "LLM_PROVIDER": "openai",
        "LLM_BASE_URL": INTERNAL_AI_URL,
        "LLM_MODEL": model,
        "LLM_API_KEY": key,
        "LLM_TIMEOUT": "240",
        "LLM_SCORE_BATCH": "3",
    })
    ctx.write_env_file("openshorts-ingress.env", {
        "OPENSHORTS_INGRESS_KEY": ctx.secret("openshorts-ingress-key", nbytes=32),
    })


def _app_http(ctx, method, path, **kwargs):
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["Authorization"] = "Bearer " + ctx.secret("openshorts-ingress-key", nbytes=32)
    return ctx.http(method, ctx.host_url(path), headers=headers, **kwargs)


def _json_response(response, expected, action):
    if response.status not in expected:
        raise LocalDockError("native-job-failed", f"OpenShorts {action} returned HTTP {response.status}.")
    try:
        data = response.json()
    except (ValueError, UnicodeDecodeError):
        raise LocalDockError("output-invalid", f"OpenShorts {action} returned invalid JSON.") from None
    if not isinstance(data, dict):
        raise LocalDockError("output-invalid", f"OpenShorts {action} returned an invalid object.")
    return data


def ready(ctx):
    try:
        rows = ctx.containers()
        expected = {"backend", "frontend", "renderer", "ingress"}
        if {row.get("service") for row in rows} != expected or not all(
            row.get("state") == "running" and row.get("health") == "healthy" for row in rows
        ):
            return {"ready": False, "detail": "Waiting for all OpenShorts application and authenticated ingress roles to be healthy."}
        response = _app_http(ctx, "GET", "/api/config", timeout=5, max_bytes=65536)
    except LocalDockError as error:
        if error.code == "cancelled":
            raise
        return {"ready": False, "detail": "OpenShorts configuration is not responding."}
    if response.status != 200:
        return {"ready": False, "detail": "OpenShorts configuration is not ready."}
    try:
        config = response.json()
    except ValueError:
        return {"ready": False, "detail": "OpenShorts configuration response is invalid."}
    local = config.get("localLlm") if isinstance(config, dict) else None
    enabled = (
        isinstance(local, dict) and local.get("provider") == "openai"
        and local.get("baseUrl") == INTERNAL_AI_URL
        and isinstance(local.get("model"), str) and bool(local["model"])
        and config.get("billingEnabled") is False
    )
    return {
        "ready": enabled,
        "detail": "Native transcript selection uses the local gateway; Gemini/vision and publication are off."
        if enabled else "The native OpenAI-compatible transcript-selection path is not configured.",
    }


def setup(ctx):
    state = ready(ctx)
    if not state["ready"]:
        raise LocalDockError("app-not-ready", state["detail"])
    return {"configured": True, "selection": "native-openai-compatible", "publishing": False,
            "supported_input": "speech-containing video", "vision": "not-supported"}


def _native_id(value, name):
    if not isinstance(value, str) or UUID.fullmatch(value) is None:
        raise LocalDockError("output-invalid", f"OpenShorts returned an invalid {name}.")
    return value


def _gateway_window(ctx, connection):
    try:
        response = ctx.http(
            "GET", connection["host_url"] + "/requests",
            headers={"Authorization": "Bearer " + connection["api_key"]},
            timeout=10, max_bytes=262144,
        )
        if response.status == 401:
            raise LocalDockError("intelligence-auth-unavailable", "The OpenShorts gateway key was not accepted.")
        if response.status != 200:
            ctx.record_native("gateway_correlation", {"status": "unavailable", "reason": f"http-{response.status}"})
            ctx.log("Gateway request metadata is unavailable; no request IDs or call count are inferred.")
            return None
        data = response.json()
        cursor = data.get("next_cursor")
        if data.get("data") != [] or data.get("has_more") is not False or not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
            raise ValueError("invalid metadata cursor")
        ctx.record_native("gateway_cursor", cursor)
        ctx.record_native("gateway_correlation", {"status": "capturing", "kind": "app-window", "attribution": WINDOW_NOTE})
        return cursor
    except LocalDockError as error:
        if error.code in {"cancelled", "intelligence-auth-unavailable"}:
            raise
        ctx.record_native("gateway_correlation", {"status": "unavailable", "reason": "metadata-unavailable"})
    except (ValueError, TypeError, AttributeError):
        ctx.record_native("gateway_correlation", {"status": "unavailable", "reason": "invalid-metadata"})
    ctx.log("Gateway request metadata is unavailable; no request IDs or call count are inferred.")
    return None


def _gateway_row(row):
    if (
        not isinstance(row, dict) or not set(GATEWAY_FIELDS) <= row.keys()
        or not isinstance(row["request_id"], str) or not REQUEST_ID.fullmatch(row["request_id"])
        or row["app"] != APP or not isinstance(row["cursor"], str) or not 1 <= len(row["cursor"]) <= 2048
    ):
        raise ValueError("invalid request metadata")
    if row["model"] is not None and (not isinstance(row["model"], str) or not 1 <= len(row["model"]) <= 128):
        raise ValueError("invalid request model")
    if type(row.get("status")) is not int or not 100 <= row["status"] <= 599:
        raise ValueError("invalid request status")
    if row.get("duration_ms") is not None and (not _finite_number(row["duration_ms"]) or row["duration_ms"] < 0):
        raise ValueError("invalid request duration")
    if row["started"] is not None:
        if not isinstance(row["started"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", row["started"]):
            raise ValueError("invalid request timestamp")
        datetime.strptime(row["started"], "%Y-%m-%dT%H:%M:%S.%fZ")
    if row["error_code"] is not None and (
        not isinstance(row["error_code"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", row["error_code"])
    ):
        raise ValueError("invalid request error code")
    usage = row.get("usage")
    if usage is not None:
        if not isinstance(usage, dict):
            raise ValueError("invalid usage metadata")
        retained = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if key in usage:
                if type(usage[key]) is not int or usage[key] < 0:
                    raise ValueError("invalid token count")
                retained[key] = usage[key]
        usage = retained or None
    return {key: row[key] for key in GATEWAY_FIELDS} | {"usage": usage}


def _collect_gateway_window(ctx, connection, cursor):
    if cursor is None:
        return {"status": "unavailable", "correlation": "app-window", "attribution": WINDOW_NOTE, "requests": []}
    rows, seen, seen_cursors = [], set(), {cursor}
    failure_reason = "metadata-unavailable"
    try:
        for _ in range(8):
            ctx.check_cancelled()
            query = urlencode({"after": cursor, "limit": 100})
            response = ctx.http(
                "GET", connection["host_url"] + "/requests?" + query,
                headers={"Authorization": "Bearer " + connection["api_key"]},
                timeout=10, max_bytes=262144,
            )
            if response.status != 200:
                failure_reason = "cursor-expired" if response.status == 409 else f"metadata-http-{response.status}"
                raise LocalDockError("intelligence-unavailable", f"metadata-http-{response.status}")
            data = response.json()
            if (
                not isinstance(data.get("data"), list)
                or len(data["data"]) > 100 or type(data.get("has_more")) is not bool
            ):
                raise ValueError("invalid metadata page")
            overflow = False
            for raw in data["data"]:
                row = _gateway_row(raw)
                if row["request_id"] not in seen:
                    if len(rows) == 20:
                        overflow = True
                        break
                    rows.append(row)
                    seen.add(row["request_id"])
            next_cursor = data.get("next_cursor")
            if not isinstance(next_cursor, str) or not 1 <= len(next_cursor) <= 2048:
                raise ValueError("invalid metadata cursor")
            ctx.record_native("gateway_cursor_after", next_cursor)
            if not data["has_more"] or len(rows) == 20:
                truncated = data["has_more"] or overflow
                result = {"status": "truncated" if truncated else "observed", "correlation": "app-window",
                          "attribution": WINDOW_NOTE, "requests": rows, "per_job_call_count": None}
                ctx.record_native("gateway_correlation", {"status": result["status"], "kind": "app-window",
                                                         "attribution": WINDOW_NOTE,
                                                         "request_ids": [row["request_id"] for row in rows]})
                return result
            if next_cursor in seen_cursors:
                raise ValueError("metadata cursor did not advance")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        reason = "scan-bound"
    except LocalDockError as error:
        if error.code == "cancelled":
            raise
        reason = failure_reason
    except (ValueError, TypeError, AttributeError):
        reason = "invalid-metadata"
    ctx.record_native("gateway_correlation", {"status": "unavailable", "reason": reason, "kind": "app-window"})
    ctx.log("Gateway correlation could not be completed; per-job call count remains unknown.")
    return {"status": "unavailable", "correlation": "app-window", "attribution": WINDOW_NOTE,
            "reason": reason, "requests": [], "per_job_call_count": None}


def _probe(ctx, operation, value, timeout=45):
    completed = ctx.exec(
        "backend", ["python", "-c", PROBE.read_text(), operation, value],
        timeout=timeout, check=False,
    )
    if completed.returncode != 0:
        raise LocalDockError("output-invalid", "OpenShorts native media verification failed.")
    try:
        data = json.loads(completed.stdout)
    except (ValueError, TypeError):
        raise LocalDockError("output-invalid", "OpenShorts native observation was invalid.") from None
    if not isinstance(data, dict) or data.get("error"):
        raise LocalDockError("output-invalid", "OpenShorts native observation failed.")
    return data


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _clip_path(value, job_id):
    if not isinstance(value, str):
        raise LocalDockError("output-invalid", "OpenShorts clip has no native file URL.")
    parsed = urlsplit(value)
    path = unquote(parsed.path)
    parts = path.split("/")
    if (
        parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
        or len(parts) != 4 or parts[:3] != ["", "videos", job_id]
        or not FILENAME.fullmatch(parts[-1]) or not parts[-1].endswith(".mp4")
        or parts[-1].startswith(".")
    ):
        raise LocalDockError("output-invalid", "OpenShorts returned an unsafe clip location.")
    return f"/app/output/{job_id}/{parts[-1]}"


def _observed_phase(status):
    if status.get("status") == "queued":
        return "queued-native"
    lines = status.get("logs")
    text = "\n".join(line[-500:] for line in lines[-80:] if isinstance(line, str)).lower() if isinstance(lines, list) else ""
    if any(marker in text for marker in ("processing clip", "clip saved", "auto-caption", "clip ready", "rendering")):
        return "rendering"
    if any(marker in text for marker in ("analyzing with local llm", "shortlisted", "scoring window")):
        return "selecting"
    if "transcrib" in text:
        return "transcribing"
    return None


def _no_speech(ctx, job_id, status):
    lines = status.get("logs")
    text = "\n".join(line[-500:] for line in lines[-100:] if isinstance(line, str)).lower() if isinstance(lines, list) else ""
    if any(marker in text for marker in ("switching to visual analysis", "no audio stream", "no audio track", "only 0 word")):
        return True
    # A failed native job may retain the real transcript checkpoint. Never infer
    # speech or a provider result from an empty/failed metadata read.
    observed = _probe(ctx, "speech", job_id)
    return observed.get("observed") is True and observed.get("usable") is False


def _native_clips(status):
    result = status.get("result")
    if result is None:
        return []
    if not isinstance(result, dict) or not isinstance(result.get("clips", []), list):
        raise LocalDockError("output-invalid", "OpenShorts returned malformed native clip results.")
    return result.get("clips", [])


def _wait_job(ctx, job_id):
    last_phase = None
    order = {"queued-native": 0, "transcribing": 1, "selecting": 2, "rendering": 3}
    deadline = time.monotonic() + JOB_TIMEOUT
    while time.monotonic() < deadline:
        ctx.check_cancelled()
        status = _json_response(
            _app_http(ctx, "GET", f"/api/status/{job_id}", timeout=15, max_bytes=2 * 1024 * 1024),
            {200}, "job status",
        )
        native_status = status.get("status")
        if native_status not in {"queued", "processing", "completed", "failed", "cancelled"}:
            raise LocalDockError("output-invalid", "OpenShorts returned an unknown native job state.")
        if native_status in {"completed", "failed", "cancelled"}:
            ctx.record_native("job_status", native_status)
            if native_status == "cancelled":
                raise LocalDockError("cancelled", "OpenShorts cancelled the native job.")
            if native_status == "failed" and _no_speech(ctx, job_id, status):
                raise LocalDockError(
                    "not-supported", "no-usable-speech: OpenShorts found no usable speech. Silent/vision selection is unsupported."
                )
            clips = _native_clips(status)
            if native_status == "failed" and not clips:
                raise LocalDockError("native-job-failed", f"OpenShorts job {job_id} failed; no verified clips were delivered.")
            return status
        phase = _observed_phase(status) or last_phase or "transcribing"
        if phase != last_phase and (last_phase is None or order[phase] >= order[last_phase]):
            ctx.phase(phase, "Observed native OpenShorts progress; nothing is published.")
            last_phase = phase
        time.sleep(POLL_INTERVAL)
    ctx.record_native("job_status", "unknown-after-timeout")
    raise LocalDockError(
        "native-job-failed", f"OpenShorts job {job_id} exceeded the local deadline. Reconcile that job before retrying."
    )


def _read_metadata(ctx, job_id):
    observation = _probe(ctx, "metadata", job_id)
    path = observation.get("path")
    if not isinstance(path, str) or not path.startswith(f"/app/output/{job_id}/") or not path.endswith("_metadata.json"):
        raise LocalDockError("output-invalid", "OpenShorts metadata location is invalid.")
    copied = ctx.copy_from("backend", path, "native-metadata.json", "application/json")
    local = Path(copied["path"])
    if local.stat().st_size > 16 * 1024 * 1024:
        raise LocalDockError("output-invalid", "OpenShorts metadata exceeds the local bound.")
    try:
        metadata = json.loads(local.read_bytes())
    except (ValueError, UnicodeDecodeError):
        raise LocalDockError("output-invalid", "OpenShorts metadata is malformed.") from None
    if not isinstance(metadata, dict):
        raise LocalDockError("output-invalid", "OpenShorts metadata is not an object.")
    return metadata


def _transcript(metadata, duration):
    transcript = metadata.get("transcript")
    if not isinstance(transcript, dict) or not isinstance(transcript.get("segments"), list):
        raise LocalDockError("output-invalid", "OpenShorts did not retain a source transcript.")
    segments = []
    total_words = 0
    for segment in transcript["segments"]:
        if not isinstance(segment, dict):
            raise LocalDockError("output-invalid", "The native transcript contains an invalid segment.")
        start, end, text = segment.get("start"), segment.get("end"), segment.get("text")
        if not (_finite_number(start) and _finite_number(end) and 0 <= start <= end <= duration + 1 and isinstance(text, str)):
            raise LocalDockError("output-invalid", "The native transcript is outside the source time bounds.")
        total_words += len(text.split())
        words = segment.get("words", [])
        if not isinstance(words, list):
            raise LocalDockError("output-invalid", "The native transcript word timing is invalid.")
        retained = []
        for word in words:
            if not isinstance(word, dict):
                raise LocalDockError("output-invalid", "The native transcript word is invalid.")
            a, b, value = word.get("start"), word.get("end"), word.get("word")
            if not (_finite_number(a) and _finite_number(b) and 0 <= a <= b <= duration + 1 and isinstance(value, str)):
                raise LocalDockError("output-invalid", "The native word timing is outside source bounds.")
            retained.append({"start": a, "end": b, "word": value})
        segments.append({"start": start, "end": end, "text": text, "words": retained})
    if total_words < 8 or total_words / max(duration / 60, 1e-6) < 5:
        raise LocalDockError("not-supported", "no-usable-speech: too little spoken content for transcript selection.")
    language = transcript.get("language")
    return {"language": language if isinstance(language, str) else "unknown", "segments": segments}


def clips(ctx, source_path, clip_count=3):
    if not isinstance(source_path, str) or not source_path.strip() or type(clip_count) is not int or not 1 <= clip_count <= 5:
        raise LocalDockError("invalid-input", "Provide a local spoken video and a clip count from 1 to 5.")
    ctx.check_cancelled()
    ctx.phase("sealing-input", "Sealing the owner-selected local video.")
    sealed = ctx.seal_input(source_path)
    if not 0 < sealed["bytes"] <= MAX_INPUT_BYTES:
        raise LocalDockError("invalid-input", "OpenShorts accepts videos up to 256MiB in this local slice.")
    data = Path(sealed["path"]).read_bytes()
    if len(data) != sealed["bytes"] or hashlib.sha256(data).hexdigest() != sealed["sha256"]:
        raise LocalDockError("invalid-input", "The sealed video changed before upload.")
    connection = ctx.intelligence()
    model = connection["model"]
    ctx.phase("uploading", "Uploading the sealed video to the private native application.")
    slot = _json_response(
        _app_http(ctx, "POST", "/api/uploads", json_body={"filename": "source.mp4"}, timeout=30, max_bytes=65536),
        {200}, "upload reservation",
    )
    upload_id = _native_id(slot.get("upload_id"), "upload identifier")
    ctx.record_native("upload_id", upload_id)
    uploaded = _json_response(
        _app_http(ctx, "PUT", f"/api/uploads/{upload_id}", data=data,
                 headers={"Content-Type": "application/octet-stream"}, timeout=180, max_bytes=65536),
        {200}, "video upload",
    )
    del data
    if uploaded.get("bytes") != sealed["bytes"]:
        raise LocalDockError("output-invalid", "The native upload did not receive the sealed video bytes.")
    media = _probe(ctx, "input", f"/app/uploads/pending_{upload_id}_source.mp4")
    duration = media.get("duration")
    if not _finite_number(duration) or not MIN_SOURCE_SECONDS <= duration <= MAX_SOURCE_SECONDS:
        raise LocalDockError("invalid-input", "Spoken videos must be between 45 seconds and 10 minutes.")
    if not media.get("audio_codec"):
        _app_http(ctx, "DELETE", f"/api/uploads/{upload_id}", timeout=15, max_bytes=65536)
        raise LocalDockError("not-supported", "no-usable-speech: the video has no audio track; vision selection is unsupported.")
    if not all(type(media.get(key)) is int and 0 < media[key] <= 4096 for key in ("width", "height")):
        raise LocalDockError("invalid-input", "Source video dimensions exceed the 4096-pixel bound.")
    ctx.record_native("sealed_input", {
        "sha256": sealed["sha256"], "bytes": sealed["bytes"], "duration": duration,
    })
    ctx.record_native("selection_model", model)
    ctx.check_cancelled()
    gateway_cursor = _gateway_window(ctx, connection)
    ctx.record_native("submission", "dispatching")
    ctx.phase("submitting_native", "Submitting the native Whisper and gateway-backed selection job.")
    try:
        response = _app_http(
            ctx, "POST", "/api/process", json_body={
                "upload_id": upload_id, "acknowledged": True, "output_format": "vertical",
                "layouts": ["none"], "target_clips": clip_count,
                "clip_min_seconds": 10, "clip_max_seconds": 40,
                "captions": True, "auto_hook": False,
            }, timeout=30, max_bytes=65536,
        )
    except LocalDockError as error:
        ctx.record_native("submission", "outcome-unknown")
        if error.code == "cancelled":
            raise
        raise LocalDockError("native-job-failed", "Native submission outcome is unknown; reconcile before retrying.") from None
    if response.status not in {200, 202}:
        ctx.record_native("submission", "rejected")
    accepted = _json_response(response, {200, 202}, "job submission")
    try:
        job_id = _native_id(accepted.get("job_id"), "job identifier")
    except LocalDockError:
        ctx.record_native("submission", "outcome-unknown")
        raise
    ctx.record_native("job_id", job_id)
    ctx.record_native("submission", "accepted")
    ctx.phase("transcribing", "Native job accepted; waiting for observed Whisper and selection progress.")
    status = _wait_job(ctx, job_id)
    return _collect_results(
        ctx, job_id=job_id, upload_id=upload_id, clip_count=clip_count, sealed=sealed,
        duration=duration, model=model, status=status, connection=connection, gateway_cursor=gateway_cursor,
    )


def _collect_results(ctx, *, job_id, upload_id, clip_count, sealed, duration, model, status,
                     connection=None, gateway_cursor=None, recovered_from=None):
    ctx.phase("verifying", "Verifying actual rendered video, audio, geometry and source ranges.")
    metadata = _read_metadata(ctx, job_id)
    transcript = _transcript(metadata, duration)
    native_clips = _native_clips(status)
    if not isinstance(native_clips, list) or not native_clips:
        raise LocalDockError("output-invalid", "OpenShorts completed without usable clip files.")
    artifacts, ranges, rejected = [], [], []
    seen_paths = set()
    for index, clip in enumerate(native_clips[:clip_count], 1):
        ctx.check_cancelled()
        if not isinstance(clip, dict):
            raise LocalDockError("output-invalid", "A native clip record is invalid.")
        start, end = clip.get("start"), clip.get("end")
        if not (_finite_number(start) and _finite_number(end) and 0 <= start < end <= duration + 0.5):
            raise LocalDockError("output-invalid", "A selected clip is outside the sealed source duration.")
        container_path = _clip_path(clip.get("video_url"), job_id)
        if container_path in seen_paths:
            raise LocalDockError("output-invalid", "OpenShorts returned duplicate clip files.")
        seen_paths.add(container_path)
        try:
            verified = _probe(ctx, "clip", container_path, timeout=180)
            if abs(verified["duration"] - (end - start)) > 2:
                raise LocalDockError("output-invalid", "Rendered duration does not match the selected source range.")
            artifact = ctx.copy_from("backend", container_path, f"clip-{index:02d}.mp4", "video/mp4")
            if artifact["sha256"] != verified["sha256"] or artifact["bytes"] != verified["bytes"]:
                raise LocalDockError("output-invalid", "The copied clip differs from the verified native bytes.")
            ctx.mark_verified(artifact)
        except LocalDockError as error:
            if error.code != "output-invalid":
                raise
            rejected.append(index)
            ctx.log(f"Clip {index} failed independent media verification; it is not delivered.")
            continue
        artifacts.append(artifact)
        ranges.append({
            "clip": artifact["name"], "source_start": start, "source_end": end,
            "title": str(clip.get("video_title_for_youtube_short", ""))[:200],
            "source_window_id": str(clip.get("source_window_id", ""))[:100],
            "sha256": artifact["sha256"], "duration": verified["duration"],
            "width": verified["width"], "height": verified["height"],
            "audio_codec": verified["audio_codec"], "video_codec": verified["video_codec"],
            "nonblank": verified["nonblank"],
            "captions": "native-burned" if Path(container_path).name.startswith("subtitled_") else "not-observed",
        })
    if not artifacts:
        raise LocalDockError("output-invalid", "No native clip passed independent media verification.")
    for name, payload in [
        ("transcript.json", transcript),
        ("source-ranges.json", {
            "native_job_id": job_id, "source_sha256": sealed["sha256"], "source_duration": duration,
            "requested_clips": clip_count, "delivered_clips": len(ranges), "clips": ranges,
            "selection": "native OpenShorts via tool-free Copilot gateway", "publishing": False,
        }),
    ]:
        artifact = ctx.save_output(name, (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(),
                                   "application/json")
        ctx.mark_verified(artifact)
        artifacts.append(artifact)
    delivered = len(ranges)
    gateway = _collect_gateway_window(ctx, connection, gateway_cursor)
    if gateway_cursor is not None:
        artifact = ctx.save_output(
            "gateway-requests.json", (json.dumps(gateway, indent=2, allow_nan=False) + "\n").encode(), "application/json",
        )
        ctx.mark_verified(artifact)
        artifacts.append(artifact)
    partial = delivered < clip_count or status["status"] == "failed"
    correlation = {
        "status": gateway["status"], "kind": "app-window", "attribution": WINDOW_NOTE,
        "request_ids": [row["request_id"] for row in gateway["requests"]],
    }
    message = (
        f"{delivered} of {clip_count} vertical clips verified" if partial
        else f"{delivered} vertical {'clip' if delivered == 1 else 'clips'} verified"
    )
    outcome = {
        "status": "partial" if partial else "succeeded",
        "message": message + "; transcript and source ranges saved. Nothing was published.",
        "result": {"requested_clip_count": clip_count, "verified_clip_count": delivered,
                   "rejected_clip_indexes": rejected, "publishing": False, "source_sha256": sealed["sha256"],
                   "source_duration": duration, "clips": ranges, "ai_selected": True,
                   "gateway_correlation": correlation},
        "artifacts": artifacts,
        "provider": {"runtime": "copilot-cli-in-docker", "model": model, "calls": None, "request_ids": []},
        "native": {"job_id": job_id, "upload_id": upload_id, "gateway_correlation": correlation},
    }
    if recovered_from is not None:
        outcome["message"] = "Recovered retained native output: " + outcome["message"]
        outcome["result"]["recovery"] = {
            "original_operation_id": recovered_from,
            "mode": "read-only-native-collection",
            "native_submission_replayed": False,
            "inference_replayed": False,
        }
        outcome["result"]["selection_model"] = model
        outcome["provider"] = {"runtime": "none", "model": None, "calls": 0, "request_ids": []}
        outcome["native"]["recovered_from"] = recovered_from
    return outcome


def reconcile(ctx, original_operation):
    """Collect retained native bytes only; never start, upload, select, or render."""
    if (
        not isinstance(original_operation, dict)
        or original_operation.get("application") != APP
        or original_operation.get("name") != "openshorts.clips"
        or not isinstance(original_operation.get("id"), str)
        or not re.fullmatch(r"op-[0-9]{10}-[a-f0-9]{8}", original_operation["id"])
    ):
        raise LocalDockError("invalid-input", "Recovery requires an existing OpenShorts clips operation.")
    native = original_operation.get("native")
    arguments = original_operation.get("arguments")
    if not isinstance(native, dict) or not isinstance(arguments, dict):
        raise LocalDockError("native-job-failed", "Native recovery facts are unavailable; no job was resubmitted.")
    job_id = _native_id(native.get("job_id"), "retained job identifier")
    upload_id = _native_id(native.get("upload_id"), "retained upload identifier")
    count = arguments.get("clip_count", 3)
    if type(count) is not int or not 1 <= count <= 5:
        raise LocalDockError("invalid-input", "The original clip-count contract is invalid.")
    facts = native.get("sealed_input")
    if not isinstance(facts, dict):
        # Already-published historical results may predate sealed_input native
        # facts; never reopen the owner's original source path to manufacture them.
        result = original_operation.get("result")
        result = result.get("result") if isinstance(result, dict) else None
        facts = {
            "sha256": result.get("source_sha256"), "duration": result.get("source_duration"),
        } if isinstance(result, dict) else {}
    if (
        not isinstance(facts.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", facts["sha256"])
        or not _finite_number(facts.get("duration"))
        or not MIN_SOURCE_SECONDS <= facts["duration"] <= MAX_SOURCE_SECONDS
    ):
        raise LocalDockError("native-job-failed", "Retained source hash/time facts are missing; recovery will not regenerate them.")
    key_path = ctx.secret_path("openshorts-ingress-key")
    if key_path.is_symlink() or not key_path.is_file():
        raise LocalDockError("app-not-ready", "Existing app authentication is unavailable; recovery will not initialize credentials.")
    if not ctx.running():
        raise LocalDockError("app-not-ready", "OpenShorts is stopped; recovery does not auto-start it.")
    ctx.check_cancelled()
    ctx.phase("reconciling_native", "Observing the retained OpenShorts job; no generation will be replayed.")
    status = _json_response(
        _app_http(ctx, "GET", f"/api/status/{job_id}", timeout=15, max_bytes=2 * 1024 * 1024),
        {200}, "retained job status",
    )
    state = status.get("status")
    if state in {"queued", "processing"}:
        raise LocalDockError("app-not-ready", "The retained native job is still active; no duplicate job was submitted.")
    if state not in {"completed", "failed"} or not _native_clips(status):
        raise LocalDockError("native-job-failed", "No collectible completed native clips were found; no render was started.")
    ctx.record_native("job_id", job_id)
    ctx.record_native("upload_id", upload_id)
    ctx.record_native("job_status", state)
    ctx.record_native("recovered_from", original_operation["id"])
    model = native.get("selection_model")
    if not isinstance(model, str) or not model:
        result = original_operation.get("result")
        provider = result.get("provider") if isinstance(result, dict) else None
        model = provider.get("model") if isinstance(provider, dict) else None
    return _collect_results(
        ctx, job_id=job_id, upload_id=upload_id, clip_count=count, sealed=facts,
        duration=facts["duration"], model=model, status=status, recovered_from=original_operation["id"],
    )


JOBS = {
    "clips": {
        "description": "Select and render 1-5 vertical clips from a local 45s-10min speech-containing video; retain transcript and source ranges. Silent/vision features and publishing are off.",
        "parameters": {
            "source_path": {"type": "string", "minLength": 1, "maxLength": 4096},
            "clip_count": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
        },
        "required": ["source_path"],
        "run": clips,
        "heavy": True,
        "aliases": ["video", "shorts", "clip", "spoken video", "vertical", "captions"],
    },
}
