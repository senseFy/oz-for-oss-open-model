from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from typing import Any, Mapping

from . import conftest  # noqa: F401

from core.dispatch import DispatchRequest
from core.poll_runs import WorkflowHandlers
from core.routing import WORKFLOW_REVIEW_PR
from core.signatures import expected_signature
from core.state import (
    InMemoryStateStore,
    RUN_STATE_KEY_PREFIX,
    RunState,
    load_run_state,
)
from runtime.common import (
    process_webhook_request,
    run_cron_tick,
    summarize_drain_outcomes,
)


_SECRET = "runtime-dry-run-secret"


class RuntimeCommonDryRunTest(unittest.TestCase):
    def test_signed_webhook_dispatch_can_be_drained_successfully(self) -> None:
        payload = {
            "action": "opened",
            "repository": {"full_name": "acme/widgets"},
            "installation": {"id": 1234},
            "pull_request": {
                "number": 42,
                "state": "open",
                "draft": False,
                "user": {"login": "carol", "type": "User"},
                "author_association": "MEMBER",
                "head": {"ref": "feature"},
                "base": {"ref": "main"},
            },
        }
        body = json.dumps(payload).encode("utf-8")
        signature = expected_signature(_SECRET, body)
        store = InMemoryStateStore()

        def builder(payload: Mapping[str, Any]) -> DispatchRequest:
            return DispatchRequest(
                workflow=WORKFLOW_REVIEW_PR,
                repo="acme/widgets",
                installation_id=1234,
                config_name=WORKFLOW_REVIEW_PR,
                title="PR review #42",
                skill_name="review-pr",
                prompt="review this pull request",
                payload_subset={"pr_number": 42},
            )

        runner_calls: list[dict[str, Any]] = []

        def runner(**kwargs: Any) -> Any:
            runner_calls.append(kwargs)
            return SimpleNamespace(run_id="runtime-run-1")

        config_factory_calls: list[tuple[str, str]] = []

        def config_factory(name: str, role: str) -> Mapping[str, Any]:
            config_factory_calls.append((name, role))
            return {"environment_id": "env-runtime", "name": name, "role": role}

        response = process_webhook_request(
            body=body,
            signature_header=signature,
            event_header="pull_request",
            delivery_id="delivery-runtime-1",
            secret=_SECRET,
            builder_registry={WORKFLOW_REVIEW_PR: builder},
            runner=runner,
            config_factory=config_factory,
            store=store,
        )

        self.assertEqual(response.status, 202)
        self.assertEqual(response.body["workflow"], WORKFLOW_REVIEW_PR)
        self.assertTrue(response.body["dispatched"])
        self.assertEqual(response.body["run_id"], "runtime-run-1")
        self.assertEqual(len(runner_calls), 1)
        self.assertEqual(runner_calls[0]["workflow"], WORKFLOW_REVIEW_PR)
        self.assertEqual(config_factory_calls, [(WORKFLOW_REVIEW_PR, "review-triage")])
        self.assertEqual(store.keys(RUN_STATE_KEY_PREFIX), [
            "oz-control-plane:in-flight:runtime-run-1"
        ])

        saved_state = load_run_state(store, "runtime-run-1")
        self.assertIsNotNone(saved_state)
        assert saved_state is not None
        self.assertEqual(saved_state.workflow, WORKFLOW_REVIEW_PR)
        self.assertEqual(saved_state.repo, "acme/widgets")
        self.assertEqual(saved_state.installation_id, 1234)
        self.assertEqual(saved_state.payload_subset, {"pr_number": 42})

        class Retriever:
            def retrieve(self, run_id: str) -> Any:
                self_run = SimpleNamespace(state="SUCCEEDED", run_id=run_id)
                return self_run

        loaded_artifacts: list[str] = []

        def artifact_loader(run_id: str) -> dict[str, Any]:
            loaded_artifacts.append(run_id)
            return {"verdict": "COMMENT", "summary": "dry-run review"}

        applied: list[dict[str, Any]] = []

        def result_applier(
            *, state: RunState, result: Mapping[str, Any], run: Any | None = None
        ) -> None:
            applied.append({"state": state, "result": dict(result), "run": run})

        outcomes = run_cron_tick(
            store=store,
            retriever=Retriever(),
            handlers={
                WORKFLOW_REVIEW_PR: WorkflowHandlers(
                    artifact_loader=artifact_loader,
                    result_applier=result_applier,
                )
            },
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].run_id, "runtime-run-1")
        self.assertEqual(outcomes[0].workflow, WORKFLOW_REVIEW_PR)
        self.assertEqual(outcomes[0].state, "SUCCEEDED")
        self.assertTrue(outcomes[0].applied)
        self.assertEqual(loaded_artifacts, ["runtime-run-1"])
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["state"].run_id, "runtime-run-1")
        self.assertEqual(
            applied[0]["result"],
            {"verdict": "COMMENT", "summary": "dry-run review"},
        )
        self.assertEqual(applied[0]["run"].run_id, "runtime-run-1")
        self.assertEqual(store.keys(RUN_STATE_KEY_PREFIX), [])
        self.assertEqual(
            summarize_drain_outcomes(outcomes),
            {
                "drained": 1,
                "applied": 1,
                "states": {"SUCCEEDED": 1},
                "outcomes": [
                    {
                        "run_id": "runtime-run-1",
                        "workflow": WORKFLOW_REVIEW_PR,
                        "state": "SUCCEEDED",
                        "applied": True,
                        "error": "",
                    }
                ],
            },
        )


if __name__ == "__main__":
    unittest.main()
