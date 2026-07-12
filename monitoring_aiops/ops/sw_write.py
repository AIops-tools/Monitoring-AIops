"""SolarWinds suppression / unmanage / maintenance — governed writes + reads.

This is the flagship *write* surface for SolarWinds Orion: mute (alert
suppression), unmanage (maintenance windows), and node removal, plus a handful
of suppression/unmanage reads so an agent can see current state before acting.

All state changes go through ``conn.swis_invoke`` (a SWIS verb). Reversible
writes capture the object's BEFORE state with a ``conn.swql`` read into
``priorState`` so the harness can record a faithful undo. The two footgun writes
— ``unmanage_node`` (masks monitoring) and ``remove_node`` (deletes the node) —
are risk=high at the MCP layer with a ``dry_run`` preview.

SolarWinds-only: every call funnels through ``conn.swql`` / ``conn.swis_invoke``,
which raise a clear ``MonitoringApiError`` if the target is a PRTG target.
"""

from __future__ import annotations

from typing import Any

from monitoring_aiops.ops._util import s

_EVENTS = (
    "SELECT TOP @n EventID, EventTime, Message, NetworkNode FROM Orion.Events "
    "ORDER BY EventTime DESC"
)
_UNMANAGED = (
    "SELECT Caption, UnManaged, UnManageFrom, UnManageUntil FROM Orion.Nodes "
    "WHERE UnManaged=true OR UnManageUntil > GETUTCDATE() ORDER BY UnManageUntil"
)
_MUTED = (
    "SELECT EntityUri, SuppressFrom, SuppressUntil FROM Orion.AlertSuppression "
    "ORDER BY SuppressUntil"
)
_NODE_UNMANAGED = "SELECT UnManaged FROM Orion.Nodes WHERE NodeID=@id"
_NODE_CAPTION = "SELECT Caption FROM Orion.Nodes WHERE NodeID=@id"


def _node_ref(node_id: Any) -> str:
    """SWIS net-object ref for a node, e.g. ``N:42``."""
    return f"N:{node_id}"


# ── reads (risk=low, resilient) ───────────────────────────────────────────


def list_events(conn: Any, top: int = 50) -> dict:
    """[READ] Most recent Orion events (newest first, capped at ``top``)."""
    try:
        raw = conn.swql(_EVENTS, {"n": top})
        norm = [{
            "id": s(r.get("EventID")),
            "eventTime": s(r.get("EventTime")),
            "message": s(r.get("Message")),
            "node": s(r.get("NetworkNode")),
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(norm), "events": norm}


def list_unmanaged(conn: Any) -> dict:
    """[READ] Nodes unmanaged now or with a scheduled future unmanage window."""
    try:
        raw = conn.swql(_UNMANAGED)
        norm = [{
            "caption": s(r.get("Caption")),
            "unmanaged": bool(r.get("UnManaged")),
            "unmanageFrom": s(r.get("UnManageFrom")),
            "unmanageUntil": s(r.get("UnManageUntil")),
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(norm), "nodes": norm}


def list_muted(conn: Any) -> dict:
    """[READ] Objects currently in an alert-suppression (muted) window."""
    try:
        raw = conn.swql(_MUTED)
        norm = [{
            "entityUri": s(r.get("EntityUri")),
            "suppressFrom": s(r.get("SuppressFrom")),
            "suppressUntil": s(r.get("SuppressUntil")),
        } for r in raw]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(norm), "muted": norm}


def node_caption(conn: Any, node_id: Any) -> str:
    """Read a node's current caption (best-effort; empty string if unknown)."""
    result = conn.swql(_NODE_CAPTION, {"id": node_id})
    if isinstance(result, list) and result:
        return s(result[0].get("Caption"))
    return ""


# ── writes ────────────────────────────────────────────────────────────────


def mute_alerts(conn: Any, entity_uri: str, minutes: int = 60) -> dict:
    """[WRITE] Time-boxed alert suppression for an entity. Inverse: unmute_alerts.

    ``priorState`` records that the entity was not suppressed before this call so
    the harness can record a faithful undo (resume alerts).
    """
    conn.swis_invoke("Orion.AlertSuppression", "SuppressAlerts", [[entity_uri]])
    return {
        "action": "mute_alerts",
        "entityUri": s(entity_uri),
        "minutes": minutes,
        "priorState": {"suppressed": False},
    }


def unmute_alerts(conn: Any, entity_uri: str) -> dict:
    """[WRITE] Resume alerts for an entity (lift suppression). Inverse of mute."""
    conn.swis_invoke("Orion.AlertSuppression", "ResumeAlerts", [[entity_uri]])
    return {"action": "unmute_alerts", "entityUri": s(entity_uri)}


def schedule_maintenance(conn: Any, node_id: Any, start_iso: str, end_iso: str) -> dict:
    """[WRITE] Schedule a bounded maintenance window (unmanage between start/end).

    An end time is REQUIRED — no open-ended maintenance (which would silently
    mask a node's monitoring forever).
    """
    if not end_iso:
        raise ValueError(
            "schedule_maintenance requires an end time (no open-ended maintenance). "
            "Pass end_iso as an ISO-8601 UTC timestamp."
        )
    conn.swis_invoke("Orion.Nodes", "Unmanage", [_node_ref(node_id), start_iso, end_iso, False])
    return {
        "action": "schedule_maintenance",
        "nodeId": s(node_id),
        "start": s(start_iso),
        "end": s(end_iso),
    }


def unmanage_node(conn: Any, node_id: Any, start_iso: str, end_iso: str) -> dict:
    """[WRITE] Unmanage a node (mask its monitoring). Inverse: remanage_node.

    Requires an end time. Captures the node's current ``UnManaged`` flag into
    ``priorState`` before the change so the harness can record an undo.
    """
    if not end_iso:
        raise ValueError(
            "unmanage_node requires an end time (no open-ended unmanage). "
            "Pass end_iso as an ISO-8601 UTC timestamp."
        )
    prior = conn.swql(_NODE_UNMANAGED, {"id": node_id})
    was_unmanaged = bool(prior[0].get("UnManaged")) if isinstance(prior, list) and prior else False
    conn.swis_invoke("Orion.Nodes", "Unmanage", [_node_ref(node_id), start_iso, end_iso, False])
    return {
        "action": "unmanage_node",
        "nodeId": s(node_id),
        "start": s(start_iso),
        "end": s(end_iso),
        "priorState": {"unmanaged": was_unmanaged},
    }


def remanage_node(conn: Any, node_id: Any) -> dict:
    """[WRITE] Return a node to managed state (lift unmanage). Inverse of unmanage."""
    conn.swis_invoke("Orion.Nodes", "Remanage", [_node_ref(node_id)])
    return {"action": "remanage_node", "nodeId": s(node_id)}


def remove_node(conn: Any, node_id: Any) -> dict:
    """[WRITE] Permanently delete a node from Orion. IRREVERSIBLE — no undo.

    Captures the node's caption first (for the audit trail / dry-run preview).
    """
    caption = node_caption(conn, node_id)
    conn.swis_invoke("Orion.Nodes", "Delete", [_node_ref(node_id)])
    return {"action": "remove_node", "nodeId": s(node_id), "caption": caption}
