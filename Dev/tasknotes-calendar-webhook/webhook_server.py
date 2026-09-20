#!/usr/bin/env python3
"""Private Google Calendar push receiver for the TaskNotes vault."""
from __future__ import annotations

import hmac
import json
import logging
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.getenv("TASKNOTES_WEBHOOK_HOST", "127.0.0.1")
PORT = int(os.getenv("TASKNOTES_WEBHOOK_PORT", "8787"))
TOKEN = os.getenv("TASKNOTES_WEBHOOK_TOKEN", "")
VAULT = os.getenv("TASKNOTES_OBSIDIAN_VAULT", "default")
COMMAND = os.getenv("TASKNOTES_REFRESH_COMMAND", "tasknotes:refresh-google-calendar")
OBSIDIAN = os.getenv("TASKNOTES_OBSIDIAN_COMMAND", "/home/ubuntu/.local/bin/obsidian")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("tasknotes-webhook")


def refresh_tasknotes() -> None:
    result = subprocess.run(
        [OBSIDIAN, f"vault={VAULT}", "command", f"id={COMMAND}"],
        capture_output=True, text=True, timeout=90, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Obsidian command failed")


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict[str, str]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._send(200, {"status": "ok"}) if self.path == "/healthz" else self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/google/webhook":
            self._send(404, {"error": "not found"})
            return
        if not TOKEN:
            self._send(503, {"error": "webhook token is not configured"})
            return
        # Google Calendar push uses X-Goog-Channel-Token. Authorization is
        # accepted as a local smoke-test fallback, but Google never sends it.
        supplied = self.headers.get("X-Goog-Channel-Token", "")
        if not supplied:
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(supplied, TOKEN):
            self._send(401, {"error": "unauthorized"})
            return
        try:
            refresh_tasknotes()
        except Exception as exc:  # pragma: no cover - process boundary
            log.exception("TaskNotes refresh failed")
            self._send(502, {"error": str(exc)})
            return
        self._send(202, {"status": "refresh requested"})

    def log_message(self, fmt: str, *args: object) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("TASKNOTES_WEBHOOK_TOKEN must be set")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("TaskNotes webhook listening on %s:%s", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
