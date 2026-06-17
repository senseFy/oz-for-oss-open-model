# oz-for-oss-open-model

This repository is an open-source fork of Warp's [`warpdotdev/oz-for-oss`](https://github.com/warpdotdev/oz-for-oss). The upstream project provides the reusable GitHub control plane that powers Oz-backed issue triage, spec drafting, implementation PRs, pull request review, PR-comment responses, and verification workflows.

This fork keeps that architecture and attribution intact, but it has a narrower goal: make the pull-request review workflow runnable with a transparent, provider-configurable model layer. The default backend remains the upstream Oz Platform. Operators can opt into an OpenAI-compatible backend by setting `REVIEW_AGENT_BACKEND=open-model` and configuring either a local file-backed worker or a remote review backend service.

The intent is not to rebrand Oz. The intent is to study, preserve, and extend the public workflow mechanics in a way that lets teams choose their own model provider, such as OpenAI, DeepSeek, OpenRouter, or any service exposing an OpenAI-compatible `chat/completions` API.

## Current Status

- Upstream-compatible Oz backend remains the default.
- `open-model` review backend is available as an experimental MVP.
- The MVP supports the `review-pull-request` workflow first.
- The backend accepts the same prompt and attachments produced by the existing review workflow, calls an OpenAI-compatible model, validates inline comments against the annotated PR diff, writes `review.json`, and lets the existing cron-side applier publish the review to GitHub.
- Non-review workflows still belong to the upstream Oz path for now.

## Documentation

- [Platform overview](docs/platform.md) — agent roles, prompt construction, and how skills back each workflow.
- [Architecture](docs/architecture.md) — repository layout and the end-to-end webhook flow.
- [Open-model architecture](docs/open-model-architecture.md) — fork-specific architecture direction, runtime boundaries, and upstream differences.
- [Onboarding](docs/onboarding.md) — install the GitHub App and deploy the Vercel control plane.
- [Open-model review backend spec](specs/open-model-review-backend/tech.md) — staged architecture for the provider-configurable backend.
- [Contributing](CONTRIBUTING.md) — issue/PR workflow, label conventions, and local development.

## Open-Model Review Backend

Run the backend service:

```sh
source .venv/bin/activate
export REVIEW_AGENT_BACKEND=open-model
export OPEN_MODEL_API_BASE_URL=https://api.openai.com/v1
export OPEN_MODEL_API_KEY=...
export OPEN_MODEL_MODEL=gpt-4.1
python scripts/open_model_review_backend.py --host 127.0.0.1 --port 8787
```

Point the webhook/cron control plane at that service:

```sh
export REVIEW_AGENT_BACKEND=open-model
export OPEN_MODEL_BACKEND_URL=http://127.0.0.1:8787
```

For a single-process self-hosted deployment, omit `OPEN_MODEL_BACKEND_URL`; the control plane uses `OPEN_MODEL_RUN_STORE_DIR` directly as a local file-backed queue and artifact store.

## Upstream Relationship

This fork is derived from `warpdotdev/oz-for-oss`. Upstream copyright and license terms remain governed by the repository license. Changes in this fork should stay easy to compare against upstream so useful improvements can be contributed back where appropriate.
