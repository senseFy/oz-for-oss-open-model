from __future__ import annotations

import base64
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from . import conftest  # noqa: F401


class CreateImplementationApplyTest(unittest.TestCase):
    def _context(self) -> dict[str, object]:
        return {
            "owner": "acme",
            "repo": "widgets",
            "issue_number": 12,
            "target_branch": "oz-agent/implement-issue-12",
            "default_branch": "main",
            "issue_title": "Add retries",
            "issue_labels": [],
            "requester": "alice",
            "selected_spec_pr_number": 0,
            "selected_spec_pr_url": "",
            "has_existing_implementation_pr": False,
        }

    def test_rejects_sibling_branch_override(self) -> None:
        from core.workflows.create_implementation_from_issue import (
            apply_create_implementation_result,
        )

        progress = MagicMock()
        run_created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
        run = SimpleNamespace(run_id="run-1", created_at=run_created_at)
        metadata = {
            "branch_name": "oz-agent/implement-issue-123",
            "pr_title": "feat: add retries",
            "pr_summary": "Closes #12\n\nSummary",
        }

        with patch(
            "core.workflows.create_implementation_from_issue.branch_updated_since",
            return_value=False,
        ) as branch_updated_since:
            apply_create_implementation_result(
                MagicMock(),
                context=self._context(),
                run=run,
                result=metadata,
                progress=progress,
            )

        branch_updated_since.assert_called_once()
        self.assertEqual(
            branch_updated_since.call_args.args[3],
            "oz-agent/implement-issue-12",
        )

    def test_accepts_delimiter_bounded_branch_override_and_uses_cushion(self) -> None:
        from core.workflows.create_implementation_from_issue import (
            apply_create_implementation_result,
        )

        progress = MagicMock()
        run_created_at = datetime(2026, 4, 30, 12, 0)
        run = SimpleNamespace(run_id="run-1", created_at=run_created_at)
        metadata = {
            "branch_name": "oz-agent/implement-issue-12-add-retries",
            "pr_title": "feat: add retries",
            "pr_summary": "Closes #12\n\nSummary",
        }

        with patch(
            "core.workflows.create_implementation_from_issue.branch_updated_since",
            return_value=False,
        ) as branch_updated_since:
            apply_create_implementation_result(
                MagicMock(),
                context=self._context(),
                run=run,
                result=metadata,
                progress=progress,
            )

        branch_updated_since.assert_called_once()
        self.assertEqual(
            branch_updated_since.call_args.args[3],
            "oz-agent/implement-issue-12-add-retries",
        )
        self.assertEqual(
            branch_updated_since.call_args.kwargs["created_after"],
            run_created_at.replace(tzinfo=timezone.utc) - timedelta(minutes=1),
        )


class CreateImplementationTriggeringCommentTest(unittest.TestCase):
    """The implementation run must carry the triggering comment forward,
    matching the triage and spec workflows."""

    def _triggering_attachment(self, context: dict[str, object]) -> str:
        from core.workflows.create_implementation_from_issue import (
            create_implementation_context_attachments,
        )

        attachment = next(
            a
            for a in create_implementation_context_attachments(context)
            if a["file_name"] == "triggering_comment.md"
        )
        return base64.b64decode(attachment["data"]).decode("utf-8")

    def test_comment_forwarded_to_attachment_and_prompt(self) -> None:
        from core.workflows.create_implementation_from_issue import (
            build_create_implementation_prompt,
        )

        comment = "@alice commented:\nimplement but skip the migration"
        self.assertEqual(
            self._triggering_attachment(
                {"spec_context_text": "Spec body", "triggering_comment_text": comment}
            ),
            comment,
        )

        prompt = build_create_implementation_prompt(
            owner="acme",
            repo="widgets",
            issue_number=12,
            issue_title="Add retries",
            issue_labels=["ready-to-implement"],
            issue_assignees=["oz-agent"],
            spec_context_text="Spec body",
            triggering_comment_text=comment,
            target_branch="oz-agent/implement-issue-12",
            default_branch="main",
            implement_specs_skill_path="a",
            spec_driven_implementation_skill_path="b",
            implement_issue_skill_path="c",
            coauthor_directives="",
        )
        self.assertIn("triggering_comment.md", prompt)

    def test_missing_comment_uses_none_placeholder(self) -> None:
        self.assertEqual(
            self._triggering_attachment({"spec_context_text": "Spec body"}),
            "- None",
        )


class CreateSpecApplyTest(unittest.TestCase):
    def test_branch_updated_since_uses_one_minute_cushion(self) -> None:
        from core.workflows.create_spec_from_issue import apply_create_spec_result

        progress = MagicMock()
        run_created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
        run = SimpleNamespace(run_id="run-1", created_at=run_created_at)

        with patch(
            "core.workflows.create_spec_from_issue.branch_updated_since",
            return_value=False,
        ) as branch_updated_since:
            apply_create_spec_result(
                MagicMock(),
                context={
                    "owner": "acme",
                    "repo": "widgets",
                    "issue_number": 12,
                    "branch_name": "oz-agent/spec-issue-12",
                    "default_branch": "main",
                    "issue_title": "Add retries",
                    "requester": "alice",
                },
                run=run,
                result={
                    "pr_title": "spec: add retries",
                    "pr_summary": "Related issue: #12",
                },
                progress=progress,
            )

        branch_updated_since.assert_called_once()
        self.assertEqual(
            branch_updated_since.call_args.kwargs["created_after"],
            run_created_at - timedelta(minutes=1),
        )


class RespondToPrCommentApplyTest(unittest.TestCase):
    def _context(self) -> dict[str, object]:
        return {
            "owner": "acme",
            "repo": "widgets",
            "pr_number": 7,
            "head_branch": "feature",
            "head_repo_full_name": "acme/widgets",
            "base_repo_full_name": "acme/widgets",
            "branch_strategy": "push-head",
            "agent_push_repo_full_name": "acme/widgets",
            "agent_push_branch": "feature",
            "requester": "alice",
        }

    def test_direct_fork_push_checks_head_repo_branch(self) -> None:
        from core.workflows.respond_to_pr_comment import apply_pr_comment_result

        base_repo = MagicMock()
        base_repo.get_pull.return_value = MagicMock()
        fork_repo = MagicMock()
        client = MagicMock()
        client.get_repo.return_value = fork_repo
        progress = MagicMock()
        run_created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
        run = SimpleNamespace(run_id="run-1", created_at=run_created_at)
        context = self._context()
        context.update(
            {
                "head_repo_full_name": "contributor/widgets",
                "base_repo_full_name": "acme/widgets",
                "agent_push_repo_full_name": "contributor/widgets",
            }
        )

        with patch(
            "core.workflows.respond_to_pr_comment.branch_updated_since",
            return_value=True,
        ) as branch_updated_since, patch(
            "core.workflows.respond_to_pr_comment.try_load_pr_metadata_artifact",
            return_value=None,
        ), patch(
            "core.workflows.respond_to_pr_comment.try_load_resolved_review_comments_artifact",
            return_value=[],
        ):
            apply_pr_comment_result(
                base_repo,
                context=context,
                run=run,
                client=client,
                progress=progress,
            )

        client.get_repo.assert_called_once_with("contributor/widgets")
        branch_updated_since.assert_called_once()
        self.assertIs(branch_updated_since.call_args.args[0], fork_repo)
        self.assertEqual(branch_updated_since.call_args.args[1], "contributor")
        self.assertEqual(branch_updated_since.call_args.args[2], "widgets")
        self.assertEqual(branch_updated_since.call_args.args[3], "feature")
        progress.complete.assert_called_once()
        self.assertIn("I pushed changes to this PR", progress.complete.call_args.args[0])

    def test_fallback_strategy_opens_pr_against_fork_branch(self) -> None:
        from core.workflows.respond_to_pr_comment import apply_pr_comment_result

        base_repo = MagicMock()
        base_repo.get_pull.return_value = MagicMock()
        fork_repo = MagicMock()
        fork_repo.create_pull.return_value = SimpleNamespace(
            html_url="https://github.com/contributor/widgets/pull/3"
        )
        client = MagicMock()
        client.get_repo.return_value = fork_repo
        progress = MagicMock()
        run_created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
        run = SimpleNamespace(run_id="run-1", created_at=run_created_at)
        context = self._context()
        context.update(
            {
                "head_repo_full_name": "contributor/widgets",
                "base_repo_full_name": "acme/widgets",
                "branch_strategy": "fallback-pr-to-fork",
                "agent_push_repo_full_name": "acme/widgets",
                "agent_push_branch": "oz-agent/respond-pr-7",
                "fallback_pr_base_repo_full_name": "contributor/widgets",
                "fallback_pr_base_branch": "feature",
                "fallback_pr_head": "acme:oz-agent/respond-pr-7",
            }
        )
        metadata = {
            "branch_name": "oz-agent/respond-pr-7",
            "pr_title": "fix: handle review feedback",
            "pr_summary": "Summary",
        }

        with patch(
            "core.workflows.respond_to_pr_comment.branch_updated_since",
            return_value=True,
        ) as branch_updated_since, patch(
            "core.workflows.respond_to_pr_comment.try_load_resolved_review_comments_artifact",
            return_value=[],
        ):
            apply_pr_comment_result(
                base_repo,
                context=context,
                run=run,
                result=metadata,
                client=client,
                progress=progress,
            )

        branch_updated_since.assert_called_once()
        self.assertIs(branch_updated_since.call_args.args[0], base_repo)
        self.assertEqual(branch_updated_since.call_args.args[3], "oz-agent/respond-pr-7")
        client.get_repo.assert_called_once_with("contributor/widgets")
        fork_repo.get_pulls.assert_called_once_with(
            state="open",
            head="acme:oz-agent/respond-pr-7",
            base="feature",
        )
        fork_repo.create_pull.assert_called_once_with(
            title="fix: handle review feedback",
            head="acme:oz-agent/respond-pr-7",
            base="feature",
            body="Summary",
            draft=False,
        )
        progress.complete.assert_called_once()
        self.assertIn("follow-up PR", progress.complete.call_args.args[0])
        self.assertIn(
            "`contributor/widgets:feature`",
            progress.complete.call_args.args[0],
        )

    def test_fallback_strategy_updates_existing_pr_against_fork_branch(self) -> None:
        from core.workflows.respond_to_pr_comment import apply_pr_comment_result

        base_repo = MagicMock()
        base_repo.get_pull.return_value = MagicMock()
        existing_pr = MagicMock(html_url="https://github.com/contributor/widgets/pull/3")
        fork_repo = MagicMock()
        fork_repo.get_pulls.return_value = [existing_pr]
        client = MagicMock()
        client.get_repo.return_value = fork_repo
        progress = MagicMock()
        run_created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
        run = SimpleNamespace(run_id="run-1", created_at=run_created_at)
        context = self._context()
        context.update(
            {
                "head_repo_full_name": "contributor/widgets",
                "base_repo_full_name": "acme/widgets",
                "branch_strategy": "fallback-pr-to-fork",
                "agent_push_repo_full_name": "acme/widgets",
                "agent_push_branch": "oz-agent/respond-pr-7",
                "fallback_pr_base_repo_full_name": "contributor/widgets",
                "fallback_pr_base_branch": "feature",
                "fallback_pr_head": "acme:oz-agent/respond-pr-7",
            }
        )
        metadata = {
            "branch_name": "oz-agent/respond-pr-7",
            "pr_title": "fix: handle review feedback",
            "pr_summary": "Updated summary",
        }

        with patch(
            "core.workflows.respond_to_pr_comment.branch_updated_since",
            return_value=True,
        ) as branch_updated_since, patch(
            "core.workflows.respond_to_pr_comment.try_load_resolved_review_comments_artifact",
            return_value=[],
        ):
            apply_pr_comment_result(
                base_repo,
                context=context,
                run=run,
                result=metadata,
                client=client,
                progress=progress,
            )

        branch_updated_since.assert_called_once()
        client.get_repo.assert_called_once_with("contributor/widgets")
        fork_repo.get_pulls.assert_called_once_with(
            state="open",
            head="acme:oz-agent/respond-pr-7",
            base="feature",
        )
        fork_repo.create_pull.assert_not_called()
        existing_pr.edit.assert_called_once_with(
            title="fix: handle review feedback",
            body="Updated summary",
        )
        progress.complete.assert_called_once()
        self.assertIn("updated a [follow-up PR]", progress.complete.call_args.args[0])

    def test_fallback_strategy_rejects_metadata_branch_mismatch(self) -> None:
        from core.workflows.respond_to_pr_comment import apply_pr_comment_result

        base_repo = MagicMock()
        base_repo.get_pull.return_value = MagicMock()
        progress = MagicMock()
        run = SimpleNamespace(
            run_id="run-1",
            created_at=datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc),
        )
        context = self._context()
        context.update(
            {
                "head_repo_full_name": "contributor/widgets",
                "base_repo_full_name": "acme/widgets",
                "branch_strategy": "fallback-pr-to-fork",
                "agent_push_repo_full_name": "acme/widgets",
                "agent_push_branch": "oz-agent/respond-pr-7",
                "fallback_pr_base_repo_full_name": "contributor/widgets",
                "fallback_pr_base_branch": "feature",
                "fallback_pr_head": "acme:oz-agent/respond-pr-7",
            }
        )
        metadata = {
            "branch_name": "feature",
            "pr_title": "fix: handle review feedback",
            "pr_summary": "Summary",
        }

        with patch(
            "core.workflows.respond_to_pr_comment.branch_updated_since",
            return_value=True,
        ), self.assertRaisesRegex(RuntimeError, "expected push branch"):
            apply_pr_comment_result(
                base_repo,
                context=context,
                run=run,
                result=metadata,
                client=MagicMock(),
                progress=progress,
            )


if __name__ == "__main__":
    unittest.main()
