"""Eagerly cancel in-flight review runs when a pull request closes.

The webhook routes ``pull_request.closed`` to this fully-synchronous
path. The helper scans the in-flight KV records for review runs that
target the closed PR, cancels them via the Oz API, and deletes the KV
record on success so the cron poller never treats the cancellation as
a workflow failure. Cancel failures fail open: the record is left in
place and the cron drains the run with today's semantics.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Mapping

from .routing import WORKFLOW_REVIEW_PR
from .state import RunState, StateStore, delete_run_state, list_in_flight_runs
from .workflow_adapters import reconstruct_progress

logger = logging.getLogger(__name__)

# The cancel endpoint returns 409 while a run is still PENDING; one short
# retry covers the dispatch-to-queued transition without blocking the
# webhook for long.
_PENDING_RETRY_DELAY_SECONDS = 1.0
_PENDING_STATUS_CODE = 409

CANCELLED_PROGRESS_MESSAGE = (
    "I cancelled the in-progress review run because this pull request was closed."
)


def _status_code(exc: Exception) -> int:
    try:
        return int(getattr(exc, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _cancel_run(
    canceller: Callable[[str], Any],
    run_id: str,
    *,
    sleep: Callable[[float], None],
) -> bool:
    for attempt in range(2):
        try:
            canceller(run_id)
            return True
        except Exception as exc:
            if _status_code(exc) == _PENDING_STATUS_CODE and attempt == 0:
                sleep(_PENDING_RETRY_DELAY_SECONDS)
                continue
            logger.warning(
                "cancel-review-runs: failed to cancel run %s; leaving its "
                "in-flight record for the cron poller: %s",
                run_id,
                exc,
            )
            return False
    return False


def _complete_progress_comment(
    state: RunState,
    *,
    github_client_factory: Callable[[int], Any] | None,
) -> None:
    if github_client_factory is None:
        return
    try:
        client = github_client_factory(state.installation_id)
        repo_handle = client.get_repo(state.repo)
        progress = reconstruct_progress(
            repo_handle,
            state=state,
            workflow=WORKFLOW_REVIEW_PR,
        )
        progress.complete(CANCELLED_PROGRESS_MESSAGE)
    except Exception:
        logger.exception(
            "cancel-review-runs: failed to update progress comment for run %s",
            state.run_id,
        )


def _matches_pr(state: RunState, *, repo_full_name: str, pr_number: int) -> bool:
    if state.workflow != WORKFLOW_REVIEW_PR:
        return False
    if state.repo.lower() != repo_full_name.lower():
        return False
    try:
        return int((state.payload_subset or {}).get("pr_number") or 0) == pr_number
    except (TypeError, ValueError):
        return False


def cancel_in_flight_review_runs(
    *,
    store: StateStore,
    canceller: Callable[[str], Any],
    payload: Mapping[str, Any],
    github_client_factory: Callable[[int], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Cancel every in-flight review run targeting the closed PR.

    Returns a structured outcome the webhook surfaces in the 202
    response body:

    - ``{"action": "skipped", "reason": ...}`` when the payload is
      missing the repository slug or PR number.
    - ``{"action": "noop", ...}`` when no in-flight review run targets
      the PR (the common case).
    - ``{"action": "cancelled", "cancelled_run_ids": [...],
      "failed_run_ids": [...]}`` otherwise. Failed cancels keep their
      KV record so the cron poller drains them as before.
    """
    repo_payload = payload.get("repository") or {}
    full_name = str(
        repo_payload.get("full_name") or "" if isinstance(repo_payload, dict) else ""
    ).strip()
    pr_payload = payload.get("pull_request") or {}
    try:
        pr_number = int(
            (pr_payload.get("number") if isinstance(pr_payload, dict) else 0) or 0
        )
    except (TypeError, ValueError):
        pr_number = 0
    if "/" not in full_name or pr_number <= 0:
        return {
            "action": "skipped",
            "reason": "missing repository.full_name or pull_request.number",
        }

    matches = [
        state
        for state in list_in_flight_runs(store)
        if _matches_pr(state, repo_full_name=full_name, pr_number=pr_number)
    ]
    if not matches:
        return {
            "action": "noop",
            "reason": "no in-flight review runs",
            "pr_number": pr_number,
        }

    cancelled_run_ids: list[str] = []
    failed_run_ids: list[str] = []
    for state in matches:
        if not _cancel_run(canceller, state.run_id, sleep=sleep):
            failed_run_ids.append(state.run_id)
            continue
        delete_run_state(store, state.run_id)
        cancelled_run_ids.append(state.run_id)
        _complete_progress_comment(
            state, github_client_factory=github_client_factory
        )
    return {
        "action": "cancelled",
        "pr_number": pr_number,
        "cancelled_run_ids": cancelled_run_ids,
        "failed_run_ids": failed_run_ids,
    }


__all__ = [
    "CANCELLED_PROGRESS_MESSAGE",
    "cancel_in_flight_review_runs",
]
