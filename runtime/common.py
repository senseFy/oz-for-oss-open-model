"""Platform-neutral webhook and drain orchestration."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Mapping

from core.dispatch import (
    DispatchRequest,
    DispatchResult,
    PromptBuilder,
    dispatch_run,
    evaluate_route,
)
from core.poll_runs import (
    DEFAULT_MAX_IN_FLIGHT_AGE_SECONDS,
    DEFAULT_MAX_IN_FLIGHT_ATTEMPTS,
    DrainOutcome,
    WorkflowHandlers,
    drain_in_flight_runs,
)
from core.routing import (
    RouteDecision,
    WORKFLOW_ANNOUNCE_READY_ISSUE,
    WORKFLOW_CANCEL_REVIEW_RUNS,
    WORKFLOW_PLAN_APPROVED,
    needs_triage_bot_author_allowlist,
    route_event,
)
from core.signatures import SignatureVerificationError, verify_signature
from core.state import StateStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebhookResponse:
    """Structured response returned after processing a webhook delivery."""

    status: int
    body: dict[str, Any]


def _run_synchronous_plan_approved(
    payload: Mapping[str, Any],
    *,
    sync_plan_approved: Callable[[Mapping[str, Any]], dict[str, Any] | None] | None,
) -> dict[str, Any] | None:
    if sync_plan_approved is None:
        return None
    return sync_plan_approved(payload)


def _run_synchronous_announce_ready_issue(
    payload: Mapping[str, Any],
    *,
    sync_announce_ready_issue: Callable[[Mapping[str, Any]], dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if sync_announce_ready_issue is None:
        return None
    return sync_announce_ready_issue(payload)


def process_webhook_request(
    *,
    body: bytes,
    signature_header: str | None,
    event_header: str | None,
    delivery_id: str | None,
    secret: str,
    builder_registry: Mapping[str, PromptBuilder] | None = None,
    runner: Callable[..., Any] | None = None,
    config_factory: Callable[[str, str], Mapping[str, Any]] | None = None,
    store: StateStore | None = None,
    sync_plan_approved: Callable[[Mapping[str, Any]], dict[str, Any] | None] | None = None,
    sync_announce_ready_issue: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
    sync_cancel_review_runs: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
    triage_bot_author_allowlist: Iterable[str] | None = None,
    triage_bot_author_allowlist_loader: Callable[[Mapping[str, Any]], Iterable[str]] | None = None,
) -> WebhookResponse:
    """Validate a webhook delivery and dispatch the configured workflow."""
    try:
        verify_signature(secret=secret, body=body, signature_header=signature_header)
    except SignatureVerificationError as exc:
        logger.warning("Rejected webhook delivery %s: %s", delivery_id, exc)
        return WebhookResponse(status=401, body={"error": "invalid signature"})

    if not isinstance(event_header, str) or not event_header.strip():
        return WebhookResponse(
            status=400,
            body={"error": "missing X-GitHub-Event header"},
        )
    event = event_header.strip().lower()

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return WebhookResponse(
            status=400,
            body={"error": f"invalid JSON body: {exc}"},
        )
    if not isinstance(payload, dict):
        return WebhookResponse(
            status=400,
            body={"error": "webhook payload must be a JSON object"},
        )

    route_triage_bot_author_allowlist: frozenset[str] = frozenset(
        triage_bot_author_allowlist or ()
    )
    if (
        triage_bot_author_allowlist_loader is not None
        and needs_triage_bot_author_allowlist(event, payload)
    ):
        try:
            route_triage_bot_author_allowlist = frozenset(
                triage_bot_author_allowlist_loader(payload)
            )
        except Exception as exc:
            logger.exception("Failed to load triage bot author allowlist")
            return WebhookResponse(
                status=500,
                body={
                    "event": event,
                    "workflow": None,
                    "reason": "failed to load triage bot author allowlist",
                    "delivery": delivery_id or "",
                    "error": f"route config failed: {exc}",
                },
            )

    decision: RouteDecision = route_event(
        event,
        payload,
        triage_bot_author_allowlist=route_triage_bot_author_allowlist,
    )
    base_body: dict[str, Any] = {
        "event": event,
        "workflow": decision.workflow,
        "reason": decision.reason,
        "delivery": delivery_id or "",
    }

    if decision.workflow is None:
        return WebhookResponse(status=202, body=base_body)

    if decision.workflow == WORKFLOW_PLAN_APPROVED:
        try:
            outcome = _run_synchronous_plan_approved(
                payload, sync_plan_approved=sync_plan_approved
            )
        except Exception as exc:
            logger.exception("Synchronous plan-approved run failed")
            return WebhookResponse(
                status=500,
                body={**base_body, "error": f"plan-approved path failed: {exc}"},
            )
        if outcome is not None:
            return WebhookResponse(
                status=202,
                body={**base_body, "plan_approved": outcome},
            )

    if decision.workflow == WORKFLOW_ANNOUNCE_READY_ISSUE:
        try:
            outcome = _run_synchronous_announce_ready_issue(
                payload, sync_announce_ready_issue=sync_announce_ready_issue
            )
        except Exception as exc:
            logger.exception("Synchronous announce-ready-issue run failed")
            return WebhookResponse(
                status=500,
                body={**base_body, "error": f"announce-ready-issue path failed: {exc}"},
            )
        if outcome is None:
            return WebhookResponse(status=202, body=base_body)
        return WebhookResponse(
            status=202,
            body={**base_body, "announce_ready_issue": outcome},
        )

    if decision.workflow == WORKFLOW_CANCEL_REVIEW_RUNS:
        if sync_cancel_review_runs is None:
            return WebhookResponse(status=202, body=base_body)
        try:
            outcome = sync_cancel_review_runs(payload)
        except Exception as exc:
            logger.exception("Synchronous cancel-review-runs failed")
            return WebhookResponse(
                status=500,
                body={**base_body, "error": f"cancel-review-runs path failed: {exc}"},
            )
        return WebhookResponse(
            status=202,
            body={**base_body, "cancel_review_runs": outcome},
        )

    if builder_registry is None or runner is None or config_factory is None or store is None:
        return WebhookResponse(status=202, body=base_body)

    try:
        request: DispatchRequest | None = evaluate_route(
            decision=decision,
            payload=payload,
            builder_registry=builder_registry,
        )
    except Exception as exc:
        logger.exception("Failed to evaluate route for delivery %s", delivery_id)
        return WebhookResponse(
            status=500,
            body={**base_body, "error": f"builder failed: {exc}"},
        )
    if request is None:
        return WebhookResponse(
            status=202,
            body={**base_body, "dispatched": False},
        )

    try:
        result: DispatchResult = dispatch_run(
            request=request,
            runner=runner,
            config_factory=config_factory,
            store=store,
        )
    except Exception as exc:
        logger.exception("Failed to dispatch run for delivery %s", delivery_id)
        return WebhookResponse(
            status=500,
            body={**base_body, "error": f"dispatch failed: {exc}"},
        )

    return WebhookResponse(
        status=202,
        body={
            **base_body,
            "dispatched": True,
            "run_id": result.run_id,
        },
    )


def run_cron_tick(
    *,
    store: StateStore,
    retriever: Any,
    handlers: Mapping[str, WorkflowHandlers],
    max_attempts: int | None = None,
    max_age_seconds: float | None = None,
) -> list[DrainOutcome]:
    """Process one scheduler tick using platform-neutral drain logic."""
    return drain_in_flight_runs(
        store=store,
        retriever=retriever,
        handlers=handlers,
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


def summarize_drain_outcomes(outcomes: list[DrainOutcome]) -> dict[str, Any]:
    """Return the stable JSON summary used by cron HTTP responses."""
    counters: dict[str, int] = {}
    for outcome in outcomes:
        counters[outcome.state] = counters.get(outcome.state, 0) + 1
    return {
        "drained": len(outcomes),
        "applied": sum(1 for outcome in outcomes if outcome.applied),
        "states": counters,
        "outcomes": [asdict(outcome) for outcome in outcomes],
    }


__all__ = [
    "WebhookResponse",
    "process_webhook_request",
    "run_cron_tick",
    "summarize_drain_outcomes",
]
