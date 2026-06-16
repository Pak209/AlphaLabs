"""
alpha_lab/env.py — minimal, dependency-free .env loader.

The app reads configuration (API keys, feature flags, paths) from environment
variables. In local dev those live in a ``.env`` file at the project root. We
load them here without pulling in python-dotenv so the dependency footprint stays
tiny and the loader's exact rules are visible and testable.

Rules (chosen to be safe and predictable):
  * The real process environment ALWAYS wins. A variable already set in the
    shell is never overwritten, so ``POLYGON_API_KEY=x python -m alpha_lab.main``
    still takes precedence over the .env file. (override=True flips this.)
  * Blank lines and ``#`` comment lines are ignored. A leading ``export`` is
    tolerated (``export FOO=bar``).
  * Surrounding single/double quotes around a value are stripped. Inside double
    quotes, ``#`` is literal; for unquoted values a trailing `` # comment`` is
    stripped.
  * Malformed lines are skipped silently — a bad .env never crashes startup.

This module imports nothing from the rest of the package, so it is safe to call
from ``alpha_lab/__init__`` before any other submodule reads ``os.getenv``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def find_dotenv(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from ``start`` (default: this file's dir) looking for a .env."""
    here = (start or Path(__file__).resolve()).parent
    for directory in (here, *here.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def _strip_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    # Unquoted: drop an inline comment that is preceded by whitespace.
    hash_idx = value.find(" #")
    if hash_idx != -1:
        value = value[:hash_idx].rstrip()
    return value


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse .env file text into a dict. Pure — easy to unit test."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if not key:
            continue
        out[key] = _strip_value(raw)
    return out


def load_dotenv(path: Optional[Path] = None, *, override: bool = False) -> dict[str, str]:
    """Load a .env file into ``os.environ`` and return the values applied.

    Returns the parsed key/value pairs that were actually set (respecting the
    ``override`` rule). Missing file -> no-op, returns ``{}``.
    """
    dotenv_path = path or find_dotenv()
    if not dotenv_path or not dotenv_path.is_file():
        return {}
    try:
        parsed = parse_dotenv(dotenv_path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    applied: dict[str, str] = {}
    for key, value in parsed.items():
        if override or key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied
