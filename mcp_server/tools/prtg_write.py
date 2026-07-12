"""PRTG governed-write MCP tools: pause / resume / maintenance window."""

from typing import Any, Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from monitoring_aiops.governance import governed_tool
from monitoring_aiops.ops import prtg_write as ops


def _pause_undo(params: dict[str, Any], result: dict[str, Any]) -> dict:
    """Inverse of pause_sensor: resume the same object (reads result['priorState'])."""
    return {
        "tool": "resume_sensor",
        "params": {"object_id": params.get("object_id")},
        "note": f"resume paused object (priorState={result.get('priorState')})",
    }


@mcp.tool()
@governed_tool(risk_level="medium", undo=_pause_undo)
@tool_errors("dict")
def pause_sensor(
    object_id: str,
    minutes: int = 0,
    message: str = "paused",
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=medium] Pause a PRTG object; reversible via resume_sensor.

    Open-ended when minutes is 0, otherwise auto-resumes after ``minutes``.

    Args:
        object_id: PRTG object id (sensor/device/group) to pause.
        minutes: Auto-resume after this many minutes; 0 pauses indefinitely.
        message: Pause message shown in PRTG.
        target: Monitoring target name from config; omit for the default.
    """
    return ops.pause_sensor(_get_connection(target), object_id, minutes, message)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def resume_sensor(object_id: str, target: Optional[str] = None) -> dict:
    """[WRITE][risk=medium] Resume a paused PRTG object (inverse of pause_sensor).

    Args:
        object_id: PRTG object id to resume.
        target: Monitoring target name from config; omit for the default.
    """
    return ops.resume_sensor(_get_connection(target), object_id)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def schedule_maintenance_prtg(object_id: str, minutes: int, target: Optional[str] = None) -> dict:
    """[WRITE][risk=medium] Time-boxed maintenance window (a pause of ``minutes``).

    Requires minutes > 0 — maintenance windows are never open-ended.

    Args:
        object_id: PRTG object id to place in maintenance.
        minutes: Maintenance duration in minutes (must be > 0).
        target: Monitoring target name from config; omit for the default.
    """
    return ops.schedule_maintenance(_get_connection(target), object_id, minutes)
