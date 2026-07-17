"""Tests for ``monitoring_aiops.doctor.run_doctor``.

Everything runs against an ``isolated_home`` (see conftest) — no real
``~/.monitoring-aiops`` and no network: the connectivity check is exercised by
patching ``ConnectionManager`` at the connection-module boundary.

Monitoring specifics: three platforms per fleet — ``solarwinds`` targets are
probed with a canned SWQL query, ``prtg`` targets with a status-API GET, and
``zabbix`` targets with the unauthenticated ``apiinfo.version`` (connectivity)
followed by a cheap authed host count (token validity).
"""

from __future__ import annotations

import io
from typing import Any

import pytest
import yaml
from rich.console import Console

import monitoring_aiops.doctor as doc
import monitoring_aiops.secretstore as ss
from tests.conftest import MASTER_PW

pytestmark = pytest.mark.unit


@pytest.fixture
def doctor_out(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    """Capture doctor output on a wide console (no line-wrapping surprises)."""
    buf = io.StringIO()
    monkeypatch.setattr(doc, "_console", Console(file=buf, width=200))
    return buf


def _write_config(home, targets: list[dict]) -> None:
    (home / "config.yaml").write_text(yaml.safe_dump({"targets": targets}), "utf-8")


def _seed_secret(name: str, value: str) -> None:
    ss.SecretStore.unlock(MASTER_PW).set(name, value)


NOC1 = {
    "name": "noc1",
    "platform": "solarwinds",
    "host": "orion.example.com",
    "port": 17778,
    "username": "admin",
}
PRTG1 = {"name": "prtg1", "platform": "prtg", "host": "prtg.example.com", "port": 443}
ZBX1 = {"name": "zbx1", "platform": "zabbix", "host": "zabbix.example.com", "port": 443}


# ─── broken-environment paths ───────────────────────────────────────────────


def test_missing_config_file(isolated_home, doctor_out):
    assert doc.run_doctor() == 1
    out = doctor_out.getvalue()
    assert "✗ Config file missing" in out
    assert "monitoring-aiops init" in out


def test_config_load_failure(isolated_home, doctor_out):
    (isolated_home / "config.yaml").write_text("targets: [ {name: broken", "utf-8")
    assert doc.run_doctor() == 1
    assert "✗ Config load failed" in doctor_out.getvalue()


def test_no_targets_configured(isolated_home, doctor_out):
    _write_config(isolated_home, [])
    assert doc.run_doctor() == 1
    assert "✗ No targets configured" in doctor_out.getvalue()


def test_no_secret_store_and_no_secret(isolated_home, doctor_out):
    _write_config(isolated_home, [NOC1])
    assert doc.run_doctor(skip_auth=True) == 1
    out = doctor_out.getvalue()
    assert "! No secret store yet" in out
    assert "✗ No secret for target 'noc1'" in out


def test_legacy_env_file_warns_but_works(isolated_home, doctor_out, monkeypatch):
    _write_config(isolated_home, [NOC1])
    (isolated_home / ".env").write_text("MONITORING_NOC1_SECRET=legacy\n", "utf-8")
    monkeypatch.setenv("MONITORING_NOC1_SECRET", "legacy")
    assert doc.run_doctor(skip_auth=True) == 0
    out = doctor_out.getvalue()
    assert "legacy plaintext .env" in out
    assert "secret migrate" in out
    assert "✓ Secret present for 'noc1' (solarwinds)" in out


def test_world_readable_secrets_warns(isolated_home, doctor_out):
    _write_config(isolated_home, [NOC1])
    _seed_secret("noc1", "s3cret")
    (isolated_home / "secrets.enc").chmod(0o644)
    assert doc.run_doctor(skip_auth=True) == 0  # warning, not a failure
    assert "should be 600" in doctor_out.getvalue()


# ─── healthy paths ───────────────────────────────────────────────────────────


def test_healthy_skip_auth(isolated_home, doctor_out):
    _write_config(isolated_home, [NOC1])
    _seed_secret("noc1", "s3cret")
    assert doc.run_doctor(skip_auth=True) == 0
    out = doctor_out.getvalue()
    assert "✓ Config file present" in out
    assert "✓ 1 target(s) configured" in out
    assert "✓ Encrypted secret store present" in out
    assert "✓ Secret present for 'noc1' (solarwinds)" in out
    assert "Skipping connectivity check" in out


class _FakeConn:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.zbx_methods: list[str] = []

    def swql(self, query: str, **_: Any) -> Any:
        assert "Orion.Nodes" in query
        return self._result

    def prtg_get(self, path: str, **_: Any) -> Any:
        assert path == "/api/status.json"
        return self._result

    def zabbix_rpc(self, method: str, params: Any = None) -> Any:
        self.zbx_methods.append(method)
        if method == "apiinfo.version":  # unauthenticated connectivity probe
            return self._result
        assert method == "host.get" and params == {"countOutput": True}  # authed probe
        return "3"


class _FakeMgr:
    """Stands in for ConnectionManager; per-target canned results."""

    results: dict[str, Any] = {}

    def __init__(self, config: Any) -> None:
        self._config = config

    def connect(self, name: str) -> _FakeConn:
        result = self.results[name]
        if isinstance(result, Exception):
            raise result
        return _FakeConn(result)


@pytest.fixture
def fake_mgr(monkeypatch: pytest.MonkeyPatch) -> type[_FakeMgr]:
    import monitoring_aiops.connection as conn_mod

    _FakeMgr.results = {}
    monkeypatch.setattr(conn_mod, "ConnectionManager", _FakeMgr)
    return _FakeMgr


def test_healthy_solarwinds_end_to_end(isolated_home, doctor_out, fake_mgr):
    _write_config(isolated_home, [NOC1])
    _seed_secret("noc1", "s3cret")
    fake_mgr.results["noc1"] = [{"NodeID": 1}]
    assert doc.run_doctor() == 0
    out = doctor_out.getvalue()
    assert "✓ Connected to 'noc1' (solarwinds orion.example.com)" in out
    assert "SWIS/SWQL query OK" in out


def test_healthy_prtg_end_to_end(isolated_home, doctor_out, fake_mgr):
    _write_config(isolated_home, [PRTG1])
    _seed_secret("prtg1", "api-token")
    fake_mgr.results["prtg1"] = {"Version": "24.x"}
    assert doc.run_doctor() == 0
    out = doctor_out.getvalue()
    assert "✓ Connected to 'prtg1' (prtg prtg.example.com)" in out
    assert "PRTG API OK" in out


def test_healthy_zabbix_end_to_end(isolated_home, doctor_out, fake_mgr):
    """Zabbix probe = apiinfo.version (no auth) THEN a cheap authed host count."""
    _write_config(isolated_home, [ZBX1])
    _seed_secret("zbx1", "api-token")
    fake_mgr.results["zbx1"] = "7.0.0"
    assert doc.run_doctor() == 0
    out = doctor_out.getvalue()
    assert "✓ Connected to 'zbx1' (zabbix zabbix.example.com)" in out
    assert "Zabbix API 7.0.0 OK (token valid)" in out


def test_connect_failure_is_status_not_crash(isolated_home, doctor_out, fake_mgr):
    _write_config(isolated_home, [NOC1])
    _seed_secret("noc1", "s3cret")
    fake_mgr.results["noc1"] = ConnectionError("connection refused")
    assert doc.run_doctor() == 1
    assert "✗ Connect to 'noc1' failed: connection refused" in doctor_out.getvalue()


def test_mixed_fleet_one_bad_target_fails_overall(isolated_home, doctor_out, fake_mgr):
    _write_config(isolated_home, [NOC1, PRTG1])
    _seed_secret("noc1", "s1")
    _seed_secret("prtg1", "s2")
    fake_mgr.results["noc1"] = [{"NodeID": 1}]
    fake_mgr.results["prtg1"] = RuntimeError("401 auth failed")
    assert doc.run_doctor() == 1
    out = doctor_out.getvalue()
    assert "✓ Connected to 'noc1'" in out
    assert "✗ Connect to 'prtg1' failed: 401 auth failed" in out
