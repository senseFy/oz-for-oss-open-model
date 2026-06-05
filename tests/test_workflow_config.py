from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from . import conftest  # noqa: F401

from oz.workflow_config import (
    load_triage_bot_author_allowlist,
    load_triage_workflow_config_from_text,
)


class TriageWorkflowConfigTest(unittest.TestCase):
    def _load_config(self, text: str):
        return load_triage_workflow_config_from_text(text)

    def test_defaults_bot_author_allowlist_to_empty(self) -> None:
        config = self._load_config(
            "version: 1\n",
        )
        self.assertEqual(config.prior_triage_labels, frozenset({"triaged"}))
        self.assertEqual(config.bot_author_allowlist, frozenset())

    def test_parses_bot_author_allowlist(self) -> None:
        config = self._load_config(
            "\n".join(
                [
                    "version: 1",
                    "triage:",
                    "  prior_triage_labels:",
                    "    - triaged",
                    "  bot_author_allowlist:",
                    "    - warp-dev-github-integration[bot]",
                    "    - '@Trusted-Intake[Bot]'",
                    "",
                ]
            ),
        )
        self.assertEqual(
            config.bot_author_allowlist,
            frozenset(
                {
                    "warp-dev-github-integration[bot]",
                    "trusted-intake[bot]",
                }
            ),
        )

    def test_rejects_non_list_bot_author_allowlist(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "triage.bot_author_allowlist must be a list",
        ):
            self._load_config(
                "\n".join(
                    [
                        "version: 1",
                        "triage:",
                        "  bot_author_allowlist: warp-dev-github-integration[bot]",
                        "",
                    ]
                ),
            )

    def test_rejects_malformed_yaml(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Invalid YAML"):
            self._load_config("version: 1\ntriage: [")


class LoadTriageBotAuthorAllowlistTest(unittest.TestCase):
    def _call(self, *, config_text: str | None, fallback_workspace: Path) -> frozenset[str]:
        repo = MagicMock()
        repo.full_name = "acme/widgets"
        fetcher = MagicMock(return_value=config_text)
        return load_triage_bot_author_allowlist(
            repo,
            fallback_workspace=fallback_workspace,
            repo_text_fetcher=fetcher,
        )

    def test_uses_consuming_repo_config_when_present(self) -> None:
        config_text = "\n".join([
            "version: 1",
            "triage:",
            "  bot_author_allowlist:",
            "    - custom-bot[bot]",
            "",
        ])
        result = self._call(
            config_text=config_text,
            fallback_workspace=Path("/nonexistent"),
        )
        self.assertEqual(result, frozenset({"custom-bot[bot]"}))

    def test_falls_back_to_bundled_config_when_repo_config_missing(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        result = self._call(
            config_text=None,
            fallback_workspace=repo_root,
        )
        self.assertIn("warp-dev-github-integration[bot]", result)

    def test_raises_on_malformed_repo_config(self) -> None:
        with self.assertRaises(RuntimeError):
            self._call(
                config_text="version: 1\ntriage: [",
                fallback_workspace=Path("/nonexistent"),
            )


if __name__ == "__main__":
    unittest.main()
