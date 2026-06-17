# Local Runtime

The local runtime runs the GitHub webhook receiver, in-flight run store,
open-model worker, and drain loop in one local Python process. It is meant for
developer preview and small self-hosted experiments, not production
high-availability hosting.

## What It Runs

```text
GitHub webhook
  -> local HTTP server
  -> runtime.common.process_webhook_request
  -> FileStateStore
  -> FileOpenModelBackend
  -> OpenAI-compatible model provider
  -> review.json
  -> runtime.common.run_cron_tick
  -> GitHub review applier
```

The default local endpoint is:

```text
http://127.0.0.1:8788/webhook
```

`/api/webhook` is also accepted for parity with the Vercel deployment shape.

## Quickstart

Create a local env file:

```sh
cp .env.example .env.local
```

Fill in:

- `OZ_GITHUB_WEBHOOK_SECRET`
- `OZ_GITHUB_APP_ID`
- `OZ_GITHUB_APP_PRIVATE_KEY_FILE`
- `OPEN_MODEL_API_BASE_URL`
- `OPEN_MODEL_API_KEY`
- `OPEN_MODEL_MODEL`

Start the runtime:

```sh
source .venv/bin/activate
python scripts/reveal_bot_local.py --host 127.0.0.1 --port 8788
```

Health check:

```sh
curl http://127.0.0.1:8788/healthz
```

Expose the local webhook with a tunnel such as ngrok or Cloudflare Tunnel, then
configure the GitHub App webhook URL to point at:

```text
https://<your-tunnel>/webhook
```

Use the same value for the GitHub App webhook secret and
`OZ_GITHUB_WEBHOOK_SECRET`.

## Runtime Files

By default, local runtime state is written under:

```text
.local-runtime/state
.local-runtime/open-model-runs
```

These paths are ignored by git.

## Endpoints

- `GET /healthz`: readiness and in-flight count.
- `POST /webhook`: GitHub webhook receiver.
- `POST /api/webhook`: Vercel-compatible webhook receiver alias.
- `POST /drain`: manually run one drain tick.

The daemon also runs background loops:

- open-model worker loop: processes queued local model runs
- drain loop: applies completed runs back to GitHub

## Limits

- The local file store is not designed for multiple daemon processes.
- It still uses GitHub App authentication for real GitHub mutations.
- It currently targets the PR review path first.
- Full production hardening should use a hosted runtime provider with a durable
  state store.
