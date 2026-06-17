"""Vercel serverless entrypoint for inbound GitHub webhooks."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler
from typing import Any

from core.signatures import SIGNATURE_HEADER
from runtime.common import WebhookResponse, process_webhook_request
from runtime.vercel import build_webhook_wiring, resolve_webhook_secret

logger = logging.getLogger(__name__)

# Header GitHub uses to communicate the event name. Lowercased so the
# handler can do a case-insensitive lookup against the dictionary
# returned by ``BaseHTTPRequestHandler.headers``.
_EVENT_HEADER = "x-github-event"
_DELIVERY_HEADER = "x-github-delivery"

# Backwards-compatible aliases for tests or downstream imports that reached
# into the old Vercel entrypoint module.
_resolve_secret = resolve_webhook_secret
_build_runtime_wiring = build_webhook_wiring


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel requires this exact symbol name.
    """Vercel-compatible request handler."""

    server_version = "OzForOSSWebhook/1.0"

    def do_POST(self) -> None:  # noqa: N802 - signature comes from BaseHTTPRequestHandler.
        try:
            secret = resolve_webhook_secret()
        except RuntimeError as exc:
            logger.error("%s", exc)
            self._respond(500, {"error": str(exc)})
            return
        length = int(self.headers.get("content-length", "0") or 0)
        body = self.rfile.read(length) if length > 0 else b""

        try:
            wiring = build_webhook_wiring(body=body)
        except Exception as exc:
            logger.exception("Webhook runtime wiring failed")
            self._respond(500, {"error": f"webhook runtime not ready: {exc}"})
            return

        response = process_webhook_request(
            body=body,
            signature_header=self.headers.get(SIGNATURE_HEADER),
            event_header=self.headers.get(_EVENT_HEADER),
            delivery_id=self.headers.get(_DELIVERY_HEADER),
            secret=secret,
            builder_registry=wiring.builder_registry,
            runner=wiring.runner,
            config_factory=wiring.config_factory,
            store=wiring.store,
            sync_plan_approved=wiring.sync_plan_approved,
            sync_announce_ready_issue=wiring.sync_announce_ready_issue,
            sync_cancel_review_runs=wiring.sync_cancel_review_runs,
            triage_bot_author_allowlist_loader=wiring.triage_bot_author_allowlist_loader,
        )
        self._respond(response.status, response.body)

    def do_GET(self) -> None:  # noqa: N802 - intentional override for readiness probes.
        self._respond(200, {"status": "ok"})

    def _respond(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


__all__ = [
    "WebhookResponse",
    "handler",
    "process_webhook_request",
]
