# SPDX-License-Identifier: MIT OR Apache-2.0

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from . import run_demo


class EventHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps(
            {"event_type": "signup", "user": "alice", "payload": {"age": 30}},
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return None


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), EventHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        summary = run_demo(f"http://127.0.0.1:{port}/event")
    finally:
        server.shutdown()
        thread.join()

    payload = json.dumps(summary["payload"], separators=(",", ":"))
    print(
        "recognize-demo-python round-trip: "
        f"rowid={summary['rowid']} user={summary['user']} "
        f"type={summary['type']} report=\"{payload}\""
    )


if __name__ == "__main__":
    main()
