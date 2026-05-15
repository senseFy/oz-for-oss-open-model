"""Tests for sibling-PR discovery and same-issue reviewer reuse.

Covers both the API-backed helpers in :mod:`oz.helpers` and the
control-plane reviewer-reuse selector wired into
``workflows.review_pr._resolve_recommended_reviewers``.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from . import conftest  # noqa: F401

from oz.helpers import (
    build_related_pr_reviewer_candidates,
    find_related_prs_for_issue,
)
from oz.ownership import OwnershipArea

from workflows.review_pr import (  # type: ignore[import-not-found]
    _resolve_recommended_reviewers,
    _resolve_same_issue_reviewer,
    apply_review_result,
)


STAKEHOLDERS = [
    {"pattern": "*", "owners": ["fallback"]},
    {"pattern": "/docs/", "owners": ["docs-owner"]},
]

OWNERSHIP_AREAS = [
    OwnershipArea(
        name="Docs",
        owners=["docs-owner", "secondary-owner"],
        matches="Docs and reference",
    ),
    OwnershipArea(
        name="Runtime",
        owners=["runtime-owner"],
        matches="Runtime internals",
    ),
]


def _user(login: str, *, type_: str = "User") -> SimpleNamespace:
    return SimpleNamespace(login=login, type=type_)


def _cross_ref_node(
    *,
    pr_number: int,
    title: str = "Other PR",
    url: str = "",
    state: str = "OPEN",
    author_login: str = "external-1",
    author_typename: str = "User",
    owner: str = "acme",
    repo: str = "widgets",
) -> dict:
    return {
        "__typename": "CrossReferencedEvent",
        "isCrossRepository": False,
        "source": {
            "__typename": "PullRequest",
            "number": pr_number,
            "title": title,
            "url": url or f"https://github.com/{owner}/{repo}/pull/{pr_number}",
            "state": state,
            "author": {"login": author_login, "__typename": author_typename},
            "repository": {
                "owner": {"login": owner},
                "name": repo,
            },
        },
    }


class FindRelatedPrsForIssueTest(unittest.TestCase):
    """``find_related_prs_for_issue`` queries the issue timeline.

    Mocks GraphQL via ``github.requester.graphql_query`` to return
    cross-referenced events, and PyGithub via ``github.get_pull(...)``
    to expose ``get_review_requests`` / ``get_reviews`` for each
    sibling PR.
    """

    def _make_github(
        self,
        *,
        timeline_nodes: list[dict],
        siblings: dict[int, MagicMock],
        page_info: dict | None = None,
    ) -> MagicMock:
        page_info = page_info or {"hasNextPage": False, "endCursor": None}
        graphql_response = (
            {},
            {
                "data": {
                    "repository": {
                        "issue": {
                            "timelineItems": {
                                "pageInfo": page_info,
                                "nodes": timeline_nodes,
                            }
                        }
                    }
                }
            },
        )
        requester = MagicMock()
        requester.graphql_query.return_value = graphql_response
        github = MagicMock()
        github.requester = requester

        def _get_pull(pr_number: int) -> MagicMock:
            return siblings[int(pr_number)]

        github.get_pull.side_effect = _get_pull
        return github

    def _make_sibling(
        self,
        *,
        requested_users: list[SimpleNamespace] | None = None,
        reviews: list[SimpleNamespace] | None = None,
    ) -> MagicMock:
        pr = MagicMock()
        pr.get_review_requests.return_value = (requested_users or [], [])
        pr.get_reviews.return_value = reviews or []
        return pr

    def test_returns_sibling_with_requested_and_prior_reviewers(self) -> None:
        sibling = self._make_sibling(
            requested_users=[_user("docs-owner")],
            reviews=[
                SimpleNamespace(
                    state="APPROVED",
                    user=_user("secondary-owner"),
                )
            ],
        )
        github = self._make_github(
            timeline_nodes=[_cross_ref_node(pr_number=100, author_login="ext-1")],
            siblings={100: sibling},
        )

        related = find_related_prs_for_issue(
            github, "acme", "widgets", 42,
            exclude_pr_number=99,
            exclude_pr_author_login="contributor",
        )

        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["number"], 100)
        self.assertEqual(related[0]["state"], "OPEN")
        self.assertEqual(related[0]["author_login"], "ext-1")
        self.assertEqual(related[0]["requested_reviewers"], ["docs-owner"])
        self.assertEqual(related[0]["prior_reviewers"], ["secondary-owner"])

    def test_excludes_current_pr_and_cross_repo_sources(self) -> None:
        # The current PR (#99) and a cross-repo PR source must be
        # filtered out before reviewer signals are gathered.
        cross_repo_node = _cross_ref_node(pr_number=200, owner="fork-owner")
        nodes = [
            _cross_ref_node(pr_number=99),
            cross_repo_node,
            _cross_ref_node(pr_number=101, author_login="ext-2"),
        ]
        sibling_101 = self._make_sibling()
        github = self._make_github(
            timeline_nodes=nodes,
            siblings={101: sibling_101},
        )

        related = find_related_prs_for_issue(
            github, "acme", "widgets", 42,
            exclude_pr_number=99,
            exclude_pr_author_login="contributor",
        )

        # Only #101 survives: #99 is excluded, the cross-repo node is
        # dropped by the same-repo filter inside the helper.
        self.assertEqual([entry["number"] for entry in related], [101])

    def test_excludes_bot_authored_sibling(self) -> None:
        nodes = [
            _cross_ref_node(
                pr_number=110,
                author_login="dependabot[bot]",
                author_typename="Bot",
            ),
            _cross_ref_node(pr_number=111, author_login="ext-3"),
        ]
        sibling_111 = self._make_sibling()
        github = self._make_github(
            timeline_nodes=nodes,
            siblings={111: sibling_111},
        )

        related = find_related_prs_for_issue(
            github, "acme", "widgets", 42,
            exclude_pr_number=0,
            exclude_pr_author_login="contributor",
        )

        # The bot-authored PR is dropped before we even look up reviewer
        # signals, and the human-authored sibling is preserved.
        self.assertEqual([entry["number"] for entry in related], [111])

    def test_excludes_sibling_author_from_reviewer_signals(self) -> None:
        sibling = self._make_sibling(
            requested_users=[_user("ext-author"), _user("docs-owner")],
            reviews=[
                SimpleNamespace(state="APPROVED", user=_user("ext-author")),
                SimpleNamespace(state="APPROVED", user=_user("secondary-owner")),
            ],
        )
        github = self._make_github(
            timeline_nodes=[
                _cross_ref_node(pr_number=120, author_login="ext-author"),
            ],
            siblings={120: sibling},
        )

        related = find_related_prs_for_issue(
            github, "acme", "widgets", 42,
            exclude_pr_number=99,
            exclude_pr_author_login="contributor",
        )

        # The sibling PR's own author and bot reviewers are filtered
        # out; everyone else remains.
        self.assertEqual(related[0]["requested_reviewers"], ["docs-owner"])
        self.assertEqual(related[0]["prior_reviewers"], ["secondary-owner"])

    def test_excludes_bot_reviewers(self) -> None:
        sibling = self._make_sibling(
            requested_users=[
                SimpleNamespace(login="oz-for-oss[bot]", type="Bot"),
                _user("docs-owner"),
            ],
            reviews=[
                SimpleNamespace(
                    state="APPROVED",
                    user=SimpleNamespace(login="ci-bot[bot]", type="Bot"),
                ),
                SimpleNamespace(state="APPROVED", user=_user("secondary-owner")),
            ],
        )
        github = self._make_github(
            timeline_nodes=[_cross_ref_node(pr_number=130)],
            siblings={130: sibling},
        )

        related = find_related_prs_for_issue(
            github, "acme", "widgets", 42,
            exclude_pr_number=99,
            exclude_pr_author_login="contributor",
        )

        self.assertEqual(related[0]["requested_reviewers"], ["docs-owner"])
        self.assertEqual(related[0]["prior_reviewers"], ["secondary-owner"])

    def test_fail_open_on_graphql_error(self) -> None:
        requester = MagicMock()
        requester.graphql_query.side_effect = RuntimeError("graphql down")
        github = MagicMock()
        github.requester = requester

        related = find_related_prs_for_issue(
            github, "acme", "widgets", 42,
            exclude_pr_number=99,
            exclude_pr_author_login="contributor",
        )

        # Helper swallows the error and returns an empty list so the
        # workflow falls through to the existing reviewer-resolution
        # path.
        self.assertEqual(related, [])


class BuildRelatedPrReviewerCandidatesTest(unittest.TestCase):
    def test_orders_requested_open_before_prior_review(self) -> None:
        related = [
            {
                "number": 11,
                "state": "OPEN",
                "requested_reviewers": ["alice"],
                "prior_reviewers": ["bob"],
            },
            {
                "number": 12,
                "state": "CLOSED",
                "requested_reviewers": ["carol"],
                "prior_reviewers": ["dave"],
            },
        ]
        candidates = build_related_pr_reviewer_candidates(related)
        self.assertEqual(
            candidates,
            [
                {"login": "alice", "source": "requested-open"},
                {"login": "bob", "source": "prior-review"},
                {"login": "dave", "source": "prior-review"},
            ],
        )

    def test_skips_requested_reviewers_from_closed_siblings(self) -> None:
        related = [
            {
                "number": 21,
                "state": "MERGED",
                "requested_reviewers": ["alice"],
                "prior_reviewers": ["bob"],
            }
        ]
        candidates = build_related_pr_reviewer_candidates(related)
        self.assertEqual(
            candidates,
            [{"login": "bob", "source": "prior-review"}],
        )

    def test_dedupes_within_tier(self) -> None:
        related = [
            {"number": 31, "state": "OPEN", "requested_reviewers": ["alice"]},
            {"number": 32, "state": "OPEN", "requested_reviewers": ["alice"]},
            {"number": 33, "state": "OPEN", "prior_reviewers": ["alice"]},
        ]
        candidates = build_related_pr_reviewer_candidates(related)
        # ``alice`` appears once per tier, even though she shows up on
        # multiple sibling PRs.
        self.assertEqual(
            candidates,
            [
                {"login": "alice", "source": "requested-open"},
                {"login": "alice", "source": "prior-review"},
            ],
        )


class ResolveSameIssueReviewerTest(unittest.TestCase):
    def test_picks_requested_open_tier_when_unique(self) -> None:
        candidates = [
            {"login": "docs-owner", "source": "requested-open"},
            {"login": "runtime-owner", "source": "prior-review"},
        ]
        reviewers = _resolve_same_issue_reviewer(
            candidates,
            ownership_areas=OWNERSHIP_AREAS,
            stakeholder_entries=[],
            pr_author_login="contributor",
        )
        self.assertEqual(reviewers, ["docs-owner"])

    def test_falls_through_to_prior_review_tier(self) -> None:
        candidates = [{"login": "runtime-owner", "source": "prior-review"}]
        reviewers = _resolve_same_issue_reviewer(
            candidates,
            ownership_areas=OWNERSHIP_AREAS,
            stakeholder_entries=[],
            pr_author_login="contributor",
        )
        self.assertEqual(reviewers, ["runtime-owner"])

    def test_ambiguous_requested_tier_skips_to_next_tier(self) -> None:
        candidates = [
            {"login": "docs-owner", "source": "requested-open"},
            {"login": "secondary-owner", "source": "requested-open"},
            {"login": "runtime-owner", "source": "prior-review"},
        ]
        reviewers = _resolve_same_issue_reviewer(
            candidates,
            ownership_areas=OWNERSHIP_AREAS,
            stakeholder_entries=[],
            pr_author_login="contributor",
        )
        # The requested-open tier is ambiguous (two eligible logins),
        # so we skip to the prior-review tier and pick the single
        # eligible login there.
        self.assertEqual(reviewers, ["runtime-owner"])

    def test_returns_empty_when_all_tiers_ambiguous(self) -> None:
        candidates = [
            {"login": "docs-owner", "source": "requested-open"},
            {"login": "secondary-owner", "source": "requested-open"},
            {"login": "runtime-owner", "source": "prior-review"},
            {"login": "docs-owner", "source": "prior-review"},
        ]
        reviewers = _resolve_same_issue_reviewer(
            candidates,
            ownership_areas=OWNERSHIP_AREAS,
            stakeholder_entries=[],
            pr_author_login="contributor",
        )
        self.assertEqual(reviewers, [])

    def test_filters_logins_outside_ownership_owner_set(self) -> None:
        candidates = [
            {"login": "outsider", "source": "requested-open"},
            {"login": "docs-owner", "source": "prior-review"},
        ]
        reviewers = _resolve_same_issue_reviewer(
            candidates,
            ownership_areas=OWNERSHIP_AREAS,
            stakeholder_entries=[],
            pr_author_login="contributor",
        )
        # ``outsider`` is not in the ownership-areas owner set, so the
        # requested-open tier becomes empty and we fall through to the
        # prior-review tier where docs-owner is eligible.
        self.assertEqual(reviewers, ["docs-owner"])

    def test_uses_stakeholders_when_ownership_areas_unavailable(self) -> None:
        candidates = [
            {"login": "outsider", "source": "requested-open"},
            {"login": "docs-owner", "source": "prior-review"},
        ]
        reviewers = _resolve_same_issue_reviewer(
            candidates,
            ownership_areas=[],
            stakeholder_entries=STAKEHOLDERS,
            pr_author_login="contributor",
        )
        # Falls back to the STAKEHOLDERS roster; ``outsider`` is not
        # listed, ``docs-owner`` is.
        self.assertEqual(reviewers, ["docs-owner"])

    def test_excludes_pr_author_from_candidates(self) -> None:
        candidates = [
            {"login": "docs-owner", "source": "requested-open"},
        ]
        reviewers = _resolve_same_issue_reviewer(
            candidates,
            ownership_areas=OWNERSHIP_AREAS,
            stakeholder_entries=[],
            pr_author_login="docs-owner",
        )
        # The PR author cannot review their own PR; this candidate is
        # dropped and no reviewer is selected.
        self.assertEqual(reviewers, [])

    def test_returns_empty_with_no_candidates(self) -> None:
        self.assertEqual(
            _resolve_same_issue_reviewer(
                [],
                ownership_areas=OWNERSHIP_AREAS,
                stakeholder_entries=[],
                pr_author_login="contributor",
            ),
            [],
        )

    def test_returns_empty_without_maintainer_set(self) -> None:
        # Sibling reuse without any maintainer guard would risk pulling
        # in random logins, so the selector intentionally bails out.
        candidates = [{"login": "docs-owner", "source": "requested-open"}]
        self.assertEqual(
            _resolve_same_issue_reviewer(
                candidates,
                ownership_areas=[],
                stakeholder_entries=[],
                pr_author_login="contributor",
            ),
            [],
        )


class ResolveRecommendedReviewersWithSiblingsTest(unittest.TestCase):
    """``_resolve_recommended_reviewers`` prefers sibling-PR reuse."""

    def test_sibling_reviewer_wins_over_ownership_area(self) -> None:
        repo_handle = MagicMock()
        candidates = [{"login": "secondary-owner", "source": "requested-open"}]
        with patch(
            "workflows.review_pr.load_stakeholders_from_repo",
            return_value=STAKEHOLDERS,
        ):
            reviewers = _resolve_recommended_reviewers(
                {"recommended_area": "Docs"},
                ownership_areas=OWNERSHIP_AREAS,
                repo_handle=repo_handle,
                pr_author_login="contributor",
                changed_paths=["docs/readme.md"],
                related_pr_reviewer_candidates=candidates,
            )
        # ``Docs`` ownership area would yield ``docs-owner`` (or a random
        # pick); the sibling-PR signal overrides that with the requested
        # reviewer from the open sibling.
        self.assertEqual(reviewers, ["secondary-owner"])

    def test_no_sibling_signal_falls_back_to_ownership_area(self) -> None:
        repo_handle = MagicMock()
        with patch(
            "workflows.review_pr.load_stakeholders_from_repo",
            return_value=STAKEHOLDERS,
        ):
            reviewers = _resolve_recommended_reviewers(
                {"recommended_area": "Runtime"},
                ownership_areas=OWNERSHIP_AREAS,
                repo_handle=repo_handle,
                pr_author_login="contributor",
                changed_paths=["src/runtime.py"],
                related_pr_reviewer_candidates=[],
            )
        self.assertEqual(reviewers, ["runtime-owner"])

    def test_ambiguous_sibling_signal_falls_through(self) -> None:
        repo_handle = MagicMock()
        candidates = [
            {"login": "docs-owner", "source": "requested-open"},
            {"login": "secondary-owner", "source": "requested-open"},
        ]
        with patch(
            "workflows.review_pr.load_stakeholders_from_repo",
            return_value=STAKEHOLDERS,
        ):
            reviewers = _resolve_recommended_reviewers(
                {"recommended_area": "Runtime"},
                ownership_areas=OWNERSHIP_AREAS,
                repo_handle=repo_handle,
                pr_author_login="contributor",
                changed_paths=["src/runtime.py"],
                related_pr_reviewer_candidates=candidates,
            )
        # Sibling signal is ambiguous in the requested-open tier and
        # the prior-review tier is empty, so we use the ownership-area
        # match instead.
        self.assertEqual(reviewers, ["runtime-owner"])


class ApplyReviewResultSameIssueReuseTest(unittest.TestCase):
    """End-to-end: ``apply_review_result`` honors sibling-PR reuse."""

    def _make_context(
        self,
        *,
        related_pr_reviewer_candidates: list[dict[str, str]] | None = None,
    ) -> dict:
        return {
            "owner": "acme",
            "repo": "widgets",
            "pr_number": 99,
            "requester": "alice",
            "is_non_member": True,
            "pr_author_login": "contributor",
            "stakeholder_entries": STAKEHOLDERS,
            "stakeholder_logins": ["fallback", "docs-owner"],
            "ownership_areas": [area.to_dict() for area in OWNERSHIP_AREAS],
            "ownership_areas_loaded": True,
            "diff_line_map": {},
            "diff_content_map": {},
            "linked_issue_number": 42,
            "related_prs": [],
            "related_pr_reviewer_candidates": related_pr_reviewer_candidates or [],
        }

    def _make_github(self, pr: MagicMock) -> MagicMock:
        github = MagicMock()
        github.get_pull.return_value = pr
        return github

    def test_sibling_requested_reviewer_is_requested(self) -> None:
        pr = MagicMock()
        github = self._make_github(pr)
        progress = MagicMock()
        candidates = [{"login": "secondary-owner", "source": "requested-open"}]
        with patch(
            "workflows.review_pr.load_stakeholders_from_repo",
            return_value=STAKEHOLDERS,
        ):
            apply_review_result(
                github,
                context=self._make_context(
                    related_pr_reviewer_candidates=candidates,
                ),
                run=MagicMock(),
                result={
                    "verdict": "APPROVE",
                    "summary": "Looks good",
                    "comments": [],
                    "recommended_area": "Docs",
                },
                progress=progress,
            )
        pr.create_review_request.assert_called_once_with(
            reviewers=["secondary-owner"]
        )

    def test_member_pr_ignores_sibling_signal(self) -> None:
        pr = MagicMock()
        github = self._make_github(pr)
        progress = MagicMock()
        context = self._make_context(
            related_pr_reviewer_candidates=[
                {"login": "secondary-owner", "source": "requested-open"},
            ],
        )
        context["is_non_member"] = False
        with patch(
            "workflows.review_pr.load_stakeholders_from_repo",
            return_value=STAKEHOLDERS,
        ):
            apply_review_result(
                github,
                context=context,
                run=MagicMock(),
                result={
                    "verdict": "APPROVE",
                    "summary": "Looks good",
                    "comments": [],
                    "recommended_area": "Docs",
                },
                progress=progress,
            )
        # Member PRs never request human review; the sibling-PR
        # signal should not change that.
        pr.create_review_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
