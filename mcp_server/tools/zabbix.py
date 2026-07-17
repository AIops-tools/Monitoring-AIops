"""Zabbix monitoring MCP tools (Zabbix 6.x/7.x, read-only)."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from monitoring_aiops.governance import governed_tool
from monitoring_aiops.ops import zabbix as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def zabbix_problems(min_severity: int = 0, target: Optional[str] = None) -> dict:
    """[READ] Current Zabbix problems (active alerts) with mapped severity levels.

    Args:
        min_severity: Only problems at this Zabbix severity (0-5) or above.
        target: Zabbix target name from config; omit for the default.
    """
    return ops.list_problems(_get_connection(target), min_severity)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def zabbix_hosts(target: Optional[str] = None) -> dict:
    """[READ] Zabbix hosts with interfaces + owning groups (health inventory).

    Args:
        target: Zabbix target name from config; omit for the default.
    """
    return ops.list_hosts(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def zabbix_hostgroups(target: Optional[str] = None) -> dict:
    """[READ] Zabbix host groups (ids + names, for inventory and maintenance).

    Args:
        target: Zabbix target name from config; omit for the default.
    """
    return ops.list_hostgroups(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def zabbix_triggers(only_problems: bool = True, target: Optional[str] = None) -> dict:
    """[READ] Zabbix triggers, by default only those currently firing (PROBLEM).

    Args:
        only_problems: If True (default), only triggers in PROBLEM state.
        target: Zabbix target name from config; omit for the default.
    """
    return ops.list_triggers(_get_connection(target), only_problems)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def zabbix_events(top: int = 50, target: Optional[str] = None) -> dict:
    """[READ] Most recent Zabbix trigger events (newest first).

    Args:
        top: Number of events to return (newest first, capped at 500).
        target: Zabbix target name from config; omit for the default.
    """
    return ops.list_events(_get_connection(target), top)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def zabbix_item_history(
    item_id: str, hours: int = 24, limit: int = 100, target: Optional[str] = None
) -> dict:
    """[READ] Bounded metric detail for one Zabbix item (meta + history points).

    Args:
        item_id: Zabbix item id (from the host's items).
        hours: Look-back window in hours (capped at 168).
        limit: Max history points to return (capped at 500).
        target: Zabbix target name from config; omit for the default.
    """
    return ops.item_history(_get_connection(target), item_id, hours, limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def zabbix_maintenances(target: Optional[str] = None) -> dict:
    """[READ] Zabbix maintenance windows with their hosts/groups and periods.

    Args:
        target: Zabbix target name from config; omit for the default.
    """
    return ops.list_maintenances(_get_connection(target))
