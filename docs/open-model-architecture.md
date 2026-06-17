# Open-Model Architecture

This document tracks the architecture direction of `oz-for-oss-open-model`.
It focuses on the parts that intentionally diverge from upstream
`warpdotdev/oz-for-oss`.

## Purpose

The upstream project is centered on Warp's Oz runtime. This fork keeps the
public workflow mechanics from upstream, but makes the execution stack more
transparent and replaceable over time.

The long-term goal is a review automation system where operators can choose:

- the GitHub delivery runtime
- the state store
- the scheduler
- the agent/model backend
- the model provider

The project should remain honest about what is inherited from upstream and what
is new in this fork.

## Current Architecture

Today the fork has two major backend layers:

1. Delivery/control-plane runtime
2. Agent/model backend

### Delivery Runtime

The delivery runtime receives GitHub webhook events, verifies signatures, routes
events to workflows, persists in-flight run state, and drains completed runs
back into GitHub.

Current implementation:

- Provider: Vercel
- Entrypoints: `api/webhook.py`, `api/cron.py`
- State store: Vercel KV / Upstash Redis
- Scheduler: Vercel Cron

This is still largely inherited from upstream.

### Agent/Model Backend

The agent/model backend executes the review task and produces workflow
artifacts such as `review.json`.

Current implementations:

- `oz`: upstream Warp/Oz backend; default
- `open-model`: OpenAI-compatible backend; opt-in via
  `REVIEW_AGENT_BACKEND=open-model`

The `open-model` backend currently supports the `review-pull-request` workflow.
It accepts the prompt and attachments produced by the existing review workflow,
calls an OpenAI-compatible model provider, validates inline comments against the
annotated PR diff, and stores `review.json` for the existing GitHub applier.

## Architecture Matrix

| Layer | Current default | Current alternative | Planned alternatives |
|---|---|---|---|
| Delivery runtime | Vercel | none | local daemon, Docker, Cloudflare, Fly.io, Railway |
| State store | Vercel KV / Upstash Redis | file store for open-model runs only | SQLite, Cloudflare KV/D1/Durable Objects |
| Scheduler | Vercel Cron | manual/local process for backend worker | local loop, Cloudflare Cron Trigger |
| Agent/model backend | Oz | open-model | provider adapters, repair/eval passes |
| Model provider | Warp/Oz managed | OpenAI-compatible endpoint | LiteLLM, OpenRouter profiles, local gateways |

## Difference From Upstream

Upstream `oz-for-oss` assumes:

- Vercel-hosted webhook and cron entrypoints
- Vercel KV / Upstash Redis for in-flight run state
- Oz API for agent execution
- Oz artifacts for workflow outputs

This fork currently changes:

- adds `REVIEW_AGENT_BACKEND`
- keeps `oz` as the default
- adds an `open-model` backend for PR review
- adds a runnable backend service at `scripts/open_model_review_backend.py`
- documents the provider-configurable model layer

This fork has not yet changed:

- GitHub App based authentication
- Vercel as the delivery runtime
- Vercel KV / Upstash Redis as the production run-state store
- issue triage/spec/implementation execution paths

## Next Refactor: Runtime Provider Abstraction

The next architecture PR should introduce a runtime provider boundary.

Target shape:

```text
runtime/
  __init__.py
  types.py
  common.py
  vercel.py
  stores/
    upstash.py
```

Desired split:

- `runtime.common` owns platform-neutral webhook and drain orchestration.
- `runtime.vercel` adapts Vercel's `BaseHTTPRequestHandler` entrypoints to the
  common runtime functions.
- `runtime.stores.upstash` owns the Upstash/Vercel KV `StateStore`
  implementation.
- `api/webhook.py` and `api/cron.py` become thin compatibility entrypoints.

Out of scope for that PR:

- implementing Cloudflare
- implementing local daemon runtime
- replacing GitHub App auth
- expanding open-model beyond PR review

## Planned Runtime Providers

### Vercel

Vercel should remain a first-class provider. It is useful for quick hosted
deployments because it gives us serverless HTTP handlers, cron, environment
variable management, and an easy Upstash integration.

### Local Daemon

The local daemon should be the easiest open-source quickstart path. It should
combine webhook receiver, scheduler loop, file/SQLite state, and open-model
execution in one process.

Possible command:

```sh
python scripts/reveal_bot_local.py --repo owner/name
```

The goal is a low-friction smoke test, not production hardening.

### Cloudflare

Cloudflare should be modeled as another delivery runtime provider, not as a
special model backend.

Likely mapping:

- Workers for webhook handling
- Cron Triggers for drain ticks
- KV, D1, or Durable Objects for run state

Cloudflare support should wait until the runtime provider boundary exists.

## Design Principles

- Keep upstream behavior working by default.
- Prefer narrow interfaces over large platform abstractions.
- Separate delivery runtime from model backend.
- Separate run-state storage from artifact/model execution.
- Keep the review path runnable before expanding to more workflows.
- Document every meaningful divergence from upstream.

## Operational Status

Current runnable path:

```text
GitHub App
  -> Vercel webhook
  -> Upstash run state
  -> open-model backend
  -> OpenAI-compatible model provider
  -> review.json
  -> Vercel cron
  -> GitHub review
```

Current local smoke-test path:

```text
synthetic run
  -> local open-model backend
  -> OpenRouter/OpenAI-compatible provider
  -> review.json artifact
```
