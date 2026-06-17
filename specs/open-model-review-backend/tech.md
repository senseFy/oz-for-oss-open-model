# Open-Model Review Backend Technical Spec

## Current Architecture

The upstream control plane receives GitHub webhooks in `api/webhook.py`, routes events through `core/routing.py`, builds workflow-specific dispatch requests in `core/workflows`, starts an Oz run through `core/dispatch.py`, stores `RunState`, and later drains terminal runs in `api/cron.py`.

For pull-request reviews, `core/workflows/review_pr.py` already gathers:

- PR metadata and body
- annotated PR diff
- linked spec context
- reviewer-selection context
- serialized diff line/content maps for apply-time validation

The cron-side applier already normalizes `review.json`, drops invalid inline comments, posts a GitHub review, and requests a human reviewer where appropriate.

## Proposed Design

Add a backend selection boundary:

- `REVIEW_AGENT_BACKEND=oz` keeps upstream behavior.
- `REVIEW_AGENT_BACKEND=open-model` uses a provider-transparent review backend.

The backend must satisfy the same minimum interfaces the current poller already needs:

- runner: enqueue a run and return `run_id`
- retriever: return a run object with `state`
- artifact loader: return `review.json`
- canceller: cancel an in-flight review run

## MVP Components

### Backend Selector

`oz/backend.py` centralizes backend selection and validation. The default is `oz`, so existing deployments do not change.

### Open-Model Backend

`oz/open_model_backend.py` provides:

- `FileOpenModelBackend` for local/single-node queue and artifact storage
- `HTTPOpenModelBackend` for a remote backend service
- `OpenModelChatClient` for OpenAI-compatible `chat/completions`
- `build_review_messages()` to combine trusted workflow instructions with untrusted attachments
- `review.json` normalization and diff-line validation before artifact storage

### Backend Service

`scripts/open_model_review_backend.py` exposes a small HTTP API:

- `POST /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/artifacts/review.json`
- `POST /runs/{run_id}/cancel`
- `GET /healthz`

The service stores run state locally and can run an embedded worker thread that processes queued review runs.

## Runtime Configuration

Required for open-model processing:

- `REVIEW_AGENT_BACKEND=open-model`
- `OPEN_MODEL_API_BASE_URL`
- `OPEN_MODEL_MODEL`

Optional:

- `OPEN_MODEL_API_KEY`
- `OPEN_MODEL_BACKEND_URL`
- `OPEN_MODEL_BACKEND_TOKEN`
- `OPEN_MODEL_RUN_STORE_DIR`
- `OPEN_MODEL_TIMEOUT_SECONDS`
- `OPEN_MODEL_TEMPERATURE`
- `OPEN_MODEL_MAX_ATTACHMENT_CHARS`
- `OPEN_MODEL_RESPONSE_FORMAT_JSON`

## Data Flow

1. GitHub webhook enters `api/webhook.py`.
2. Existing routing selects `review-pull-request`.
3. Existing review workflow gathers PR context and attachments.
4. `core/dispatch.py` passes `workflow` plus prompt/attachments to the configured runner.
5. The open-model runner enqueues a run through local files or HTTP.
6. Worker calls the configured OpenAI-compatible model.
7. Worker parses JSON, validates inline comments against `pr_diff.txt`, and stores `review.json`.
8. `api/cron.py` retrieves terminal state through the configured backend.
9. Existing review handlers load `review.json` and apply the GitHub review.

## Compatibility

The Oz backend remains the default and should not require config changes. Open-model mode intentionally supports only `review-pull-request` in the first milestone. Other workflows should continue using Oz or fail explicitly if routed to open-model by mistake.

## Validation Plan

- Unit test backend selection defaults and open-model selection.
- Unit test file-backed run enqueue, processing, retrieval, artifact loading, and cancellation.
- Unit test that `dispatch_run` forwards the workflow name to runners.
- Run the existing test suite to catch regressions in upstream behavior.

## Known Limits

- File-backed state is not a production-grade distributed queue.
- The MVP uses one model call per review run.
- There is no automatic second-pass repair for malformed model output yet.
- The HTTP backend has bearer-token auth only; production deployments should place it behind private networking or a stronger gateway.

## Phase Exit

This phase is considered runnable when a self-hosted process can enqueue a review run, process it with an OpenAI-compatible model, expose the resulting `review.json`, and let the existing cron-side applier consume that artifact.
