"""PRTG governed writes — pause / resume / maintenance windows.

PRTG's classic HTTP API drives these state changes:

  * **pause** an object indefinitely (``/api/pause.htm?action=0``) or for a fixed
    window (``/api/pauseobjectfor.htm?duration=…``) — silences a noisy sensor.
  * **resume** an object (``/api/pause.htm?action=1``) — the inverse of pause.
  * a **maintenance window** is just a time-boxed pause, so it must always carry
    a positive duration (no open-ended maintenance).

Each write returns a plain descriptor; ``pause_sensor`` also records the BEFORE
state (``priorState``) so the MCP layer can wire a ``resume_sensor`` undo.
"""

from __future__ import annotations

from typing import Any

from monitoring_aiops.ops._util import s


def pause_sensor(conn: Any, object_id: str, minutes: int = 0, message: str = "paused") -> dict:
    """[WRITE][med] Pause a PRTG object (open-ended, or for ``minutes`` if > 0)."""
    if minutes > 0:
        conn.prtg_post(
            "/api/pauseobjectfor.htm",
            {"id": object_id, "duration": minutes, "pausemsg": message},
        )
    else:
        conn.prtg_post(
            "/api/pause.htm",
            {"id": object_id, "action": 0, "pausemsg": message},
        )
    return {
        "action": "pause_sensor",
        "objectId": s(object_id),
        "minutes": minutes,
        "priorState": {"paused": False},
    }


def resume_sensor(conn: Any, object_id: str) -> dict:
    """[WRITE][med] Resume a paused PRTG object (the inverse of pause_sensor)."""
    conn.prtg_post("/api/pause.htm", {"id": object_id, "action": 1})
    return {"action": "resume_sensor", "objectId": s(object_id)}


def schedule_maintenance(conn: Any, object_id: str, minutes: int) -> dict:
    """[WRITE][med] Time-boxed pause acting as a maintenance window (minutes > 0)."""
    if minutes <= 0:
        raise ValueError(
            "schedule_maintenance requires minutes > 0 — a maintenance window must be "
            "time-boxed. For an open-ended pause use pause_sensor."
        )
    conn.prtg_post(
        "/api/pauseobjectfor.htm",
        {"id": object_id, "duration": minutes, "pausemsg": "maintenance"},
    )
    return {"action": "schedule_maintenance_prtg", "objectId": s(object_id), "minutes": minutes}
