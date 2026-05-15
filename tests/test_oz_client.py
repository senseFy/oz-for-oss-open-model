from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import conftest  # noqa: F401

from oz.oz_client import skill_file_path, skill_spec


def _write_skill(root: Path, name: str) -> Path:
    path = root / ".agents" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nname: test\n---\n", encoding="utf-8")
    return path


class SkillResolutionTest(unittest.TestCase):
    def test_common_skill_resolution_uses_common_skills_repo_without_local_file(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                skill_file_path("implement-specs"),
                ".agents/skills/implement-specs/SKILL.md",
            )
            self.assertEqual(
                skill_spec("implement-specs"),
                "warpdotdev/common-skills:.agents/skills/implement-specs/SKILL.md",
            )

    def test_local_skill_resolution_uses_workflow_repo_without_github_actions_env(self) -> None:
        with tempfile.TemporaryDirectory() as workflow_dir:
            workflow_root = Path(workflow_dir)
            _write_skill(workflow_root, "implement-issue")

            with patch.dict(os.environ, {}, clear=True), patch(
                "oz.oz_client._workflow_code_root",
                return_value=workflow_root,
            ):
                self.assertEqual(
                    skill_file_path("implement-issue"),
                    ".agents/skills/implement-issue/SKILL.md",
                )
                self.assertEqual(
                    skill_spec("implement-issue"),
                    "warpdotdev/oz-for-oss:.agents/skills/implement-issue/SKILL.md",
                )

    def test_github_actions_env_vars_do_not_override_workflow_skill(self) -> None:
        with tempfile.TemporaryDirectory() as workflow_dir, tempfile.TemporaryDirectory() as workspace_dir:
            workflow_root = Path(workflow_dir)
            workspace_root = Path(workspace_dir)
            _write_skill(workflow_root, "implement-issue")
            _write_skill(workspace_root, "implement-issue")

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
                    skill_file_path("implement-issue"),
                    ".agents/skills/implement-issue/SKILL.md",
                )
                self.assertEqual(
                    skill_spec("implement-issue"),
                    "warpdotdev/oz-for-oss:.agents/skills/implement-issue/SKILL.md",
                )

    def test_workflow_code_repository_env_var_selects_skill_repo(self) -> None:
        with tempfile.TemporaryDirectory() as workflow_dir:
            workflow_root = Path(workflow_dir)
            _write_skill(workflow_root, "implement-issue")

            with patch.dict(
                os.environ,
                {"WORKFLOW_CODE_REPOSITORY": "forks/oz-for-oss"},
                clear=True,
            ), patch(
                "oz.oz_client._workflow_code_root",
                return_value=workflow_root,
            ):
                self.assertEqual(
                    skill_spec("implement-issue"),
                    "forks/oz-for-oss:.agents/skills/implement-issue/SKILL.md",
                )

    def test_common_skills_repository_env_var_selects_common_skill_repo(self) -> None:
        with patch.dict(
            os.environ,
            {"COMMON_SKILLS_REPOSITORY": "forks/common-skills"},
            clear=True,
        ):
            self.assertEqual(
                skill_spec("review-pr"),
                "forks/common-skills:.agents/skills/review-pr/SKILL.md",
            )


if __name__ == "__main__":
    unittest.main()
