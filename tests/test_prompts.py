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
from workflows.create_implementation_from_issue import build_create_implementation_prompt
from workflows.create_spec_from_issue import build_create_spec_prompt
from workflows.review_pr import (
    _format_non_member_review_section,
    build_review_prompt_for_dispatch,
)
from workflows.verify_pr_comment import build_verification_prompt


class FetchContextCommandPromptTest(unittest.TestCase):
    def test_create_implementation_prompt_uses_bare_shared_skill_names(self) -> None:
        prompt = build_create_implementation_prompt(
            owner="acme",
            repo="widgets",
            issue_number=42,
            issue_title="Add retry",
            issue_labels=[],
            issue_assignees=[],
            spec_context_text="Spec body",
            triggering_comment_text="",
            target_branch="oz-agent/implement-issue-42",
            default_branch="main",
            implement_specs_skill_path="warpdotdev/common-skills:.agents/skills/implement-specs/SKILL.md",
            spec_driven_implementation_skill_path="warpdotdev/common-skills:.agents/skills/spec-driven-implementation/SKILL.md",
            implement_issue_skill_path=".agents/skills/implement-issue/SKILL.md",
            coauthor_directives="",
        )
        self.assertIn(
            "Use the shared implementation skills `implement-specs` and "
            "`spec-driven-implementation`",
            prompt,
        )
        self.assertNotIn("warpdotdev/common-skills", prompt)

    def test_create_spec_prompt_uses_bare_shared_skill_names(self) -> None:
        prompt = build_create_spec_prompt(
            owner="acme",
            repo="widgets",
            issue_number=42,
            issue_title="Add retry",
            issue_labels=[],
            issue_assignees=[],
            issue_body="Body",
            comments_text="",
            triggering_comment_text="",
            default_branch="main",
            branch_name="oz-agent/spec-issue-42",
            spec_driven_implementation_skill_path="warpdotdev/common-skills:.agents/skills/spec-driven-implementation/SKILL.md",
            write_product_spec_skill_path="warpdotdev/common-skills:.agents/skills/write-product-spec/SKILL.md",
            create_product_spec_skill_path=".agents/skills/create-product-spec/SKILL.md",
            write_tech_spec_skill_path="warpdotdev/common-skills:.agents/skills/write-tech-spec/SKILL.md",
            create_tech_spec_skill_path=".agents/skills/create-tech-spec/SKILL.md",
            coauthor_directives="",
        )
        self.assertIn(
            "Use the shared spec-first skill `spec-driven-implementation`",
            prompt,
        )
        self.assertIn("shared product-spec skill `write-product-spec`", prompt)
        self.assertIn("shared tech-spec skill `write-tech-spec`", prompt)
        self.assertNotIn("warpdotdev/common-skills", prompt)

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
            "python .agents/shared/scripts/fetch_github_context.py "
            "--repo acme/widgets pr --number 12",
            prompt,
        )
        self.assertIn(
            "python .agents/shared/scripts/fetch_github_context.py "
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
            "python .agents/shared/scripts/fetch_github_context.py "
            "--repo acme/widgets pr --number 12",
            prompt,
        )
        self.assertIn(
            "python .agents/shared/scripts/fetch_github_context.py "
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



class ReviewDispatchPromptNonMemberTest(unittest.TestCase):
    def _base_context(self) -> dict[str, object]:
        return {
            "owner": "acme",
            "repo": "widgets",
            "pr_number": 12,
            "pr_title": "feat: add widget",
            "pr_body": "Implements the widget flow.",
            "base_branch": "main",
            "head_branch": "feature",
            "trigger_source": "pull_request",
            "focus_line": "Perform a general review of the pull request.",
            "issue_line": "#100",
            "skill_name": "review-pr",
            "supplemental_skill_line": "Also apply security-review-pr.",
            "repo_local_section": "",
            "non_member_review_section": "",
            "pr_description_text": "PR description body",
            "pr_diff_text": "diff --git a/src/app.py b/src/app.py\n+++ b/src/app.py\n[NEW:1] print('hello')\n",
            "spec_context_text": "",
        }

    def test_prompt_includes_ownership_area_selection_instructions(self) -> None:
        context = self._base_context()
        context["non_member_review_section"] = _format_non_member_review_section(
            pr_author_login="contributor",
            is_non_member=True,
            ownership_areas_block=(
                "- MCP (Model Context Protocol)\n"
                "  owners: @peicodes, @vkodithala\n"
                "  matches: MCP server connections and resources"
            ),
            stakeholders_block="- * → @fallback-owner",
            ownership_areas_loaded=True,
        )
        prompt = build_review_prompt_for_dispatch(context)
        self.assertIn("Ownership Areas (from `warpdotdev/warp-ownership`)", prompt)
        self.assertIn("Fallback Stakeholders (from `.github/STAKEHOLDERS`)", prompt)
        self.assertIn("Use `.github/STAKEHOLDERS` only as the fallback source", prompt)
        self.assertIn("recommended_area", prompt)
        self.assertIn("Do NOT invent area names", prompt)
        self.assertIn("empty string `\"\"`", prompt)
        self.assertIn("- * → @fallback-owner", prompt)
        self.assertNotIn("exactly one bare GitHub login string", prompt)

    def test_prompt_references_shared_spec_alignment_skill(self) -> None:
        prompt = build_review_prompt_for_dispatch(self._base_context())
        self.assertIn("shared `check-impl-against-spec` guidance", prompt)

    def test_prompt_includes_stakeholders_fallback_instructions(self) -> None:
        context = self._base_context()
        context["non_member_review_section"] = _format_non_member_review_section(
            pr_author_login="contributor",
            is_non_member=True,
            stakeholders_block="- /docs/ → @docs-owner",
            ownership_areas_loaded=False,
        )
        prompt = build_review_prompt_for_dispatch(context)
        self.assertIn("Stakeholders (from `.github/STAKEHOLDERS`)", prompt)
        self.assertIn("recommended_reviewers", prompt)
        self.assertIn("exactly one bare GitHub login string", prompt)
        self.assertNotIn("Ownership Areas (from `warpdotdev/warp-ownership`)", prompt)


if __name__ == "__main__":
    unittest.main()
