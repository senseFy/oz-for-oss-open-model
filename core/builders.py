"""Prompt-builder registry for cloud-agent workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .dispatch import DispatchRequest, PromptBuilder
from .routing import (
    WORKFLOW_CREATE_IMPLEMENTATION_FROM_ISSUE,
    WORKFLOW_CREATE_SPEC_FROM_ISSUE,
    WORKFLOW_PLAN_APPROVED,
    WORKFLOW_RESPOND_TO_PR_COMMENT,
    WORKFLOW_REVIEW_PR,
    WORKFLOW_TRIAGE_NEW_ISSUES,
    WORKFLOW_VERIFY_PR_COMMENT,
)
from .workflow_adapters import dispatch_request_for_workflow, prompt_builder_for_workflow
from .workflows import (
    CreateImplementationWorkflow,
    CreateSpecWorkflow,
    PlanApprovedWorkflow,
    RespondWorkflow,
    ReviewWorkflow,
    TriageWorkflow,
    VerifyWorkflow,
    build_workflow_registry,
)


def _request_for(
    workflow,
    payload: Mapping[str, Any],
    *,
    github_client: Any,
    workspace_path: Path | None = None,
) -> DispatchRequest:
    return dispatch_request_for_workflow(
        workflow,
        payload,
        github_client=github_client,
        workspace_path=workspace_path,
    )


def build_review_request(
    payload: Mapping[str, Any],
    *,
    github_client: Any,
    workspace_path: Path | None = None,
) -> DispatchRequest:
    return _request_for(
        ReviewWorkflow(),
        payload,
        github_client=github_client,
        workspace_path=workspace_path,
    )


def build_respond_request(
    payload: Mapping[str, Any],
    *,
    github_client: Any,
    workspace_path: Path | None = None,
) -> DispatchRequest:
    return _request_for(
        RespondWorkflow(),
        payload,
        github_client=github_client,
        workspace_path=workspace_path,
    )


def build_verify_request(
    payload: Mapping[str, Any],
    *,
    github_client: Any,
    workspace_path: Path | None = None,
) -> DispatchRequest:
    return _request_for(
        VerifyWorkflow(),
        payload,
        github_client=github_client,
        workspace_path=workspace_path,
    )


def build_triage_request(
    payload: Mapping[str, Any],
    *,
    github_client: Any,
    workspace_path: Path | None = None,
) -> DispatchRequest:
    return _request_for(
        TriageWorkflow(),
        payload,
        github_client=github_client,
        workspace_path=workspace_path,
    )


def build_create_spec_request(
    payload: Mapping[str, Any],
    *,
    github_client: Any,
    workspace_path: Path | None = None,
) -> DispatchRequest:
    return _request_for(
        CreateSpecWorkflow(),
        payload,
        github_client=github_client,
        workspace_path=workspace_path,
    )


def build_create_implementation_request(
    payload: Mapping[str, Any],
    *,
    github_client: Any,
    workspace_path: Path | None = None,
) -> DispatchRequest:
    return _request_for(
        CreateImplementationWorkflow(),
        payload,
        github_client=github_client,
        workspace_path=workspace_path,
    )


def build_plan_approved_request(
    payload: Mapping[str, Any],
    *,
    github_client: Any,
    workspace_path: Path | None = None,
) -> DispatchRequest:
    return _request_for(
        PlanApprovedWorkflow(),
        payload,
        github_client=github_client,
        workspace_path=workspace_path,
    )



def build_builder_registry(
    *,
    github_client_factory,
    workspace_path: Path | None = None,
    ownership_github_client_factory=None,
) -> Mapping[str, PromptBuilder]:
    """Build the prompt-builder registry consumed by :func:`api.webhook.process_webhook_request`.

    *ownership_github_client_factory* is an optional zero-argument
    callable that returns a :class:`github.Github` minted against the
    installation token for ``warpdotdev/warp-ownership`` (or the slug
    configured via ``WARP_OWNERSHIP_REPO``). When omitted, ownership
    areas are unavailable and the review workflow falls back to the
    legacy STAKEHOLDERS prompt for non-member PRs.
    """
    return {
        name: prompt_builder_for_workflow(
            workflow,
            github_client_factory=github_client_factory,
            workspace_path=workspace_path,
            ownership_github_client_factory=ownership_github_client_factory,
        )
        for name, workflow in build_workflow_registry().items()
    }


__all__ = [
    "build_builder_registry",
    "build_create_implementation_request",
    "build_create_spec_request",
    "build_plan_approved_request",
    "build_respond_request",
    "build_review_request",
    "build_triage_request",
    "build_verify_request",
    "WORKFLOW_CREATE_IMPLEMENTATION_FROM_ISSUE",
    "WORKFLOW_CREATE_SPEC_FROM_ISSUE",
    "WORKFLOW_PLAN_APPROVED",
    "WORKFLOW_RESPOND_TO_PR_COMMENT",
    "WORKFLOW_REVIEW_PR",
    "WORKFLOW_TRIAGE_NEW_ISSUES",
    "WORKFLOW_VERIFY_PR_COMMENT",
]
