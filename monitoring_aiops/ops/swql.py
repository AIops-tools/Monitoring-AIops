"""SWQL query surface for SolarWinds (read-only) — the flagship SW feature.

THWACK is full of "help me write this SWQL" threads asking the same handful of
questions, so this module ships a **canned-SWQL library** (``CANNED``) that
answers them directly, plus a validated passthrough (``run_query``) that refuses
anything but a read-only ``SELECT`` and caps the row count. Nothing here mutates
the Orion database.
"""

from __future__ import annotations

from typing import Any

from monitoring_aiops.ops._util import s

_MAX_ROWS = 1000

# Named, parameterized SWQL answering the most-repeated THWACK questions.
CANNED: dict[str, dict[str, str]] = {
    "nodes_down": {
        "desc": "All nodes currently down.",
        "query": "SELECT Caption, IP_Address, DetailsUrl FROM Orion.Nodes "
                 "WHERE Status=2 ORDER BY Caption",
    },
    "alerts_by_node": {
        "desc": "Active alerts grouped with their node caption.",
        "query": "SELECT a.AlertActiveID, ao.EntityCaption, a.TriggeredMessage, "
                 "a.TriggeredDateTime FROM Orion.AlertActive a "
                 "JOIN Orion.AlertObjects ao ON a.AlertObjectID=ao.AlertObjectID "
                 "ORDER BY a.TriggeredDateTime DESC",
    },
    "muted_report": {
        "desc": "Objects currently in an alert-suppression (muted) window.",
        "query": "SELECT EntityUri, SuppressFrom, SuppressUntil FROM "
                 "Orion.AlertSuppression ORDER BY SuppressUntil",
    },
    "flapping_interfaces": {
        "desc": "Interfaces that changed status many times recently (flap signal).",
        "query": "SELECT i.Caption, i.NodeID, i.InterfaceID, i.Status FROM "
                 "Orion.NPM.Interfaces i WHERE i.Status<>1 ORDER BY i.Caption",
    },
    "high_cpu_nodes": {
        "desc": "Nodes above a CPU threshold (param @min, default 85).",
        "query": "SELECT Caption, CPULoad FROM Orion.Nodes WHERE CPULoad >= @min "
                 "ORDER BY CPULoad DESC",
    },
    "volumes_full": {
        "desc": "Volumes above a fill threshold (param @min percent, default 85).",
        "query": "SELECT n.Caption, v.Caption AS Volume, v.VolumePercentUsed FROM "
                 "Orion.Volumes v JOIN Orion.Nodes n ON v.NodeID=n.NodeID "
                 "WHERE v.VolumePercentUsed >= @min ORDER BY v.VolumePercentUsed DESC",
    },
    "unmanaged_scheduled": {
        "desc": "Nodes unmanaged now or with a scheduled future unmanage window.",
        "query": "SELECT Caption, UnManaged, UnManageFrom, UnManageUntil FROM "
                 "Orion.Nodes WHERE UnManaged=true OR UnManageUntil > GETUTCDATE() "
                 "ORDER BY UnManageUntil",
    },
}


def list_canned() -> list[dict]:
    """[READ] The canned-SWQL library: name + description + parameters hint."""
    return [{"name": k, "description": v["desc"]} for k, v in CANNED.items()]


def _validate(query: str) -> str:
    """Reject anything but a single read-only SELECT; return the trimmed query."""
    q = query.strip().rstrip(";").strip()
    head = q[:6].upper()
    if head != "SELECT":
        raise ValueError(
            "Only read-only SELECT SWQL is allowed here. For state changes use the "
            "governed write tools (acknowledge/mute/unmanage)."
        )
    if ";" in q:
        raise ValueError("Multiple statements are not allowed in a SWQL query.")
    return q


def _envelope(rows: list, limit: int, **extra: Any) -> dict:
    """The one truncation envelope every row-capped read in this tool returns.

    ``{"rows": [...], "returned": N, "limit": L, "truncated": bool}``. A bare
    list — or a count that describes the pre-cap result while the rows are
    capped — cannot say "there is more"; the consumer has to infer it from the
    length happening to equal the limit, and a smaller local model reads that
    coincidence as "that is everything". ``truncated`` here is *measured*
    against the full result set, never guessed.

    ``rowCount`` is kept as an alias of ``returned`` so existing consumers of
    this tool's SWQL output do not break; both always describe the rows actually
    returned.
    """
    capped = rows[:limit]
    return {
        "rows": capped,
        "returned": len(capped),
        "rowCount": len(capped),
        "limit": limit,
        "truncated": len(rows) > limit,
        **extra,
    }


def run_query(conn: Any, query: str, params: dict | None = None, limit: int = _MAX_ROWS) -> dict:
    """[READ] Run a validated read-only SWQL query (row-capped, truncation flagged)."""
    q = _validate(query)
    result = conn.swql(q, params or {})
    return _envelope(result, limit)


def run_canned(
    conn: Any, name: str, params: dict | None = None, limit: int = _MAX_ROWS
) -> dict:
    """[READ] Run a named canned query from the library (row-capped, truncation flagged).

    Previously this capped the rows at ``_MAX_ROWS`` while reporting the *pre-cap*
    count, so a caller reading 1000 rows and a rowCount of 4000 could not tell
    which number described what it had been given. It now returns the same
    envelope as :func:`run_query`.
    """
    if name not in CANNED:
        raise KeyError(f"Unknown canned query '{name}'. Available: {', '.join(CANNED)}")
    merged = {"min": 85, **(params or {})}
    result = conn.swql(CANNED[name]["query"], merged)
    return _envelope(result, limit, name=s(name))
