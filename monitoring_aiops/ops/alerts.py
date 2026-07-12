"""Active alerts + acknowledge (platform-aware).

Reads the active-alert firehose from whichever platform the target is, and
**dedups/rolls up** repeats of the same message (the interface-flap / node-down
storm problem operators complain about) so an agent sees "12× interface down"
instead of 12 rows. ``acknowledge_alert`` is the flagship light write.
"""

from __future__ import annotations

from typing import Any

from monitoring_aiops.config import PLATFORM_SOLARWINDS
from monitoring_aiops.ops._util import rows, s

_SW_ACTIVE = (
    "SELECT a.AlertActiveID, a.AlertObjectID, ao.EntityCaption, a.TriggeredMessage, "
    "a.TriggeredDateTime, a.Acknowledged FROM Orion.AlertActive a "
    "JOIN Orion.AlertObjects ao ON a.AlertObjectID=ao.AlertObjectID"
)


def _dedup(items: list[dict], key: str) -> list[dict]:
    """Roll up rows sharing the same ``key`` message into one with a count."""
    groups: dict[str, dict] = {}
    for it in items:
        k = it.get(key) or "(no message)"
        g = groups.setdefault(k, {"message": s(k), "count": 0, "examples": []})
        g["count"] += 1
        if len(g["examples"]) < 3:
            g["examples"].append(it)
    return sorted(groups.values(), key=lambda g: g["count"], reverse=True)


def active_alerts(conn: Any) -> dict:
    """[READ] Active alerts with dedup/rollup by message. Works on SW and PRTG."""
    platform = conn.target.platform
    try:
        if platform == PLATFORM_SOLARWINDS:
            raw = conn.swql(_SW_ACTIVE)
            norm = [{
                "id": s(r.get("AlertActiveID")),
                "entity": s(r.get("EntityCaption")),
                "message": s(r.get("TriggeredMessage")),
                "acknowledged": bool(r.get("Acknowledged")),
                "triggeredAt": s(r.get("TriggeredDateTime")),
            } for r in raw]
        else:  # PRTG — sensors in a non-up state are the active alarms
            data = conn.prtg_get("/api/table.json", {
                "content": "sensors",
                "columns": "objid,sensor,device,status,message",
                "filter_status": "5",  # 5 = down
            })
            norm = [{
                "id": s(r.get("objid")),
                "entity": s(r.get("device")),
                "message": s(r.get("message") or r.get("sensor")),
                "acknowledged": False,
                "status": s(r.get("status")),
            } for r in rows(data, "sensors")]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "platform": platform}

    return {
        "platform": platform,
        "total": len(norm),
        "unacknowledged": sum(1 for a in norm if not a.get("acknowledged")),
        "rollup": _dedup(norm, "message"),
    }


def acknowledge_alert(conn: Any, alert_id: str) -> dict:
    """[WRITE][low] Acknowledge one active alert (SolarWinds or PRTG)."""
    platform = conn.target.platform
    if platform == PLATFORM_SOLARWINDS:
        conn.swis_invoke("Orion.AlertActive", "Acknowledge", [[int(alert_id)], "acknowledged"])
    else:
        conn.prtg_post("/api/acknowledgealarm.htm", {"id": alert_id, "ackmsg": "acknowledged"})
    return {"action": "acknowledge_alert", "platform": platform, "alertId": s(alert_id)}
