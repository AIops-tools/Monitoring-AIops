"""Shared helpers for Monitoring ops modules.

SolarWinds SWIS returns ``{"results": [...]}`` (unwrapped to rows by the
connection's ``swql``); PRTG returns objects/arrays under keys like ``sensors``.
``rows`` / ``as_obj`` normalise access, and all server text reaches the caller
only after ``sanitize()`` (output hygiene: control/format-char stripping + truncation).
"""

from __future__ import annotations

from typing import Any

from monitoring_aiops.governance import sanitize


def rows(data: Any, key: str = "") -> list[dict]:
    """Return a list of dict rows from a list, or from ``data[key]`` if a dict."""
    if isinstance(data, dict):
        items = data.get(key, []) if key else data.get("results", [])
    else:
        items = data
    return [r for r in (items or []) if isinstance(r, dict)]


def as_obj(data: Any) -> dict:
    """Return ``data`` as a dict (empty dict if it isn't one)."""
    return data if isinstance(data, dict) else {}


def s(value: Any, limit: int = 256) -> str:
    """Sanitize an arbitrary value to a bounded, injection-safe string."""
    return sanitize(str(value if value is not None else ""), limit)
