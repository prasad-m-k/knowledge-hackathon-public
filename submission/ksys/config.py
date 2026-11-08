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
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ksys.config")

SUBMISSION_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SUBMISSION_DIR / "ksys.config.json"


@dataclass(frozen=True)
class Config:
    cache_backend: str = "memory"        # "memory" or "sqlite"
    cache_path: Optional[Path] = None    # set when cache_backend == "sqlite"
    source: Optional[Path] = None        # config file that produced this, if any
    log_level: str = "WARNING"           # logging level (overridable via KSYS_LOG_LEVEL)


def _configure_logging(level_name: str) -> None:
    root = logging.getLogger("ksys")
    level = getattr(logging, level_name.upper(), logging.WARNING)
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
        root.addHandler(handler)


def load_config() -> Config:
    env_level = os.environ.get("KSYS_LOG_LEVEL", "WARNING").upper()
    _configure_logging(env_level)
    env = os.environ.get("KSYS_CONFIG")
    path = Path(env).expanduser() if env else DEFAULT_CONFIG
    if not path.is_file():
        return Config(log_level=env_level)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("config root must be a JSON object")
    except (OSError, ValueError) as e:
        logger.warning("ignoring unreadable config %s: %s", path, e)
        return Config(log_level=env_level)
    level = str(data.get("log_level", env_level)).upper()
    _configure_logging(level)
    cache = data.get("cache") or {}
    if not isinstance(cache, dict) or str(cache.get("backend", "")).lower() != "sqlite" or not cache.get("path"):
        return Config(source=path, log_level=level)
    p = Path(str(cache["path"])).expanduser()
    if not p.is_absolute():
        p = path.parent / p
    return Config(cache_backend="sqlite", cache_path=p, source=path, log_level=level)
