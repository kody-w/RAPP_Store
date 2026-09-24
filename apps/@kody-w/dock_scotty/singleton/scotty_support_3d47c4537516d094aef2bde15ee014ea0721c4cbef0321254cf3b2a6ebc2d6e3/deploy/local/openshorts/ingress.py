"""Small authenticated edge for the closed local OpenShorts job surface."""

from __future__ import annotations

import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading
from urllib.parse import urlsplit

UUID = r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
FILE = r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,239}"
MAX_JSON = 64 * 1024
MAX_MEDIA = 256 * 1024 * 1024
MAX_RESPONSE = MAX_MEDIA


class Refused(ValueError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def route(method, target):
    parsed = urlsplit(target)
    if (
        parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
        or not parsed.path.startswith("/") or "%" in target or "\\" in target
        or any(part in (".", "..") for part in parsed.path.split("/"))
    ):
        raise Refused(400, "invalid-path")
    path = parsed.path
    if method in {"GET", "HEAD"} and path == "/health":
        return "health"
    if method in {"GET", "HEAD"} and (
        path == "/" or re.fullmatch(r"/assets/" + FILE, path)
        or re.fullmatch(r"/(?:fonts/)?"+ FILE + r"\.(?:png|ico|svg|ttf|woff2?)", path)
    ):
        return "static"
    if method == "GET" and path == "/api/config":
        return "config"
    if method == "POST" and path == "/api/uploads":
        return "create-upload"
    if re.fullmatch("/api/uploads/" + UUID, path):
        if method == "PUT":
            return "upload"
        if method == "DELETE":
            return "delete-upload"
    if method == "POST" and path == "/api/process":
        return "process"
    if method == "GET" and re.fullmatch("/api/status/" + UUID, path):
        return "status"
    if method in {"GET", "HEAD"} and re.fullmatch("/videos/" + UUID + "/" + FILE + r"\.mp4", path):
        return "video"
    if method == "POST" and path == "/api/render":
        return "render"
    if method == "GET" and re.fullmatch("/api/render/" + UUID, path):
        return "render-status"
    raise Refused(403, "route-not-supported")


def authorize(method, target, headers, *, public_port, key):
    kind = route(method, target)
    hosts = {f"127.0.0.1:{public_port}", f"localhost:{public_port}"}
    host_values = headers.get_all("Host", []) if hasattr(headers, "get_all") else [headers.get("Host", "")]
    if len(host_values) != 1 or host_values[0].lower() not in hosts:
        raise Refused(403, "host-not-allowed")
    origin = headers.get("Origin")
    if origin is not None and origin not in {"http://" + host for host in hosts}:
        raise Refused(403, "origin-not-allowed")
    if headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
        raise Refused(403, "origin-not-allowed")
    if kind != "health":
        values = headers.get_all("Authorization", []) if hasattr(headers, "get_all") else [headers.get("Authorization", "")]
        expected = "Bearer " + key
        if len(values) != 1 or not hmac.compare_digest(values[0].encode(), expected.encode()):
            raise Refused(401, "app-authentication-required")
    return kind


def json_body(kind, raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise Refused(400, "invalid-json") from None
    if not isinstance(value, dict):
        raise Refused(400, "invalid-body")
    if kind == "create-upload":
        if set(value) != {"filename"} or not isinstance(value["filename"], str) or not re.fullmatch(FILE, value["filename"]):
            raise Refused(400, "invalid-upload")
    elif kind == "process":
        expected = {"upload_id", "acknowledged", "output_format", "layouts", "target_clips",
                    "clip_min_seconds", "clip_max_seconds", "captions", "auto_hook"}
        if set(value) != expected or not isinstance(value["upload_id"], str) or not re.fullmatch(UUID, value["upload_id"]):
            raise Refused(400, "unsupported-process-body")
        if (
            value["acknowledged"] is not True or value["output_format"] != "vertical"
            or value["layouts"] != ["none"] or value["captions"] is not True or value["auto_hook"] is not False
            or type(value["target_clips"]) is not int or not 1 <= value["target_clips"] <= 5
            or value["clip_min_seconds"] != 10 or value["clip_max_seconds"] != 40
        ):
            raise Refused(400, "unsupported-process-options")
    elif kind == "render":
        if set(value) != {"jobId", "clipIndex", "props"} or not isinstance(value["jobId"], str) or not re.fullmatch(UUID, value["jobId"]):
            raise Refused(400, "unsupported-render-body")
        if type(value["clipIndex"]) is not int or not 0 <= value["clipIndex"] <= 4:
            raise Refused(400, "invalid-render-index")
        props = value["props"]
        fields = {"videoUrl", "durationInFrames", "fps", "width", "height", "subtitles", "hook", "effects"}
        if not isinstance(props, dict) or set(props) != fields:
            raise Refused(400, "unsupported-render-props")
        if not isinstance(props["videoUrl"], str) or not re.fullmatch(
            "http://renderer:3100/output/" + value["jobId"] + "/" + FILE + r"\.mp4", props["videoUrl"]
        ):
            raise Refused(400, "external-render-input-refused")
        for key, maximum in (("durationInFrames", 5400), ("fps", 60), ("width", 1920), ("height", 1920)):
            if type(props[key]) is not int or not 1 <= props[key] <= maximum:
                raise Refused(400, "render-bound-exceeded")
        if props["durationInFrames"] / props["fps"] > 90 or any(props[key] is not None for key in ("subtitles", "hook", "effects")):
            raise Refused(400, "unsupported-render-options")
    else:
        raise Refused(400, "unexpected-body")
    return raw


class EdgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, key, public_port):
        self.key, self.public_port = key, public_port
        self.slots = threading.BoundedSemaphore(4)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "OpenShortsLocal"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, *_):
        pass

    def handle_expect_100(self):
        self.reply(417, "expect-not-supported")
        return False

    def reply(self, status, code):
        body = json.dumps({"error": code} if status != 200 else {"status": "ok"}).encode()
        self.response_started = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if status == 401:
            self.send_header("WWW-Authenticate", "Bearer")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def dispatch(self):
        upstream = None
        self.response_started = False
        try:
            kind = authorize(self.command, self.path, self.headers, public_port=self.server.public_port, key=self.server.key)
            if self.headers.get("Transfer-Encoding") or self.headers.get("Expect"):
                raise Refused(400, "unsupported-transfer")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) > 1 or lengths and not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
                raise Refused(400, "invalid-content-length")
            length = int(lengths[0]) if lengths else 0
            limit = MAX_MEDIA if kind == "upload" else MAX_JSON
            if length > limit:
                raise Refused(413, "body-too-large")
            body_kind = kind in {"create-upload", "process", "render", "upload"}
            if body_kind and not length:
                raise Refused(400, "body-required")
            if not body_kind and length:
                raise Refused(400, "unexpected-body")
            if kind == "health":
                self.reply(200, "ok")
                return
            data = None
            if kind in {"create-upload", "process", "render"}:
                if self.headers.get_content_type() != "application/json":
                    raise Refused(415, "json-required")
                data = self.rfile.read(length)
                if len(data) != length:
                    raise Refused(400, "incomplete-body")
                json_body(kind, data)
            elif kind == "upload" and self.headers.get_content_type() != "application/octet-stream":
                raise Refused(415, "binary-upload-required")
            # The request is now authenticated and constrained. No user-provided
            # destination, authorization header, cookie or redirect is forwarded.
            upstream = http.client.HTTPConnection("frontend", 80, timeout=600)
            upstream.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            upstream.putheader("Host", "frontend")
            if body_kind:
                upstream.putheader("Content-Length", str(length))
                upstream.putheader("Content-Type", "application/octet-stream" if kind == "upload" else "application/json")
            requested_range = self.headers.get("Range")
            if requested_range and kind == "video":
                if not re.fullmatch(r"bytes=[0-9]+-[0-9]*", requested_range):
                    raise Refused(400, "unsupported-range")
                upstream.putheader("Range", requested_range)
            upstream.endheaders()
            if data is not None:
                upstream.send(data)
            elif kind == "upload":
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        raise Refused(400, "incomplete-upload")
                    upstream.send(chunk)
                    remaining -= len(chunk)
            response = upstream.getresponse()
            if 300 <= response.status <= 399:
                raise Refused(502, "upstream-redirect-refused")
            response_length = response.getheader("Content-Length")
            if response_length and (not response_length.isdigit() or int(response_length) > MAX_RESPONSE):
                raise Refused(502, "upstream-response-too-large")
            self.response_started = True
            self.send_response(response.status)
            for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                value = response.getheader(name)
                if value is not None:
                    self.send_header(name, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            total = 0
            if self.command != "HEAD":
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > MAX_RESPONSE:
                        self.close_connection = True
                        return
                    self.wfile.write(chunk)
        except Refused as error:
            self.reply(error.status, error.code)
        except (OSError, TimeoutError, http.client.HTTPException):
            self.close_connection = True
            if not self.response_started:
                try:
                    self.reply(502, "native-app-unavailable")
                except OSError:
                    pass
        finally:
            if upstream is not None:
                upstream.close()

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_OPTIONS = do_PATCH = do_TRACE = do_CONNECT = dispatch


def main():
    key = os.environ.get("OPENSHORTS_INGRESS_KEY", "")
    port = os.environ.get("OPENSHORTS_PUBLIC_PORT", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", key) or not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise RuntimeError("OpenShorts edge configuration is absent or invalid")
    EdgeServer(("0.0.0.0", 8080), key, int(port)).serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
