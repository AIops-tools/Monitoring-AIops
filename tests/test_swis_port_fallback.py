"""SolarWinds SWIS port: modern 17774 default with a one-shot 17778 fallback.

Orion 2023.1 moved the SWIS REST endpoint from 17778 to 17774 and documents the
old port as slated for removal, so shipping 17778 as the default aimed every
fresh install at a port the server may not serve at all. The default is now
17774; a pre-2023.1 Orion stays reachable because the first transport failure
buys ONE retry on 17778, and the port that answered is remembered for the life
of the connection — the probe costs one extra request per connection, never one
per call. An operator-set ``port:`` is used verbatim and never probed: they
already said where SWIS lives.

Same probe-and-remember shape as the Zabbix Bearer/legacy-auth fallback in
``zabbix_rpc``. No live Orion needed — a fake client records the base_url in
force for each request, so the ports actually dialled are directly assertable.
"""

from __future__ import annotations

import httpx
import pytest
import yaml

from monitoring_aiops.config import (
    SWIS_LEGACY_PORT,
    SWIS_PORT,
    TargetConfig,
    load_config,
)
from monitoring_aiops.connection import MonitoringApiError, MonitoringConnection

pytestmark = pytest.mark.unit


class _Resp:
    def __init__(self, payload: dict | None = None, status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.content = b"{}"
        self.text = "body"

    def json(self) -> dict:
        return self._payload


class _PortClient:
    """Fake httpx client recording which base_url each request went out on."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.base_url = ""
        self.calls: list[tuple[str, str, str]] = []  # (method, path, base_url)
        self.closed = False

    def request(self, method: str, path: str, **kwargs: object) -> object:
        self.calls.append((method, path, self.base_url))
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    def close(self) -> None:
        self.closed = True

    @property
    def ports(self) -> list[int]:
        """The port dialled for each request, in order."""
        return [int(base.rsplit(":", 1)[1]) for _, _, base in self.calls]


def _conn(
    monkeypatch: pytest.MonkeyPatch,
    responses: list,
    *,
    port: int = 0,
    scheme: str = "https",
) -> tuple[MonitoringConnection, _PortClient]:
    monkeypatch.setenv("MONITORING_SW1_SECRET", "pw")
    target = TargetConfig(name="sw1", platform="solarwinds", host="orion.local",
                          port=port, username="admin", verify_ssl=False, scheme=scheme)
    client = _PortClient(responses)
    client.base_url = target.base_url  # real httpx gets this via the constructor
    return MonitoringConnection(target, client=client), client


# ── the default: modern port, no probe when it answers ───────────────────────


def test_default_port_is_the_modern_swis_port_and_is_used_first(monkeypatch):
    conn, client = _conn(monkeypatch, [_Resp({"results": [{"NodeID": 1}]})])
    assert SWIS_PORT == 17774
    assert conn.target.port == 17774
    assert conn.swql("SELECT 1") == [{"NodeID": 1}]
    # A 2023.1+ server pays nothing for the fallback: one request, modern port.
    assert client.ports == [17774]
    assert conn.port == 17774


def test_modern_port_answering_with_an_http_error_still_settles_the_port(monkeypatch):
    """A 401 proves something is listening and speaking HTTP there — the port
    is right and the credentials are wrong. Retrying 17778 would only swap a
    precise auth error for a confusing reachability one."""
    conn, client = _conn(monkeypatch, [
        _Resp(None, status_code=401),
        _Resp({"results": []}),
    ])
    with pytest.raises(MonitoringApiError, match="Authentication failed"):
        conn.swql("SELECT 1")
    conn.swql("SELECT 2")
    assert client.ports == [17774, 17774]


# ── the fallback: legacy port, probed once, then remembered ──────────────────


def test_refused_modern_port_falls_back_to_legacy_and_succeeds(monkeypatch):
    conn, client = _conn(monkeypatch, [
        httpx.ConnectError("refused"),
        _Resp({"results": [{"NodeID": 7}]}),
    ])
    assert conn.swql("SELECT 1") == [{"NodeID": 7}]
    assert client.ports == [17774, SWIS_LEGACY_PORT]
    assert conn.port == 17778
    assert conn.base_url == "https://orion.local:17778"
    assert client.base_url == "https://orion.local:17778"


def test_working_legacy_port_is_cached_so_the_probe_never_repeats(monkeypatch):
    conn, client = _conn(monkeypatch, [
        httpx.ConnectError("refused"),
        _Resp({"results": []}),
        _Resp({"results": []}),
        _Resp({"results": []}),
    ])
    conn.swql("SELECT 1")
    conn.swql("SELECT 2")
    conn.swql("SELECT 3")
    # One probe on the first call; every later call goes straight to 17778.
    assert client.ports == [17774, 17778, 17778, 17778]


def test_a_later_transient_failure_never_migrates_a_settled_connection(monkeypatch):
    """Once a port has proven itself, a blip must surface as a reachability
    error — not quietly move a healthy connection onto the deprecated port."""
    conn, client = _conn(monkeypatch, [
        _Resp({"results": []}),
        httpx.ConnectError("blip"),
    ])
    conn.swql("SELECT 1")
    with pytest.raises(MonitoringApiError) as exc:
        conn.swql("SELECT 2")
    assert client.ports == [17774, 17774]  # no fallback probe
    assert conn.port == 17774
    assert "Could not reach solarwinds" in str(exc.value)


def test_fallback_preserves_the_configured_scheme(monkeypatch):
    """The scheme knob and the port fallback are independent: an http-only
    Orion behind a reverse proxy must not get silently promoted to https."""
    conn, client = _conn(monkeypatch, [
        httpx.ConnectError("refused"),
        _Resp({"results": []}),
    ], scheme="http")
    conn.swql("SELECT 1")
    assert conn.base_url == "http://orion.local:17778"
    assert client.base_url == "http://orion.local:17778"


# ── an operator-set port is intent, not a guess ──────────────────────────────


@pytest.mark.parametrize("port", [17774, 17778, 8787])
def test_operator_set_port_is_used_verbatim_with_no_fallback(monkeypatch, port):
    conn, client = _conn(monkeypatch, [httpx.ConnectError("refused")], port=port)
    assert conn.target.port_is_explicit is True
    with pytest.raises(MonitoringApiError) as exc:
        conn.swql("SELECT 1")
    # Tried exactly once, exactly where the operator said — no second guess.
    assert client.ports == [port]
    msg = str(exc.value)
    assert "Could not reach solarwinds" in msg
    assert "either SWIS port" not in msg


def test_load_config_preserves_stated_versus_defaulted_port(tmp_path):
    """Both targets resolve to 17774; only one of them asked for it. The
    fallback hinges entirely on telling those two apart."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"targets": [
        {"name": "stated", "platform": "solarwinds", "host": "a", "port": 17774},
        {"name": "defaulted", "platform": "solarwinds", "host": "b"},
    ]}), "utf-8")
    cfg = load_config(path)
    stated = cfg.get_target("stated")
    defaulted = cfg.get_target("defaulted")
    assert stated.port == defaulted.port == SWIS_PORT
    assert stated.port_is_explicit is True
    assert defaulted.port_is_explicit is False


# ── both ports down: the message has to teach ────────────────────────────────


def test_both_ports_failing_names_both_and_how_to_pin_one(monkeypatch):
    conn, client = _conn(monkeypatch, [
        httpx.ConnectError("refused-modern"),
        httpx.ConnectError("refused-legacy"),
    ])
    with pytest.raises(MonitoringApiError) as exc:
        conn.swql("SELECT 1")
    assert client.ports == [17774, 17778]
    msg = str(exc.value)
    assert "17774" in msg and "17778" in msg          # both ports named
    assert "2023.1" in msg                            # which one is modern
    assert "legacy" in msg                            # and which one is not
    assert "refused-modern" in msg and "refused-legacy" in msg  # both causes
    assert "port:" in msg and "config.yaml" in msg    # the explicit override
    assert "sw1" in msg                               # the target to edit
    assert exc.value.path == "/SolarWinds/InformationService/v3/Json/Query"


# ── other platforms are untouched ────────────────────────────────────────────


@pytest.mark.parametrize("platform", ["prtg", "zabbix"])
def test_other_platforms_never_probe_a_second_port(monkeypatch, platform):
    """Only SolarWinds moved its port; PRTG/Zabbix must fail fast on one try."""
    monkeypatch.setenv("MONITORING_P1_SECRET", "tok")
    target = TargetConfig(name="p1", platform=platform, host="h", verify_ssl=False)
    client = _PortClient([httpx.ConnectError("refused")])
    client.base_url = target.base_url
    conn = MonitoringConnection(target, client=client)
    with pytest.raises(MonitoringApiError) as exc:
        if platform == "prtg":
            conn.prtg_get("/api/status.json")
        else:
            conn.zabbix_rpc("apiinfo.version")
    assert len(client.calls) == 1
    msg = str(exc.value)
    assert f"Could not reach {platform}" in msg
    assert "reachability" in msg
