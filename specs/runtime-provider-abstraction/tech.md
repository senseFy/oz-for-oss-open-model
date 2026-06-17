# Runtime Provider Abstraction Technical Spec

## Current Architecture

The repository already has several platform-neutral workflow functions:

- `api.webhook.process_webhook_request()` verifies a signed payload, routes it,
  runs synchronous helper paths when needed, dispatches an agent run, and saves
  `RunState`.
- `api.cron.run_cron_tick()` drains in-flight runs by calling
  `core.poll_runs.drain_in_flight_runs()`.
- `core.state.StateStore` is a small storage protocol used by both dispatch and
  drain paths.
- `core.dispatch`, `core.poll_runs`, workflow builders, and workflow handlers do
  not need to know which hosting provider delivered the request.

The provider-specific code is concentrated in two entrypoints:

- `api/webhook.py`: Vercel `BaseHTTPRequestHandler`, secret resolution, request
  parsing, production wiring, GitHub App token/client creation, backend
  selection, sync helper wiring, and state-store construction.
- `api/cron.py`: Vercel `BaseHTTPRequestHandler`, cron auth, Upstash/Vercel KV
  store construction, retriever selection, workflow handler construction, and
  drain response formatting.

The implementation PR should preserve the current behavior while moving
provider-specific construction into a runtime package.

## Proposed Module Layout

```text
runtime/
  __init__.py
  common.py
  types.py
  vercel.py
  stores/
    __init__.py
    upstash.py
```

### `runtime.types`

Define typed wiring records instead of passing unstructured dictionaries between
entrypoints and runtime code.

Suggested records:

```python
@dataclass(frozen=True)
class WebhookRuntimeWiring:
    builder_registry: Mapping[str, PromptBuilder]
    runner: AgentRunner
    config_factory: Callable[[str, str], Mapping[str, Any]]
    store: StateStore
    sync_plan_approved: Callable[[Mapping[str, Any]], dict[str, Any] | None] | None
    sync_announce_ready_issue: Callable[[Mapping[str, Any]], dict[str, Any]] | None
    sync_cancel_review_runs: Callable[[Mapping[str, Any]], dict[str, Any]] | None
    triage_bot_author_allowlist_loader: Callable[
        [Mapping[str, Any]], Iterable[str]
    ] | None


@dataclass(frozen=True)
class CronRuntimeWiring:
    store: StateStore
    retriever: RunRetriever
    handlers: Mapping[str, WorkflowHandlers]
    max_attempts: int
    max_age_seconds: int
```

These records are internal construction contracts. They should not become a
large public plugin API yet.

### `runtime.common`

Own platform-neutral orchestration that should be reused by every runtime.

Move or re-export:

- `WebhookResponse`
- `process_webhook_request()`
- `run_cron_tick()`
- cron outcome summarization if it is not Vercel-specific

Compatibility requirement:

- Existing imports from `api.webhook.process_webhook_request` and
  `api.cron.run_cron_tick` should continue to work during this phase, either by
  leaving thin re-exports in `api/` or by updating tests and downstream imports
  in the same PR.

### `runtime.stores.upstash`

Move the production Upstash/Vercel KV adapter out of `api/cron.py`.

Suggested surface:

```python
class UpstashStateStore:
    def __init__(self, redis: Any) -> None: ...
    def put(self, key: str, value: str) -> None: ...
    def get(self, key: str) -> str | None: ...
    def delete(self, key: str) -> None: ...
    def keys(self, prefix: str) -> list[str]: ...


def build_upstash_state_store() -> StateStore: ...
```

The builder should continue to read:

- `KV_REST_API_URL`
- `KV_REST_API_TOKEN`

Import `upstash_redis.Redis` lazily inside the builder so unit tests do not need
the production dependency installed.

### `runtime.vercel`

Own Vercel-specific construction and auth helpers.

Suggested surface:

```python
def resolve_webhook_secret() -> str: ...
def resolve_cron_secret() -> str | None: ...
def build_webhook_wiring(*, body: bytes) -> WebhookRuntimeWiring: ...
def build_cron_wiring() -> CronRuntimeWiring: ...
def optional_positive_int_env(name: str, default: int) -> int: ...
```

Responsibilities:

- Preserve `OZ_GITHUB_WEBHOOK_SECRET` behavior.
- Preserve `CRON_SECRET` and `OZ_ALLOW_UNAUTHENTICATED_CRON` behavior.
- Build GitHub App clients from `OZ_GITHUB_APP_ID`,
  `OZ_GITHUB_APP_PRIVATE_KEY`, and `GITHUB_API_BASE_URL`.
- Build the workflow builder registry.
- Build synchronous helpers for `plan-approved`, `announce-ready-issue`, and
  `cancel-review-runs`.
- Select Oz or open-model runner/retriever using the existing backend selector.
- Use `runtime.stores.upstash.build_upstash_state_store()`.
- Preserve lazy imports for optional production-only dependencies.

### `api/webhook.py`

Keep this file as the Vercel HTTP adapter.

Target shape:

- Define the `handler(BaseHTTPRequestHandler)` symbol Vercel expects.
- Read the request body and headers.
- Call `runtime.vercel.resolve_webhook_secret()`.
- Call `runtime.vercel.build_webhook_wiring(body=body)`.
- Call `runtime.common.process_webhook_request(...)`.
- Serialize the JSON response.

Avoid keeping production dependency wiring in this file.

### `api/cron.py`

Keep this file as the Vercel cron HTTP adapter.

Target shape:

- Define the `handler(BaseHTTPRequestHandler)` symbol Vercel expects.
- Call `runtime.vercel.resolve_cron_secret()`.
- Validate the bearer token when a secret is configured.
- Call `runtime.vercel.build_cron_wiring()`.
- Call `runtime.common.run_cron_tick(...)`.
- Serialize the summarized JSON response.

Avoid keeping the Upstash store implementation, retriever construction, or
workflow handler construction in this file.

## Behavior Preservation Requirements

- `vercel.json` should not change in this phase unless a test or import path
  requires a minimal `PYTHONPATH` adjustment.
- `/api/webhook` should keep returning `401` for invalid signatures, `400` for
  malformed requests, `202` for accepted/dropped routed events, and `500` for
  production wiring or dispatch failures.
- `/api/cron` should keep failing closed when `CRON_SECRET` is missing unless
  `OZ_ALLOW_UNAUTHENTICATED_CRON` is explicitly enabled.
- `RunState` JSON, key prefix, attempt handling, expiration behavior, and
  deletion behavior should not change.
- The open-model backend remains a model execution backend, not a runtime
  provider.

## Migration Plan

1. Add the `runtime` package and move shared dataclasses/helpers into it.
2. Move the Upstash state-store adapter into `runtime/stores/upstash.py`.
3. Move Vercel production wiring from `api/webhook.py` and `api/cron.py` into
   `runtime/vercel.py`.
4. Keep compatibility re-exports in `api/webhook.py` and `api/cron.py` for
   tests or downstream imports that currently import helper functions from
   `api/`.
5. Update tests to assert behavior through the new runtime modules where useful,
   while keeping at least one entrypoint-level smoke test for each Vercel
   handler.
6. Update `docs/open-model-architecture.md` if the final module names differ
   from this spec.

## Validation Plan

- Run `python -m py_compile` for touched runtime, api, and store modules.
- Run `python -m pytest tests` or the repository's active test command.
- Add focused tests for:
  - cron secret resolution behavior
  - Upstash store key scanning behavior with a fake Redis client
  - Vercel webhook wiring returning typed wiring records under stubbed
    dependencies where practical
  - compatibility imports from `api.webhook` and `api.cron`
- Confirm `git diff --check` passes.

## Phase Exit

This phase is complete when the code still runs on Vercel exactly as before,
but the Vercel-specific runtime, Upstash store adapter, and platform-neutral
webhook/drain orchestration are separated enough that a local daemon can reuse
the common path without copying Vercel handler code.
