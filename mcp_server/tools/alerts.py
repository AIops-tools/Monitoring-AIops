"""Active-alert MCP tools (SolarWinds + PRTG): rollup read + acknowledge."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from monitoring_aiops.governance import governed_tool
from monitoring_aiops.ops import alerts as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def active_alerts(target: Optional[str] = None) -> dict:
    """[READ] Active alerts with dedup/rollup by message (SolarWinds or PRTG).

    Rolls up storms (e.g. interface-flap repeats) into one counted entry so the
    signal isn't buried under duplicates.

    Args:
        target: Monitoring target name from config; omit for the default.
    """
    return ops.active_alerts(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def alert_acknowledge(alert_id: str, target: Optional[str] = None) -> dict:
    """[WRITE][risk=low] Acknowledge one active alert (reversible triage action).

    Args:
        alert_id: Alert id (AlertActiveID on SolarWinds, sensor objid on PRTG).
        target: Monitoring target name from config; omit for the default.
    """
    return ops.acknowledge_alert(_get_connection(target), alert_id)
