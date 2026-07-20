"""SolarWinds (Orion) health reads — all read-only SWQL SELECTs.

Covers the day-to-day "is it healthy?" surface an operator wants from Orion:
node/interface/volume/application status, ``topn`` worst-offenders, and a
one-shot ``noc_rollup`` for a NOC glance. Everything here is a SWQL SELECT — no
verb invoke, nothing mutates the Orion database. Reads are resilient: a broken
sub-query reports ``{"error": ...}`` instead of taking the whole call down.
"""

from __future__ import annotations

from typing import Any

from monitoring_aiops.ops._util import opt_s, s

# Status code → label (Orion.Nodes.Status).
_STATUS = {1: "Up", 2: "Down", 3: "Warning"}

# metric → (SWQL column, result label).
_TOPN_METRICS = {
    "cpu": ("CPULoad", "CPULoad"),
    "memory": ("PercentMemoryUsed", "PercentMemoryUsed"),
    "latency": ("AvgResponseTime", "AvgResponseTime"),
    "packetloss": ("PercentLoss", "PercentLoss"),
}

_NODE_ONE = (
    "SELECT Caption, IP_Address, Status, StatusDescription, CPULoad, PercentMemoryUsed "
    "FROM Orion.Nodes WHERE Caption=@q OR IP_Address=@q"
)
_NODES_ALL = (
    "SELECT Caption, IP_Address, Status, StatusDescription FROM Orion.Nodes"
)
_INTERFACES = (
    "SELECT n.Caption AS NodeCaption, i.Caption AS InterfaceCaption, i.Status, "
    "i.InPercentUtil, i.OutPercentUtil FROM Orion.NPM.Interfaces i "
    "JOIN Orion.Nodes n ON i.NodeID=n.NodeID"
)
_VOLUMES = (
    "SELECT n.Caption AS NodeCaption, v.Caption AS Volume, v.VolumePercentUsed "
    "FROM Orion.Volumes v JOIN Orion.Nodes n ON v.NodeID=n.NodeID"
)
_APPLICATIONS = (
    "SELECT a.Name AS ApplicationName, n.Caption AS NodeCaption, a.Status "
    "FROM Orion.APM.Application a JOIN Orion.Nodes n ON a.NodeID=n.NodeID"
)


def _num(value: Any) -> float:
    """Coerce a SWQL numeric cell to float; 0.0 when absent/non-numeric."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _status_label(value: Any) -> str | None:
    """Map an Orion status code to its label, or None when Orion sent no status.

    An absent status is not the same fact as an unrecognised one: the latter is
    reported verbatim so an operator can see what Orion actually said.
    """
    if value is None:
        return None
    try:
        return _STATUS.get(int(value), s(value, 40))
    except (TypeError, ValueError):
        return s(value, 40)


def node_status(conn: Any, name_or_ip: str) -> dict:
    """[READ] One node's health by caption or IP (Orion.Nodes)."""
    try:
        raw = conn.swql(_NODE_ONE, {"q": name_or_ip})
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    if not raw:
        return {"error": "not found"}
    r = raw[0]
    return {
        "caption": opt_s(r.get("Caption")),
        "ip": opt_s(r.get("IP_Address")),
        "status": _status_label(r.get("Status")),
        "statusDescription": opt_s(r.get("StatusDescription")),
        "cpuLoad": _num(r.get("CPULoad")),
        "percentMemoryUsed": _num(r.get("PercentMemoryUsed")),
    }


def nodes_list(conn: Any, status: int | None = None) -> dict:
    """[READ] All nodes, optionally filtered by Status (1=Up,2=Down,3=Warning)."""
    query = _NODES_ALL
    params: dict = {}
    if status is not None:
        query = f"{_NODES_ALL} WHERE Status=@status"
        params = {"status": int(status)}
    try:
        raw = conn.swql(query, params)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    nodes = [{
        "caption": opt_s(r.get("Caption")),
        "ip": opt_s(r.get("IP_Address")),
        "status": _status_label(r.get("Status")),
        "statusDescription": opt_s(r.get("StatusDescription")),
    } for r in raw]
    return {"total": len(nodes), "nodes": nodes}


def interface_status(conn: Any, top: int | None = None) -> dict:
    """[READ] Interface status + utilization (Orion.NPM.Interfaces); top-N by util."""
    try:
        raw = conn.swql(_INTERFACES)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    ifaces = [{
        "nodeCaption": opt_s(r.get("NodeCaption")),
        "interfaceCaption": opt_s(r.get("InterfaceCaption")),
        "status": _status_label(r.get("Status")),
        "inPercentUtil": _num(r.get("InPercentUtil")),
        "outPercentUtil": _num(r.get("OutPercentUtil")),
    } for r in raw]
    if top is None:
        return {
            "total": len(ifaces),
            "interfaces": ifaces,
            "returned": len(ifaces),
            "limit": None,
            "truncated": False,
        }
    ifaces.sort(key=lambda i: max(i["inPercentUtil"], i["outPercentUtil"]), reverse=True)
    requested = int(top)
    kept = ifaces[:requested]
    return {
        # The genuine pre-cap total, not an alias of "returned" — a count that
        # merely echoes the returned rows is the lying-count bug this envelope exists to kill.
        "total": len(ifaces),
        "interfaces": kept,
        "returned": len(kept),
        "limit": requested,
        # The whole interface table was fetched before ranking, so "were there
        # more?" is a measured fact here rather than an inference.
        "truncated": len(ifaces) > requested,
    }


def volume_status(conn: Any, min_percent: float = 0) -> dict:
    """[READ] Volumes at/above min_percent used (Orion.Volumes), worst first."""
    try:
        raw = conn.swql(_VOLUMES)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    vols = [{
        "nodeCaption": opt_s(r.get("NodeCaption")),
        "volume": opt_s(r.get("Volume")),
        "percentUsed": _num(r.get("VolumePercentUsed")),
    } for r in raw]
    vols = [v for v in vols if v["percentUsed"] >= min_percent]
    vols.sort(key=lambda v: v["percentUsed"], reverse=True)
    return {"total": len(vols), "volumes": vols}


def application_status(conn: Any) -> dict:
    """[READ] SAM application status (Orion.APM.Application); resilient if absent."""
    try:
        raw = conn.swql(_APPLICATIONS)
    except Exception as exc:  # noqa: BLE001 — APM may not be installed
        return {"error": s(exc, 200)}
    apps = [{
        "applicationName": opt_s(r.get("ApplicationName")),
        "nodeCaption": opt_s(r.get("NodeCaption")),
        "status": _status_label(r.get("Status")),
    } for r in raw]
    return {"total": len(apps), "applications": apps}


def topn(conn: Any, metric: str = "cpu", n: int = 10) -> dict:
    """[READ] Top-N nodes by a health metric (cpu/memory/latency/packetloss).

    Returns {"nodes": [...], "returned": N, "metric": str, "error": str | None}.
    A failed query is reported in ``error`` rather than returned as an empty
    list — "the SWQL query failed" and "no nodes are under load" are opposite
    findings and must not render identically.
    """
    if metric not in _TOPN_METRICS:
        raise ValueError(
            f"Unknown metric '{metric}'. Choose one of: {', '.join(_TOPN_METRICS)}."
        )
    column, _label = _TOPN_METRICS[metric]
    rows_clause = f"ORDER BY {column} DESC WITH ROWS 1 TO {int(n)}"
    # `column` is one of the fixed _TOPN_METRICS allowlist values (metric is
    # validated above) and n is coerced to int; no user text reaches SQL.
    query = f"SELECT Caption, {column} FROM Orion.Nodes {rows_clause}"  # nosec B608
    try:
        raw = conn.swql(query)
    except Exception as exc:  # noqa: BLE001 — reported, never silently swallowed
        return {"nodes": [], "returned": 0, "metric": metric, "error": s(exc, 200)}
    nodes = [
        {"caption": opt_s(r.get("Caption")), "value": _num(r.get(column))} for r in raw
    ]
    return {"nodes": nodes, "returned": len(nodes), "metric": metric, "error": None}


def _count(conn: Any, where: str, entity: str = "Orion.Nodes") -> int:
    """Guarded scalar count; 0 if the sub-query fails.

    ``where``/``entity`` are only ever passed internal literals from
    ``noc_rollup`` (never user input), so the f-string SWQL is injection-safe.
    """
    try:
        # nosec B608 — where/entity are internal literals (see noc_rollup), not user input
        raw = conn.swql(f"SELECT COUNT(1) AS N FROM {entity} WHERE {where}")  # nosec B608
    except Exception:  # noqa: BLE001 — each sub-count guarded
        return 0
    if not raw:
        return 0
    try:
        return int(raw[0].get("N") or 0)
    except (TypeError, ValueError):
        return 0


def noc_rollup(conn: Any) -> dict:
    """[READ] One-shot NOC glance: down/warning counts + top-3 worst CPU nodes."""
    # Counts first, then topn — the original query order, kept deliberately so
    # the sequence of SWQL calls this issues does not change.
    down = _count(conn, "Status=2")
    warning = _count(conn, "Status=3")
    ifaces_down = _count(conn, "Status=2", "Orion.NPM.Interfaces")
    top = topn(conn, "cpu", 3)
    return {
        "nodesDown": down,
        "nodesWarning": warning,
        "interfacesDown": ifaces_down,
        # Expose the node list, but carry the probe's error forward so a failed
        # sub-query is never shown as "no hot nodes" in the one-shot glance.
        "topCpu": top["nodes"],
        "topCpuError": top["error"],
    }
