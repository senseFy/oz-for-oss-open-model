"""Filesystem-backed state store for local runtime deployments."""

from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
from pathlib import Path


class FileStateStore:
    """Durable local :class:`core.state.StateStore` implementation."""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def put(self, key: str, value: str) -> None:
        payload = {"key": key, "value": value}
        path = self._path_for_key(key)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(path.parent),
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                temp_name = handle.name
            os.replace(temp_name, path)

    def get(self, key: str) -> str | None:
        path = self._path_for_key(key)
        with self._lock:
            if not path.is_file():
                return None
            try:
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError):
                return None
        if not isinstance(payload, dict) or payload.get("key") != key:
            return None
        value = payload.get("value")
        return value if isinstance(value, str) else None

    def delete(self, key: str) -> None:
        path = self._path_for_key(key)
        with self._lock:
            try:
                path.unlink()
            except FileNotFoundError:
                return

    def keys(self, prefix: str) -> list[str]:
        found: list[str] = []
        with self._lock:
            paths = sorted(self.base_dir.glob("*.json"))
            for path in paths:
                try:
                    with path.open("r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                key = payload.get("key")
                if isinstance(key, str) and key.startswith(prefix):
                    found.append(key)
        return found

    def _path_for_key(self, key: str) -> Path:
        encoded = base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii")
        return self.base_dir / f"{encoded.rstrip('=')}.json"


__all__ = ["FileStateStore"]
