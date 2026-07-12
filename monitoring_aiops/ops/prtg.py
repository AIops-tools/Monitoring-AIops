"""PRTG monitoring surface (Paessler PRTG, read-only).

Thin, resilient wrappers over the PRTG web API's table / status / details /
history endpoints. Everything here is a **read**: sensors, devices, groups, one
sensor's details + history, the system status counters, and the active-alarm
list (sensors in a down state). Every call is wrapped so a transport/parse
failure surfaces as ``{"error": ...}`` instead of raising, and all server text
reaches the caller only after ``sanitize()`` via the ``s`` helper.

The connection already appends the PRTG API token, so these functions only pass
``content`` / ``columns`` / ``filter_status`` (and ids) as params.
"""

from __future__ import annotations

from typing import Any

from monitoring_aiops.ops._util import as_obj, rows, s


def list_sensors(conn: Any, status: str | None = None) -> dict:
    """[READ] All sensors (optionally filtered by PRTG status code)."""
    try:
        params: dict = {
            "content": "sensors",
            "columns": "objid,sensor,device,status,message,lastvalue",
        }
        if status is not None:
            params["filter_status"] = s(status, 16)
        data = conn.prtg_get("/api/table.json", params)
        sensors = [{
            "objid": s(r.get("objid")),
            "sensor": s(r.get("sensor")),
            "device": s(r.get("device")),
            "status": s(r.get("status")),
            "message": s(r.get("message")),
            "lastValue": s(r.get("lastvalue")),
        } for r in rows(data, "sensors")]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(sensors), "sensors": sensors}


def sensor_details(conn: Any, sensor_id: str) -> dict:
    """[READ] Normalized details for one sensor (name, status, lastvalue, ...)."""
    try:
        data = conn.prtg_get("/api/getsensordetails.json", {"id": s(sensor_id, 32)})
        obj = as_obj(as_obj(data).get("sensordata")) or as_obj(data)
        return {
            "sensorId": s(sensor_id),
            "name": s(obj.get("name")),
            "status": s(obj.get("statustext") or obj.get("status")),
            "lastValue": s(obj.get("lastvalue")),
            "lastMessage": s(obj.get("lastmessage")),
            "sensorType": s(obj.get("sensortype")),
        }
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "sensorId": s(sensor_id)}


def list_devices(conn: Any) -> dict:
    """[READ] All monitored devices with host + status + owning group."""
    try:
        data = conn.prtg_get("/api/table.json", {
            "content": "devices",
            "columns": "objid,device,host,status,group",
        })
        devices = [{
            "objid": s(r.get("objid")),
            "device": s(r.get("device")),
            "host": s(r.get("host")),
            "status": s(r.get("status")),
            "group": s(r.get("group")),
        } for r in rows(data, "devices")]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(devices), "devices": devices}


def list_groups(conn: Any) -> dict:
    """[READ] All device groups with their rollup status."""
    try:
        data = conn.prtg_get("/api/table.json", {
            "content": "groups",
            "columns": "objid,group,status",
        })
        groups = [{
            "objid": s(r.get("objid")),
            "group": s(r.get("group")),
            "status": s(r.get("status")),
        } for r in rows(data, "groups")]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(groups), "groups": groups}


def sensor_history(conn: Any, sensor_id: str, hours: int = 24) -> dict:
    """[READ] Historic data points for one sensor over the recent window."""
    try:
        data = conn.prtg_get("/api/historicdata.json", {"id": s(sensor_id, 32), "avg": 0})
        points = [{
            "datetime": s(r.get("datetime")),
            "value": s(r.get("value") if r.get("value") is not None else r.get("value_raw")),
        } for r in rows(data, "histdata")]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "sensorId": s(sensor_id)}
    return {"sensorId": s(sensor_id), "hours": hours, "points": points}


def system_status(conn: Any) -> dict:
    """[READ] System-wide sensor-state counters (up/down/warning/paused/alarms)."""
    try:
        obj = as_obj(conn.prtg_get("/api/status.json"))
        pick = lambda *keys: next(  # noqa: E731 — first present key value
            (obj[k] for k in keys if obj.get(k) is not None), None
        )
        return {
            "sensorsUp": s(pick("totalsensorup", "upsens", "ok")) or None,
            "sensorsDown": s(pick("totalsensordown", "downsens", "down")) or None,
            "sensorsWarning": s(pick("totalsensorwarning", "warnsens", "warn")) or None,
            "sensorsPaused": s(pick("totalsensorpaused", "pausedsens", "paused")) or None,
            "alarms": s(pick("alarms", "totalalarms")) or None,
        }
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}


def list_alarms(conn: Any) -> dict:
    """[READ] Active alarms — sensors in a down state (PRTG status 5)."""
    try:
        data = conn.prtg_get("/api/table.json", {
            "content": "sensors",
            "columns": "objid,sensor,device,status,message",
            "filter_status": "5",
        })
        alarms = [{
            "objid": s(r.get("objid")),
            "sensor": s(r.get("sensor")),
            "device": s(r.get("device")),
            "status": s(r.get("status")),
            "message": s(r.get("message")),
        } for r in rows(data, "sensors")]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(alarms), "alarms": alarms}
