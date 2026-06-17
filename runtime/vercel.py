"""Vercel runtime provider wiring."""

from __future__ import annotations

import logging
import os

from core.poll_runs import DEFAULT_MAX_IN_FLIGHT_AGE_SECONDS, DEFAULT_MAX_IN_FLIGHT_ATTEMPTS
from core.state import StateStore
from oz.backend import use_open_model_backend
from runtime.stores.upstash import build_upstash_state_store
from runtime.types import CronRuntimeWiring, WebhookRuntimeWiring
from runtime.wiring import (
    build_runner_and_config,
    build_webhook_runtime_wiring,
    build_workflow_handlers,
)

logger = logging.getLogger(__name__)


def resolve_webhook_secret() -> str:
    secret = os.environ.get("OZ_GITHUB_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "OZ_GITHUB_WEBHOOK_SECRET is not configured for this Vercel "
            "deployment. Webhooks cannot be verified."
        )
    return secret


def _allow_unauthenticated_cron() -> bool:
    raw = os.environ.get("OZ_ALLOW_UNAUTHENTICATED_CRON", "").strip().lower()
    return raw in {"1", "true", "yes", "local"}


def resolve_cron_secret() -> str | None:
    """Return the configured cron secret, failing closed by default."""
    secret = os.environ.get("CRON_SECRET", "").strip()
    if secret:
        return secret
    if _allow_unauthenticated_cron():
        return None
    raise RuntimeError(
        "CRON_SECRET is required for /api/cron. Set "
        "OZ_ALLOW_UNAUTHENTICATED_CRON=true only for local development."
    )


def optional_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; using default %s", name, raw, default)
        return default
    if value <= 0:
        logger.warning(
            "Ignoring non-positive %s=%r; using default %s",
            name,
            raw,
            default,
        )
        return default
    return value


def build_state_store() -> StateStore:
    """Build the Vercel production state store."""
    return build_upstash_state_store()


def build_webhook_wiring(*, body: bytes) -> WebhookRuntimeWiring:
    """Construct Vercel production wiring for one webhook delivery."""
    return build_webhook_runtime_wiring(
        body=body,
        store=build_state_store(),
    )


def build_cron_wiring() -> CronRuntimeWiring:
    """Construct Vercel production wiring for one cron drain tick."""
    store = build_state_store()
    if use_open_model_backend():
        from oz.open_model_backend import build_open_model_backend

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
        max_attempts=optional_positive_int_env(
            "OZ_IN_FLIGHT_MAX_ATTEMPTS",
            DEFAULT_MAX_IN_FLIGHT_ATTEMPTS,
        ),
        max_age_seconds=optional_positive_int_env(
            "OZ_IN_FLIGHT_MAX_AGE_SECONDS",
            DEFAULT_MAX_IN_FLIGHT_AGE_SECONDS,
        ),
    )


__all__ = [
    "build_cron_wiring",
    "build_state_store",
    "build_webhook_wiring",
    "build_workflow_handlers",
    "optional_positive_int_env",
    "resolve_cron_secret",
    "resolve_webhook_secret",
]
