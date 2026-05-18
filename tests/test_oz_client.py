from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from . import conftest  # noqa: F401
from oz.attachments import text_attachment
from oz.oz_client import dispatch_run, skill_file_path, skill_spec


def _write_skill(root: Path, name: str) -> Path:
    path = root / ".agents" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nname: test\n---\n", encoding="utf-8")
    return path


class SkillResolutionTest(unittest.TestCase):
    def test_skill_resolution_uses_workflow_repo_without_github_actions_env(self) -> None:
        with tempfile.TemporaryDirectory() as workflow_dir:
            workflow_root = Path(workflow_dir)
            _write_skill(workflow_root, "implement-specs")

            with patch.dict(os.environ, {}, clear=True), patch(
                "oz.oz_client._workflow_code_root",
                return_value=workflow_root,
            ):
                self.assertEqual(
                    skill_file_path("implement-specs"),
                    ".agents/skills/implement-specs/SKILL.md",
                )
                self.assertEqual(
                    skill_spec("implement-specs"),
                    "warpdotdev/oz-for-oss:.agents/skills/implement-specs/SKILL.md",
                )

    def test_github_actions_env_vars_do_not_override_workflow_skill(self) -> None:
        with tempfile.TemporaryDirectory() as workflow_dir, tempfile.TemporaryDirectory() as workspace_dir:
            workflow_root = Path(workflow_dir)
            workspace_root = Path(workspace_dir)
            _write_skill(workflow_root, "review-pr")
            _write_skill(workspace_root, "review-pr")

            with patch.dict(
                os.environ,
                {
                    "GITHUB_REPOSITORY": "acme/widgets",
                    "GITHUB_WORKSPACE": workspace_root.as_posix(),
                },
                clear=True,
            ), patch(
                "oz.oz_client._workflow_code_root",
                return_value=workflow_root,
            ):
                self.assertEqual(
                    skill_file_path("review-pr"),
                    ".agents/skills/review-pr/SKILL.md",
                )
                self.assertEqual(
                    skill_spec("review-pr"),
                    "warpdotdev/oz-for-oss:.agents/skills/review-pr/SKILL.md",
                )

    def test_workflow_code_repository_env_var_selects_skill_repo(self) -> None:
        with tempfile.TemporaryDirectory() as workflow_dir:
            workflow_root = Path(workflow_dir)
            _write_skill(workflow_root, "review-pr")

            with patch.dict(
                os.environ,
                {"WORKFLOW_CODE_REPOSITORY": "forks/oz-for-oss"},
                clear=True,
            ), patch(
                "oz.oz_client._workflow_code_root",
                return_value=workflow_root,
            ):
                self.assertEqual(
                    skill_spec("review-pr"),
                    "forks/oz-for-oss:.agents/skills/review-pr/SKILL.md",
                )


class _FakeAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(run_id="oz-run-1")


class _FakeClient:
    def __init__(self) -> None:
        self.agent = _FakeAgent()


class DispatchRunAttachmentTest(unittest.TestCase):
    def test_dispatch_run_includes_attachments_when_provided(self) -> None:
        client = _FakeClient()
        attachment = text_attachment(
            file_name="context.txt",
            text="hello from an attachment",
        )

        response = dispatch_run(
            prompt="prompt body",
            skill_name=None,
            title="Attachment test",
            config={"environment_id": "env", "name": "attachment-test"},
            attachments=[attachment],
            client=client,  # type: ignore[arg-type]
        )

        self.assertEqual(response.run_id, "oz-run-1")
        self.assertEqual(client.agent.calls[0]["attachments"], (attachment,))

    def test_dispatch_run_omits_attachments_when_empty(self) -> None:
        client = _FakeClient()

        dispatch_run(
            prompt="prompt body",
            skill_name=None,
            title="Attachment test",
            config={"environment_id": "env", "name": "attachment-test"},
            attachments=[],
            client=client,  # type: ignore[arg-type]
        )

        self.assertNotIn("attachments", client.agent.calls[0])


if __name__ == "__main__":
    unittest.main()
