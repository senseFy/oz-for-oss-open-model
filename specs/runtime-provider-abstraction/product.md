# Runtime Provider Abstraction Product Spec

## Summary

Introduce a runtime provider boundary for the GitHub delivery/control-plane
layer while keeping the current Vercel deployment as the default and only
production provider in this phase.

This is a preparation step for future local daemon, Docker, Cloudflare, or other
runtime providers. The first implementation should preserve current behavior and
make the Vercel-specific pieces easier to identify, test, and replace.

## Problem

The fork now has a provider-configurable review backend, but the delivery
runtime is still Vercel-shaped throughout the entrypoints:

- `api/webhook.py` owns Vercel `BaseHTTPRequestHandler` plumbing, webhook
  signature handling, production dependency wiring, GitHub client creation,
  sync workflow helpers, backend selection, and state-store construction.
- `api/cron.py` owns Vercel cron auth, the Upstash/Vercel KV adapter, retriever
  selection, workflow handler construction, and drain response formatting.
- The `StateStore` protocol is storage-agnostic, but the only production store
  adapter is defined inline inside the cron entrypoint.

This makes Vercel the implicit runtime rather than one provider. It also makes
future runtime work harder because a local daemon or Cloudflare Worker would
have to copy code from the Vercel entrypoints instead of reusing a shared
control-plane core.

## Goals

- Keep Vercel as the default provider and preserve the existing hosted
  deployment path.
- Introduce a small runtime boundary around webhook delivery, cron/drain ticks,
  production wiring, and state-store construction.
- Move the Upstash/Vercel KV state-store adapter out of `api/cron.py` into a
  reusable runtime store module.
- Keep the platform-neutral workflow behavior in `core.routing`,
  `core.dispatch`, `core.poll_runs`, workflow builders, and workflow handlers.
- Keep the model backend boundary separate from the runtime provider boundary.
- Preserve existing environment variables, Vercel routes, response shapes, and
  run-state schema.
- Keep `api/webhook.py` and `api/cron.py` as thin Vercel compatibility
  entrypoints.
- Add tests that prove the refactor keeps webhook dispatch, cron auth, state
  store behavior, and run draining unchanged.
- Document where future runtime providers should plug in.

## Non-Goals

- Implementing a Cloudflare runtime provider.
- Implementing a local daemon or Docker runtime.
- Replacing GitHub App authentication.
- Changing the GitHub webhook routes or Vercel `vercel.json` schedule.
- Changing the `RunState` schema or in-flight key namespace.
- Changing Oz vs open-model backend selection.
- Expanding open-model support beyond pull-request review.
- Rewriting workflow builders, result appliers, or prompt construction.
- Introducing a broad framework-style runtime abstraction before a second
  provider exists.

## User Experience

### Existing Vercel operator

An existing deployment should continue to use:

- `/api/webhook`
- `/api/cron`
- `OZ_GITHUB_WEBHOOK_SECRET`
- `CRON_SECRET`
- `KV_REST_API_URL`
- `KV_REST_API_TOKEN`
- existing Oz or open-model backend configuration

No deployment configuration changes should be required for this phase.

### Contributor adding a future runtime

A contributor should be able to see which parts are runtime-specific:

- HTTP request/response adaptation
- scheduler invocation
- state-store adapter
- production wiring for GitHub clients, workflow handlers, runner/retriever, and
  config factories

They should not need to copy Vercel handler code to reuse the common webhook and
drain behavior.

## Acceptance Criteria

- Vercel deployments still expose `/api/webhook` and `/api/cron` through the
  existing `api/` entrypoints.
- Webhook signature verification, routing, synchronous helper behavior, dispatch
  behavior, and response payloads remain compatible with the current code.
- Cron secret enforcement and the local unauthenticated opt-out remain
  compatible with the current code.
- The Upstash-backed `StateStore` adapter is no longer defined inline in
  `api/cron.py`.
- `api/webhook.py` and `api/cron.py` contain only Vercel HTTP handler plumbing
  plus imports from the runtime layer.
- The runtime layer exposes narrow construction functions for Vercel webhook and
  cron wiring.
- The existing test suite passes.
- New or moved tests cover the runtime/store boundary enough to catch accidental
  behavior changes.

## Risks

- Moving production wiring can accidentally change lazy-import behavior and make
  tests require optional production dependencies.
- Over-abstracting before a second provider exists can make the code harder to
  read.
- Cron auth behavior must stay fail-closed by default.
- Upstash scan behavior must stay compatible with the existing in-flight key
  listing logic.
- Import cycles are easy to introduce if runtime modules depend on `api/`
  modules.

## Follow-Ups

- Add a local daemon runtime that combines webhook receiver, scheduler loop,
  file/SQLite state, and open-model execution.
- Add a Cloudflare runtime provider after the shared runtime boundary is proven.
- Add deployment documentation for each runtime provider.
- Add provider-specific smoke tests or example configs once more than one
  runtime exists.
