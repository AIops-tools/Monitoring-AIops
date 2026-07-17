"""Zabbix monitoring surface (Zabbix 6.x/7.x, read-only).

Thin, resilient wrappers over the Zabbix JSON-RPC API mapped onto the tool's
canonical surface: ``problem.get`` → active alerts (with the 0-5 severity scale
mapped to canonical levels), ``host.get`` + interfaces + ``hostgroup.get`` →
node/sensor health inventory, ``trigger.get`` → firing triggers, ``event.get`` →
recent events, ``maintenance.get`` → maintenance windows, and a **bounded**
``item.get`` + ``history.get`` pair for metric detail. Every call is wrapped so
a transport/parse failure surfaces as ``{"error": ...}`` instead of raising, and
all server text reaches the caller only after ``sanitize()`` via ``s``.

The connection handles the JSON-RPC envelope + token auth, so these functions
only pass method + params.
"""

from __future__ import annotations

import time
from typing import Any

from monitoring_aiops.ops._util import s

# Zabbix problem/trigger severity scale (0-5) → the platform's own names…
SEVERITY_NAMES = {
    0: "not_classified",
    1: "information",
    2: "warning",
    3: "average",
    4: "high",
    5: "disaster",
}
# …and the canonical alert levels the rest of this tool speaks.
SEVERITY_LEVELS = {
    0: "info",
    1: "info",
    2: "warning",
    3: "warning",
    4: "high",
    5: "critical",
}

# Bounds for the metric-detail read (history.get can be an unbounded firehose).
MAX_HISTORY_HOURS = 168  # one week
MAX_HISTORY_POINTS = 500


def severity_of(value: Any) -> dict:
    """Map a raw Zabbix severity (0-5, often a string) to name + level."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 0
    n = n if n in SEVERITY_NAMES else 0
    return {"severity": SEVERITY_NAMES[n], "level": SEVERITY_LEVELS[n], "severityCode": n}


def _dicts(result: Any) -> list[dict]:
    """JSON-RPC results are lists of objects; keep only the dict rows."""
    return [r for r in (result or []) if isinstance(r, dict)] if isinstance(result, list) else []


def list_problems(conn: Any, min_severity: int = 0) -> dict:
    """[READ] Current problems (active alerts) with severity mapped to levels."""
    try:
        params: dict = {
            "output": ["eventid", "objectid", "name", "severity", "acknowledged", "clock"],
            "recent": False,
            "sortfield": ["eventid"],
            "sortorder": "DESC",
        }
        if min_severity > 0:
            params["severities"] = list(range(min_severity, 6))
        raw = _dicts(conn.zabbix_rpc("problem.get", params))
        problems = [{
            "eventId": s(r.get("eventid")),
            "triggerId": s(r.get("objectid")),
            "name": s(r.get("name")),
            **severity_of(r.get("severity")),
            "acknowledged": str(r.get("acknowledged")) == "1",
            "clock": s(r.get("clock")),
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(problems), "problems": problems}


def list_hosts(conn: Any) -> dict:
    """[READ] Monitored hosts with interfaces + owning groups (health inventory)."""
    try:
        raw = _dicts(conn.zabbix_rpc("host.get", {
            "output": ["hostid", "host", "name", "status", "active_available"],
            "selectInterfaces": ["ip", "dns", "port", "type", "available"],
            "selectHostGroups": ["groupid", "name"],
        }))
        hosts = [{
            "hostId": s(r.get("hostid")),
            "host": s(r.get("host")),
            "name": s(r.get("name")),
            # status: 0 = monitored, 1 = unmonitored (disabled)
            "monitored": str(r.get("status")) == "0",
            "interfaces": [{
                "ip": s(i.get("ip")),
                "dns": s(i.get("dns")),
                "port": s(i.get("port")),
                # available: 0 unknown, 1 available, 2 unavailable
                "available": s(i.get("available")),
            } for i in _dicts(r.get("interfaces"))],
            "groups": [s(g.get("name")) for g in _dicts(r.get("hostgroups") or r.get("groups"))],
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(hosts), "hosts": hosts}


def list_hostgroups(conn: Any) -> dict:
    """[READ] Host groups (the Zabbix inventory grouping)."""
    try:
        raw = _dicts(conn.zabbix_rpc("hostgroup.get", {"output": ["groupid", "name"]}))
        groups = [{"groupId": s(r.get("groupid")), "name": s(r.get("name"))} for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(groups), "groups": groups}


def list_triggers(conn: Any, only_problems: bool = True) -> dict:
    """[READ] Triggers (default: only those currently in PROBLEM state)."""
    try:
        params: dict = {
            "output": ["triggerid", "description", "priority", "value", "lastchange"],
            "selectHosts": ["host"],
            "sortfield": "priority",
            "sortorder": "DESC",
        }
        if only_problems:
            params["filter"] = {"value": 1}  # 1 = PROBLEM
            params["only_true"] = True
        raw = _dicts(conn.zabbix_rpc("trigger.get", params))
        triggers = [{
            "triggerId": s(r.get("triggerid")),
            "description": s(r.get("description")),
            **severity_of(r.get("priority")),
            "inProblem": str(r.get("value")) == "1",
            "lastChange": s(r.get("lastchange")),
            "hosts": [s(h.get("host")) for h in _dicts(r.get("hosts"))],
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(triggers), "triggers": triggers}


def list_events(conn: Any, top: int = 50) -> dict:
    """[READ] Most recent trigger events (newest first, capped at ``top``)."""
    try:
        raw = _dicts(conn.zabbix_rpc("event.get", {
            "output": ["eventid", "name", "severity", "acknowledged", "clock", "value"],
            "source": 0,  # trigger events
            "sortfield": ["clock", "eventid"],
            "sortorder": "DESC",
            "limit": max(1, min(int(top), 500)),
        }))
        events = [{
            "eventId": s(r.get("eventid")),
            "name": s(r.get("name")),
            **severity_of(r.get("severity")),
            "acknowledged": str(r.get("acknowledged")) == "1",
            "clock": s(r.get("clock")),
            "problem": str(r.get("value")) == "1",
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(events), "events": events}


def item_history(conn: Any, item_id: str, hours: int = 24, limit: int = 100) -> dict:
    """[READ] Bounded metric detail: one item's meta + recent history points.

    ``item.get`` first resolves the item's ``value_type`` (history.get needs it
    as the ``history`` selector); the window is capped at ``MAX_HISTORY_HOURS``
    and the point count at ``MAX_HISTORY_POINTS`` so an agent can never pull an
    unbounded firehose.
    """
    try:
        hours = max(1, min(int(hours), MAX_HISTORY_HOURS))
        limit = max(1, min(int(limit), MAX_HISTORY_POINTS))
        items = _dicts(conn.zabbix_rpc("item.get", {
            "itemids": [str(item_id)],
            "output": ["itemid", "name", "key_", "value_type", "units", "lastvalue"],
        }))
        if not items:
            return {"error": f"Item '{s(item_id, 32)}' not found.", "itemId": s(item_id)}
        item = items[0]
        raw = _dicts(conn.zabbix_rpc("history.get", {
            "itemids": [str(item_id)],
            "history": int(item.get("value_type", 0)),
            "time_from": int(time.time()) - hours * 3600,
            "sortfield": "clock",
            "sortorder": "DESC",
            "limit": limit,
        }))
        points = [{"clock": s(r.get("clock")), "value": s(r.get("value"))} for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "itemId": s(item_id)}
    return {
        "itemId": s(item_id),
        "name": s(item.get("name")),
        "key": s(item.get("key_")),
        "units": s(item.get("units")),
        "lastValue": s(item.get("lastvalue")),
        "hours": hours,
        "points": points,
    }


def list_maintenances(conn: Any) -> dict:
    """[READ] Maintenance windows with their hosts/groups and time periods."""
    try:
        raw = _dicts(conn.zabbix_rpc("maintenance.get", {
            "output": ["maintenanceid", "name", "active_since", "active_till", "description"],
            "selectHosts": ["hostid", "host"],
            "selectHostGroups": ["groupid", "name"],
        }))
        windows = [{
            "maintenanceId": s(r.get("maintenanceid")),
            "name": s(r.get("name")),
            "activeSince": s(r.get("active_since")),
            "activeTill": s(r.get("active_till")),
            "hosts": [s(h.get("host")) for h in _dicts(r.get("hosts"))],
            "groups": [s(g.get("name")) for g in _dicts(r.get("hostgroups") or r.get("groups"))],
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(windows), "maintenances": windows}
