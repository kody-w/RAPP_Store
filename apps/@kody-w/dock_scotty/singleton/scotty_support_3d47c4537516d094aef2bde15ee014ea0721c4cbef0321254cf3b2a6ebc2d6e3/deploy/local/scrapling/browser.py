"""Native-arm64 Chromium with an internal-only, fixed-port CDP relay."""
from __future__ import annotations

import http.client
import select
import signal
import socket
import socketserver
import subprocess
import threading
import time

COMMAND = [
    "/usr/bin/chromium", "--headless=new", "--no-sandbox",
    "--disable-dev-shm-usage", "--disable-gpu", "--disable-background-networking",
    "--disable-extensions", "--disable-sync", "--disable-component-update",
    "--disable-domain-reliability", "--disable-client-side-phishing-detection",
    "--disable-notifications", "--disable-default-apps", "--no-pings",
    "--metrics-recording-only", "--no-first-run", "--no-default-browser-check",
    "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9223",
    "--user-data-dir=/runtime/profile", "--disk-cache-dir=/runtime/cache",
    "--crash-dumps-dir=/runtime/crash",
    "--proxy-server=http://egress:8081", "--proxy-bypass-list=<-loopback>",
    "--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "about:blank",
]


class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with socket.create_connection(("127.0.0.1", 9223), timeout=5) as upstream:
                self.request.settimeout(5)
                deadline, total = time.monotonic() + 90, 0
                while time.monotonic() < deadline:
                    readable, _, _ = select.select([self.request, upstream], [], [], 5)
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        total += len(data)
                        if total > 16 * 1024 * 1024:
                            return
                        (upstream if source is self.request else self.request).sendall(data)
        except (OSError, TimeoutError):
            return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, *args):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(*args)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request, address):
        return


def main():
    def stop(_signal, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    with subprocess.Popen(COMMAND) as browser:
        try:
            deadline = time.monotonic() + 25
            while True:
                if browser.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Native browser did not become ready.")
                connection = http.client.HTTPConnection("127.0.0.1", 9223, timeout=1)
                try:
                    connection.request("GET", "/json/version")
                    if connection.getresponse().status == 200:
                        break
                except OSError:
                    time.sleep(0.25)
                finally:
                    connection.close()
            with Server(("0.0.0.0", 9222), Relay) as server:
                server.serve_forever()
        finally:
            browser.terminate()
            try:
                browser.wait(timeout=8)
            except subprocess.TimeoutExpired:
                browser.kill()
                browser.wait(timeout=3)


if __name__ == "__main__":
    main()
