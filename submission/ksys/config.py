"""Optional configuration (DECISIONS.md D-015).

No config file means the default: everything in memory, nothing written to disk. That is what
evaluators get. A config file is only for development or a persistent deployment.

Lookup order:
  1. the path in the KSYS_CONFIG environment variable
  2. ksys.config.json in the submission folder (gitignored; see ksys.config.example.json)

Recognised settings:
  {"cache": {"backend": "sqlite", "path": "cache/ksys.sqlite3"}}
A relative path is resolved against the config file's folder. Anything else, a missing file
or an unreadable one, falls back to the in-memory defaults.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SUBMISSION_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SUBMISSION_DIR / "ksys.config.json"


@dataclass(frozen=True)
class Config:
    cache_backend: str = "memory"        # "memory" or "sqlite"
    cache_path: Optional[Path] = None    # set when cache_backend == "sqlite"
    source: Optional[Path] = None        # config file that produced this, if any


def load_config() -> Config:
    env = os.environ.get("KSYS_CONFIG")
    path = Path(env).expanduser() if env else DEFAULT_CONFIG
    if not path.is_file():
        return Config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"[ksys] ignoring unreadable config {path}: {e}", file=sys.stderr)
        return Config()
    cache = data.get("cache") or {}
    if str(cache.get("backend", "")).lower() != "sqlite" or not cache.get("path"):
        return Config(source=path)
    p = Path(str(cache["path"])).expanduser()
    if not p.is_absolute():
        p = path.parent / p
    return Config(cache_backend="sqlite", cache_path=p, source=path)
