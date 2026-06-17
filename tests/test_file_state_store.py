from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from . import conftest  # noqa: F401

from runtime.stores.file import FileStateStore


class FileStateStoreTest(unittest.TestCase):
    def test_put_get_delete_and_prefix_listing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileStateStore(temp_dir)

            store.put("oz-control-plane:in-flight:run-1", '{"run_id":"run-1"}')
            store.put("other:key", "ignored")

            self.assertEqual(
                store.get("oz-control-plane:in-flight:run-1"),
                '{"run_id":"run-1"}',
            )
            self.assertEqual(
                store.keys("oz-control-plane:in-flight:"),
                ["oz-control-plane:in-flight:run-1"],
            )

            store.delete("oz-control-plane:in-flight:run-1")
            self.assertIsNone(store.get("oz-control-plane:in-flight:run-1"))
            self.assertEqual(store.keys("oz-control-plane:in-flight:"), [])

    def test_state_persists_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            FileStateStore(temp_dir).put("state:1", "value")

            self.assertEqual(FileStateStore(temp_dir).get("state:1"), "value")

    def test_malformed_files_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "broken.json").write_text("{", encoding="utf-8")
            store = FileStateStore(temp_dir)

            self.assertEqual(store.keys("state:"), [])


if __name__ == "__main__":
    unittest.main()
