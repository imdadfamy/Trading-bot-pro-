"""Dependency-free, localhost-only development API. No execution routes."""
from __future__ import annotations
import json
import os
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .service import Service


def handler_factory(service: Service, operator_key: str | None = None):
    preview = Path(__file__).resolve().parents[2] / "web" / "preview"
    class Handler(BaseHTTPRequestHandler):
        def _static(self, filename, content_type):
            data = (preview / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def _download(self, data, filename, content_type):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status, payload):
            data = json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            origin = self.headers.get("Origin")
            if origin in {"http://localhost:3000", "http://127.0.0.1:3000"}:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self):
            candidate = self.headers.get("X-Operator-Key") or ""
            return bool(operator_key and candidate and compare_digest(candidate, operator_key))

        def do_GET(self):
            path = urlsplit(self.path).path
            static_files = {"/": ("index.html", "text/html; charset=utf-8"),
                            "/preview.css": ("preview.css", "text/css; charset=utf-8"),
                            "/preview.js": ("preview.js", "text/javascript; charset=utf-8"),
                            "/labels.json": ("labels.json", "application/json; charset=utf-8")}
            if path in static_files:
                return self._static(*static_files[path])
            if path in {"/settings", "/audit", "/audit/integrity", "/export/signals.csv", "/orders/intents"} and not self._authorized():
                return self._json(403, {"error": "Operator authentication required"})
            if path == "/export/signals.csv":
                from .exports import signals_csv
                return self._download(signals_csv(service.store), "signals.csv", "text/csv; charset=utf-8")
            if path == "/audit":
                return self._json(200, service.store.journal.events(100))
            if path == "/audit/integrity":
                return self._json(200, {"valid": service.store.journal.verify_audit()})
            if path == "/settings":
                return self._json(200, service.settings())
            try:
                self._json(200, service.read(path))
            except KeyError:
                self._json(404, {"error": "Unknown route"})

        def do_POST(self):
            if not self._authorized():
                return self._json(403, {"error": "Operator authentication required"})
            if urlsplit(self.path).path == "/risk/kill-switch":
                service.store.set_killed()
                return self._json(200, {"killed": True})
            if urlsplit(self.path).path == "/experiments":
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if size <= 0 or size > 8192:
                        return self._json(413, {"error": "Invalid request size"})
                    data = json.loads(self.rfile.read(size))
                    from .experiments import ExperimentManager
                    identifier = ExperimentManager(service.store).draft(data)
                    return self._json(201, {"id": identifier, "status": "draft"})
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    return self._json(400, {"error": str(exc)})
            self._json(404, {"error": "Unknown or unavailable operation"})

        def do_PATCH(self):
            if not self._authorized():
                return self._json(403, {"error": "Operator authentication required"})
            if urlsplit(self.path).path != "/settings":
                return self._json(404, {"error": "Unknown route"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 8192:
                    return self._json(413, {"error": "Invalid settings size"})
                payload = json.loads(self.rfile.read(size))
                result = service.update_settings(payload["settings"], payload["expected_version"],
                                                 self.headers.get("X-Operator-Name", "local-operator"))
                self._json(200, result)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
            except RuntimeError as exc:
                self._json(409, {"error": str(exc)})

        def do_OPTIONS(self):
            self.send_response(204)
            origin = self.headers.get("Origin")
            if origin in {"http://localhost:3000", "http://127.0.0.1:3000"}:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "X-Operator-Key, X-Operator-Name, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
            self.end_headers()

        def log_message(self, format, *args):
            # Never log request headers or operator keys.
            return
    return Handler


def main():
    import argparse
    from .local_env import load_local_env
    load_local_env()
    parser = argparse.ArgumentParser(description="Local observation API only")
    parser.add_argument("--database", default=os.getenv("TIP_DB", "data/trading.db"))
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Invalid port")
    service = Service(args.database)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_factory(service, os.getenv("TIP_OPERATOR_KEY")))
    print(f"Local observation API: http://127.0.0.1:{args.port} (no broker execution)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
