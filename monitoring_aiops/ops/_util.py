"""Shared helpers for Monitoring ops modules.

SolarWinds SWIS returns ``{"results": [...]}`` (unwrapped to rows by the
connection's ``swql``); PRTG returns objects/arrays under keys like ``sensors``.
``rows`` / ``as_obj`` normalise access, and all server text reaches the caller
only after ``sanitize()`` (output hygiene: control/format-char stripping + truncation).
"""

from __future__ import annotations

from typing import Any

from monitoring_aiops.governance import opt_str, sanitize


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


def opt_s(value: Any, limit: int = 256) -> str | None:
    """Sanitize a value that may legitimately be absent, preserving that absence.

    Companion to :func:`s`, which folds ``None`` into ``""``. That conflation is
    invisible downstream: an empty string reads as "the platform returned this
    column and it was blank" when the truth may be "Orion/PRTG/Zabbix never
    returned the column at all" (a SWQL SELECT that omits it, a PRTG build that
    names the field differently, an unset Zabbix host field). Neither a consumer
    nor a smaller local model can recover the difference, and both invent one.

    Use this for any optional platform field; keep :func:`s` for values that are
    always present, such as a caller-supplied id being echoed back.
    """
    return opt_str(value, limit)
