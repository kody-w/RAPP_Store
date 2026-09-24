"""Fixed native-file observations for the adapter; no application/provider emulation."""

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

OUTPUT = Path("/app/output")
UPLOADS = Path("/app/uploads")
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")


def scoped_file(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path.is_symlink():
        raise ValueError("unsafe native path")
    resolved = path.resolve(strict=True)
    if resolved != path or not any(root in resolved.parents for root in (OUTPUT, UPLOADS)):
        raise ValueError("native file is outside the application state")
    if not resolved.is_file():
        raise ValueError("native artifact is not a regular file")
    return resolved


def media(value, verify):
    path = scoped_file(value)
    process = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,width,height,nb_frames,r_frame_rate,duration:format=duration,size",
        "-of", "json", str(path),
    ], capture_output=True, timeout=30, check=True)
    info = json.loads(process.stdout)
    streams = info.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    duration = float((info.get("format") or {}).get("duration", 0))
    if not video or not math.isfinite(duration) or duration <= 0:
        raise ValueError("video duration or stream is invalid")
    result = {
        "duration": duration, "width": video.get("width"), "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name") if audio else None,
        "bytes": path.stat().st_size,
    }
    if verify:
        width, height = result["width"], result["height"]
        if result["video_codec"] != "h264" or result["audio_codec"] != "aac":
            raise ValueError("clip must contain H.264 video and AAC audio")
        if not width or not height or abs(width * 16 - height * 9) > 16:
            raise ValueError("clip is not 9:16")
        if duration > 190 or path.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("clip exceeds output bounds")
        subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror",
            "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
        ], capture_output=True, check=True, timeout=120)
        sample = subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-ss", str(min(duration / 2, 2)), "-i", str(path), "-frames:v", "1",
            "-vf", "scale=32:32", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ], capture_output=True, check=True, timeout=20).stdout
        colors = len({sample[index:index + 3] for index in range(0, len(sample), 3)})
        if len(sample) != 32 * 32 * 3 or colors < 8 or max(sample) - min(sample) < 8:
            raise ValueError("clip is blank or unusable")
        with path.open("rb") as stream:
            sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        result.update(sha256=sha256, decoded=True, nonblank=True, sample_colors=colors)
    return result


def metadata(job_id):
    if not UUID.fullmatch(job_id):
        raise ValueError("invalid native job identifier")
    directory = OUTPUT / job_id
    candidates = sorted(directory.glob("*_metadata.json"))
    if len(candidates) != 1:
        raise ValueError("native metadata missing or ambiguous")
    path = scoped_file(str(candidates[0]))
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("native metadata exceeds bounds")
    return {"path": str(path), "bytes": path.stat().st_size}


def speech(job_id):
    if not UUID.fullmatch(job_id):
        raise ValueError("invalid native job identifier")
    checkpoint = OUTPUT / job_id / ".transcript_checkpoint.json"
    if not checkpoint.exists():
        return {"observed": False}
    path = scoped_file(str(checkpoint))
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("transcript exceeds bounds")
    data = json.loads(path.read_bytes())
    segments = data.get("transcript", {}).get("segments", [])
    words = sum(len(str(segment.get("text", "")).split()) for segment in segments)
    duration = float(data.get("source", {}).get("duration", 0))
    sparse = words < 8 or words / max(duration / 60, 1e-6) < 5
    return {"observed": True, "usable": not sparse, "words": words, "duration": duration}


def main():
    operation, value = sys.argv[1:]
    if operation == "input":
        result = media(value, False)
    elif operation == "clip":
        result = media(value, True)
    elif operation == "metadata":
        result = metadata(value)
    elif operation == "speech":
        result = speech(value)
    else:
        raise ValueError("unknown observation")
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print(json.dumps({"error": "native-observation-failed"}))
        raise SystemExit(2)
