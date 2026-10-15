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
    assert out["nodes"] == [
        {"caption": "hot", "value": 99.0},
        {"caption": "warm", "value": 70.0},
    ]
    assert out["returned"] == 2 and out["error"] is None
    query = conn.swql.call_args.args[0]
    assert "ORDER BY CPULoad DESC WITH ROWS 1 TO 5" in query


@pytest.mark.unit
def test_topn_reports_failure_instead_of_empty_list():
    """A failed SWQL query and "no nodes under load" are opposite findings."""
    from monitoring_aiops.ops import sw_health as ops

    out = ops.topn(_conn(side_effect=RuntimeError("boom")), "memory")
    assert out["nodes"] == []
    assert out["returned"] == 0
    assert out["metric"] == "memory"
    assert "boom" in out["error"]


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


@pytest.mark.unit
def test_volume_with_unreadable_usage_is_kept_aside_not_dropped():
    from monitoring_aiops.ops import sw_health as ops

    conn = _conn([
        {"NodeCaption": "n", "Volume": "D", "VolumePercentUsed": 95},
        {"NodeCaption": "n", "Volume": "X", "VolumePercentUsed": None},
        {"NodeCaption": "n", "Volume": "Y"},
    ])
    out = ops.volume_status(conn, min_percent=90)
    assert [v["volume"] for v in out["volumes"]] == ["D"]
    assert sorted(v["volume"] for v in out["unreadableVolumes"]) == ["X", "Y"]
    assert all(v["percentUsed"] is None for v in out["unreadableVolumes"])
    assert out["total"] == 1


@pytest.mark.unit
def test_measured_zero_percent_is_a_real_reading():
    from monitoring_aiops.ops import sw_health as ops

    out = ops.volume_status(_conn([{"NodeCaption": "n", "Volume": "Z", "VolumePercentUsed": 0}]))
    assert [v["percentUsed"] for v in out["volumes"]] == [0.0]
    assert out["unreadableVolumes"] == []


@pytest.mark.unit
def test_noc_rollup_failed_count_is_null_not_zero_down():
    from monitoring_aiops.ops import sw_health as ops

    conn = MagicMock(name="conn")

    def swql(q):
        if "Orion.NPM.Interfaces" in q:
            raise RuntimeError("SWIS 403")
        if "COUNT" in q:
            return [{"N": 0}]
        return []

    conn.swql.side_effect = swql
    out = ops.noc_rollup(conn)
    assert out["nodesDown"] == 0  # measured
    assert out["interfacesDown"] is None  # not measured
    assert any("403" in e for e in out["countErrors"])


@pytest.mark.unit
def test_non_numeric_usage_is_unreadable_not_zero():
    from monitoring_aiops.ops import sw_health as ops

    row = {"NodeCaption": "n", "Volume": "Q", "VolumePercentUsed": "n/a"}
    out = ops.volume_status(_conn([row]))
    assert out["volumes"] == []
    assert [v["volume"] for v in out["unreadableVolumes"]] == ["Q"]


@pytest.mark.unit
def test_count_row_without_a_value_is_null():
    from monitoring_aiops.ops import sw_health as ops

    conn = MagicMock(name="conn")
    conn.swql.side_effect = lambda q: [{"N": None}] if "COUNT" in q else []
    out = ops.noc_rollup(conn)
    assert out["nodesDown"] is None
    assert len(out["countErrors"]) == 3  # every null count says why
