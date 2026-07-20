"""Unit tests for the SolarWinds (Orion) health ops + MCP tools.

All read-only SWQL, exercised against a MagicMock connection (no real Orion).
"""

from unittest.mock import MagicMock

import pytest


def _conn(rows):
    conn = MagicMock(name="conn")
    conn.target.platform = "solarwinds"
    conn.swql.return_value = rows
    return conn


@pytest.mark.unit
def test_nodes_list_normalizes_rows():
    from monitoring_aiops.ops import sw_health as ops

    conn = _conn([
        {"Caption": "sw1", "IP_Address": "10.0.0.1", "Status": 1,
         "StatusDescription": "Up"},
        {"Caption": "sw2", "IP_Address": "10.0.0.2", "Status": 2,
         "StatusDescription": "Down"},
    ])
    out = ops.nodes_list(conn)
    assert out["total"] == 2
    assert out["nodes"][0] == {
        "caption": "sw1", "ip": "10.0.0.1", "status": "Up",
        "statusDescription": "Up",
    }
    assert out["nodes"][1]["status"] == "Down"


@pytest.mark.unit
def test_topn_rejects_unknown_metric():
    from monitoring_aiops.ops import sw_health as ops

    conn = _conn([])
    with pytest.raises(ValueError):
        ops.topn(conn, "temperature")
    conn.swql.assert_not_called()


@pytest.mark.unit
def test_noc_rollup_returns_count_keys_and_is_resilient():
    from monitoring_aiops.ops import sw_health as ops

    conn = MagicMock(name="conn")
    conn.target.platform = "solarwinds"
    conn.swql.side_effect = RuntimeError("SWIS unavailable")
    out = ops.noc_rollup(conn)
    assert set(out) == {
        "nodesDown", "nodesWarning", "interfacesDown", "topCpu", "topCpuError",
    }
    assert out["nodesDown"] == 0
    assert out["nodesWarning"] == 0
    assert out["interfacesDown"] == 0
    assert out["topCpu"] == []


@pytest.mark.unit
def test_all_tools_risk_low_and_governed():
    from mcp_server.tools import sw_health

    tools = [
        sw_health.node_status, sw_health.nodes_list, sw_health.interface_status,
        sw_health.volume_status, sw_health.application_status, sw_health.topn,
        sw_health.noc_rollup,
    ]
    for fn in tools:
        assert fn._risk_level == "low"
        assert getattr(fn, "_is_governed_tool", False)
