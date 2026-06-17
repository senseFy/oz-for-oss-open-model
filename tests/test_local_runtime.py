from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from unittest.mock import patch

from . import conftest  # noqa: F401

from core.dispatch import DispatchRequest
from core.poll_runs import WorkflowHandlers
from core.routing import WORKFLOW_REVIEW_PR
from core.signatures import expected_signature
from core.state import InMemoryStateStore, RUN_STATE_KEY_PREFIX, RunState
from runtime.common import run_cron_tick
from runtime.local import LocalDaemon, LocalRuntimeConfig, LocalRuntimeHandler, LocalRuntimeServer
from runtime.types import WebhookRuntimeWiring


_SECRET = "local-runtime-secret"


def _http_request(
    method: str,
    host: str,
    port: int,
    path: str,
    *,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=dict(headers or {}))
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        return response.status, payload
    finally:
        connection.close()


class LocalRuntimeHTTPTest(unittest.TestCase):
    def test_webhook_healthz_and_manual_drain(self) -> None:
        store = InMemoryStateStore()
        applied: list[dict[str, Any]] = []

        def request_builder(payload: Mapping[str, Any]) -> DispatchRequest:
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

        def runner(**kwargs: Any) -> Any:
            return SimpleNamespace(run_id="local-run-1")

        def config_factory(name: str, role: str) -> Mapping[str, Any]:
            return {"name": name, "role": role}

        def webhook_wiring_builder(body: bytes) -> WebhookRuntimeWiring:
            return WebhookRuntimeWiring(
                builder_registry={WORKFLOW_REVIEW_PR: request_builder},
                runner=runner,
                config_factory=config_factory,
                store=store,
                sync_plan_approved=None,
                sync_announce_ready_issue=None,
                sync_cancel_review_runs=None,
                triage_bot_author_allowlist_loader=None,
            )

        class Retriever:
            def retrieve(self, run_id: str) -> Any:
                return SimpleNamespace(state="SUCCEEDED", run_id=run_id)

        def artifact_loader(run_id: str) -> dict[str, Any]:
            return {"verdict": "COMMENT", "summary": "local runtime dry run"}

        def result_applier(
            *, state: RunState, result: Mapping[str, Any], run: Any | None = None
        ) -> None:
            applied.append({"state": state, "result": dict(result), "run": run})

        def drain_runner():
            return run_cron_tick(
                store=store,
                retriever=Retriever(),
                handlers={
                    WORKFLOW_REVIEW_PR: WorkflowHandlers(
                        artifact_loader=artifact_loader,
                        result_applier=result_applier,
                    )
                },
            )

        server = LocalRuntimeServer(
            ("127.0.0.1", 0),
            LocalRuntimeHandler,
            webhook_secret=_SECRET,
            store=store,
            webhook_wiring_builder=webhook_wiring_builder,
            drain_runner=drain_runner,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            health = _http_request("GET", host, port, "/healthz")
            self.assertEqual(health[0], 200)
            self.assertEqual(health[1]["runtime"], "local")
            self.assertEqual(health[1]["in_flight"], 0)

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
            webhook = _http_request(
                "POST",
                host,
                port,
                "/webhook",
                body=body,
                headers={
                    "content-type": "application/json",
                    "x-github-event": "pull_request",
                    "x-github-delivery": "delivery-local-1",
                    "x-hub-signature-256": expected_signature(_SECRET, body),
                },
            )
            self.assertEqual(webhook[0], 202)
            self.assertEqual(webhook[1]["run_id"], "local-run-1")
            self.assertEqual(store.keys(RUN_STATE_KEY_PREFIX), [
                "oz-control-plane:in-flight:local-run-1"
            ])

            drain = _http_request("POST", host, port, "/drain")
            self.assertEqual(drain[0], 200)
            self.assertEqual(drain[1]["drained"], 1)
            self.assertEqual(drain[1]["applied"], 1)
            self.assertEqual(drain[1]["states"], {"SUCCEEDED": 1})
            self.assertEqual(store.keys(RUN_STATE_KEY_PREFIX), [])
            self.assertEqual(len(applied), 1)
            self.assertEqual(applied[0]["state"].run_id, "local-run-1")
            self.assertEqual(
                applied[0]["result"],
                {"verdict": "COMMENT", "summary": "local runtime dry run"},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

class LocalDaemonSmokeTest(unittest.TestCase):
    def test_daemon_healthz_starts_without_github_or_model_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ",
            {"OZ_GITHUB_WEBHOOK_SECRET": _SECRET},
            clear=True,
        ):
            root = Path(temp_dir)
            config = LocalRuntimeConfig(
                host="127.0.0.1",
                port=0,
                state_dir=root / "state",
                open_model_run_store_dir=root / "open-model-runs",
                poll_interval_seconds=0.05,
                process_open_model=False,
            )
            daemon = LocalDaemon(config)
            thread = threading.Thread(target=daemon.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = daemon.server.server_address
                status, payload = _http_request(
                    "GET",
                    host,
                    port,
                    "/healthz",
                )
                self.assertEqual(status, 200)
                self.assertEqual(payload["status"], "ok")
                self.assertEqual(payload["runtime"], "local")
                self.assertEqual(payload["in_flight"], 0)
            finally:
                daemon.shutdown()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
