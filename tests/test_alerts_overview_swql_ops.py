"""Extra unit coverage for the platform-aware alerts surface, the NOC overview,
and the SWQL query surface (validation + canned library).

All against a MagicMock connection (no real SolarWinds / PRTG / Zabbix).
"""

from unittest.mock import MagicMock

import pytest


def _sw_conn():
    conn = MagicMock(name="conn")
    conn.target.platform = "solarwinds"
    conn.target.name = "orion1"
    return conn


def _prtg_conn():
    conn = MagicMock(name="conn")
    conn.target.platform = "prtg"
    conn.target.name = "prtg1"
    return conn


# ── alerts: SolarWinds + PRTG dedup/rollup ──────────────────────────────────


@pytest.mark.unit
def test_active_alerts_solarwinds_rolls_up_repeated_messages():
    from monitoring_aiops.ops import alerts as ops

    conn = _sw_conn()
    conn.swql.return_value = [
        {"AlertActiveID": 1, "EntityCaption": "gi1", "TriggeredMessage": "interface down",
         "TriggeredDateTime": "t1", "Acknowledged": False},
        {"AlertActiveID": 2, "EntityCaption": "gi2", "TriggeredMessage": "interface down",
         "TriggeredDateTime": "t2", "Acknowledged": False},
        {"AlertActiveID": 3, "EntityCaption": "n1", "TriggeredMessage": "node down",
         "TriggeredDateTime": "t3", "Acknowledged": True},
    ]
    out = ops.active_alerts(conn)
    assert out["platform"] == "solarwinds"
    assert out["total"] == 3 and out["unacknowledged"] == 2
    top = out["rollup"][0]
    assert top["message"] == "interface down" and top["count"] == 2
    assert len(top["examples"]) == 2


@pytest.mark.unit
def test_active_alerts_prtg_uses_down_sensors_and_dedups_empty_message():
    from monitoring_aiops.ops import alerts as ops

    conn = _prtg_conn()
    conn.prtg_get.return_value = {"sensors": [
        {"objid": 1, "sensor": "Ping", "device": "web01", "status": "Down", "message": ""},
        {"objid": 2, "sensor": "Ping", "device": "web02", "status": "Down", "message": ""},
    ]}
    out = ops.active_alerts(conn)
    assert out["platform"] == "prtg" and out["total"] == 2
    # empty message falls back to the sensor name for the rollup key.
    assert out["rollup"][0]["count"] == 2
    assert conn.prtg_get.call_args.args[1]["filter_status"] == "5"


@pytest.mark.unit
def test_active_alerts_reports_partial_on_failure():
    from monitoring_aiops.ops import alerts as ops

    conn = _sw_conn()
    conn.swql.side_effect = RuntimeError("swis down")
    out = ops.active_alerts(conn)
    assert "swis down" in out["error"] and out["platform"] == "solarwinds"


@pytest.mark.unit
def test_acknowledge_alert_solarwinds_dispatches_verb():
    from monitoring_aiops.ops import alerts as ops

    conn = _sw_conn()
    out = ops.acknowledge_alert(conn, "55")
    assert out["platform"] == "solarwinds" and out["alertId"] == "55"
    assert "priorState" not in out  # SW ack has no captured prior state here
    entity, verb, args = conn.swis_invoke.call_args.args
    assert (entity, verb) == ("Orion.AlertActive", "Acknowledge")
    assert args == [[55], "acknowledged"]  # id coerced to int


@pytest.mark.unit
def test_acknowledge_alert_prtg_posts_ack():
    from monitoring_aiops.ops import alerts as ops

    conn = _prtg_conn()
    out = ops.acknowledge_alert(conn, "9")
    assert out["platform"] == "prtg"
    path, params = conn.prtg_post.call_args.args
    assert path == "/api/acknowledgealarm.htm"
    assert params["id"] == "9"


# ── overview: NOC one-shot ───────────────────────────────────────────────────


@pytest.mark.unit
def test_fleet_overview_summarizes_counts_and_top_rollup():
    from monitoring_aiops.ops import overview as ops

    conn = _sw_conn()
    conn.swql.return_value = [
        {"AlertActiveID": i, "EntityCaption": "x", "TriggeredMessage": "flap",
         "TriggeredDateTime": "t", "Acknowledged": False}
        for i in range(3)
    ]
    out = ops.fleet_overview(conn)
    assert out["platform"] == "solarwinds" and out["target"] == "orion1"
    assert out["activeAlerts"] == 3 and out["unacknowledged"] == 3
    assert out["topRollup"][0]["count"] == 3
    assert out["errors"] == []


@pytest.mark.unit
def test_fleet_overview_degrades_with_errors_list():
    from monitoring_aiops.ops import overview as ops

    conn = _sw_conn()
    conn.swql.side_effect = RuntimeError("boom")
    out = ops.fleet_overview(conn)
    assert out["activeAlerts"] is None
    assert out["topRollup"] == []
    assert any("boom" in e for e in out["errors"])


# ── swql: validation + canned library ────────────────────────────────────────


@pytest.mark.unit
def test_run_query_validates_select_only():
    from monitoring_aiops.ops import swql as ops

    conn = _sw_conn()
    conn.swql.return_value = [{"NodeID": 1}]
    out = ops.run_query(conn, "  SELECT NodeID FROM Orion.Nodes ; ")
    assert out["rowCount"] == 1 and out["truncated"] is False
    # trailing semicolon is trimmed before dispatch.
    assert conn.swql.call_args.args[0] == "SELECT NodeID FROM Orion.Nodes"


@pytest.mark.unit
def test_run_query_rejects_writes_and_multi_statement():
    from monitoring_aiops.ops import swql as ops

    conn = _sw_conn()
    with pytest.raises(ValueError, match="read-only SELECT"):
        ops.run_query(conn, "DELETE FROM Orion.Nodes")
    with pytest.raises(ValueError, match="Multiple statements"):
        ops.run_query(conn, "SELECT 1; SELECT 2")
    conn.swql.assert_not_called()


@pytest.mark.unit
def test_run_query_caps_rows_and_flags_truncation():
    from monitoring_aiops.ops import swql as ops

    conn = _sw_conn()
    conn.swql.return_value = [{"i": i} for i in range(10)]
    out = ops.run_query(conn, "SELECT i FROM T", limit=3)
    assert out["rowCount"] == 3 and out["truncated"] is True
    assert len(out["rows"]) == 3


@pytest.mark.unit
def test_run_canned_merges_default_min_param():
    from monitoring_aiops.ops import swql as ops

    conn = _sw_conn()
    conn.swql.return_value = []
    ops.run_canned(conn, "high_cpu_nodes")
    query, params = conn.swql.call_args.args
    assert params == {"min": 85}  # default threshold merged in
    assert "CPULoad >= @min" in query
    # caller override wins.
    ops.run_canned(conn, "high_cpu_nodes", {"min": 95})
    assert conn.swql.call_args.args[1]["min"] == 95


@pytest.mark.unit
def test_run_canned_unknown_name_raises_and_list_canned_lists_all():
    from monitoring_aiops.ops import swql as ops

    with pytest.raises(KeyError, match="Unknown canned query"):
        ops.run_canned(_sw_conn(), "does_not_exist")
    names = {c["name"] for c in ops.list_canned()}
    assert {"nodes_down", "high_cpu_nodes", "volumes_full"} <= names
