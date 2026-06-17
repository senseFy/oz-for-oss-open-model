#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oz.open_model_backend import (
    OPEN_MODEL_BACKEND_TOKEN_ENV,
    REVIEW_ARTIFACT,
    FileOpenModelBackend,
)


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _error(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
    _json_response(handler, status, {"error": message})


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length", "0") or 0)
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


class ReviewBackendServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        *,
        backend: FileOpenModelBackend,
        token: str,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.backend = backend
        self.token = token


class Handler(BaseHTTPRequestHandler):
    server: ReviewBackendServer
    server_version = "OpenModelReviewBackend/0.1"

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        parts = self._path_parts()
        try:
            if parts == ["healthz"]:
                _json_response(self, 200, {"status": "ok"})
                return
            if len(parts) == 2 and parts[0] == "runs":
                run = self.server.backend.retrieve(parts[1])
                _json_response(
                    self,
                    200,
                    {
                        "run_id": run.run_id,
                        "state": run.state,
                        "created_at": run.created_at.timestamp(),
                        "updated_at": run.updated_at.timestamp(),
                        "error": run.status_message,
                        "session_link": run.session_link,
                        "artifacts": [
                            {"filename": artifact.data.filename}
                            for artifact in run.artifacts or []
                            if getattr(artifact, "data", None) is not None
                        ],
                    },
                )
                return
            if (
                len(parts) == 4
                and parts[0] == "runs"
                and parts[2] == "artifacts"
            ):
                _json_response(
                    self,
                    200,
                    self.server.backend.load_json_artifact(parts[1], parts[3]),
                )
                return
        except Exception as exc:
            _error(self, 500, str(exc))
            return
        _error(self, 404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        parts = self._path_parts()
        try:
            if parts == ["runs"]:
                body = _read_json_body(self)
                run_id = self.server.backend.create_run(
                    prompt=str(body.get("prompt") or ""),
                    title=str(body.get("title") or ""),
                    config=body.get("config") if isinstance(body.get("config"), dict) else {},
                    skill=(
                        str(body.get("skill"))
                        if body.get("skill") is not None
                        else None
                    ),
                    team=bool(body.get("team")),
                    attachments=tuple(body.get("attachments") or ()),
                    workflow=(
                        str(body.get("workflow"))
                        if body.get("workflow") is not None
                        else None
                    ),
                )
                _json_response(self, 202, {"run_id": run_id})
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "cancel":
                self.server.backend.cancel(parts[1])
                _json_response(self, 202, {"run_id": parts[1], "state": "CANCELLED"})
                return
        except Exception as exc:
            _error(self, 500, str(exc))
            return
        _error(self, 404, "not found")

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _path_parts(self) -> list[str]:
        path = urlparse(self.path).path.strip("/")
        if not path:
            return []
        return [unquote(part) for part in path.split("/") if part]

    def _authorized(self) -> bool:
        token = self.server.token
        if not token:
            return True
        if self.headers.get("authorization", "") == f"Bearer {token}":
            return True
        _error(self, 401, "unauthorized")
        return False


def _worker_loop(backend: FileOpenModelBackend, *, poll_interval: float) -> None:
    while True:
        try:
            run_id = backend.process_next()
            if run_id is None:
                time.sleep(poll_interval)
        except Exception as exc:
            print(f"open-model worker error: {exc}")
            time.sleep(poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the provider-transparent review backend service."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--no-worker",
        action="store_true",
        help="Serve the HTTP API without processing queued runs.",
    )
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one queued run and exit instead of serving HTTP.",
    )
    args = parser.parse_args()

    backend = FileOpenModelBackend.from_env()
    if args.once:
        run_id = backend.process_next()
        print(run_id or "no queued runs")
        return

    if not args.no_worker:
        thread = threading.Thread(
            target=_worker_loop,
            kwargs={"backend": backend, "poll_interval": args.poll_interval},
            daemon=True,
        )
        thread.start()

    token = os.environ.get(OPEN_MODEL_BACKEND_TOKEN_ENV, "").strip()
    server = ReviewBackendServer(
        (args.host, args.port),
        Handler,
        backend=backend,
        token=token,
    )
    print(
        f"open-model review backend listening on http://{args.host}:{args.port}; "
        f"artifact={REVIEW_ARTIFACT}"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
