"""Zabbix governed writes — event acknowledge + maintenance windows.

Three state changes, all through ``conn.zabbix_rpc``:

  * **acknowledge_event** — ``event.acknowledge`` (action 6 = acknowledge + add
    message). No inverse tool is exposed, but ``priorState`` faithfully records
    the event's acknowledged flag (read via ``event.get`` BEFORE the change).
  * **create_maintenance** — ``maintenance.create`` with a single one-time
    period. Always **time-boxed** (minutes > 0, matching the line-wide "no
    open-ended maintenance" rule) and must name at least one host or group.
    The returned maintenance id makes the undo a replayable
    ``delete_maintenance`` of exactly that id.
  * **delete_maintenance** — ``maintenance.delete``; the window's FULL
    definition is captured into ``priorState`` first (deletion is otherwise
    unrecoverable), which is why the MCP layer treats it as risk=high.
"""

from __future__ import annotations

import time
from typing import Any

from monitoring_aiops.ops._util import s


def _dicts(result: Any) -> list[dict]:
    return [r for r in (result or []) if isinstance(r, dict)] if isinstance(result, list) else []


def acknowledge_event(conn: Any, event_id: str, message: str = "acknowledged") -> dict:
    """[WRITE][low] Acknowledge one Zabbix problem event (with a message).

    Captures the event's BEFORE acknowledged state into ``priorState``.
    """
    prior = _dicts(conn.zabbix_rpc("event.get", {
        "eventids": [str(event_id)],
        "output": ["eventid", "acknowledged"],
    }))
    was_acked = bool(prior) and str(prior[0].get("acknowledged")) == "1"
    conn.zabbix_rpc("event.acknowledge", {
        "eventids": [str(event_id)],
        "action": 6,  # 2 = acknowledge + 4 = add message
        "message": message,
    })
    return {
        "action": "acknowledge_event",
        "eventId": s(event_id),
        "priorState": {"acknowledged": was_acked},
    }


def create_maintenance(
    conn: Any,
    name: str,
    minutes: int,
    host_ids: list[str] | None = None,
    group_ids: list[str] | None = None,
) -> dict:
    """[WRITE][med] Create a time-boxed maintenance window. Undo: delete it.

    Requires ``minutes > 0`` (no open-ended maintenance) and at least one host
    or host group. Returns the new ``maintenanceId`` so the harness can record
    a replayable ``delete_maintenance`` undo for exactly that window.
    """
    if minutes <= 0:
        raise ValueError(
            "create_maintenance requires minutes > 0 — a maintenance window must "
            "be time-boxed (no open-ended maintenance)."
        )
    if not host_ids and not group_ids:
        raise ValueError(
            "create_maintenance requires at least one host_ids or group_ids entry "
            "— a maintenance window must name what it covers (use zabbix_hosts / "
            "zabbix_hostgroups to find ids)."
        )
    now = int(time.time())
    params: dict = {
        "name": name,
        "active_since": now,
        "active_till": now + minutes * 60,
        "timeperiods": [{"timeperiod_type": 0, "start_date": now, "period": minutes * 60}],
    }
    if host_ids:
        params["hosts"] = [{"hostid": str(h)} for h in host_ids]
    if group_ids:
        params["groups"] = [{"groupid": str(g)} for g in group_ids]
    result = conn.zabbix_rpc("maintenance.create", params)
    ids = result.get("maintenanceids", []) if isinstance(result, dict) else []
    return {
        "action": "create_maintenance",
        "name": s(name),
        "minutes": minutes,
        "maintenanceId": s(ids[0]) if ids else "",
        "hosts": [s(h) for h in (host_ids or [])],
        "groups": [s(g) for g in (group_ids or [])],
    }


def maintenance_definition(conn: Any, maintenance_id: str) -> dict:
    """Read one maintenance window's full definition (for priorState / dry-run)."""
    raw = _dicts(conn.zabbix_rpc("maintenance.get", {
        "maintenanceids": [str(maintenance_id)],
        "output": "extend",
        "selectHosts": ["hostid", "host"],
        "selectHostGroups": ["groupid", "name"],
        "selectTimeperiods": "extend",
    }))
    if not raw:
        return {}
    r = raw[0]
    return {
        "maintenanceId": s(r.get("maintenanceid")),
        "name": s(r.get("name")),
        "activeSince": s(r.get("active_since")),
        "activeTill": s(r.get("active_till")),
        "description": s(r.get("description")),
        "hosts": [
            {"hostId": s(h.get("hostid")), "host": s(h.get("host"))}
            for h in _dicts(r.get("hosts"))
        ],
        "groups": [
            {"groupId": s(g.get("groupid")), "name": s(g.get("name"))}
            for g in _dicts(r.get("hostgroups") or r.get("groups"))
        ],
        "timeperiods": [
            {"type": s(p.get("timeperiod_type")), "startDate": s(p.get("start_date")),
             "period": s(p.get("period"))}
            for p in _dicts(r.get("timeperiods"))
        ],
    }


def delete_maintenance(conn: Any, maintenance_id: str) -> dict:
    """[WRITE][high] Delete a maintenance window. IRREVERSIBLE — no undo.

    Captures the window's FULL definition into ``priorState`` BEFORE deleting
    (audit trail + manual re-creation are the only way back).
    """
    prior = maintenance_definition(conn, maintenance_id)
    if not prior:
        raise ValueError(
            f"Maintenance '{s(maintenance_id, 32)}' not found — nothing to delete. "
            f"Use zabbix_maintenances to list current windows."
        )
    conn.zabbix_rpc("maintenance.delete", [str(maintenance_id)])
    return {
        "action": "delete_maintenance",
        "maintenanceId": s(maintenance_id),
        "priorState": prior,
    }
