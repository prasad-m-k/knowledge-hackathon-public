"""Cache store for ingest layers (DECISIONS.md D-013, D-015).

One small key-value interface, two backends:

  MemoryStore  default; plain dict, nothing on disk.
  SQLiteStore  only when the config asks for it; persists across runs (stdlib sqlite3).

Keys are namespaced by layer and already include the inputs and code version, e.g.
namespace "blocks", key "<content_hash>:v1". Values must be JSON-serialisable.
The store is used during ingest only; answer() reads in-memory structures (D-013).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from typing import Any, Dict, Optional, Tuple

from .config import Config, load_config


class MemoryStore:
    backend = "memory"

    def __init__(self) -> None:
        self._data: Dict[Tuple[str, str], str] = {}

    def get(self, namespace: str, key: str) -> Optional[Any]:
        raw = self._data.get((namespace, key))
        return None if raw is None else json.loads(raw)

    def put(self, namespace: str, key: str, value: Any) -> None:
        # Stored as JSON so both backends behave identically (no shared mutable objects).
        self._data[(namespace, key)] = json.dumps(value, sort_keys=True)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class SQLiteStore:
    backend = "sqlite"

    def __init__(self, path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the harness calls answer() from a worker thread. The store is
        # only written during ingest, but this keeps any late read from raising.
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache (ns TEXT NOT NULL, key TEXT NOT NULL, "
            "value TEXT NOT NULL, PRIMARY KEY (ns, key))"
        )
        self._db.commit()
        self.path = path

    def get(self, namespace: str, key: str) -> Optional[Any]:
        row = self._db.execute("SELECT value FROM cache WHERE ns = ? AND key = ?", (namespace, key)).fetchone()
        return None if row is None else json.loads(row[0])

    def put(self, namespace: str, key: str, value: Any) -> None:
        self._db.execute("INSERT OR REPLACE INTO cache (ns, key, value) VALUES (?, ?, ?)",
                         (namespace, key, json.dumps(value, sort_keys=True)))

    def flush(self) -> None:
        self._db.commit()

    def close(self) -> None:
        self._db.commit()
        self._db.close()


def open_store(config: Optional[Config] = None):
    """Store chosen by config. Any problem opening SQLite falls back to memory, never fails ingest."""
    config = config or load_config()
    if config.cache_backend == "sqlite" and config.cache_path is not None:
        try:
            return SQLiteStore(config.cache_path)
        except (OSError, sqlite3.Error) as e:
            print(f"[ksys] sqlite cache unavailable at {config.cache_path} ({e}); using memory", file=sys.stderr)
    return MemoryStore()
