"""Extra unit coverage for the PRTG read surface (Paessler PRTG web API).

MagicMock connection (no real PRTG). Asserts the table/status/details/history
request params (content/columns/filter_status), normalization of rows, the
status-counter key fallbacks, and resilient {"error": ...} partials.
"""

from unittest.mock import MagicMock

import pytest


def _conn(get_return=None, get_side_effect=None):
    conn = MagicMock(name="conn")
    conn.target.platform = "prtg"
    if get_side_effect is not None:
        conn.prtg_get.side_effect = get_side_effect
    else:
        conn.prtg_get.return_value = get_return
    return conn


@pytest.mark.unit
def test_list_sensors_params_and_status_filter():
    from monitoring_aiops.ops import prtg as ops

    conn = _conn({"sensors": [
        {"objid": 1, "sensor": "CPU", "device": "web01", "status": "Up",
         "message": "OK", "lastvalue": "5%"},
    ]})
    out = ops.list_sensors(conn, status="5")
    assert out["total"] == 1 and out["sensors"][0]["device"] == "web01"
    path, params = conn.prtg_get.call_args.args
    assert path == "/api/table.json"
    assert params["content"] == "sensors"
    assert "objid,sensor,device,status,message,lastvalue" == params["columns"]
    assert params["filter_status"] == "5"


@pytest.mark.unit
def test_list_sensors_without_status_omits_filter():
    from monitoring_aiops.ops import prtg as ops

    conn = _conn({"sensors": []})
    ops.list_sensors(conn)
    assert "filter_status" not in conn.prtg_get.call_args.args[1]


@pytest.mark.unit
def test_sensor_details_unwraps_sensordata_envelope():
    from monitoring_aiops.ops import prtg as ops

    conn = _conn({"sensordata": {
        "name": "CPU Load", "statustext": "Up", "lastvalue": "5 %",
        "lastmessage": "OK", "sensortype": "cpuload",
    }})
    out = ops.sensor_details(conn, "42")
    assert out["sensorId"] == "42" and out["name"] == "CPU Load"
    assert out["status"] == "Up"
    assert conn.prtg_get.call_args.args[1] == {"id": "42"}


@pytest.mark.unit
def test_list_devices_and_groups_params():
    from monitoring_aiops.ops import prtg as ops

    dconn = _conn({"devices": [
        {"objid": 1, "device": "web01", "host": "10.0.0.1", "status": "Up",
         "group": "prod"},
    ]})
    dev = ops.list_devices(dconn)
    assert dev["devices"][0]["host"] == "10.0.0.1"
    assert dconn.prtg_get.call_args.args[1]["content"] == "devices"

    gconn = _conn({"groups": [{"objid": 2, "group": "prod", "status": "Up"}]})
    grp = ops.list_groups(gconn)
    assert grp["groups"][0]["group"] == "prod"
    assert gconn.prtg_get.call_args.args[1]["content"] == "groups"


@pytest.mark.unit
def test_sensor_history_points_and_hours_passthrough():
    from monitoring_aiops.ops import prtg as ops

    conn = _conn({"histdata": [
        {"datetime": "t1", "value": None, "value_raw": "12"},
        {"datetime": "t2", "value": "13"},
    ]})
    out = ops.sensor_history(conn, "7", hours=12)
    assert out["hours"] == 12
    assert out["points"][0]["value"] == "12"  # falls back to value_raw
    assert out["points"][1]["value"] == "13"
    assert conn.prtg_get.call_args.args[0] == "/api/historicdata.json"


@pytest.mark.unit
def test_system_status_picks_first_present_key():
    from monitoring_aiops.ops import prtg as ops

    conn = _conn({"upsens": "100", "downsens": "3", "warnsens": "2",
                  "pausedsens": "1", "alarms": "5"})
    out = ops.system_status(conn)
    assert out["sensorsUp"] == "100" and out["sensorsDown"] == "3"
    assert out["alarms"] == "5"


@pytest.mark.unit
def test_list_alarms_filters_down_status_5():
    from monitoring_aiops.ops import prtg as ops

    conn = _conn({"sensors": [
        {"objid": 9, "sensor": "Ping", "device": "web01", "status": "Down",
         "message": "timeout"},
    ]})
    out = ops.list_alarms(conn)
    assert out["alarms"][0]["message"] == "timeout"
    assert conn.prtg_get.call_args.args[1]["filter_status"] == "5"


@pytest.mark.unit
def test_prtg_reads_degrade_to_partial_error():
    from monitoring_aiops.ops import prtg as ops

    conn = _conn(get_side_effect=RuntimeError("prtg unreachable"))
    for out in (ops.list_sensors(conn), ops.list_devices(conn),
                ops.list_groups(conn), ops.system_status(conn),
                ops.list_alarms(conn)):
        assert "prtg unreachable" in out["error"]
    # detail/history carry the sensorId alongside the error.
    det = ops.sensor_details(conn, "5")
    assert det["sensorId"] == "5" and "prtg unreachable" in det["error"]
