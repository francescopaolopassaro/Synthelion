# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Local, read-only web dashboard over Synthelion's savings ledger and session memory.

Serves a Bootstrap 5 page (vendored locally — no CDN, works offline) backed by
a few read-only JSON endpoints. Binds to 127.0.0.1 by default: it is meant to
be opened in a browser on the same machine, not exposed to a network.

Run:
    synthelion serve-dashboard
    synthelion serve-dashboard --port 8787 --host 0.0.0.0   # explicit opt-in to expose it

Every request just reads from disk (ledger.py / session_db.py already support
many concurrent readers/writers without locks — see those modules), so
multiple browser tabs or a monitoring script can poll this concurrently.
"""
from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_ASSETS_DIR = Path(__file__).parent / "dashboard_assets"

# Explicit allow-list of static files servable under /assets/ — avoids any
# path-traversal surface from request paths.
_STATIC_FILES = {
    "/assets/dashboard.css": _ASSETS_DIR / "dashboard.css",
    "/assets/dashboard.js": _ASSETS_DIR / "dashboard.js",
    "/assets/vendor/bootstrap/bootstrap.min.css": _ASSETS_DIR / "vendor" / "bootstrap" / "bootstrap.min.css",
    "/assets/vendor/bootstrap/bootstrap.bundle.min.js": _ASSETS_DIR / "vendor" / "bootstrap" / "bootstrap.bundle.min.js",
    "/assets/vendor/chartjs/chart.umd.min.js": _ASSETS_DIR / "vendor" / "chartjs" / "chart.umd.min.js",
    "/assets/img/logo.png": _ASSETS_DIR / "img" / "logo.png",
    "/assets/img/mark.png": _ASSETS_DIR / "img" / "mark.png",
    "/assets/img/apple-touch-icon.png": _ASSETS_DIR / "img" / "apple-touch-icon.png",
    "/assets/img/favicon-96x96.png": _ASSETS_DIR / "img" / "favicon-96x96.png",
    "/favicon.ico": _ASSETS_DIR / "img" / "favicon.ico",
}


class _DashboardHandler(BaseHTTPRequestHandler):
    server_version = "SynthelionDashboard/1.0"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - silence default stderr logging
        pass

    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        try:
            if path == "/" or path == "/index.html":
                self._serve_file(_ASSETS_DIR / "index.html", "text/html; charset=utf-8")
            elif path in _STATIC_FILES:
                self._serve_file(_STATIC_FILES[path], _guess_type(path))
            elif path == "/api/summary":
                self._serve_json(self._summary(qs))
            elif path == "/api/records":
                self._serve_json(self._records(qs))
            elif path == "/api/sessions":
                self._serve_json(self._sessions(qs))
            elif path == "/api/decisions":
                self._serve_json(self._decisions(qs))
            elif path == "/api/version":
                self._serve_json(self._version())
            else:
                self._error(404, "Not found")
        except Exception as exc:  # noqa: BLE001 - never let one bad request kill the server
            self._error(500, str(exc))

    # ── read-only data endpoints ─────────────────────────────────────────────

    @staticmethod
    def _summary(qs: dict) -> dict:
        from synthelion.analytics.ledger import get_ledger

        ledger = get_ledger()
        days = qs.get("days", [None])[0]
        records = ledger.records_since(int(days)) if days else ledger.all_records()
        return ledger.summary(records)

    @staticmethod
    def _records(qs: dict) -> dict:
        from synthelion.analytics.ledger import get_ledger

        ledger = get_ledger()
        days = qs.get("days", [None])[0]
        records = ledger.records_since(int(days)) if days else ledger.all_records()
        limit = qs.get("limit", [None])[0]
        if limit:
            records = sorted(records, key=lambda r: r.get("ts") or "", reverse=True)[: int(limit)]
        return {"records": records, "count": len(records)}

    @staticmethod
    def _sessions(qs: dict) -> dict:
        from synthelion.analytics.ledger import get_ledger

        ledger = get_ledger()
        days = qs.get("days", [None])[0]
        records = ledger.records_since(int(days)) if days else ledger.all_records()
        sessions = ledger.sessions_summary(records)
        limit = qs.get("limit", [None])[0]
        if limit:
            sessions = sessions[: int(limit)]
        return {"sessions": sessions, "count": len(sessions)}

    @staticmethod
    def _decisions(qs: dict) -> dict:
        from synthelion.analytics.session_db import get_session_db

        db = get_session_db()
        limit = int(qs.get("limit", [20])[0])
        return {"decisions": db.list_decisions(limit=limit), "backend": db.backend()}

    @staticmethod
    def _version() -> dict:
        import synthelion

        return {"version": synthelion.__version__}

    # ── plumbing ─────────────────────────────────────────────────────────────

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._error(404, "Not found")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_json(self, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, code: int, message: str) -> None:
        data = json.dumps({"error": message}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _guess_type(path: str) -> str:
    ctype, _ = mimetypes.guess_type(path)
    return ctype or "application/octet-stream"


def run_dashboard(host: str = "127.0.0.1", port: int = 8787) -> None:
    """Start the dashboard HTTP server and block until interrupted."""
    server = ThreadingHTTPServer((host, port), _DashboardHandler)
    url = f"http://{host}:{port}/"
    print(f"Synthelion dashboard — {url}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
