"""A small local web service for the GUI. Python standard library only.

Read-only: the Record is opened read-only for every request and nothing is ever written.
Bound to localhost.
"""
from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlparse

from aggregator import RecordStore

import html

from .api import NO_AS_OF, ROOT, ROUTES, ApiError

STATIC = Path(__file__).with_name("static")


def handle_api(db_path: Path, planted: Optional[Path], route: str, query: dict[str, str]) -> tuple[int, Any]:
    """Run one API call. Returns (HTTP status, JSON-able body). Used by the server and by tests."""
    func = ROUTES.get(route)
    if func is None:
        return 404, {"error": f"no such endpoint: {route}"}
    if route not in NO_AS_OF and not query.get("as_of"):
        return 400, {"error": "missing required parameter 'as_of': every read names a moment"}
    store = RecordStore.open(db_path)
    try:
        return 200, func(store, query, {"planted": planted})
    except ApiError as exc:
        return exc.status, {"error": str(exc)}
    except KeyError as exc:
        return 404, {"error": str(exc)}
    finally:
        store.close()


SOURCE_DIRS = ("example_device", "aggregator", "utils", "viewer")


def source_page(rel: str) -> Optional[bytes]:
    """One source file of this project as a page with numbered, linkable lines. Read-only."""
    target = (ROOT / rel).resolve()
    allowed = any((ROOT / d).resolve() in target.parents for d in SOURCE_DIRS)
    if not allowed or target.suffix not in (".py", ".sql") or not target.is_file():
        return None
    rows = "".join(f'<tr id="L{n}"><td class="n">{n}</td><td><pre>{html.escape(line) or " "}</pre></td></tr>'
                   for n, line in enumerate(target.read_text().splitlines(), 1))
    return (f"<!doctype html><meta charset='utf-8'><title>{html.escape(rel)}</title>"
            "<style>body{font:13px ui-monospace,Menlo,monospace;margin:0;background:#fcfcfb;color:#0b0b0b}"
            "h1{font:600 15px system-ui,sans-serif;margin:0;padding:10px 16px;position:sticky;top:0;background:#fcfcfb;"
            "border-bottom:1px solid #e1e0d9}table{border-collapse:collapse}pre{margin:0}"
            "tr{scroll-margin-top:48px}td{padding:0 10px;vertical-align:top}td.n{color:#898781;text-align:right;user-select:none}"
            "tr:target{background:#efedfb}tr:target td.n{color:#6250d6;font-weight:700}"
            "@media(prefers-color-scheme:dark){body,h1{background:#1a1a19;color:#f0efec}tr:target{background:#24223a}}</style>"
            f"<h1>{html.escape(rel)} <span style='font-weight:400;color:#898781'>read-only view of the running code</span></h1>"
            f"<table>{rows}</table>").encode()


def make_handler(db_path: Path, planted: Optional[Path]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            if url.path.startswith("/api/"):
                status, body = handle_api(db_path, planted, url.path[len("/api/"):], dict(parse_qsl(url.query)))
                self._send(status, json.dumps(body).encode(), "application/json")
                return
            if url.path.startswith("/source/"):
                page = source_page(url.path[len("/source/"):])
                self._send(200 if page else 404, page or b"not found", "text/html" if page else "text/plain")
                return
            rel = "index.html" if url.path in ("", "/") else url.path.lstrip("/")
            target = (STATIC / rel).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():
                self._send(404, b"not found", "text/plain")
                return
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), ctype)

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8" if ctype.startswith(("text", "application/j")) else ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            pass

    return Handler


def make_server(db_path: str | Path, port: int = 8765) -> ThreadingHTTPServer:
    db_path = Path(db_path)
    RecordStore.open(db_path).close()          # fail early if there is no Record
    planted = db_path.with_name("planted.json")
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(db_path, planted if planted.exists() else None))


def serve(db_path: str | Path, port: int = 8765) -> None:
    server = make_server(db_path, port)
    print(f"Operations Record browser: http://127.0.0.1:{server.server_port}/")
    print(f"Record: {db_path} (read-only). Stop with Ctrl-C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
