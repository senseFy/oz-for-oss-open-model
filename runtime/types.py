"""Typed construction records shared by runtime provider adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from core.dispatch import AgentRunner, PromptBuilder
from core.poll_runs import RunRetriever, WorkflowHandlers
from core.state import StateStore


@dataclass(frozen=True)
class WebhookRuntimeWiring:
    """Production dependencies needed to process one webhook delivery."""

    builder_registry: Mapping[str, PromptBuilder]
    runner: AgentRunner
    config_factory: Callable[[str, str], Mapping[str, Any]]
    store: StateStore
    sync_plan_approved: Callable[[Mapping[str, Any]], dict[str, Any] | None] | None
    sync_announce_ready_issue: Callable[[Mapping[str, Any]], dict[str, Any]] | None
    sync_cancel_review_runs: Callable[[Mapping[str, Any]], dict[str, Any]] | None
    triage_bot_author_allowlist_loader: Callable[
        [Mapping[str, Any]], Iterable[str]
    ] | None


@dataclass(frozen=True)
class CronRuntimeWiring:
    """Production dependencies needed to process one drain tick."""

    store: StateStore
    retriever: RunRetriever
    handlers: Mapping[str, WorkflowHandlers]
    max_attempts: int
    max_age_seconds: int


__all__ = ["CronRuntimeWiring", "WebhookRuntimeWiring"]
