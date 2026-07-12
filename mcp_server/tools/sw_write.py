"""SolarWinds suppression / unmanage / maintenance MCP tools (reads + writes).

Reversible writes (mute, unmanage) pass an ``undo=`` callback so the harness
records an inverse descriptor. The two footgun writes — ``unmanage_node`` (masks
monitoring) and ``remove_node`` (deletes the node) — are risk=high with a
``dry_run`` preview and require an approver under the graduated-autonomy policy.
"""

from typing import Any, Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from monitoring_aiops.governance import governed_tool
from monitoring_aiops.ops import sw_write as ops


def _mute_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of mute_alerts: resume alerts for the same entity."""
    if not isinstance(result, dict):
        return None
    return {
        "tool": "unmute_alerts",
        "params": {"entity_uri": params.get("entity_uri")},
        "skill": "monitoring-aiops",
        "note": "Inverse of mute_alerts: resume alerts for the entity.",
    }


def _unmanage_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of unmanage_node: return the node to managed state."""
    if not isinstance(result, dict):
        return None
    return {
        "tool": "remanage_node",
        "params": {"node_id": params.get("node_id")},
        "skill": "monitoring-aiops",
        "note": "Inverse of unmanage_node: return the node to managed.",
    }


# ── reads ──────────────────────────────────────────────────────────────────


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_events(top: int = 50, target: Optional[str] = None) -> dict:
    """[READ] Most recent SolarWinds Orion events (newest first).

    Args:
        top: Number of events to return (newest first).
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.list_events(_get_connection(target), top)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_unmanaged(target: Optional[str] = None) -> dict:
    """[READ] Nodes unmanaged now or with a scheduled future unmanage window.

    Args:
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.list_unmanaged(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_muted(target: Optional[str] = None) -> dict:
    """[READ] Objects currently in an alert-suppression (muted) window.

    Args:
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.list_muted(_get_connection(target))


# ── writes ─────────────────────────────────────────────────────────────────


@mcp.tool()
@governed_tool(risk_level="medium", undo=_mute_undo)
@tool_errors("dict")
def mute_alerts(entity_uri: str, minutes: int = 60, target: Optional[str] = None) -> dict:
    """[WRITE][risk=medium] Time-boxed alert suppression for an entity. Inverse: unmute_alerts.

    Args:
        entity_uri: SWIS entity URI to suppress (e.g. from list_muted / SWQL).
        minutes: Suppression window length in minutes.
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.mute_alerts(_get_connection(target), entity_uri, minutes)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def unmute_alerts(entity_uri: str, target: Optional[str] = None) -> dict:
    """[WRITE][risk=medium] Resume alerts for an entity (lift suppression).

    Args:
        entity_uri: SWIS entity URI to resume (from list_muted).
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.unmute_alerts(_get_connection(target), entity_uri)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def schedule_maintenance(
    node_id: int, start_iso: str, end_iso: str, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=medium] Schedule a bounded maintenance window for a node.

    An end time is REQUIRED — no open-ended maintenance.

    Args:
        node_id: Numeric Orion NodeID.
        start_iso: Window start (ISO-8601 UTC timestamp).
        end_iso: Window end (ISO-8601 UTC timestamp) — required.
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.schedule_maintenance(_get_connection(target), node_id, start_iso, end_iso)


@mcp.tool()
@governed_tool(risk_level="high", undo=_unmanage_undo)
@tool_errors("dict")
def unmanage_node(
    node_id: int,
    start_iso: str,
    end_iso: str,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=high] Unmanage a node — masks its monitoring. Inverse: remanage_node.

    Pass dry_run=True to preview. Requires an approver (set
    MONITORING_AUDIT_APPROVED_BY) under the graduated-autonomy policy. Reversible
    → remanage. An end time is required (no open-ended unmanage).

    Args:
        node_id: Numeric Orion NodeID.
        start_iso: Unmanage window start (ISO-8601 UTC timestamp).
        end_iso: Unmanage window end (ISO-8601 UTC timestamp) — required.
        dry_run: If True, preview without unmanaging.
        target: SolarWinds target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {"dryRun": True, "wouldUnmanage": {"nodeId": node_id}}
    return ops.unmanage_node(conn, node_id, start_iso, end_iso)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def remanage_node(node_id: int, target: Optional[str] = None) -> dict:
    """[WRITE][risk=medium] Return a node to managed state (lift unmanage).

    Args:
        node_id: Numeric Orion NodeID.
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.remanage_node(_get_connection(target), node_id)


@mcp.tool()
@governed_tool(risk_level="high")
@tool_errors("dict")
def remove_node(node_id: int, dry_run: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE][risk=high] Permanently delete a node from Orion. IRREVERSIBLE — no undo.

    Pass dry_run=True to preview (reports the node's caption). Requires an
    approver (MONITORING_AUDIT_APPROVED_BY) under the graduated-autonomy policy.

    Args:
        node_id: Numeric Orion NodeID to delete.
        dry_run: If True, preview without deleting.
        target: SolarWinds target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        caption = ops.node_caption(conn, node_id)
        return {"dryRun": True, "wouldRemove": {"nodeId": node_id, "caption": caption}}
    return ops.remove_node(conn, node_id)
