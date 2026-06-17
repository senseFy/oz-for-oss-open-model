# Open-Model Review Backend Product Spec

## Problem

`oz-for-oss` exposes most of the GitHub workflow mechanics for issue triage, spec generation, PR review, and result application, but the default execution path depends on Warp's Oz Platform for agent runtime, model routing, artifacts, and run lifecycle management.

Some teams want the same review workflow shape while choosing their own model provider. They may want OpenAI, DeepSeek, OpenRouter, an internal OpenAI-compatible gateway, or a future local model gateway. They also want a transparent implementation that can be audited and deployed without relying on a closed model/runtime backend for the review step.

## Goals

- Preserve the upstream `oz-for-oss` review workflow as much as possible.
- Add a provider-configurable backend for pull-request review.
- Keep the model layer explicit: endpoint, model, API key, timeout, temperature, and JSON-output behavior are operator configuration, not hidden platform behavior.
- Reuse the existing annotated diff, PR description, spec context, review schema, validation, and GitHub review applier.
- Make the first implementation runnable in a self-hosted environment.
- Keep upstream Oz as the default path so this fork remains easy to compare and rebase.

## Non-Goals

- Reimplement the full Oz Platform.
- Replace every upstream workflow in the first milestone.
- Guarantee parity with Warp-hosted Oz agent orchestration, observability, session sharing, or managed environments.
- Provide a hosted SaaS backend.
- Support arbitrary model-specific tool protocols beyond OpenAI-compatible chat completions in the first milestone.

## User Experience

An operator can configure:

- `REVIEW_AGENT_BACKEND=oz` to keep upstream behavior.
- `REVIEW_AGENT_BACKEND=open-model` to use the provider-transparent review backend.
- `OPEN_MODEL_BACKEND_URL` when the model backend runs as a separate service.
- `OPEN_MODEL_API_BASE_URL`, `OPEN_MODEL_API_KEY`, and `OPEN_MODEL_MODEL` for the model provider.

When a PR review is triggered, the existing webhook flow gathers PR context and dispatches a run. The open-model backend turns that prompt and its attachments into a model call, validates the model's `review.json`, stores it as an artifact, and lets the existing cron path apply it to GitHub.

## Acceptance Criteria

- The upstream Oz path still works by default.
- The open-model path can enqueue a review run without a Warp API key.
- A worker/server can process the queued run using an OpenAI-compatible model.
- The resulting `review.json` is validated against the annotated diff before it is stored.
- The existing cron-side review applier can load that artifact and publish the review.
- Unsupported non-review workflows fail clearly instead of silently producing invalid artifacts.

## Risks

- A single-shot chat completion may be weaker than a full agent runtime for complex PRs.
- Very large PR diffs may exceed provider context limits.
- File-backed storage is suitable for local/single-node deployments but not for horizontally scaled production.
- Model-specific JSON behavior varies; the backend must tolerate providers that do not support OpenAI `response_format`.

## Follow-Ups

- Add a database-backed queue/artifact store.
- Add richer model adapters through LiteLLM or a similar routing layer.
- Add retry and repair passes for malformed `review.json`.
- Add evaluation fixtures comparing open-model reviews against known PRs.
- Expand beyond `review-pull-request` only after the review path is stable.
