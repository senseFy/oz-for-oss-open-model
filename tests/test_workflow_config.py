from __future__ import annotations

import unittest

from . import conftest  # noqa: F401

try:
    import yaml  # noqa: F401
except ModuleNotFoundError:
    _HAS_YAML = False
else:
    _HAS_YAML = True


@unittest.skipUnless(_HAS_YAML, "PyYAML is not installed")
class TriageWorkflowConfigTest(unittest.TestCase):
    def _load_config(self, text: str):
        from oz.workflow_config import load_triage_workflow_config_from_text

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


if __name__ == "__main__":
    unittest.main()
