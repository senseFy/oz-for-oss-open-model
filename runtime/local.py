"""Local daemon runtime provider."""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from core.poll_runs import (
    DEFAULT_MAX_IN_FLIGHT_AGE_SECONDS,
    DEFAULT_MAX_IN_FLIGHT_ATTEMPTS,
    DrainOutcome,
)
from core.signatures import SIGNATURE_HEADER
from core.state import RUN_STATE_KEY_PREFIX, StateStore
from oz.backend import BACKEND_ENV, BACKEND_OPEN_MODEL, use_open_model_backend
from oz.open_model_backend import (
    OPEN_MODEL_BACKEND_URL_ENV,
    OPEN_MODEL_RUN_STORE_DIR_ENV,
    FileOpenModelBackend,
    build_open_model_backend,
)
from runtime.common import (
    process_webhook_request,
    run_cron_tick,
    summarize_drain_outcomes,
)
from runtime.stores.file import FileStateStore
from runtime.types import CronRuntimeWiring, WebhookRuntimeWiring
from runtime.wiring import build_webhook_runtime_wiring, build_workflow_handlers

logger = logging.getLogger(__name__)

LOCAL_RUNTIME_STATE_DIR_ENV = "LOCAL_RUNTIME_STATE_DIR"
LOCAL_RUNTIME_POLL_INTERVAL_SECONDS_ENV = "LOCAL_RUNTIME_POLL_INTERVAL_SECONDS"
LOCAL_RUNTIME_PROCESS_OPEN_MODEL_ENV = "LOCAL_RUNTIME_PROCESS_OPEN_MODEL"
DEFAULT_LOCAL_STATE_DIR = ".local-runtime/state"
DEFAULT_OPEN_MODEL_RUN_STORE_DIR = ".local-runtime/open-model-runs"
DEFAULT_POLL_INTERVAL_SECONDS = 2.0

_EVENT_HEADER = "x-github-event"
_DELIVERY_HEADER = "x-github-delivery"


def _optional_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _optional_float_env(name: str, default: float) -> float:
    raw = _optional_env(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _optional_int_env(name: str, default: int) -> int:
    raw = _optional_env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _optional_bool_env(name: str, default: bool = True) -> bool:
    raw = _optional_env(name)
    if not raw:
        return default
    return raw.lower() not in {"0", "false", "no", "off"}


def resolve_local_webhook_secret() -> str:
    secret = _optional_env("OZ_GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError(
            "OZ_GITHUB_WEBHOOK_SECRET is required for the local runtime."
        )
    return secret


@dataclass(frozen=True)
class LocalRuntimeConfig:
    host: str = "127.0.0.1"
    port: int = 8788
    state_dir: Path = Path(DEFAULT_LOCAL_STATE_DIR)
    open_model_run_store_dir: Path = Path(DEFAULT_OPEN_MODEL_RUN_STORE_DIR)
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    max_attempts: int = DEFAULT_MAX_IN_FLIGHT_ATTEMPTS
    max_age_seconds: int = DEFAULT_MAX_IN_FLIGHT_AGE_SECONDS
    process_open_model: bool = True

    @classmethod
    def from_env(
        cls,
        *,
        host: str | None = None,
        port: int | None = None,
        state_dir: str | Path | None = None,
        open_model_run_store_dir: str | Path | None = None,
        poll_interval_seconds: float | None = None,
        process_open_model: bool | None = None,
    ) -> "LocalRuntimeConfig":
        return cls(
            host=(
                host
                if host is not None
                else _optional_env("LOCAL_RUNTIME_HOST", "127.0.0.1")
            ),
            port=(
                port
                if port is not None
                else _optional_int_env("LOCAL_RUNTIME_PORT", 8788)
            ),
            state_dir=Path(
                state_dir
                or _optional_env(LOCAL_RUNTIME_STATE_DIR_ENV, DEFAULT_LOCAL_STATE_DIR)
            ),
            open_model_run_store_dir=Path(
                open_model_run_store_dir
                or _optional_env(
                    OPEN_MODEL_RUN_STORE_DIR_ENV,
                    DEFAULT_OPEN_MODEL_RUN_STORE_DIR,
                )
            ),
            poll_interval_seconds=(
                poll_interval_seconds
                if poll_interval_seconds is not None
                else _optional_float_env(
                    LOCAL_RUNTIME_POLL_INTERVAL_SECONDS_ENV,
                    DEFAULT_POLL_INTERVAL_SECONDS,
                )
            ),
            max_attempts=_optional_int_env(
                "OZ_IN_FLIGHT_MAX_ATTEMPTS",
                DEFAULT_MAX_IN_FLIGHT_ATTEMPTS,
            ),
            max_age_seconds=_optional_int_env(
                "OZ_IN_FLIGHT_MAX_AGE_SECONDS",
                DEFAULT_MAX_IN_FLIGHT_AGE_SECONDS,
            ),
            process_open_model=(
                process_open_model
                if process_open_model is not None
                else _optional_bool_env(LOCAL_RUNTIME_PROCESS_OPEN_MODEL_ENV, True)
            ),
        )


def configure_local_backend_defaults(config: LocalRuntimeConfig) -> None:
    """Set local-friendly defaults without overriding explicit operator config."""
    os.environ.setdefault(BACKEND_ENV, BACKEND_OPEN_MODEL)
    os.environ.setdefault(
        OPEN_MODEL_RUN_STORE_DIR_ENV,
        str(config.open_model_run_store_dir),
    )


def build_local_state_store(config: LocalRuntimeConfig) -> FileStateStore:
    return FileStateStore(config.state_dir)


def build_local_webhook_wiring(
    *,
    body: bytes,
    store: StateStore,
) -> WebhookRuntimeWiring:
    return build_webhook_runtime_wiring(body=body, store=store)


def build_local_cron_wiring(
    *,
    store: StateStore,
    config: LocalRuntimeConfig,
) -> CronRuntimeWiring:
    if use_open_model_backend():
        retriever = build_open_model_backend()
    else:
        from oz_agent_sdk import OzAPI  # type: ignore[import-not-found]

        client = OzAPI(
            api_key=os.environ["WARP_API_KEY"],
            base_url=os.environ["WARP_API_BASE_URL"],
        )
        retriever = client.agent.runs

    return CronRuntimeWiring(
        store=store,
        retriever=retriever,
        handlers=build_workflow_handlers(),
        max_attempts=config.max_attempts,
        max_age_seconds=config.max_age_seconds,
    )


def run_local_drain_once(
    *,
    store: StateStore,
    config: LocalRuntimeConfig,
) -> list[DrainOutcome]:
    if not store.keys(RUN_STATE_KEY_PREFIX):
        return []
    wiring = build_local_cron_wiring(store=store, config=config)
    return run_cron_tick(
        store=wiring.store,
        retriever=wiring.retriever,
        handlers=wiring.handlers,
        max_attempts=wiring.max_attempts,
        max_age_seconds=wiring.max_age_seconds,
    )


WebhookWiringBuilder = Callable[[bytes], WebhookRuntimeWiring]
DrainRunner = Callable[[], list[DrainOutcome]]


class LocalRuntimeServer(ThreadingHTTPServer):
    """HTTP server carrying local runtime dependencies."""

    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        *,
        webhook_secret: str,
        store: StateStore,
        webhook_wiring_builder: WebhookWiringBuilder,
        drain_runner: DrainRunner,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.webhook_secret = webhook_secret
        self.store = store
        self.webhook_wiring_builder = webhook_wiring_builder
        self.drain_runner = drain_runner


class LocalRuntimeHandler(BaseHTTPRequestHandler):
    server: LocalRuntimeServer
    server_version = "RevealLocalRuntime/0.1"

    def do_GET(self) -> None:  # noqa: N802
        if self._path() == "/healthz":
            self._json_response(
                200,
                {
                    "status": "ok",
                    "runtime": "local",
                    "in_flight": len(self.server.store.keys(RUN_STATE_KEY_PREFIX)),
                },
            )
            return
        self._json_response(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self._path()
        if path in {"/webhook", "/api/webhook"}:
            self._handle_webhook()
            return
        if path == "/drain":
            self._handle_drain()
            return
        self._json_response(404, {"error": "not found"})

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _handle_webhook(self) -> None:
        length = int(self.headers.get("content-length", "0") or 0)
        body = self.rfile.read(length) if length > 0 else b""
        try:
            wiring = self.server.webhook_wiring_builder(body)
        except Exception as exc:
            logger.exception("Local webhook runtime wiring failed")
            self._json_response(500, {"error": f"local runtime not ready: {exc}"})
            return
        response = process_webhook_request(
            body=body,
            signature_header=self.headers.get(SIGNATURE_HEADER),
            event_header=self.headers.get(_EVENT_HEADER),
            delivery_id=self.headers.get(_DELIVERY_HEADER),
            secret=self.server.webhook_secret,
            builder_registry=wiring.builder_registry,
            runner=wiring.runner,
            config_factory=wiring.config_factory,
            store=wiring.store,
            sync_plan_approved=wiring.sync_plan_approved,
            sync_announce_ready_issue=wiring.sync_announce_ready_issue,
            sync_cancel_review_runs=wiring.sync_cancel_review_runs,
            triage_bot_author_allowlist_loader=wiring.triage_bot_author_allowlist_loader,
        )
        self._json_response(response.status, response.body)

    def _handle_drain(self) -> None:
        try:
            outcomes = self.server.drain_runner()
        except Exception as exc:
            logger.exception("Local drain failed")
            self._json_response(500, {"error": str(exc)})
            return
        self._json_response(200, summarize_drain_outcomes(outcomes))

    def _path(self) -> str:
        return urlparse(self.path).path.rstrip("/") or "/"

    def _json_response(self, status: int, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class LocalDaemon:
    """Owns the local HTTP server and background runtime loops."""

    def __init__(self, config: LocalRuntimeConfig) -> None:
        configure_local_backend_defaults(config)
        self.config = config
        self.store = build_local_state_store(config)
        self.stop_event = threading.Event()
        self.open_model_backend = self._build_local_open_model_backend()
        self.server = LocalRuntimeServer(
            (config.host, config.port),
            LocalRuntimeHandler,
            webhook_secret=resolve_local_webhook_secret(),
            store=self.store,
            webhook_wiring_builder=lambda body: build_local_webhook_wiring(
                body=body,
                store=self.store,
            ),
            drain_runner=self.drain_once,
        )
        self._threads: list[threading.Thread] = []

    def start_background_workers(self) -> None:
        self._threads.append(
            threading.Thread(
                target=self._drain_loop,
                name="local-runtime-drain",
                daemon=True,
            )
        )
        if self.open_model_backend is not None and self.config.process_open_model:
            self._threads.append(
                threading.Thread(
                    target=self._open_model_worker_loop,
                    name="local-runtime-open-model-worker",
                    daemon=True,
                )
            )
        for thread in self._threads:
            thread.start()

    def serve_forever(self) -> None:
        self.start_background_workers()
        self.server.serve_forever()

    def shutdown(self) -> None:
        self.stop_event.set()
        self.server.shutdown()
        self.server.server_close()

    def drain_once(self) -> list[DrainOutcome]:
        return run_local_drain_once(store=self.store, config=self.config)

    def process_open_model_once(self) -> str | None:
        if self.open_model_backend is None:
            return None
        return self.open_model_backend.process_next()

    def _drain_loop(self) -> None:
        while not self.stop_event.wait(self.config.poll_interval_seconds):
            try:
                outcomes = self.drain_once()
                if outcomes:
                    logger.info("local runtime drained %s run(s)", len(outcomes))
            except Exception:
                logger.exception("local runtime drain tick failed")

    def _open_model_worker_loop(self) -> None:
        assert self.open_model_backend is not None
        while not self.stop_event.wait(self.config.poll_interval_seconds):
            try:
                run_id = self.open_model_backend.process_next()
                if run_id is not None:
                    logger.info("local open-model worker processed %s", run_id)
            except Exception:
                logger.exception("local open-model worker tick failed")

    def _build_local_open_model_backend(self) -> FileOpenModelBackend | None:
        if not use_open_model_backend():
            return None
        if _optional_env(OPEN_MODEL_BACKEND_URL_ENV):
            return None
        return FileOpenModelBackend(self.config.open_model_run_store_dir)


__all__ = [
    "DEFAULT_LOCAL_STATE_DIR",
    "DEFAULT_OPEN_MODEL_RUN_STORE_DIR",
    "LOCAL_RUNTIME_POLL_INTERVAL_SECONDS_ENV",
    "LOCAL_RUNTIME_PROCESS_OPEN_MODEL_ENV",
    "LOCAL_RUNTIME_STATE_DIR_ENV",
    "LocalDaemon",
    "LocalRuntimeConfig",
    "LocalRuntimeHandler",
    "LocalRuntimeServer",
    "build_local_cron_wiring",
    "build_local_state_store",
    "build_local_webhook_wiring",
    "configure_local_backend_defaults",
    "resolve_local_webhook_secret",
    "run_local_drain_once",
]
