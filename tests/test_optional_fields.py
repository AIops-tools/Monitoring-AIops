"""Absent fields come back as null, not as an empty string.

An empty string reads as "the platform returned this column and it was blank";
a missing column is a different fact. Collapsing the two hides information from
any consumer, and a smaller local model will confidently invent the difference.
These tests pin the contract end-to-end across all three platforms, plus the
truncation envelope that every row-capped read now shares.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from monitoring_aiops.governance import opt_str
from monitoring_aiops.ops import alerts as alert_ops
from monitoring_aiops.ops import prtg as prtg_ops
from monitoring_aiops.ops import sw_health, sw_write, swql, zabbix
from monitoring_aiops.ops._util import opt_s, s


@pytest.mark.unit
def test_opt_str_distinguishes_absent_from_empty():
    assert opt_str(None) is None, "absent must stay absent"
    assert opt_str("") == "", "a genuinely empty value is not the same as absent"
    assert opt_str("core-sw1", 64) == "core-sw1"


@pytest.mark.unit
def test_opt_str_still_sanitizes_and_truncates():
    assert opt_str("a\x00b") == "ab"  # control character stripped
    assert opt_str("abcdef", 3) == "abc"


@pytest.mark.unit
def test_opt_str_accepts_non_string_values():
    assert opt_str(42) == "42"


@pytest.mark.unit
def test_opt_s_and_s_differ_only_on_absence():
    assert s(None) == "" and opt_s(None) is None
    assert s("Down") == opt_s("Down") == "Down"


# ── SolarWinds ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sw_node_rows_report_absent_columns_as_none():
    """A SWQL row missing StatusDescription reports null, not ''."""
    conn = MagicMock()
    conn.swql.return_value = [{"Caption": "core-sw1", "Status": 2}]
    row = sw_health.nodes_list(conn)["nodes"][0]
    assert row["caption"] == "core-sw1" and row["status"] == "Down"
    assert row["ip"] is None and row["statusDescription"] is None


@pytest.mark.unit
def test_sw_status_label_is_none_when_orion_sent_no_status():
    """An absent status is not the same fact as an unrecognised one."""
    assert sw_health._status_label(None) is None
    assert sw_health._status_label(2) == "Down"
    assert sw_health._status_label(99) == "99", "unknown codes are reported verbatim"


@pytest.mark.unit
def test_sw_rows_keep_empty_string_when_source_is_empty():
    conn = MagicMock()
    conn.swql.return_value = [{"Caption": "core-sw1", "IP_Address": ""}]
    assert sw_health.nodes_list(conn)["nodes"][0]["ip"] == ""


@pytest.mark.unit
def test_ops_never_drop_the_key_itself():
    """Keys are always present; only their value may be null."""
    conn = MagicMock()
    conn.swql.return_value = [{}]
    row = sw_health.nodes_list(conn)["nodes"][0]
    for key in ("caption", "ip", "status", "statusDescription"):
        assert key in row, f"{key} must be present even when the source omitted it"


# ── PRTG ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_prtg_sensor_rows_report_absent_columns_as_none():
    conn = MagicMock()
    conn.prtg_get.return_value = {"sensors": [{"objid": 1, "sensor": "Ping"}]}
    row = prtg_ops.list_sensors(conn)["sensors"][0]
    assert row["sensor"] == "Ping"
    assert row["message"] is None and row["lastValue"] is None


@pytest.mark.unit
def test_prtg_system_status_reports_missing_counters_as_none():
    conn = MagicMock()
    conn.prtg_get.return_value = {"totalsensorup": 10}
    out = prtg_ops.system_status(conn)
    assert out["sensorsUp"] == "10"
    assert out["sensorsDown"] is None and out["alarms"] is None


# ── Zabbix ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_zabbix_problem_rows_report_absent_fields_as_none():
    conn = MagicMock()
    conn.zabbix_rpc.return_value = [{"eventid": "1", "severity": "4"}]
    row = zabbix.list_problems(conn)["problems"][0]
    assert row["eventId"] == "1" and row["level"] == "high"
    assert row["name"] is None and row["triggerId"] is None


# ── the consumer a null breaks ───────────────────────────────────────────


@pytest.mark.unit
def test_alert_rollup_survives_alerts_with_no_message():
    """Dedup groups by message — a null message must not become a crash or a key.

    ``_dedup`` reaches for ``it.get(key) or "(no message)"``, which is what keeps
    a null out of the grouping key. Without that guard a null message would sort
    into its own unlabelled bucket.
    """
    conn = MagicMock()
    conn.target.platform = "solarwinds"
    conn.swql.return_value = [{"AlertActiveID": 1}, {"AlertActiveID": 2}]
    out = alert_ops.active_alerts(conn)
    assert out["total"] == 2
    assert out["rollup"][0]["message"] == "(no message)"
    assert out["rollup"][0]["count"] == 2


# ── truncation announces itself ──────────────────────────────────────────


@pytest.mark.unit
def test_swql_query_returns_the_standard_envelope():
    conn = MagicMock()
    conn.swql.return_value = [{"i": i} for i in range(5)]
    out = swql.run_query(conn, "SELECT i FROM T", limit=3)
    assert out["returned"] == 3 and out["limit"] == 3
    assert out["truncated"] is True
    assert len(out["rows"]) == 3
    assert out["rowCount"] == out["returned"], "rowCount must describe the rows given"


@pytest.mark.unit
def test_swql_query_is_not_truncated_at_exactly_the_limit():
    """The boundary case a length-comparison heuristic gets wrong."""
    conn = MagicMock()
    conn.swql.return_value = [{"i": i} for i in range(3)]
    out = swql.run_query(conn, "SELECT i FROM T", limit=3)
    assert out["returned"] == 3 and out["truncated"] is False


@pytest.mark.unit
def test_swql_canned_no_longer_reports_a_precap_count():
    """The canned path used to cap rows while reporting the uncapped count.

    A caller could not tell which number described what it had been handed. Both
    now describe the returned rows, and truncation is stated outright.
    """
    conn = MagicMock()
    conn.swql.return_value = [{"i": i} for i in range(5)]
    out = swql.run_canned(conn, "nodes_down", limit=2)
    assert out["returned"] == 2 and out["rowCount"] == 2
    assert len(out["rows"]) == 2 and out["truncated"] is True
    assert out["name"] == "nodes_down"


@pytest.mark.unit
def test_zabbix_events_measures_truncation_with_a_probe_row():
    conn = MagicMock()
    conn.zabbix_rpc.return_value = [{"eventid": str(i)} for i in range(4)]
    out = zabbix.list_events(conn, top=3)
    assert out["returned"] == 3 and out["limit"] == 3 and out["truncated"] is True
    assert len(out["events"]) == 3, "the probe row is never handed to the caller"
    assert conn.zabbix_rpc.call_args[0][1]["limit"] == 4


@pytest.mark.unit
def test_sw_events_measure_truncation_with_a_probe_row():
    conn = MagicMock()
    conn.swql.return_value = [{"EventID": i} for i in range(4)]
    out = sw_write.list_events(conn, top=3)
    assert out["returned"] == 3 and out["truncated"] is True
    assert conn.swql.call_args.args[1] == {"n": 4}


@pytest.mark.unit
def test_interface_status_top_n_reports_what_it_left_out():
    conn = MagicMock()
    conn.swql.return_value = [
        {"NodeCaption": "n", "InterfaceCaption": f"Gi0/{i}", "InPercentUtil": i}
        for i in range(5)
    ]
    out = sw_health.interface_status(conn, top=2)
    assert out["returned"] == 2 and out["limit"] == 2 and out["truncated"] is True
    assert out["interfaces"][0]["interfaceCaption"] == "Gi0/4", "ranked worst-first"


@pytest.mark.unit
def test_interface_status_without_top_is_never_truncated():
    conn = MagicMock()
    conn.swql.return_value = [{"NodeCaption": "n", "InterfaceCaption": "Gi0/1"}]
    out = sw_health.interface_status(conn)
    assert out["truncated"] is False and out["limit"] is None


@pytest.mark.unit
def test_undo_list_envelope_measures_truncation(monkeypatch):
    from mcp_server.tools import undo as undo_tools

    rows = [
        {
            "undo_id": f"u{i}",
            "ts": "2026-07-18T00:00:00Z",
            "tool": "some_tool",
            "undo_tool": "some_inverse_tool",
            "note": "",
        }
        for i in range(4)
    ]
    captured = {}

    class _Store:
        def list(self, *, status=None, limit=50):
            captured["limit"] = limit
            return rows[:limit]

    monkeypatch.setattr(undo_tools, "get_undo_store", lambda: _Store())
    result = undo_tools.undo_list(limit=3)
    assert captured["limit"] == 4, "one extra row is fetched to measure truncation"
    assert result["returned"] == 3
    assert result["limit"] == 3
    assert result["truncated"] is True
    assert len(result["undos"]) == 3
