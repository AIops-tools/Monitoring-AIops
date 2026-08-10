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

from monitoring_aiops.ops._util import opt_s, s

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


def _hosts_for_events(conn: Any, event_ids: list) -> tuple[dict[str, str | None], str | None]:
    """Map eventid -> host name for the given problems, in ONE extra call.

    Returns ``(mapping, error)``. ``problem.get`` cannot return the host: it
    rejects ``selectHosts`` outright ("unexpected parameter", measured on Zabbix
    7.0.29). ``event.get`` accepts it, so the ids are resolved in a single
    batched follow-up rather than one call per problem.

    The host name is an enrichment, so a failed lookup must not cost the caller
    its alerts — but it must not hide either. A swallowed failure makes every
    ``host`` ``null``, which is indistinguishable from "these problems have no
    host", so the reason is returned and surfaced on the payload rather than
    dropped (bug class #3: a failure that looks like an absence).
    """
    ids = [str(e) for e in event_ids if e is not None]
    if not ids:
        return {}, None
    try:
        rows = _dicts(conn.zabbix_rpc("event.get", {
            "eventids": ids, "output": ["eventid"], "selectHosts": ["host"],
        }))
    except Exception as exc:  # noqa: BLE001 — reported, not swallowed
        return {}, s(exc, 200)
    out: dict[str, str | None] = {}
    for r in rows:
        hosts = [opt_s(h.get("host")) for h in _dicts(r.get("hosts"))]
        named = [h for h in hosts if h]
        # A trigger can span hosts; name them all rather than silently picking one.
        out[str(r.get("eventid"))] = ", ".join(named) if named else None
    return out, None


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
        hosts_by_event, host_error = _hosts_for_events(
            conn, [r.get("eventid") for r in raw]
        )
        problems = [{
            "eventId": opt_s(r.get("eventid")),
            "triggerId": opt_s(r.get("objectid")),
            "host": hosts_by_event.get(str(r.get("eventid"))),
            "name": opt_s(r.get("name")),
            **severity_of(r.get("severity")),
            "acknowledged": str(r.get("acknowledged")) == "1",
            "clock": opt_s(r.get("clock")),
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    out = {"total": len(problems), "problems": problems}
    if host_error:
        # Every "host" below is null because the lookup failed, NOT because the
        # problems have no host. Say which.
        out["hostLookupError"] = host_error
    return out


def list_hosts(conn: Any) -> dict:
    """[READ] Monitored hosts with interfaces + owning groups (health inventory)."""
    try:
        raw = _dicts(conn.zabbix_rpc("host.get", {
            "output": ["hostid", "host", "name", "status", "active_available"],
            "selectInterfaces": ["ip", "dns", "port", "type", "available"],
            "selectHostGroups": ["groupid", "name"],
        }))
        hosts = [{
            "hostId": opt_s(r.get("hostid")),
            "host": opt_s(r.get("host")),
            "name": opt_s(r.get("name")),
            # status: 0 = monitored, 1 = unmonitored (disabled)
            "monitored": str(r.get("status")) == "0",
            "interfaces": [{
                "ip": opt_s(i.get("ip")),
                "dns": opt_s(i.get("dns")),
                "port": opt_s(i.get("port")),
                # available: 0 unknown, 1 available, 2 unavailable
                "available": opt_s(i.get("available")),
            } for i in _dicts(r.get("interfaces"))],
            "groups": [opt_s(g.get("name"))
                       for g in _dicts(r.get("hostgroups") or r.get("groups"))],
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(hosts), "hosts": hosts}


def list_hostgroups(conn: Any) -> dict:
    """[READ] Host groups (the Zabbix inventory grouping)."""
    try:
        raw = _dicts(conn.zabbix_rpc("hostgroup.get", {"output": ["groupid", "name"]}))
        groups = [{"groupId": opt_s(r.get("groupid")), "name": opt_s(r.get("name"))} for r in raw]
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
            "triggerId": opt_s(r.get("triggerid")),
            "description": opt_s(r.get("description")),
            **severity_of(r.get("priority")),
            "inProblem": str(r.get("value")) == "1",
            "lastChange": opt_s(r.get("lastchange")),
            "hosts": [opt_s(h.get("host")) for h in _dicts(r.get("hosts"))],
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(triggers), "triggers": triggers}


def list_events(conn: Any, top: int = 50) -> dict:
    """[READ] Most recent trigger events (newest first, capped at ``top``).

    One event past the cap is requested so ``truncated`` is *measured* rather
    than guessed from the returned length happening to equal the cap — the
    coincidence a smaller local model reads as "that is every event".
    """
    requested = max(1, min(int(top), 500))
    try:
        raw = _dicts(conn.zabbix_rpc("event.get", {
            "output": ["eventid", "name", "severity", "acknowledged", "clock", "value"],
            "source": 0,  # trigger events
            "sortfield": ["clock", "eventid"],
            "sortorder": "DESC",
            "limit": requested + 1,
        }))
        truncated = len(raw) > requested
        raw = raw[:requested]
        events = [{
            "eventId": opt_s(r.get("eventid")),
            "name": opt_s(r.get("name")),
            **severity_of(r.get("severity")),
            "acknowledged": str(r.get("acknowledged")) == "1",
            "clock": opt_s(r.get("clock")),
            "problem": str(r.get("value")) == "1",
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {
        # No "total": the feed was over-fetched by one and sliced, so the real
        # server-side total is unknown. "truncated" says there is more; a
        # "total" echoing "returned" would claim otherwise.
        "events": events,
        "returned": len(events),
        "limit": requested,
        "truncated": truncated,
    }


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
            "limit": limit + 1,  # one extra: makes `truncated` measured, not guessed
        }))
        truncated = len(raw) > limit
        points = [{"clock": opt_s(r.get("clock")), "value": opt_s(r.get("value"))}
                  for r in raw[:limit]]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "itemId": s(item_id)}
    return {
        "itemId": s(item_id),
        "name": opt_s(item.get("name")),
        "key": opt_s(item.get("key_")),
        "units": opt_s(item.get("units")),
        "lastValue": opt_s(item.get("lastvalue")),
        "hours": hours,
        "points": points,
        "returned": len(points),
        "limit": limit,
        "truncated": truncated,
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
            "name": opt_s(r.get("name")),
            "activeSince": s(r.get("active_since")),
            "activeTill": s(r.get("active_till")),
            "hosts": [opt_s(h.get("host")) for h in _dicts(r.get("hosts"))],
            "groups": [opt_s(g.get("name"))
                       for g in _dicts(r.get("hostgroups") or r.get("groups"))],
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(windows), "maintenances": windows}
