"""Unit tests for the PRTG read-only ops + MCP tools.

No real PRTG is needed — the connection is a MagicMock whose ``prtg_get`` returns
canned table/status payloads. Covers sensor normalization, system-status parsing
+ resilience, alarm filtering, and the governed low-risk markers on the tools.
"""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
def test_prtg_sensors_normalizes_table_payload():
    from monitoring_aiops.ops import prtg as ops

    conn = MagicMock(name="conn")
    conn.target.platform = "prtg"
    conn.prtg_get.return_value = {"sensors": [
        {"objid": 1001, "sensor": "Ping", "device": "core-sw", "status": "Up",
         "message": "OK", "lastvalue": "2 ms"},
        {"objid": 1002, "sensor": "CPU Load", "device": "core-sw", "status": "Warning",
         "message": "high", "lastvalue": "88 %"},
    ]}
    out = ops.list_sensors(conn)
    assert out["total"] == 2
    first = out["sensors"][0]
    assert first["objid"] == "1001" and first["sensor"] == "Ping"
    assert first["device"] == "core-sw" and first["lastValue"] == "2 ms"


@pytest.mark.unit
def test_prtg_system_status_parses_counts_and_is_resilient():
    from monitoring_aiops.ops import prtg as ops

    conn = MagicMock(name="conn")
    conn.target.platform = "prtg"
    conn.prtg_get.return_value = {
        "totalsensorup": 120, "totalsensordown": 3,
        "totalsensorwarning": 2, "totalsensorpaused": 5, "alarms": 3,
    }
    out = ops.system_status(conn)
    assert out["sensorsUp"] == "120" and out["sensorsDown"] == "3"
    assert out["sensorsWarning"] == "2" and out["sensorsPaused"] == "5"
    assert out["alarms"] == "3"

    conn.prtg_get.side_effect = RuntimeError("boom")
    err = ops.system_status(conn)
    assert "error" in err and "boom" in err["error"]


@pytest.mark.unit
def test_prtg_alarms_filters_to_status_five():
    from monitoring_aiops.ops import prtg as ops

    conn = MagicMock(name="conn")
    conn.target.platform = "prtg"
    conn.prtg_get.return_value = {"sensors": [
        {"objid": 2001, "sensor": "Ping", "device": "edge-rt", "status": "Down",
         "message": "timeout"},
    ]}
    out = ops.list_alarms(conn)
    assert out["total"] == 1
    assert out["alarms"][0]["device"] == "edge-rt"
    # The table request must carry the down-state (status 5) filter.
    _, kwargs = conn.prtg_get.call_args
    params = kwargs.get("params") or conn.prtg_get.call_args[0][1]
    assert params["filter_status"] == "5"


@pytest.mark.unit
def test_prtg_tools_are_governed_low_risk():
    from mcp_server.tools import prtg

    tools = (
        prtg.prtg_sensors, prtg.prtg_sensor_details, prtg.prtg_devices,
        prtg.prtg_groups, prtg.prtg_history, prtg.prtg_system_status, prtg.prtg_alarms,
    )
    for tool in tools:
        assert tool._risk_level == "low"
        assert getattr(tool, "_is_governed_tool", False)
