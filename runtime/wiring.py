"""Shared production wiring for runtime providers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from core.state import StateStore
from oz.backend import use_open_model_backend
from runtime.types import WebhookRuntimeWiring

GITHUB_APP_PRIVATE_KEY_FILE_ENV = "OZ_GITHUB_APP_PRIVATE_KEY_FILE"


def _resolve_github_app_private_key() -> str:
    raw = os.environ.get("OZ_GITHUB_APP_PRIVATE_KEY", "").strip()
    if raw:
        return raw.replace("\\n", "\n")
    key_file = os.environ.get(GITHUB_APP_PRIVATE_KEY_FILE_ENV, "").strip()
    if key_file:
        return Path(key_file).read_text(encoding="utf-8")
    raise RuntimeError(
        "OZ_GITHUB_APP_PRIVATE_KEY or OZ_GITHUB_APP_PRIVATE_KEY_FILE is required"
    )


def build_github_client_factory():
    """Build a GitHub App installation client factory from env vars."""
    from core.github_app import fetch_installation_token  # type: ignore[import-not-found]

    import httpx
    from github import Auth, Github

    app_id = os.environ["OZ_GITHUB_APP_ID"]
    private_key = _resolve_github_app_private_key()
    api_base = os.environ.get("GITHUB_API_BASE_URL", "https://api.github.com")

    class _HttpxClient:
        def post(self, url, *, headers, timeout):
            with httpx.Client(timeout=timeout) as client:
                return client.post(url, headers=headers)

    http = _HttpxClient()

    def github_client_factory(installation_id: int) -> Github:
        token = fetch_installation_token(
            installation_id=installation_id,
            app_id=app_id,
            private_key=private_key,
            http=http,
            api_base=api_base,
        )
        return Github(auth=Auth.Token(token.token))

    return github_client_factory


def build_workflow_handlers():
    """Return the workflow-handler registry used by runtime drain loops."""
    from core.handlers import build_handler_registry  # type: ignore[import-not-found]

    return build_handler_registry(github_client_factory=build_github_client_factory())


def payload_installation_id(*, body: bytes) -> int:
    try:
        payload_for_install = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload_for_install = {}
    if not isinstance(payload_for_install, dict):
        return 0
    installation = payload_for_install.get("installation") or {}
    if not isinstance(installation, dict):
        return 0
    try:
        return int(installation.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def build_runner_and_config():
    """Build the configured agent runner, config factory, and canceller."""
    if use_open_model_backend():
        from oz.open_model_backend import (  # type: ignore[import-not-found]
            build_open_model_backend,
            build_open_model_config_factory,
        )

        open_model_backend = build_open_model_backend()
        return (
            open_model_backend,
            build_open_model_config_factory(),
            open_model_backend.cancel,
        )

    from oz.oz_client import build_agent_config  # type: ignore[import-not-found]
    from oz_agent_sdk import OzAPI  # type: ignore[import-not-found]

    sdk_client = OzAPI(
        api_key=os.environ["WARP_API_KEY"],
        base_url=os.environ["WARP_API_BASE_URL"],
    )

    def runner(
        *,
        prompt,
        title,
        config,
        skill,
        team,
        attachments=None,
        workflow=None,
    ):
        request = {
            "prompt": prompt,
            "title": title,
            "config": config,
            "team": team,
        }
        if skill:
            request["skill"] = skill
        if attachments:
            request["attachments"] = tuple(attachments)
        return sdk_client.agent.run(**request)

    def config_factory(config_name: str, role: str) -> Mapping[str, Any]:
        return build_agent_config(config_name=config_name, workspace=Path("/tmp"), role=role)

    return runner, config_factory, sdk_client.agent.runs.cancel


def build_webhook_runtime_wiring(
    *,
    body: bytes,
    store: StateStore,
) -> WebhookRuntimeWiring:
    """Construct shared runtime wiring for one webhook delivery."""
    from core.builders import build_builder_registry
    from core.cancel_runs import cancel_in_flight_review_runs
    from oz.workflow_config import (  # type: ignore[import-not-found]
        load_triage_bot_author_allowlist,
    )
    from workflows.announce_ready_issue import (  # type: ignore[import-not-found]
        apply_announce_ready_issue_sync,
    )
    from workflows.plan_approved import (  # type: ignore[import-not-found]
        apply_plan_approved_sync,
    )

    mint_github_client = build_github_client_factory()
    payload_install_id = payload_installation_id(body=body)
    cached_client: dict[str, Any] = {}

    def client_for_payload():
        if payload_install_id <= 0:
            raise RuntimeError(
                "webhook payload is missing installation.id; cannot mint a GitHub client"
            )
        if "client" not in cached_client:
            cached_client["client"] = mint_github_client(payload_install_id)
        return cached_client["client"]

    builder_registry = build_builder_registry(github_client_factory=client_for_payload)
    runner, config_factory, canceller = build_runner_and_config()

    def sync_plan_approved(payload: Mapping[str, Any]) -> dict[str, Any] | None:
        installation_id = int((payload.get("installation") or {}).get("id") or 0)
        full_name = str((payload.get("repository") or {}).get("full_name") or "")
        if installation_id <= 0 or "/" not in full_name:
            return {
                "action": "skipped",
                "reason": "missing installation_id or repository.full_name",
            }
        client = mint_github_client(installation_id)
        repo_handle = client.get_repo(full_name)
        return apply_plan_approved_sync(repo_handle, payload=payload, github_client=client)

    def sync_announce_ready_issue(payload: Mapping[str, Any]) -> dict[str, Any]:
        installation_id = int((payload.get("installation") or {}).get("id") or 0)
        full_name = str((payload.get("repository") or {}).get("full_name") or "")
        if installation_id <= 0 or "/" not in full_name:
            return {
                "action": "skipped",
                "reason": "missing installation_id or repository.full_name",
            }
        client = mint_github_client(installation_id)
        repo_handle = client.get_repo(full_name)
        return apply_announce_ready_issue_sync(repo_handle, payload=payload)

    def sync_cancel_review_runs(payload: Mapping[str, Any]) -> dict[str, Any]:
        return cancel_in_flight_review_runs(
            store=store,
            canceller=canceller,
            payload=payload,
            github_client_factory=mint_github_client,
        )

    def triage_bot_author_allowlist_loader(payload: Mapping[str, Any]) -> frozenset[str]:
        full_name = str((payload.get("repository") or {}).get("full_name") or "")
        if "/" not in full_name:
            raise RuntimeError(
                "webhook payload is missing repository.full_name; "
                "cannot load triage bot author allowlist"
            )
        repo_handle = client_for_payload().get_repo(full_name)
        workflow_root = Path(__file__).resolve().parents[1]
        return load_triage_bot_author_allowlist(
            repo_handle,
            fallback_workspace=workflow_root,
        )

    return WebhookRuntimeWiring(
        builder_registry=builder_registry,
        runner=runner,
        config_factory=config_factory,
        store=store,
        sync_plan_approved=sync_plan_approved,
        sync_announce_ready_issue=sync_announce_ready_issue,
        sync_cancel_review_runs=sync_cancel_review_runs,
        triage_bot_author_allowlist_loader=triage_bot_author_allowlist_loader,
    )


__all__ = [
    "build_github_client_factory",
    "build_runner_and_config",
    "build_webhook_runtime_wiring",
    "build_workflow_handlers",
    "payload_installation_id",
]
