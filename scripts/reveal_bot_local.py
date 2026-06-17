#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.local import LocalDaemon, LocalRuntimeConfig


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Reveal Bot runtime.")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--state-dir", default=None)
    parser.add_argument("--open-model-run-store-dir", default=None)
    parser.add_argument("--poll-interval", type=float, default=None)
    parser.add_argument(
        "--no-open-model-worker",
        action="store_true",
        help="Serve webhooks and drain runs without processing local open-model runs.",
    )
    parser.add_argument(
        "--env-file",
        default=".env.local",
        help="Load env vars from this file if it exists. Existing env vars win.",
    )
    parser.add_argument(
        "--no-env-file",
        action="store_true",
        help="Do not load an env file before starting.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.no_env_file:
        _load_env_file(Path(args.env_file))

    config = LocalRuntimeConfig.from_env(
        host=args.host,
        port=args.port,
        state_dir=args.state_dir,
        open_model_run_store_dir=args.open_model_run_store_dir,
        poll_interval_seconds=args.poll_interval,
        process_open_model=not args.no_open_model_worker,
    )
    daemon = LocalDaemon(config)
    print(
        "local Reveal Bot runtime listening on "
        f"http://{config.host}:{config.port}; webhook=/webhook; health=/healthz"
    )
    print(f"state_dir={config.state_dir}")
    print(f"open_model_run_store_dir={config.open_model_run_store_dir}")
    try:
        daemon.serve_forever()
    except KeyboardInterrupt:
        print("shutting down local Reveal Bot runtime")
        daemon.shutdown()


if __name__ == "__main__":
    main()
