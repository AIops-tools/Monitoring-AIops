"""Extra unit coverage for SolarWinds suppression/unmanage/maintenance ops.

MagicMock connection (no real Orion). Asserts the suppression/unmanage/muted
reads normalize + degrade to partials, the unmanage_node BEFORE-state capture,
the remove_node caption capture, and the node-ref SWIS verb envelopes.
"""

from unittest.mock import MagicMock

import pytest


def _conn(swql_return=None, swql_side_effect=None):
    conn = MagicMock(name="conn")
    conn.target.platform = "solarwinds"
    if swql_side_effect is not None:
        conn.swql.side_effect = swql_side_effect
    elif swql_return is not None:
        conn.swql.return_value = swql_return
    return conn


@pytest.mark.unit
def test_list_events_normalizes_and_caps_with_top_param():
    from monitoring_aiops.ops import sw_write as ops

    conn = _conn([
        {"EventID": 1, "EventTime": "t1", "Message": "boot", "NetworkNode": "n1"},
    ])
    out = ops.list_events(conn, top=10)
    assert out["total"] == 1 and out["events"][0]["message"] == "boot"
    query, params = conn.swql.call_args.args
    assert params == {"n": 10}
    assert "TOP @n" in query


@pytest.mark.unit
def test_list_unmanaged_and_muted_normalize():
    from monitoring_aiops.ops import sw_write as ops

    um = ops.list_unmanaged(_conn([
        {"Caption": "n1", "UnManaged": True, "UnManageFrom": "a", "UnManageUntil": "b"},
    ]))
    assert um["nodes"][0]["unmanaged"] is True
    mu = ops.list_muted(_conn([
        {"EntityUri": "swis://x", "SuppressFrom": "a", "SuppressUntil": "b"},
    ]))
    assert mu["muted"][0]["entityUri"] == "swis://x"


@pytest.mark.unit
def test_reads_degrade_to_partial_error():
    from monitoring_aiops.ops import sw_write as ops

    for fn in (ops.list_events, ops.list_unmanaged, ops.list_muted):
        out = fn(_conn(swql_side_effect=RuntimeError("swis down")))
        assert "swis down" in out["error"]


@pytest.mark.unit
def test_node_caption_reads_and_defaults_empty():
    from monitoring_aiops.ops import sw_write as ops

    assert ops.node_caption(_conn([{"Caption": "web01"}]), 42) == "web01"
    assert ops.node_caption(_conn([]), 99) == ""


@pytest.mark.unit
def test_unmute_alerts_dispatches_resume_verb():
    from monitoring_aiops.ops import sw_write as ops

    conn = _conn()
    ops.unmute_alerts(conn, "swis://x")
    entity, verb, args = conn.swis_invoke.call_args.args
    assert (entity, verb) == ("Orion.AlertSuppression", "ResumeAlerts")
    assert args == [["swis://x"]]


@pytest.mark.unit
def test_unmanage_node_captures_prior_unmanaged_flag():
    from monitoring_aiops.ops import sw_write as ops

    conn = _conn([{"UnManaged": True}])  # node was ALREADY unmanaged
    out = ops.unmanage_node(conn, 7, "2026-07-12T00:00:00Z", "2026-07-12T02:00:00Z")
    assert out["priorState"] == {"unmanaged": True}
    # BEFORE-state read binds the node id…
    read_query, read_params = conn.swql.call_args.args
    assert read_params == {"id": 7}
    # …and the write dispatches Unmanage with an N:<id> net-object ref.
    _entity, verb, args = conn.swis_invoke.call_args.args
    assert verb == "Unmanage" and args[0] == "N:7"


@pytest.mark.unit
def test_unmanage_node_requires_end_time():
    from monitoring_aiops.ops import sw_write as ops

    with pytest.raises(ValueError, match="end time"):
        ops.unmanage_node(_conn([{"UnManaged": False}]), 7, "start", "")


@pytest.mark.unit
def test_remanage_node_dispatches_remanage():
    from monitoring_aiops.ops import sw_write as ops

    conn = _conn()
    out = ops.remanage_node(conn, 7)
    assert out["action"] == "remanage_node"
    _entity, verb, args = conn.swis_invoke.call_args.args
    assert verb == "Remanage" and args == ["N:7"]


@pytest.mark.unit
def test_remove_node_captures_caption_before_delete():
    from monitoring_aiops.ops import sw_write as ops

    conn = _conn([{"Caption": "doomed01"}])  # caption read happens first
    out = ops.remove_node(conn, 7)
    assert out["caption"] == "doomed01"
    _entity, verb, args = conn.swis_invoke.call_args.args
    assert verb == "Delete" and args == ["N:7"]
