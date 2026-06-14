from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from pdfpoc.config import POC_ROOT, RUNS_DIR
from pdfpoc.ui.data import build_overview, page_compare, save_page_review

UI_DIR = Path(__file__).resolve().parent
STATIC_DIR = UI_DIR / "static"


def serve_ui(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    runs_dir: str | Path = RUNS_DIR,
    db_path: str | Path | None = RUNS_DIR / "index.sqlite",
) -> None:
    handler = _handler(Path(runs_dir), Path(db_path) if db_path else None)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"PDF parse review UI: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _handler(runs_dir: Path, db_path: Path | None):
    class UiHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
                return
            if parsed.path.startswith("/static/"):
                self._send_file(STATIC_DIR / parsed.path.removeprefix("/static/"))
                return
            if parsed.path == "/api/overview":
                self._send_json(build_overview(runs_dir, db_path))
                return
            if parsed.path == "/api/page":
                params = parse_qs(parsed.query)
                document_id = _one(params, "document_id")
                page = int(_one(params, "page") or "1")
                run_ids = [item for item in (_one(params, "runs") or "").split(",") if item]
                self._send_json(page_compare(document_id, page, run_ids, runs_dir=runs_dir, db_path=db_path))
                return
            if parsed.path == "/asset":
                path = Path(unquote(_one(parse_qs(parsed.query), "path")))
                if not _is_safe_asset(path):
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                self._send_file(path)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/review":
                try:
                    payload = self._read_json_body()
                    document_id = str(payload.get("document_id") or "")
                    page_number = int(payload.get("page_number") or 0)
                    if not document_id or page_number < 1:
                        raise ValueError("document_id and page_number are required")
                    review = save_page_review(
                        document_id,
                        page_number,
                        payload,
                        db_path=db_path,
                    )
                except (json.JSONDecodeError, ValueError) as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"review": review})
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict:
            size = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(size)
            data = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def _send_file(self, path: Path, content_type: str | None = None) -> None:
            if not path.exists() or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = path.read_bytes()
            guessed = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", guessed)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return UiHandler


def _one(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key) or [""]
    return values[0]


def _is_safe_asset(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    allowed_roots = [POC_ROOT.resolve()]
    return any(resolved == root or root in resolved.parents for root in allowed_roots)
