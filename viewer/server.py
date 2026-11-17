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

from adapters.control_archive import ControlArchive
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
        return 200, func(store, query, {"planted": planted, "archive": ControlArchive.find(db_path)})
    except ApiError as exc:
        return exc.status, {"error": str(exc)}
    except KeyError as exc:
        return 404, {"error": str(exc)}
    finally:
        store.close()


SOURCE_DIRS = ("example_device", "aggregator", "utils", "viewer", "adapters", "anonymizer", "summarizer", "sparsifier", "orchestrator")


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


def record_info(path: Path) -> Optional[dict[str, Any]]:
    """What a candidate Record file is, or None if it is not a Record."""
    try:
        store = RecordStore.open(path)
    except Exception:
        return None
    try:
        meta = store.meta()
        if "schema_version" not in meta:
            return None
        return {"path": str(path), "preset": meta.get("preset"), "seed": meta.get("seed"),
                "synthetic": meta.get("synthetic") == "true", "entries": store.table_counts(store.latest_known_at())["entry"],
                "size_mb": round(path.stat().st_size / 1e6, 2),
                "planted": path.with_name("planted.json").exists(),
                "archive": (path.parent / "source" / "control_archive" / "index.json").exists()}
    except Exception:
        return None
    finally:
        store.close()


def find_records(base: Path, depth: int = 3) -> list[dict[str, Any]]:
    """Record files under ``base``, for the GUI's chooser."""
    found = []
    for path in sorted(base.rglob("*.db")):
        if len(path.relative_to(base).parts) <= depth and (info := record_info(path)):
            found.append(info)
    return found


class Current:
    """Which Record the GUI is showing. The server starts with one; the GUI can switch."""

    def __init__(self, db_path: Path):
        self.base = db_path.resolve().parent.parent if db_path.resolve().parent.name != "out" else db_path.resolve().parent
        self.use(db_path)

    def use(self, db_path: Path) -> None:
        db_path = Path(db_path)
        if record_info(db_path) is None:
            raise ValueError(f"{db_path} is not a Record")
        planted = db_path.with_name("planted.json")
        self.db, self.planted = db_path, (planted if planted.exists() else None)


def make_handler(current: "Current"):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/use":
                self._send(404, b"not found", "text/plain")
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
                path = Path(str(body.get("path", ""))).expanduser()
                if not path.is_absolute():
                    path = (Path.cwd() / path)
                if path.suffix != ".db" or not path.is_file():
                    raise ValueError(f"no .db file at {path}")
                current.use(path)
                self._send(200, json.dumps({"path": str(current.db)}).encode(), "application/json")
            except Exception as exc:
                self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/api/records":
                body = {"current": str(current.db), "base": str(current.base), "records": find_records(current.base)}
                self._send(200, json.dumps(body).encode(), "application/json")
                return
            if url.path.startswith("/api/"):
                status, body = handle_api(current.db, current.planted, url.path[len("/api/"):], dict(parse_qsl(url.query)))
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
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(Current(db_path)))


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
