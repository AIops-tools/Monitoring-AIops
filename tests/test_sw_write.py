"""Unit tests for the SolarWinds suppression / unmanage / maintenance surface.

Proves: mute captures prior state and dispatches the SuppressAlerts verb;
schedule_maintenance passes a bounded end time; risk tiers are correct
(unmanage/remove = high, the rest = medium); the high-risk unmanage_node dry_run
preview does not mutate; and the mute undo descriptor inverts to unmute with the
same entity URI. No real SolarWinds is needed — the connection is a MagicMock.
"""

from unittest.mock import MagicMock

import pytest


def _sw_conn() -> MagicMock:
    conn = MagicMock(name="conn")
    conn.target.platform = "solarwinds"
    return conn


@pytest.mark.unit
def test_mute_alerts_dispatches_verb_and_captures_prior_state():
    from monitoring_aiops.ops import sw_write as ops

    conn = _sw_conn()
    out = ops.mute_alerts(conn, "swis://orion/Orion.Nodes/NodeID=1", minutes=30)

    assert out["action"] == "mute_alerts"
    assert out["minutes"] == 30
    assert out["priorState"] == {"suppressed": False}
    entity, verb, args = conn.swis_invoke.call_args.args
    assert entity == "Orion.AlertSuppression"
    assert verb == "SuppressAlerts"
    assert args == [["swis://orion/Orion.Nodes/NodeID=1"]]


@pytest.mark.unit
def test_schedule_maintenance_passes_start_and_end():
    from monitoring_aiops.ops import sw_write as ops

    conn = _sw_conn()
    out = ops.schedule_maintenance(conn, 42, "2026-07-12T00:00:00Z", "2026-07-12T02:00:00Z")

    assert out["action"] == "schedule_maintenance"
    assert out["start"] == "2026-07-12T00:00:00Z"
    _entity, verb, args = conn.swis_invoke.call_args.args
    assert verb == "Unmanage"
    # args = [N:42, start, end, False] — the end time must be passed through.
    assert args[2] == "2026-07-12T02:00:00Z"
    # An open-ended (missing end) maintenance must be refused.
    with pytest.raises(ValueError):
        ops.schedule_maintenance(conn, 42, "2026-07-12T00:00:00Z", "")


@pytest.mark.unit
def test_risk_tiers():
    from mcp_server.tools import sw_write as t

    assert t.unmanage_node._risk_level == "high"
    assert t.remove_node._risk_level == "high"
    assert t.mute_alerts._risk_level == "medium"
    assert t.unmute_alerts._risk_level == "medium"
    assert t.schedule_maintenance._risk_level == "medium"
    assert t.remanage_node._risk_level == "medium"


@pytest.mark.unit
def test_unmanage_node_dry_run_does_not_mutate(monkeypatch):
    from mcp_server.tools import sw_write as t

    conn = _sw_conn()
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)
    result = t.unmanage_node(
        node_id=7, start_iso="2026-07-12T00:00:00Z", end_iso="2026-07-12T02:00:00Z",
        dry_run=True,
    )

    assert result["dryRun"] is True
    assert result["wouldUnmanage"]["nodeId"] == 7
    conn.swis_invoke.assert_not_called()


@pytest.mark.unit
def test_mute_undo_descriptor_inverts_to_unmute():
    from mcp_server.tools import sw_write as t

    params = {"entity_uri": "swis://orion/Orion.Nodes/NodeID=1", "minutes": 30}
    descriptor = t._mute_undo(params, {"action": "mute_alerts"})

    assert descriptor["tool"] == "unmute_alerts"
    assert descriptor["params"]["entity_uri"] == "swis://orion/Orion.Nodes/NodeID=1"
