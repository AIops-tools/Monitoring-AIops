"""PRTG monitoring MCP tools (Paessler PRTG, read-only)."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from monitoring_aiops.governance import governed_tool
from monitoring_aiops.ops import prtg as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def prtg_sensors(status: Optional[str] = None, target: Optional[str] = None) -> dict:
    """[READ] List PRTG sensors (objid, sensor, device, status, message, lastValue).

    Args:
        status: Optional PRTG status code to filter by (e.g. "5" for down).
        target: PRTG target name from config; omit for the default.
    """
    return ops.list_sensors(_get_connection(target), status)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def prtg_sensor_details(sensor_id: str, target: Optional[str] = None) -> dict:
    """[READ] Detailed status for one PRTG sensor (name, status, lastvalue, ...).

    Args:
        sensor_id: PRTG sensor object id (objid).
        target: PRTG target name from config; omit for the default.
    """
    return ops.sensor_details(_get_connection(target), sensor_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def prtg_devices(target: Optional[str] = None) -> dict:
    """[READ] List monitored PRTG devices (objid, device, host, status, group).

    Args:
        target: PRTG target name from config; omit for the default.
    """
    return ops.list_devices(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def prtg_groups(target: Optional[str] = None) -> dict:
    """[READ] List PRTG device groups with their rollup status.

    Args:
        target: PRTG target name from config; omit for the default.
    """
    return ops.list_groups(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def prtg_history(sensor_id: str, hours: int = 24, target: Optional[str] = None) -> dict:
    """[READ] Historic data points for one PRTG sensor over the recent window.

    Args:
        sensor_id: PRTG sensor object id (objid).
        hours: Look-back window in hours (default 24).
        target: PRTG target name from config; omit for the default.
    """
    return ops.sensor_history(_get_connection(target), sensor_id, hours)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def prtg_system_status(target: Optional[str] = None) -> dict:
    """[READ] System-wide PRTG sensor counters (up/down/warning/paused/alarms).

    Args:
        target: PRTG target name from config; omit for the default.
    """
    return ops.system_status(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def prtg_alarms(target: Optional[str] = None) -> dict:
    """[READ] Active PRTG alarms — sensors in a down state (status 5).

    Args:
        target: PRTG target name from config; omit for the default.
    """
    return ops.list_alarms(_get_connection(target))
