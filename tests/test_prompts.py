from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from github.GithubException import UnknownObjectException

from . import conftest  # noqa: F401

from workflows.respond_to_pr_comment import (
    build_pr_comment_prompt,
    gather_pr_comment_context,
)
from workflows.verify_pr_comment import build_verification_prompt


class FetchContextCommandPromptTest(unittest.TestCase):
    def test_respond_prompt_uses_global_repo_arg_before_subcommand(self) -> None:
        prompt = build_pr_comment_prompt(
            {
                "owner": "acme",
                "repo": "widgets",
                "pr_number": 12,
                "head_branch": "feature",
                "base_branch": "main",
                "pr_title": "feat: add widget",
                "requester": "alice",
                "trigger_kind": "conversation",
                "trigger_comment_id": 99,
                "spec_context_text": "No spec context.",
                "coauthor_directives": "",
            }
        )
        self.assertIn(
            "python .agents/skills/implement-specs/scripts/fetch_github_context.py "
            "--repo acme/widgets pr --number 12",
            prompt,
        )
        self.assertIn(
            "python .agents/skills/implement-specs/scripts/fetch_github_context.py "
            "--repo acme/widgets pr-diff --number 12",
            prompt,
        )
        self.assertNotIn("fetch_github_context.py pr --repo", prompt)

    def test_verify_prompt_uses_global_repo_arg_before_subcommand(self) -> None:
        prompt = build_verification_prompt(
            owner="acme",
            repo="widgets",
            pr_number=12,
            base_branch="main",
            head_branch="feature",
            trigger_comment_id=99,
            requester="alice",
            verification_skills_text="- verify-ui",
        )
        self.assertIn(
            "python .agents/skills/implement-specs/scripts/fetch_github_context.py "
            "--repo acme/widgets pr --number 12",
            prompt,
        )
        self.assertIn(
            "python .agents/skills/implement-specs/scripts/fetch_github_context.py "
            "--repo acme/widgets pr-diff --number 12",
            prompt,
        )
        self.assertNotIn("fetch_github_context.py pr --repo", prompt)


class PrCommentContextBranchSafetyTest(unittest.TestCase):
    def _pr(
        self,
        *,
        head_repo: str,
        base_repo: str,
        maintainer_can_modify: bool = False,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            head=SimpleNamespace(
                ref="feature",
                repo=SimpleNamespace(full_name=head_repo),
            ),
            base=SimpleNamespace(
                ref="main",
                repo=SimpleNamespace(full_name=base_repo),
            ),
            title="feat: add widget",
            maintainer_can_modify=maintainer_can_modify,
        )

    def test_context_allows_push_for_existing_same_repo_branch(self) -> None:
        github = MagicMock()
        github.get_git_ref.return_value = object()
        pr = self._pr(head_repo="acme/widgets", base_repo="acme/widgets")

        with patch(
            "workflows.respond_to_pr_comment.resolve_spec_context_for_pr_via_api",
            return_value={"spec_entries": []},
        ):
            context = gather_pr_comment_context(
                github,
                owner="acme",
                repo="widgets",
                pr_number=12,
                trigger_kind="conversation",
                trigger_comment_id=99,
                requester="alice",
                event={
                    "comment": {
                        "author_association": "MEMBER",
                        "user": {"login": "alice"},
                    }
                },
                pr=pr,
            )

        self.assertFalse(context["is_cross_repository"])
        self.assertTrue(context["head_branch_exists_in_base"])
        self.assertTrue(context["can_push_to_head_branch"])
        self.assertEqual(context["branch_strategy"], "push-head")
        self.assertEqual(context["agent_push_repo_full_name"], "acme/widgets")
        self.assertEqual(context["agent_push_branch"], "feature")

    def test_context_uses_fallback_branch_for_fork_without_maintainer_modify(self) -> None:
        github = MagicMock()
        github.get_git_ref.return_value = object()
        pr = self._pr(head_repo="contributor/widgets", base_repo="acme/widgets")

        with patch(
            "workflows.respond_to_pr_comment.resolve_spec_context_for_pr_via_api",
            return_value={"spec_entries": []},
        ):
            context = gather_pr_comment_context(
                github,
                owner="acme",
                repo="widgets",
                pr_number=12,
                trigger_kind="conversation",
                trigger_comment_id=99,
                requester="alice",
                event={
                    "comment": {
                        "author_association": "MEMBER",
                        "user": {"login": "alice"},
                    }
                },
                pr=pr,
            )

        self.assertTrue(context["is_cross_repository"])
        self.assertTrue(context["head_branch_exists_in_base"])
        self.assertFalse(context["can_push_to_head_branch"])
        self.assertEqual(context["branch_strategy"], "fallback-pr-to-fork")
        self.assertEqual(context["agent_push_repo_full_name"], "acme/widgets")
        self.assertEqual(context["agent_push_branch"], "oz-agent/respond-pr-12")
        self.assertEqual(context["fallback_pr_base_repo_full_name"], "contributor/widgets")
        self.assertEqual(context["fallback_pr_base_branch"], "feature")
        self.assertEqual(context["fallback_pr_head"], "acme:oz-agent/respond-pr-12")
        self.assertTrue(context["trigger_actor_is_trusted"])

    def test_context_pushes_to_fork_head_when_maintainers_can_modify(self) -> None:
        github = MagicMock()
        github.get_git_ref.return_value = object()
        pr = self._pr(
            head_repo="contributor/widgets",
            base_repo="acme/widgets",
            maintainer_can_modify=True,
        )

        with patch(
            "workflows.respond_to_pr_comment.resolve_spec_context_for_pr_via_api",
            return_value={"spec_entries": []},
        ):
            context = gather_pr_comment_context(
                github,
                owner="acme",
                repo="widgets",
                pr_number=12,
                trigger_kind="conversation",
                trigger_comment_id=99,
                requester="alice",
                event={
                    "comment": {
                        "author_association": "MEMBER",
                        "user": {"login": "alice"},
                    }
                },
                pr=pr,
            )

        self.assertTrue(context["is_cross_repository"])
        self.assertTrue(context["maintainer_can_modify"])
        self.assertTrue(context["can_push_to_head_branch"])
        self.assertEqual(context["branch_strategy"], "push-head")
        self.assertEqual(context["agent_push_repo_full_name"], "contributor/widgets")
        self.assertEqual(context["agent_push_branch"], "feature")

    def test_context_blocks_push_when_branch_would_be_created(self) -> None:
        github = MagicMock()
        github.get_git_ref.side_effect = UnknownObjectException(404, {}, {})
        pr = self._pr(head_repo="acme/widgets", base_repo="acme/widgets")

        with patch(
            "workflows.respond_to_pr_comment.resolve_spec_context_for_pr_via_api",
            return_value={"spec_entries": []},
        ):
            context = gather_pr_comment_context(
                github,
                owner="acme",
                repo="widgets",
                pr_number=12,
                trigger_kind="conversation",
                trigger_comment_id=99,
                requester="alice",
                event={},
                pr=pr,
            )

        self.assertFalse(context["is_cross_repository"])
        self.assertFalse(context["head_branch_exists_in_base"])
        self.assertFalse(context["can_push_to_head_branch"])
        self.assertEqual(context["branch_strategy"], "blocked")


class PrCommentPromptBranchStrategyTest(unittest.TestCase):
    def _context(self) -> dict[str, object]:
        return {
            "owner": "acme",
            "repo": "widgets",
            "pr_number": 12,
            "head_branch": "feature",
            "head_repo_full_name": "acme/widgets",
            "base_branch": "main",
            "base_repo_full_name": "acme/widgets",
            "pr_title": "feat: add widget",
            "requester": "alice",
            "trigger_kind": "conversation",
            "trigger_comment_id": 99,
            "spec_context_text": "No spec context.",
            "coauthor_directives": "",
            "branch_strategy": "push-head",
            "agent_push_repo_full_name": "acme/widgets",
            "agent_push_branch": "feature",
        }

    def test_direct_fork_prompt_targets_fork_head_branch(self) -> None:
        context = self._context()
        context.update(
            {
                "head_repo_full_name": "contributor/widgets",
                "base_repo_full_name": "acme/widgets",
                "agent_push_repo_full_name": "contributor/widgets",
            }
        )

        prompt = build_pr_comment_prompt(context)

        self.assertIn("maintainers are allowed to modify the fork head branch", prompt)
        self.assertIn("push to `contributor/widgets:feature`", prompt)
        self.assertIn("Do not push a same-named branch to `acme/widgets`", prompt)

    def test_fallback_prompt_requires_metadata_for_follow_up_pr(self) -> None:
        context = self._context()
        context.update(
            {
                "head_repo_full_name": "contributor/widgets",
                "base_repo_full_name": "acme/widgets",
                "branch_strategy": "fallback-pr-to-fork",
                "agent_push_repo_full_name": "acme/widgets",
                "agent_push_branch": "oz-agent/respond-pr-12",
                "fallback_pr_base_repo_full_name": "contributor/widgets",
                "fallback_pr_base_branch": "feature",
                "fallback_pr_head": "acme:oz-agent/respond-pr-12",
            }
        )

        prompt = build_pr_comment_prompt(context)

        self.assertIn("maintainers cannot modify the fork head branch", prompt)
        self.assertIn("Do not push to `contributor/widgets:feature`", prompt)
        self.assertIn("Create or reuse branch `oz-agent/respond-pr-12`", prompt)
        self.assertIn(
            "fetch `contributor/widgets:feature` and make sure `oz-agent/respond-pr-12` starts from that fork head commit",
            prompt,
        )
        self.assertIn("follow-up PR from `acme:oz-agent/respond-pr-12`", prompt)
        self.assertIn("use `oz-agent/respond-pr-12` exactly", prompt)


if __name__ == "__main__":
    unittest.main()
