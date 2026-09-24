"""Run unchanged Presenton with a loopback provider that explicitly refuses AI calls."""
from __future__ import annotations

import json
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REFUSAL = json.dumps({
    "error": {
        "message": "Application AI providers are disabled. No model was called or output generated.",
        "type": "provider_disabled",
        "code": "RAPP_PAID_PROVIDER_DISABLED",
    },
}, separators=(",", ":")).encode()


class BlockedProvider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def refuse(self) -> None:
        self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(REFUSAL)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(REFUSAL)
        self.close_connection = True

    do_GET = refuse
    do_POST = refuse
    do_PUT = refuse
    do_DELETE = refuse
    do_PATCH = refuse
    do_OPTIONS = refuse

    def log_message(self, format: str, *args: object) -> None:
        # Never record prompts, URLs, headers or credentials sent to this stub.
        return


def provider_server(port: int = 18888) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), BlockedProvider)
    server.daemon_threads = True
    return server


def main() -> int:
    with provider_server() as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        child = subprocess.Popen(["node", "/app/start.js"])

        def stop(signum: int, _frame: object) -> None:
            if child.poll() is None:
                child.send_signal(signum)

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            return child.wait()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
