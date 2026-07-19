"""Extra unit coverage for SolarWinds (Orion) health reads.

All read-only SWQL against a MagicMock connection (no real Orion). Asserts
status-code -> label mapping, numeric coercion, top-N ordering + row-clause SWQL,
volume filtering/sorting, the noc_rollup sub-count SWQL, and resilient partials.
"""

from unittest.mock import MagicMock

import pytest


def _conn(rows=None, side_effect=None):
    conn = MagicMock(name="conn")
    conn.target.platform = "solarwinds"
    if side_effect is not None:
        conn.swql.side_effect = side_effect
    else:
        conn.swql.return_value = rows
    return conn


@pytest.mark.unit
def test_node_status_maps_codes_and_coerces_numbers():
    from monitoring_aiops.ops import sw_health as ops

    conn = _conn([{
        "Caption": "web01", "IP_Address": "10.0.0.9", "Status": 3,
        "StatusDescription": "Warning", "CPULoad": "42", "PercentMemoryUsed": None,
    }])
    out = ops.node_status(conn, "web01")
    assert out["status"] == "Warning"  # 3 -> Warning
    assert out["cpuLoad"] == 42.0  # numeric string coerced
    assert out["percentMemoryUsed"] == 0.0  # None -> 0.0
    # query uses the @q bind param for both caption and IP.
    query, params = conn.swql.call_args.args
    assert params == {"q": "web01"}
    assert "@q" in query


@pytest.mark.unit
def test_node_status_not_found_and_error_partial():
    from monitoring_aiops.ops import sw_health as ops

    assert ops.node_status(_conn([]), "nope") == {"error": "not found"}
    err = ops.node_status(_conn(side_effect=RuntimeError("swis down")), "x")
    assert "swis down" in err["error"]


@pytest.mark.unit
def test_nodes_list_status_filter_binds_param():
    from monitoring_aiops.ops import sw_health as ops

    conn = _conn([{"Caption": "n", "IP_Address": "1", "Status": 2,
                   "StatusDescription": "Down"}])
    out = ops.nodes_list(conn, status=2)
    assert out["total"] == 1 and out["nodes"][0]["status"] == "Down"
    query, params = conn.swql.call_args.args
    assert params == {"status": 2}
    assert "Status=@status" in query


@pytest.mark.unit
def test_nodes_list_unknown_status_code_falls_back_to_raw_label():
    from monitoring_aiops.ops import sw_health as ops

    conn = _conn([{"Caption": "n", "IP_Address": "1", "Status": 9,
                   "StatusDescription": "?"}])
    # code 9 isn't in the _STATUS map -> raw sanitized value returned.
    assert ops.nodes_list(conn)["nodes"][0]["status"] == "9"


@pytest.mark.unit
def test_interface_status_top_sorts_by_max_util_desc():
    from monitoring_aiops.ops import sw_health as ops

    conn = _conn([
        {"NodeCaption": "n", "InterfaceCaption": "gi1", "Status": 1,
         "InPercentUtil": 10, "OutPercentUtil": 5},
        {"NodeCaption": "n", "InterfaceCaption": "gi2", "Status": 1,
         "InPercentUtil": 3, "OutPercentUtil": 90},
        {"NodeCaption": "n", "InterfaceCaption": "gi3", "Status": 1,
         "InPercentUtil": 50, "OutPercentUtil": 1},
    ])
    out = ops.interface_status(conn, top=2)
    # "total" is the genuine pre-cap count (3 interfaces existed), while
    # "returned" is what this response carries. They must not be the same
    # number when the result was capped — a total that merely echoes returned
    # is the lying-count bug the envelope exists to prevent.
    assert out["total"] == 3
    assert out["returned"] == 2
    assert out["truncated"] is True
    assert [i["interfaceCaption"] for i in out["interfaces"]] == ["gi2", "gi3"]


@pytest.mark.unit
def test_volume_status_filters_below_threshold_and_sorts():
    from monitoring_aiops.ops import sw_health as ops

    conn = _conn([
        {"NodeCaption": "n", "Volume": "C", "VolumePercentUsed": 40},
        {"NodeCaption": "n", "Volume": "D", "VolumePercentUsed": 95},
        {"NodeCaption": "n", "Volume": "E", "VolumePercentUsed": 80},
    ])
    out = ops.volume_status(conn, min_percent=50)
    assert [v["volume"] for v in out["volumes"]] == ["D", "E"]
    assert out["total"] == 2


@pytest.mark.unit
def test_application_status_resilient_when_apm_absent():
    from monitoring_aiops.ops import sw_health as ops

    ok = ops.application_status(_conn([
        {"ApplicationName": "IIS", "NodeCaption": "web01", "Status": 1},
    ]))
    assert ok["applications"][0] == {
        "applicationName": "IIS", "nodeCaption": "web01", "status": "Up",
    }
    err = ops.application_status(_conn(side_effect=RuntimeError("no APM")))
    assert "no APM" in err["error"]


@pytest.mark.unit
def test_topn_builds_row_clause_query_and_coerces_values():
    from monitoring_aiops.ops import sw_health as ops

    conn = _conn([
        {"Caption": "hot", "CPULoad": "99"},
        {"Caption": "warm", "CPULoad": 70},
    ])
    out = ops.topn(conn, "cpu", n=5)
    assert out == [{"caption": "hot", "value": 99.0}, {"caption": "warm", "value": 70.0}]
    query = conn.swql.call_args.args[0]
    assert "ORDER BY CPULoad DESC WITH ROWS 1 TO 5" in query


@pytest.mark.unit
def test_topn_resilient_returns_empty_on_failure():
    from monitoring_aiops.ops import sw_health as ops

    assert ops.topn(_conn(side_effect=RuntimeError("boom")), "memory") == []


@pytest.mark.unit
def test_noc_rollup_issues_guarded_subcounts():
    from monitoring_aiops.ops import sw_health as ops

    # Each swql call returns a COUNT row; topn gets its own rows too.
    conn = MagicMock(name="conn")
    conn.target.platform = "solarwinds"
    conn.swql.side_effect = [
        [{"N": 4}],          # nodesDown (Status=2)
        [{"N": 2}],          # nodesWarning (Status=3)
        [{"N": 7}],          # interfacesDown
        [{"Caption": "hot", "CPULoad": 88}],  # topn cpu
    ]
    out = ops.noc_rollup(conn)
    assert out["nodesDown"] == 4 and out["nodesWarning"] == 2
    assert out["interfacesDown"] == 7
    assert out["topCpu"][0]["caption"] == "hot"
    # interfacesDown count runs against the Interfaces entity.
    iface_query = conn.swql.call_args_list[2].args[0]
    assert "Orion.NPM.Interfaces" in iface_query
