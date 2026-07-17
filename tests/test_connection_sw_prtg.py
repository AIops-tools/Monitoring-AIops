"""Connection transport tests for SolarWinds (SWIS) + PRTG + the manager.

No real SolarWinds Orion / PRTG server is needed — a fake httpx client records
each request so we can assert the exact SWIS Query / Invoke envelopes, the PRTG
``apitoken`` param handling + path encoding, the teaching-message mapping for
every HTTP status, the platform guards in both directions, and the connection
manager's session reuse. (Zabbix transport is covered in test_zabbix.py.)
"""

from __future__ import annotations

import httpx
import pytest


class _Resp:
    def __init__(self, payload, status_code=200, content=b"{}", text="body"):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.text = text

    def json(self):
        if self._payload is _RAISE:
            raise ValueError("not json")
        return self._payload


_RAISE = object()


class _Client:
    """Fake httpx client recording (method, path, kwargs) and replaying resps."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    def close(self):
        self.closed = True


def _sw(monkeypatch, responses):
    from monitoring_aiops.config import TargetConfig
    from monitoring_aiops.connection import MonitoringConnection

    monkeypatch.setenv("MONITORING_SW1_SECRET", "pw")
    target = TargetConfig(name="sw1", platform="solarwinds", host="orion.local",
                          username="admin", verify_ssl=False)
    client = _Client(responses)
    return MonitoringConnection(target, client=client), client


def _prtg(monkeypatch, responses):
    from monitoring_aiops.config import TargetConfig
    from monitoring_aiops.connection import MonitoringConnection

    monkeypatch.setenv("MONITORING_PRTG1_SECRET", "tok-xyz")
    target = TargetConfig(name="prtg1", platform="prtg", host="prtg.local",
                          verify_ssl=False)
    client = _Client(responses)
    return MonitoringConnection(target, client=client), client


# ── SolarWinds SWIS envelopes ────────────────────────────────────────────────


@pytest.mark.unit
def test_swql_posts_query_envelope_and_unwraps_results(monkeypatch):
    conn, client = _sw(monkeypatch, [
        _Resp({"results": [{"NodeID": 1}, "junk", {"NodeID": 2}]}),
    ])
    rows = conn.swql("SELECT NodeID FROM Orion.Nodes WHERE Caption=@c", {"c": "web01"})
    # non-dict rows are filtered out
    assert rows == [{"NodeID": 1}, {"NodeID": 2}]
    method, path, kwargs = client.calls[0]
    assert method == "POST"
    assert path == "/SolarWinds/InformationService/v3/Json/Query"
    assert kwargs["json"] == {
        "query": "SELECT NodeID FROM Orion.Nodes WHERE Caption=@c",
        "parameters": {"c": "web01"},
    }


@pytest.mark.unit
def test_swql_empty_params_default_to_empty_dict(monkeypatch):
    conn, client = _sw(monkeypatch, [_Resp({"results": []})])
    assert conn.swql("SELECT 1") == []
    assert client.calls[0][2]["json"]["parameters"] == {}


@pytest.mark.unit
def test_swis_invoke_encodes_entity_and_verb_into_path(monkeypatch):
    conn, client = _sw(monkeypatch, [_Resp({})])
    conn.swis_invoke("Orion.Nodes", "Unmanage", ["N:42", "start", "end", False])
    method, path, kwargs = client.calls[0]
    assert method == "POST"
    assert path == "/SolarWinds/InformationService/v3/Json/Invoke/Orion.Nodes/Unmanage"
    assert kwargs["json"] == ["N:42", "start", "end", False]


@pytest.mark.unit
def test_swis_invoke_path_segment_encoding_blocks_traversal(monkeypatch):
    conn, client = _sw(monkeypatch, [_Resp({})])
    # A hostile entity name cannot smuggle a path separator into the URL.
    conn.swis_invoke("Orion/../Secret", "Delete", None)
    path = client.calls[0][1]
    assert "Orion%2F..%2FSecret" in path
    assert client.calls[0][2]["json"] == []  # None args default to []


# ── PRTG ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_prtg_get_appends_apitoken_and_merges_params(monkeypatch):
    conn, client = _prtg(monkeypatch, [_Resp({"sensors": []})])
    conn.prtg_get("/api/table.json", {"content": "sensors"})
    method, path, kwargs = client.calls[0]
    assert (method, path) == ("GET", "/api/table.json")
    assert kwargs["params"] == {"content": "sensors", "apitoken": "tok-xyz"}


@pytest.mark.unit
def test_prtg_get_none_params_still_carries_token(monkeypatch):
    conn, client = _prtg(monkeypatch, [_Resp({"foo": 1})])
    conn.prtg_get("/api/status.json")
    assert client.calls[0][2]["params"] == {"apitoken": "tok-xyz"}


@pytest.mark.unit
def test_prtg_post_appends_token(monkeypatch):
    conn, client = _prtg(monkeypatch, [_Resp({})])
    conn.prtg_post("/api/acknowledgealarm.htm", {"id": "5", "ackmsg": "ack"})
    method, path, kwargs = client.calls[0]
    assert method == "POST"
    assert kwargs["params"] == {"id": "5", "ackmsg": "ack", "apitoken": "tok-xyz"}


# ── response edge cases ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_empty_body_returns_empty_dict(monkeypatch):
    conn, _ = _prtg(monkeypatch, [_Resp({}, content=b"")])
    assert conn.prtg_get("/api/status.json") == {}


@pytest.mark.unit
def test_non_json_body_returns_empty_dict(monkeypatch):
    conn, _ = _prtg(monkeypatch, [_Resp(_RAISE, content=b"<html/>")])
    assert conn.prtg_get("/api/status.json") == {}


# ── teaching messages for each HTTP status ──────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "status,needle",
    [
        (401, "Authentication failed"),
        (403, "Authentication failed"),
        (404, "Not found (404)"),
        (400, "Bad request (400)"),
        (500, "server error (500)"),
        (503, "server error (503)"),
        (418, "API error (418)"),
    ],
)
def test_http_errors_map_to_teaching_messages(monkeypatch, status, needle):
    from monitoring_aiops.connection import MonitoringApiError

    conn, _ = _sw(monkeypatch, [_Resp(None, status_code=status, text="detail-body")])
    with pytest.raises(MonitoringApiError) as exc:
        conn.swql("SELECT 1")
    assert needle in str(exc.value)
    assert "detail-body" in str(exc.value)  # snippet echoed
    assert exc.value.status_code == status


@pytest.mark.unit
def test_transport_error_becomes_reachability_teaching_error(monkeypatch):
    from monitoring_aiops.connection import MonitoringApiError

    conn, _ = _sw(monkeypatch, [httpx.ConnectError("refused")])
    with pytest.raises(MonitoringApiError) as exc:
        conn.swql("SELECT 1")
    msg = str(exc.value)
    assert "Could not reach solarwinds" in msg
    assert "reachability" in msg


# ── platform guards both directions ──────────────────────────────────────────


@pytest.mark.unit
def test_solarwinds_conn_rejects_prtg_and_zabbix_methods(monkeypatch):
    from monitoring_aiops.connection import MonitoringApiError

    conn, _ = _sw(monkeypatch, [])
    with pytest.raises(MonitoringApiError, match="requires a prtg target"):
        conn.prtg_get("/api/status.json")
    with pytest.raises(MonitoringApiError, match="requires a zabbix target"):
        conn.zabbix_rpc("apiinfo.version")


@pytest.mark.unit
def test_prtg_conn_rejects_swql(monkeypatch):
    from monitoring_aiops.connection import MonitoringApiError

    conn, _ = _prtg(monkeypatch, [])
    with pytest.raises(MonitoringApiError, match="requires a solarwinds target"):
        conn.swql("SELECT 1")


# ── ConnectionManager: reuse + lifecycle ─────────────────────────────────────


@pytest.mark.unit
def test_connection_manager_caches_and_disconnects(monkeypatch):
    from monitoring_aiops.config import AppConfig, TargetConfig
    from monitoring_aiops.connection import ConnectionManager

    monkeypatch.setenv("MONITORING_A_SECRET", "pw")
    monkeypatch.setenv("MONITORING_B_SECRET", "tok")
    cfg = AppConfig(targets=(
        TargetConfig(name="a", platform="solarwinds", host="h1", username="u",
                     verify_ssl=False),
        TargetConfig(name="b", platform="prtg", host="h2", verify_ssl=False),
    ))
    mgr = ConnectionManager(cfg)
    assert set(mgr.list_targets()) == {"a", "b"}
    c1 = mgr.connect("a")
    c2 = mgr.connect("a")
    assert c1 is c2  # session reuse
    assert mgr.list_connected() == ["a"]
    # default_target is the first configured one.
    assert mgr.connect().target.name == "a"
    mgr.disconnect_all()
    assert mgr.list_connected() == []
