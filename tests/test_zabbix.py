"""Unit tests for the Zabbix connection transport + read-only ops + MCP tools.

No real Zabbix is needed — the connection-level tests use a fake httpx client
that records requests (JSON-RPC envelope assertions), and the ops-level tests
use a MagicMock connection whose ``zabbix_rpc`` returns canned payloads. Covers
the JSON-RPC 2.0 envelope + Bearer auth (and the no-auth ``apiinfo.version``
exception + legacy ``auth``-field fallback), severity mapping (0-5 → canonical
levels), problem/host normalization, bounded item history, the cross-platform
alert dedup/acknowledge dispatch, and the governed low-risk markers.
"""

from unittest.mock import MagicMock

import pytest


class _Resp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.content = b"{}"
        self.text = "body"

    def json(self):
        return self._payload


class _Client:
    """Fake httpx client recording (method, path, json-body, headers)."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs.get("json"), kwargs.get("headers") or {}))
        return _Resp(self.payloads.pop(0))

    def close(self):
        pass


def _zbx_conn(monkeypatch, payloads):
    from monitoring_aiops.config import TargetConfig
    from monitoring_aiops.connection import MonitoringConnection

    monkeypatch.setenv("MONITORING_ZBX1_SECRET", "tok-123")
    target = TargetConfig(name="zbx1", platform="zabbix", host="zabbix.local",
                          verify_ssl=False)
    client = _Client(payloads)
    return MonitoringConnection(target, client=client), client


# ── connection: JSON-RPC envelope + auth modes ──────────────────────────────


@pytest.mark.unit
def test_zabbix_rpc_posts_jsonrpc_envelope_with_bearer(monkeypatch):
    conn, client = _zbx_conn(monkeypatch, [{"jsonrpc": "2.0", "result": [], "id": 1}])
    out = conn.zabbix_rpc("problem.get", {"recent": False})
    assert out == []
    method, path, body, headers = client.calls[0]
    assert (method, path) == ("POST", "/api_jsonrpc.php")
    assert body["jsonrpc"] == "2.0" and body["method"] == "problem.get"
    assert body["params"] == {"recent": False} and body["id"] == 1
    assert "auth" not in body  # token rides in the header on 6.4+/7.x
    assert headers["Authorization"] == "Bearer tok-123"


@pytest.mark.unit
def test_zabbix_rpc_ids_increment_per_call(monkeypatch):
    conn, client = _zbx_conn(monkeypatch, [
        {"result": "7.0.0"}, {"result": []},
    ])
    conn.zabbix_rpc("apiinfo.version")
    conn.zabbix_rpc("host.get", {})
    assert [c[2]["id"] for c in client.calls] == [1, 2]


@pytest.mark.unit
def test_zabbix_apiinfo_version_is_sent_unauthenticated(monkeypatch):
    conn, client = _zbx_conn(monkeypatch, [{"jsonrpc": "2.0", "result": "7.0.0", "id": 1}])
    assert conn.zabbix_rpc("apiinfo.version") == "7.0.0"
    _, _, body, headers = client.calls[0]
    assert "Authorization" not in headers
    assert "auth" not in body


@pytest.mark.unit
def test_zabbix_rpc_error_raises_teaching_message(monkeypatch):
    conn, _ = _zbx_conn(monkeypatch, [{
        "jsonrpc": "2.0",
        "error": {"code": -32602, "message": "Invalid params.",
                  "data": 'Incorrect value for field "severities".'},
        "id": 1,
    }])
    from monitoring_aiops.connection import MonitoringApiError

    with pytest.raises(MonitoringApiError) as exc:
        conn.zabbix_rpc("problem.get", {"severities": "bogus"})
    msg = str(exc.value)
    assert "problem.get" in msg and "Invalid params" in msg
    assert "API token" in msg  # teaching hint


@pytest.mark.unit
def test_zabbix_rpc_falls_back_to_legacy_auth_field_on_60(monkeypatch):
    """A Zabbix 6.0 server rejecting Bearer gets ONE retry with the ``auth``
    body field, and the connection remembers legacy mode for later calls."""
    conn, client = _zbx_conn(monkeypatch, [
        {"error": {"code": -32602, "message": "Invalid params.",
                   "data": "Not authorised."}},
        {"result": [{"hostid": "1"}]},
        {"result": []},
    ])
    out = conn.zabbix_rpc("host.get", {})
    assert out == [{"hostid": "1"}]
    assert len(client.calls) == 2
    retry_body, retry_headers = client.calls[1][2], client.calls[1][3]
    assert retry_body["auth"] == "tok-123"
    assert "Authorization" not in retry_headers
    # Subsequent calls stay in legacy mode without another failed attempt.
    conn.zabbix_rpc("problem.get", {})
    assert client.calls[2][2]["auth"] == "tok-123"


@pytest.mark.unit
def test_zabbix_platform_guard_both_directions(monkeypatch):
    from monitoring_aiops.config import TargetConfig
    from monitoring_aiops.connection import MonitoringApiError, MonitoringConnection

    # zabbix_rpc against a SolarWinds target must teaching-error…
    monkeypatch.setenv("MONITORING_SW1_SECRET", "pw")
    sw = MonitoringConnection(
        TargetConfig(name="sw1", platform="solarwinds", host="orion.local",
                     username="admin", verify_ssl=False),
        client=_Client([]),
    )
    with pytest.raises(MonitoringApiError, match="requires a zabbix target"):
        sw.zabbix_rpc("apiinfo.version")
    # …and SWQL / PRTG methods against a Zabbix target must teaching-error.
    zbx, _ = _zbx_conn(monkeypatch, [])
    with pytest.raises(MonitoringApiError, match="requires a solarwinds target"):
        zbx.swql("SELECT NodeID FROM Orion.Nodes")
    with pytest.raises(MonitoringApiError, match="requires a prtg target"):
        zbx.prtg_get("/api/status.json")


# ── ops: severity mapping + normalization ───────────────────────────────────


def _mock_conn(**rpc_results):
    """MagicMock conn whose zabbix_rpc dispatches per JSON-RPC method name."""
    conn = MagicMock(name="conn")
    conn.target.platform = "zabbix"

    def _rpc(method, params=None):
        return rpc_results[method]

    conn.zabbix_rpc = MagicMock(side_effect=_rpc)
    return conn


@pytest.mark.unit
def test_zabbix_severity_maps_zero_to_five_to_canonical_levels():
    from monitoring_aiops.ops.zabbix import severity_of

    assert severity_of(0) == {"severity": "not_classified", "level": "info", "severityCode": 0}
    assert severity_of("2") == {"severity": "warning", "level": "warning", "severityCode": 2}
    assert severity_of(4) == {"severity": "high", "level": "high", "severityCode": 4}
    assert severity_of("5") == {"severity": "disaster", "level": "critical", "severityCode": 5}
    # Unknown / junk severities degrade to not_classified, never crash.
    assert severity_of("bogus")["severity"] == "not_classified"
    assert severity_of(99)["level"] == "info"


@pytest.mark.unit
def test_zabbix_problems_normalize_and_filter_by_severity():
    from monitoring_aiops.ops import zabbix as ops

    conn = _mock_conn(**{"problem.get": [
        {"eventid": "101", "objectid": "9", "name": "High CPU on web01",
         "severity": "4", "acknowledged": "0", "clock": "1700000000"},
        {"eventid": "102", "objectid": "10", "name": "Disk full on db01",
         "severity": "5", "acknowledged": "1", "clock": "1700000100"},
    ]})
    out = ops.list_problems(conn, min_severity=3)
    assert out["total"] == 2
    first = out["problems"][0]
    assert first["eventId"] == "101" and first["severity"] == "high"
    assert first["level"] == "high" and first["acknowledged"] is False
    assert out["problems"][1]["level"] == "critical"
    assert out["problems"][1]["acknowledged"] is True
    # min_severity must reach the API as a severities filter.
    params = conn.zabbix_rpc.call_args[0][1]
    assert params["severities"] == [3, 4, 5]


@pytest.mark.unit
def test_zabbix_hosts_inventory_includes_interfaces_and_groups():
    from monitoring_aiops.ops import zabbix as ops

    conn = _mock_conn(**{"host.get": [
        {"hostid": "1", "host": "web01", "name": "Web 01", "status": "0",
         "interfaces": [{"ip": "10.0.0.5", "dns": "", "port": "10050", "available": "1"}],
         "hostgroups": [{"groupid": "2", "name": "Linux servers"}]},
        {"hostid": "2", "host": "old01", "name": "Old 01", "status": "1",
         "interfaces": [], "hostgroups": []},
    ]})
    out = ops.list_hosts(conn)
    assert out["total"] == 2
    web = out["hosts"][0]
    assert web["monitored"] is True
    assert web["interfaces"][0]["ip"] == "10.0.0.5"
    assert web["groups"] == ["Linux servers"]
    assert out["hosts"][1]["monitored"] is False


@pytest.mark.unit
def test_zabbix_item_history_is_bounded_and_resolves_value_type():
    from monitoring_aiops.ops import zabbix as ops

    conn = _mock_conn(**{
        "item.get": [{"itemid": "77", "name": "CPU util", "key_": "system.cpu.util",
                      "value_type": "0", "units": "%", "lastvalue": "12.5"}],
        "history.get": [{"clock": "1700000000", "value": "12.5"}],
    })
    out = ops.item_history(conn, "77", hours=99999, limit=99999)
    assert out["name"] == "CPU util" and out["points"][0]["value"] == "12.5"
    assert out["hours"] == ops.MAX_HISTORY_HOURS  # window capped
    hist_params = conn.zabbix_rpc.call_args_list[1][0][1]
    assert hist_params["history"] == 0  # from item.get value_type
    assert hist_params["limit"] == ops.MAX_HISTORY_POINTS  # point count capped
    assert "time_from" in hist_params  # bounded window, never full history

    missing = _mock_conn(**{"item.get": []})
    err = ops.item_history(missing, "404")
    assert "not found" in err["error"]


@pytest.mark.unit
def test_zabbix_ops_report_errors_as_partials_not_raises():
    from monitoring_aiops.ops import zabbix as ops

    conn = MagicMock(name="conn")
    conn.target.platform = "zabbix"
    conn.zabbix_rpc = MagicMock(side_effect=RuntimeError("boom"))
    for fn in (ops.list_problems, ops.list_hosts, ops.list_hostgroups,
               ops.list_triggers, ops.list_events, ops.list_maintenances):
        out = fn(conn)
        assert "error" in out and "boom" in out["error"]


# ── cross-platform alerts surface on zabbix ─────────────────────────────────


@pytest.mark.unit
def test_active_alerts_dedups_zabbix_problems_like_other_platforms():
    from monitoring_aiops.ops import alerts as ops

    conn = _mock_conn(**{"problem.get": [
        {"eventid": "1", "objectid": "7", "name": "Interface down",
         "severity": "3", "acknowledged": "0", "clock": "1"},
        {"eventid": "2", "objectid": "8", "name": "Interface down",
         "severity": "3", "acknowledged": "0", "clock": "2"},
        {"eventid": "3", "objectid": "9", "name": "Host unreachable",
         "severity": "5", "acknowledged": "1", "clock": "3"},
    ]})
    out = ops.active_alerts(conn)
    assert out["platform"] == "zabbix"
    assert out["total"] == 3 and out["unacknowledged"] == 2
    top = out["rollup"][0]
    assert top["message"] == "Interface down" and top["count"] == 2


@pytest.mark.unit
def test_acknowledge_alert_dispatches_zabbix_event_acknowledge():
    from monitoring_aiops.ops import alerts as ops

    conn = _mock_conn(**{
        "event.get": [{"eventid": "42", "acknowledged": "0"}],
        "event.acknowledge": {"eventids": ["42"]},
    })
    out = ops.acknowledge_alert(conn, "42")
    assert out["platform"] == "zabbix" and out["alertId"] == "42"
    assert out["priorState"] == {"acknowledged": False}
    ack_call = conn.zabbix_rpc.call_args_list[-1][0]
    assert ack_call[0] == "event.acknowledge"
    assert ack_call[1]["eventids"] == ["42"] and ack_call[1]["action"] == 6


# ── governed markers ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_zabbix_read_tools_are_governed_low_risk():
    from mcp_server.tools import zabbix

    tools = (
        zabbix.zabbix_problems, zabbix.zabbix_hosts, zabbix.zabbix_hostgroups,
        zabbix.zabbix_triggers, zabbix.zabbix_events, zabbix.zabbix_item_history,
        zabbix.zabbix_maintenances,
    )
    for tool in tools:
        assert tool._risk_level == "low"
        assert getattr(tool, "_is_governed_tool", False)
