from __future__ import annotations

import unittest
from typing import Any

from . import conftest  # noqa: F401

from runtime.stores.upstash import UpstashStateStore


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.scan_calls: list[tuple[int | str, str | None]] = []
        self.scan_results: list[tuple[int | str, list[str]]] = []

    def set(self, key: str, value: str) -> None:
        self.data[key] = value

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def delete(self, key: str) -> None:
        self.data.pop(key, None)

    def scan(self, cursor: int | str, *, match: str | None = None):
        self.scan_calls.append((cursor, match))
        if not self.scan_results:
            return [0, []]
        next_cursor, keys = self.scan_results.pop(0)
        return [next_cursor, keys]


class UpstashStateStoreTest(unittest.TestCase):
    def test_put_get_delete(self) -> None:
        redis = FakeRedis()
        store = UpstashStateStore(redis)

        store.put("run:1", '{"state":"queued"}')
        self.assertEqual(store.get("run:1"), '{"state":"queued"}')

        store.delete("run:1")
        self.assertIsNone(store.get("run:1"))

    def test_get_serializes_non_string_values(self) -> None:
        redis = FakeRedis()
        redis.data["run:1"] = {"state": "queued"}
        store = UpstashStateStore(redis)

        self.assertEqual(store.get("run:1"), '{"state": "queued"}')

    def test_keys_walks_upstash_scan_cursor(self) -> None:
        redis = FakeRedis()
        redis.scan_results = [
            (12, ["oz-control-plane:in-flight:1"]),
            ("0", ["oz-control-plane:in-flight:2"]),
        ]
        store = UpstashStateStore(redis)

        self.assertEqual(
            store.keys("oz-control-plane:in-flight:"),
            [
                "oz-control-plane:in-flight:1",
                "oz-control-plane:in-flight:2",
            ],
        )
        self.assertEqual(
            redis.scan_calls,
            [
                (0, "oz-control-plane:in-flight:*"),
                (12, "oz-control-plane:in-flight:*"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
