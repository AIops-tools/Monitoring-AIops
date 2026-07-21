"""Zabbix governed-write MCP tools: maintenance window create / delete.

``create_maintenance`` records a **replayable undo**: deleting exactly the
maintenance id it created. ``delete_maintenance`` is the footgun (the window's
definition is gone) — risk=high with a ``dry_run`` preview, and the full BEFORE
definition is captured into ``priorState`` for the audit trail.

(Acknowledging a Zabbix problem goes through the cross-platform
``alert_acknowledge`` tool, which records the prior ack state.)
"""

from typing import Any, Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from monitoring_aiops.governance import governed_tool
from monitoring_aiops.ops import zabbix_write as ops


def _create_maintenance_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of zabbix_create_maintenance: delete THAT maintenance id."""
    if not isinstance(result, dict) or not result.get("maintenanceId"):
        return None
    return {
        "tool": "zabbix_delete_maintenance",
        "params": {"maintenance_id": result["maintenanceId"]},
        "skill": "monitoring-aiops",
        "note": "Inverse of zabbix_create_maintenance: delete the created window.",
    }


@mcp.tool()
@governed_tool(risk_level="medium", undo=_create_maintenance_undo)
@tool_errors("dict")
def zabbix_create_maintenance(
    name: str,
    minutes: int,
    host_ids: Optional[list[str]] = None,
    group_ids: Optional[list[str]] = None,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=medium] Create a time-boxed Zabbix maintenance window.

    Requires minutes > 0 (never open-ended) and at least one host or group id.
    Reversible: the undo deletes exactly the maintenance id this call created.

    Args:
        name: Maintenance window name shown in Zabbix.
        minutes: Window length in minutes (must be > 0).
        host_ids: Host ids to cover (from zabbix_hosts).
        group_ids: Host-group ids to cover (from zabbix_hostgroups).
        target: Zabbix target name from config; omit for the default.
    """
    return ops.create_maintenance(_get_connection(target), name, minutes, host_ids, group_ids)


@mcp.tool()
@governed_tool(risk_level="high")
@tool_errors("dict")
def zabbix_delete_maintenance(
    maintenance_id: str, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=high] Delete a Zabbix maintenance window. IRREVERSIBLE — no undo.

    Pass dry_run=True to preview (reports the window's full definition).
    The BEFORE definition lands in priorState.

    Args:
        maintenance_id: Maintenance id to delete (from zabbix_maintenances).
        dry_run: If True, preview without deleting.
        target: Zabbix target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {"dryRun": True, "wouldDelete": ops.maintenance_definition(conn, maintenance_id)}
    return ops.delete_maintenance(conn, maintenance_id)
