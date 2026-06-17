"""Vercel cron entrypoint."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler
from typing import Any, Mapping

from core.poll_runs import (
    DEFAULT_MAX_IN_FLIGHT_AGE_SECONDS,
    DEFAULT_MAX_IN_FLIGHT_ATTEMPTS,
    DrainOutcome,
    WorkflowHandlers,
)
from core.state import StateStore
from runtime.common import (
    run_cron_tick as _run_common_cron_tick,
    summarize_drain_outcomes,
)
from runtime.vercel import (
    build_cron_wiring,
    build_state_store,
    build_workflow_handlers,
    optional_positive_int_env,
    resolve_cron_secret,
)

logger = logging.getLogger(__name__)

# Backwards-compatible aliases for tests or downstream imports that reached
# into the old Vercel entrypoint module.
_resolve_cron_secret = resolve_cron_secret
_optional_positive_int_env = optional_positive_int_env
_summarize = summarize_drain_outcomes


def run_cron_tick(
    *,
    store: StateStore,
    retriever: Any,
    handlers: Mapping[str, WorkflowHandlers] | None = None,
    max_attempts: int | None = None,
    max_age_seconds: float | None = None,
) -> list[DrainOutcome]:
    """Compatibility wrapper around platform-neutral drain orchestration."""
    return _run_common_cron_tick(
        store=store,
        retriever=retriever,
        handlers=handlers or build_workflow_handlers(),
        max_attempts=(
            DEFAULT_MAX_IN_FLIGHT_ATTEMPTS
            if max_attempts is None
            else max_attempts
        ),
        max_age_seconds=(
            DEFAULT_MAX_IN_FLIGHT_AGE_SECONDS
            if max_age_seconds is None
            else max_age_seconds
        ),
    )


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel requires this exact symbol name.
    server_version = "OzForOSSCron/1.0"

    def do_GET(self) -> None:  # noqa: N802 - signature comes from BaseHTTPRequestHandler.
        try:
            secret = resolve_cron_secret()
        except RuntimeError as exc:
            logger.error("%s", exc)
            self._respond(500, {"error": str(exc)})
            return
        if secret is not None:
            auth_header = self.headers.get("authorization", "")
            if auth_header != f"Bearer {secret}":
                self._respond(401, {"error": "invalid cron secret"})
                return
        try:
            wiring = build_cron_wiring()
            outcomes = _run_common_cron_tick(
                store=wiring.store,
                retriever=wiring.retriever,
                handlers=wiring.handlers,
                max_attempts=wiring.max_attempts,
                max_age_seconds=wiring.max_age_seconds,
            )
        except Exception as exc:
            logger.exception("Cron tick aborted")
            self._respond(500, {"error": str(exc)})
            return
        self._respond(200, summarize_drain_outcomes(outcomes))

    def _respond(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


__all__ = [
    "build_state_store",
    "build_workflow_handlers",
    "handler",
    "run_cron_tick",
]
