"""HTTP probe (disabled by default) used during discovery experiments."""

from __future__ import annotations

import http.server
import json
from typing import Any

from . import event_log


class ProbeHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Serve the fake logger identity response."""

    server_version = "SolisDataLogger/1.0"
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802
        self._handle(True)

    def do_POST(self) -> None:  # noqa: N802
        self._handle(True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle(False)

    def log_message(self, *args: Any) -> None:
        pass

    def _handle(self, send_body: bool) -> None:
        event_log.log_event(
            "http_request",
            peer_ip=self.client_address[0],
            method=self.command,
            path=self.path,
        )
        payload = json.dumps(
            {"vendor": "Ginlong", "model": "S6-EH1P", "status": "online"}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if send_body:
            self.wfile.write(payload)
