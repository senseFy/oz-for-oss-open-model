from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from . import conftest  # noqa: F401

from core.routing import WORKFLOW_REVIEW_PR
from oz.attachments import text_attachment
from oz.backend import selected_review_backend, use_open_model_backend
from oz.open_model_backend import FileOpenModelBackend


class FakeChatClient:
    def __init__(self, payload):
        self.payload = payload
        self.config = SimpleNamespace(max_attachment_chars=50_000)
        self.messages = []

    def complete_json(self, *, messages):
        self.messages.append(messages)
        return dict(self.payload)


def _annotated_diff() -> str:
    return "\n".join(
        [
            "diff --git a/src/app.py b/src/app.py",
            "--- a/src/app.py",
            "+++ b/src/app.py",
            "@@ -1,1 +1,2 @@",
            "[OLD:1,NEW:1] print('ok')",
            "[NEW:2] print('bad')",
            "",
        ]
    )


class BackendSelectionTest(unittest.TestCase):
    def test_default_backend_is_oz(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(selected_review_backend(), "oz")
            self.assertFalse(use_open_model_backend())

    def test_open_model_backend_selection(self) -> None:
        with patch.dict(os.environ, {"REVIEW_AGENT_BACKEND": "open-model"}, clear=True):
            self.assertEqual(selected_review_backend(), "open-model")
            self.assertTrue(use_open_model_backend())


class FileOpenModelBackendTest(unittest.TestCase):
    def test_processes_review_run_and_stores_validated_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = FileOpenModelBackend(temp_dir)
            response = backend(
                prompt="Review the pull request.",
                title="PR review #1",
                config={"name": "review-pull-request"},
                skill="warpdotdev/common-skills:.agents/skills/review-pr/SKILL.md",
                team=True,
                workflow=WORKFLOW_REVIEW_PR,
                attachments=(
                    text_attachment("pr_diff.txt", _annotated_diff()),
                    text_attachment("pr_description.md", "Test PR"),
                ),
            )
            run = backend.retrieve(response.run_id)
            self.assertEqual(run.state, "QUEUED")

            client = FakeChatClient(
                {
                    "verdict": "REJECT",
                    "body": (
                        "## Overview\nFound a problem.\n\n"
                        "## Verdict\nFound: 0 critical, 1 important, 0 suggestions\n\n"
                        "**Request changes**"
                    ),
                    "comments": [
                        {
                            "path": "src/app.py",
                            "line": 2,
                            "side": "RIGHT",
                            "body": "important: explain the bug",
                        }
                    ],
                }
            )

            self.assertEqual(backend.process_next(client), response.run_id)
            run = backend.retrieve(response.run_id)
            self.assertEqual(run.state, "SUCCEEDED")
            artifact = backend.load_json_artifact(response.run_id, "review.json")
            self.assertEqual(artifact["verdict"], "REJECT")
            self.assertEqual(len(artifact["comments"]), 1)
            self.assertEqual(artifact["comments"][0]["path"], "src/app.py")
            self.assertEqual(artifact["comments"][0]["line"], 2)
            self.assertEqual(len(client.messages), 1)

    def test_invalid_inline_comments_are_dropped_before_artifact_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = FileOpenModelBackend(temp_dir)
            response = backend(
                prompt="Review the pull request.",
                title="PR review #1",
                config={},
                skill="review-pr",
                team=True,
                workflow=WORKFLOW_REVIEW_PR,
                attachments=(text_attachment("pr_diff.txt", _annotated_diff()),),
            )
            client = FakeChatClient(
                {
                    "verdict": "APPROVE",
                    "body": "## Verdict\nFound: 0 critical, 0 important, 0 suggestions\n\n**Approve**",
                    "comments": [
                        {
                            "path": "src/app.py",
                            "line": 999,
                            "side": "RIGHT",
                            "body": "not commentable",
                        }
                    ],
                }
            )

            backend.process_next(client)
            artifact = backend.load_json_artifact(response.run_id, "review.json")
            self.assertEqual(artifact["comments"], [])

    def test_rejects_non_review_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = FileOpenModelBackend(temp_dir)
            with self.assertRaisesRegex(RuntimeError, "supports only"):
                backend(
                    prompt="Create a spec.",
                    title="Spec",
                    config={},
                    skill="create-tech-spec",
                    team=True,
                    workflow="create-spec-from-issue",
                    attachments=(),
                )

    def test_cancel_marks_queued_run_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = FileOpenModelBackend(temp_dir)
            response = backend(
                prompt="Review.",
                title="PR review #1",
                config={},
                skill="review-pr",
                team=True,
                workflow=WORKFLOW_REVIEW_PR,
                attachments=(),
            )
            backend.cancel(response.run_id)
            self.assertEqual(backend.retrieve(response.run_id).state, "CANCELLED")


if __name__ == "__main__":
    unittest.main()
