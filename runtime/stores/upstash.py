"""Upstash/Vercel KV adapter for in-flight run state."""

from __future__ import annotations

import json
import os
from typing import Any

from core.state import StateStore


class UpstashStateStore:
    """Small :class:`StateStore` wrapper around an Upstash Redis client."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def put(self, key: str, value: str) -> None:
        self._redis.set(key, value)

    def get(self, key: str) -> str | None:
        value = self._redis.get(key)
        if value is None:
            return None
        return value if isinstance(value, str) else json.dumps(value)

    def delete(self, key: str) -> None:
        self._redis.delete(key)

    def keys(self, prefix: str) -> list[str]:
        pattern = f"{prefix}*"
        found: list[str] = []
        cursor: int | str = 0
        while True:
            result = self._redis.scan(cursor, match=pattern)
            cursor = result[0]
            found.extend(result[1])
            if str(cursor) == "0":
                break
        return found


def build_upstash_state_store() -> StateStore:
    """Build the production Upstash-backed :class:`StateStore`.

    The official Upstash SDK consumes the ``KV_REST_API_URL`` and
    ``KV_REST_API_TOKEN`` env vars Vercel injects when a KV resource is
    connected. The import stays lazy so local tests do not need the
    production dependency installed.
    """
    try:
        from upstash_redis import Redis  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - production-only path
        raise RuntimeError(
            "upstash-redis is not installed; the production runtime needs "
            "the Upstash Redis SDK to read in-flight run state."
        ) from exc

    return UpstashStateStore(
        Redis(
            url=os.environ["KV_REST_API_URL"],
            token=os.environ["KV_REST_API_TOKEN"],
        )
    )


__all__ = ["UpstashStateStore", "build_upstash_state_store"]
