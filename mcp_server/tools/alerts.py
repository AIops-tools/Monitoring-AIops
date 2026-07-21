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
@governed_tool(risk_level="medium")
@tool_errors("dict")
def alert_acknowledge(
    alert_id: str, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=medium] Acknowledge one active alert (reversible triage action).

    Pass dry_run=True to preview (reports the platform whose acknowledge API
    would be called — the three platforms take different endpoints and different
    id shapes, so it is the part of this call most worth confirming first).

    Args:
        alert_id: Alert id (AlertActiveID on SolarWinds, sensor objid on PRTG,
            problem event id on Zabbix).
        dry_run: If True, preview without acknowledging.
        target: Monitoring target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {
            "dryRun": True,
            "wouldAcknowledge": {
                "alertId": alert_id,
                "platform": conn.target.platform,
            },
        }
    return ops.acknowledge_alert(conn, alert_id)
