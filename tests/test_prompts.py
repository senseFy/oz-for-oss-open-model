from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from github.GithubException import UnknownObjectException

from . import conftest  # noqa: F401
from workflows.respond_to_pr_comment import gather_pr_comment_context


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



if __name__ == "__main__":
    unittest.main()
