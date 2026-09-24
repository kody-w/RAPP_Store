"""Bounded public-only forward proxy and fixed-origin MCP ingress.

Only this service has an external route. The native browser is on an isolated
internal bridge; every proxy connection resolves, validates, then pins its IP.
"""
from __future__ import annotations

import http.client
import json
import os
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

try:
    from .url_policy import URLNotAllowed, connect_public, public_url
except ImportError:
    from url_policy import URLNotAllowed, connect_public, public_url

MAX_RESPONSE = 8 * 1024 * 1024
MAX_REQUEST = 64 * 1024
_HOP_HEADERS = {
    "connection", "proxy-connection", "proxy-authorization", "keep-alive",
    "transfer-encoding", "upgrade", "te", "trailer",
}


class ApprovedTargets:
    def __init__(self):
        self.lock = threading.Lock()
        self.targets = {}

    def allow(self, target):
        with self.lock:
            now = time.monotonic()
            self.targets = {key: expiry for key, expiry in self.targets.items() if expiry > now}
            if len(self.targets) >= 256:
                oldest = min(self.targets, key=self.targets.get)
                self.targets.pop(oldest)
            self.targets[(target.host, target.port)] = now + 90

    def allows(self, target):
        with self.lock:
            return self.targets.get((target.host, target.port), 0) > time.monotonic()


APPROVED = ApprovedTargets()


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
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

    def handle_error(self, request, client_address):
        return


class QuietHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Dock"

    def setup(self):
        super().setup()
        self.connection.settimeout(90)

    def log_message(self, *_args):
        return

    def fail(self, status: int, code: str):
        payload = ('{"error":"' + code + '"}').encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if code == "url-not-allowed":
            self.send_header("X-Rapp-Dock-Policy", code)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def reply(self, response, body: bytes):
        self.send_response(response.status)
        for name, value in response.getheaders():
            if name.lower() not in _HOP_HEADERS | {"content-length", "set-cookie"}:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


class PublicProxy(QuietHandler):
    def do_CONNECT(self):
        if any(char in self.path for char in "/?#"):
            self.fail(403, "url-not-allowed")
            return
        try:
            target = public_url("https://" + self.path)
            if not APPROVED.allows(target):
                raise URLNotAllowed()
            upstream = connect_public(target)
        except URLNotAllowed:
            self.fail(403, "url-not-allowed")
            return
        except OSError:
            self.fail(502, "public-fetch-unavailable")
            return
        with upstream:
            self.send_response(200, "Connection Established")
            self.end_headers()
            self.wfile.flush()
            deadline = time.monotonic() + 60
            received = sent = 0
            try:
                while time.monotonic() < deadline:
                    readable, _, _ = select.select([self.connection, upstream], [], [], 5)
                    if not readable:
                        continue
                    for source in readable:
                        block = source.recv(65536)
                        if not block:
                            return
                        if source is upstream:
                            received += len(block)
                            if received > MAX_RESPONSE:
                                return
                            self.connection.sendall(block)
                        else:
                            sent += len(block)
                            if sent > MAX_REQUEST * 16:
                                return
                            upstream.sendall(block)
            except (OSError, TimeoutError):
                return
            finally:
                self.close_connection = True

    def do_GET(self):
        self._get()

    def do_HEAD(self):
        self._get()

    def _get(self):
        upstream = None
        try:
            target = public_url(self.path)
            parsed = urlsplit(target.url)
            if parsed.scheme != "http":
                raise URLNotAllowed()
            if not APPROVED.allows(target):
                raise URLNotAllowed()
            upstream = connect_public(target)
            route = parsed.path + ("?" + parsed.query if parsed.query else "")
            headers = {
                name: value for name, value in self.headers.items()
                if name.lower() not in _HOP_HEADERS | {
                    "host", "authorization", "cookie", "content-length", "expect",
                }
            }
            headers.update(Host=parsed.netloc, Connection="close")
            request = f"{self.command} {route} HTTP/1.1\r\n"
            request += "".join(f"{name}: {value}\r\n" for name, value in headers.items()) + "\r\n"
            upstream.sendall(request.encode("latin-1"))
            response = http.client.HTTPResponse(upstream, method=self.command)
            response.begin()
            body = response.read(MAX_RESPONSE + 1)
            if len(body) > MAX_RESPONSE:
                self.fail(502, "response-too-large")
            else:
                self.reply(response, body)
        except URLNotAllowed:
            self.fail(403, "url-not-allowed")
        except (OSError, ValueError, http.client.HTTPException):
            self.fail(502, "public-fetch-unavailable")
        finally:
            if upstream is not None:
                upstream.close()

    def do_POST(self):
        if self.path != "/policy":
            self.fail(405, "method-not-allowed")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.headers.get("Transfer-Encoding") or not 0 < length <= 4096:
                raise ValueError()
            body = self.rfile.read(length)
            value = json.loads(body)
            if not isinstance(value, dict) or set(value) != {"url"}:
                raise ValueError()
            target = public_url(value["url"])
        except URLNotAllowed:
            self.fail(403, "url-not-allowed")
            return
        except (ValueError, TypeError):
            self.fail(400, "invalid-body")
            return
        APPROVED.allow(target)
        payload = json.dumps({"url": target.url}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True


class MCPIngress(QuietHandler):
    def _forward(self):
        authority = "127.0.0.1:" + os.environ["RAPP_DOCK_PORT"]
        if self.headers.get("Host") != authority or self.headers.get("Origin") not in (
            None, "http://" + authority,
        ):
            self.fail(403, "origin-not-allowed")
            return
        if self.path not in ("/mcp", "/mcp/"):
            self.fail(404, "not-found")
            return
        if self.headers.get("Transfer-Encoding"):
            self.fail(400, "invalid-body")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_REQUEST:
            self.fail(413, "invalid-body")
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self.fail(400, "invalid-body")
            return
        headers = {
            name: value for name, value in self.headers.items()
            if name.lower() not in _HOP_HEADERS | {"host", "origin", "content-length"}
        }
        headers["Host"] = "scrapling:8000"
        connection = http.client.HTTPConnection("scrapling", 8000, timeout=85)
        try:
            connection.request(self.command, "/mcp", body=body or None, headers=headers)
            response = connection.getresponse()
            payload = response.read(MAX_RESPONSE + 1)
            if len(payload) > MAX_RESPONSE:
                self.fail(502, "response-too-large")
            else:
                self.reply(response, payload)
        except (OSError, http.client.HTTPException):
            self.fail(502, "app-not-ready")
        finally:
            connection.close()

    do_POST = _forward
    do_GET = _forward
    do_DELETE = _forward


def main():
    proxy = BoundedServer(("0.0.0.0", 8081), PublicProxy)
    ingress = BoundedServer(("0.0.0.0", 8000), MCPIngress)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    ingress.serve_forever()


if __name__ == "__main__":
    main()
