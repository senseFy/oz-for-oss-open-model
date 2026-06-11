"""Tests for ``core.cancel_runs``."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from . import conftest  # noqa: F401

from core.cancel_runs import cancel_in_flight_review_runs
from core.routing import WORKFLOW_REVIEW_PR
from core.state import InMemoryStateStore, RunState, load_run_state, save_run_state


class _ApiError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def _payload(*, full_name: str = "acme/widgets", pr_number: int = 42) -> dict[str, Any]:
    return {
        "action": "closed",
        "repository": {"full_name": full_name},
        "pull_request": {"number": pr_number, "state": "closed"},
    }


def _review_state(run_id: str, *, pr_number: int = 42, repo: str = "acme/widgets") -> RunState:
    return RunState(
        run_id=run_id,
        workflow=WORKFLOW_REVIEW_PR,
        repo=repo,
        installation_id=1234,
        payload_subset={"pr_number": pr_number},
    )


def _client_factory(pr_state: str) -> Any:
    # Minimal GitHub client stub: supports the live PR-state lookup and
    # leaves every other attribute missing so progress-comment updates
    # fail, exercising the best-effort path.
    def factory(_installation_id: int) -> Any:
        return SimpleNamespace(
            get_repo=lambda _full_name: SimpleNamespace(
                get_pull=lambda _number: SimpleNamespace(state=pr_state)
            )
        )

    return factory


class CancelInFlightReviewRunsTest(unittest.TestCase):
    def test_cancels_matching_run_and_keeps_others(self) -> None:
        store = InMemoryStateStore()
        save_run_state(store, _review_state("run-1"))
        save_run_state(store, _review_state("run-other-pr", pr_number=7))

        cancelled: list[str] = []

        outcome = cancel_in_flight_review_runs(
            store=store,
            canceller=cancelled.append,
            payload=_payload(),
            github_client_factory=_client_factory("closed"),
        )
        self.assertEqual(outcome["action"], "cancelled")
        self.assertEqual(outcome["cancelled_run_ids"], ["run-1"])
        self.assertEqual(outcome["failed_run_ids"], [])
        self.assertEqual(cancelled, ["run-1"])
        self.assertIsNone(load_run_state(store, "run-1"))
        self.assertIsNotNone(load_run_state(store, "run-other-pr"))

    def test_cancel_failure_keeps_state(self) -> None:
        store = InMemoryStateStore()
        save_run_state(store, _review_state("run-1"))

        def canceller(_run_id: str) -> None:
            raise _ApiError(400)

        outcome = cancel_in_flight_review_runs(
            store=store,
            canceller=canceller,
            payload=_payload(),
        )
        self.assertEqual(outcome["failed_run_ids"], ["run-1"])
        self.assertEqual(outcome["cancelled_run_ids"], [])
        self.assertIsNotNone(load_run_state(store, "run-1"))

    def test_pending_409_is_retried_once(self) -> None:
        store = InMemoryStateStore()
        save_run_state(store, _review_state("run-1"))

        attempts: list[str] = []
        sleeps: list[float] = []

        def canceller(run_id: str) -> None:
            attempts.append(run_id)
            if len(attempts) == 1:
                raise _ApiError(409)

        outcome = cancel_in_flight_review_runs(
            store=store,
            canceller=canceller,
            payload=_payload(),
            sleep=sleeps.append,
        )
        self.assertEqual(outcome["cancelled_run_ids"], ["run-1"])
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(sleeps), 1)
        self.assertIsNone(load_run_state(store, "run-1"))

    def test_noop_when_no_matching_runs(self) -> None:
        store = InMemoryStateStore()
        save_run_state(store, _review_state("run-1", repo="other/repo"))

        outcome = cancel_in_flight_review_runs(
            store=store,
            canceller=lambda _run_id: self.fail("should not cancel"),
            payload=_payload(),
        )
        self.assertEqual(outcome["action"], "noop")
        self.assertIsNotNone(load_run_state(store, "run-1"))

    def test_skips_cancellation_when_pr_no_longer_closed(self) -> None:
        # A stale ``closed`` delivery processed after a reopen must not
        # cancel the fresh review run dispatched for the reopened PR.
        store = InMemoryStateStore()
        save_run_state(store, _review_state("run-1"))

        outcome = cancel_in_flight_review_runs(
            store=store,
            canceller=lambda _run_id: self.fail("should not cancel"),
            payload=_payload(),
            github_client_factory=_client_factory("open"),
        )
        self.assertEqual(outcome["action"], "skipped")
        self.assertIn("no longer closed", outcome["reason"])
        self.assertIsNotNone(load_run_state(store, "run-1"))

    def test_skips_cancellation_when_state_lookup_fails(self) -> None:
        store = InMemoryStateStore()
        save_run_state(store, _review_state("run-1"))

        def factory(_installation_id: int) -> Any:
            raise RuntimeError("github outage")

        outcome = cancel_in_flight_review_runs(
            store=store,
            canceller=lambda _run_id: self.fail("should not cancel"),
            payload=_payload(),
            github_client_factory=factory,
        )
        self.assertEqual(outcome["action"], "skipped")
        self.assertIn("could not verify", outcome["reason"])
        self.assertIsNotNone(load_run_state(store, "run-1"))


if __name__ == "__main__":
    unittest.main()
