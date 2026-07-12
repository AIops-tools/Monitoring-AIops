"""One-shot NOC overview (read-only).

A single call an agent can lead with: the target's platform, its active-alert
count + unacknowledged count, and the top rolled-up alert groups. Resilient — a
failing sub-call degrades to a partial summary with an ``errors`` list.
"""

from __future__ import annotations

from typing import Any

from monitoring_aiops.ops import alerts as al


def fleet_overview(conn: Any) -> dict:
    """[READ] NOC summary: platform + active/unacked alert counts + top rollup."""
    errors: list[str] = []
    a = al.active_alerts(conn)
    if "error" in a:
        errors.append(f"alerts: {a['error']}")
        a = {}
    return {
        "platform": conn.target.platform,
        "target": conn.target.name,
        "activeAlerts": a.get("total"),
        "unacknowledged": a.get("unacknowledged"),
        "topRollup": (a.get("rollup") or [])[:5],
        "errors": errors,
    }
