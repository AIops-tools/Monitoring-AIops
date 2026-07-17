"""Smoke + ops tests for monitoring-aiops.

Proves: every module imports, the CLI builds and --help works, the MCP server
exposes the expected tools and EVERY tool carries the harness marker
``_is_governed_tool``, the platform-dispatching connection (SolarWinds SWQL vs
PRTG) + SWQL read-only validation work, the flagship canned-SWQL library + alert
dedup/rollup behave, and the acknowledge write dispatches per platform. No real
SolarWinds/PRTG is needed — the connection is a fake/MagicMock.
"""

import asyncio
import importlib
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

# Kept in sync with mcp_server/server.py (the full registered tool surface).
EXPECTED_TOOLS = {
    # swql
    "swql_library", "swql_canned", "swql_query",
    # alerts
    "active_alerts", "alert_acknowledge",
    # sw_health
    "node_status", "nodes_list", "interface_status", "volume_status",
    "application_status", "topn", "noc_rollup",
    # sw_write
    "list_events", "list_unmanaged", "list_muted", "mute_alerts", "unmute_alerts",
    "schedule_maintenance", "unmanage_node", "remanage_node", "remove_node",
    # prtg
    "prtg_sensors", "prtg_sensor_details", "prtg_devices", "prtg_groups",
    "prtg_history", "prtg_system_status", "prtg_alarms",
    # prtg_write
    "pause_sensor", "resume_sensor", "schedule_maintenance_prtg",
    # zabbix
    "zabbix_problems", "zabbix_hosts", "zabbix_hostgroups", "zabbix_triggers",
    "zabbix_events", "zabbix_item_history", "zabbix_maintenances",
    # zabbix_write
    "zabbix_create_maintenance", "zabbix_delete_maintenance",
}


@pytest.mark.unit
def test_all_modules_import():
    for name in (
        "monitoring_aiops", "monitoring_aiops.config", "monitoring_aiops.connection",
        "monitoring_aiops.doctor", "monitoring_aiops.secretstore",
        "monitoring_aiops.ops.swql", "monitoring_aiops.ops.alerts",
        "monitoring_aiops.ops.overview",
        "monitoring_aiops.ops.zabbix", "monitoring_aiops.ops.zabbix_write",
        "monitoring_aiops.cli", "monitoring_aiops.cli._root", "monitoring_aiops.cli._common",
        "monitoring_aiops.cli.init", "monitoring_aiops.cli.secret", "monitoring_aiops.cli.swql",
        "monitoring_aiops.cli.alert", "monitoring_aiops.cli.overview",
        "monitoring_aiops.cli.doctor",
        "mcp_server.server", "mcp_server._shared",
        "mcp_server.tools.swql", "mcp_server.tools.alerts",
        "mcp_server.tools.zabbix", "mcp_server.tools.zabbix_write",
    ):
        importlib.import_module(name)


@pytest.mark.unit
def test_version_matches_pyproject():
    """__version__ is single-sourced from package metadata; it must track
    pyproject.toml so a release bump can never ship a stale self-report."""
    import tomllib
    from pathlib import Path

    import monitoring_aiops

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text("utf-8"))["project"]["version"]
    assert monitoring_aiops.__version__ == expected


@pytest.mark.unit
def test_cli_app_builds_and_help_works():
    from monitoring_aiops.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for sub in ("swql", "alert", "secret", "init", "overview", "doctor", "mcp"):
        assert sub in result.output


@pytest.mark.unit
def test_cli_leaf_help_triggers_lazy_imports():
    from monitoring_aiops.cli import app

    runner = CliRunner()
    for cmd in (
        ["swql", "--help"], ["alert", "--help"], ["secret", "--help"],
        ["doctor", "--help"], ["overview", "--help"], ["init", "--help"],
        ["swql", "library", "--help"], ["swql", "canned", "--help"], ["swql", "query", "--help"],
        ["alert", "list", "--help"], ["alert", "ack", "--help"],
        ["secret", "list", "--help"], ["secret", "set", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"


@pytest.mark.unit
def test_mcp_list_tools_exposes_expected_tools():
    from mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"


@pytest.mark.unit
def test_every_mcp_tool_is_governed_by_harness():
    from mcp_server import _shared

    tool_objs = _shared.mcp._tool_manager._tools
    assert EXPECTED_TOOLS <= set(tool_objs), "tool registry incomplete"
    for name, tool in tool_objs.items():
        fn = getattr(tool, "fn", None)
        assert fn is not None, f"{name} has no fn"
        assert getattr(fn, "_is_governed_tool", False), f"{name} missing @governed_tool"


# ── config platform validation ──────────────────────────────────────────


@pytest.mark.unit
def test_config_rejects_bad_platform_and_defaults_port():
    from monitoring_aiops.config import TargetConfig

    with pytest.raises(ValueError):
        TargetConfig(name="x", platform="nagios", host="h")
    sw = TargetConfig(name="sw", platform="solarwinds", host="h")
    assert sw.port == 17778
    prtg = TargetConfig(name="p", platform="prtg", host="h")
    assert prtg.port == 443
    zbx = TargetConfig(name="z", platform="zabbix", host="h")
    assert zbx.port == 443


# ── connection: SWQL passthrough + platform guard ───────────────────────


class _Resp:
    def __init__(self, status, payload=None, content=b"{}"):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = "body"

    def json(self):
        return self._payload


@pytest.mark.unit
def test_connection_swql_and_platform_guard(monkeypatch):
    from monitoring_aiops.config import TargetConfig
    from monitoring_aiops.connection import MonitoringApiError, MonitoringConnection

    monkeypatch.setenv("MONITORING_SW1_SECRET", "pw")
    target = TargetConfig(name="sw1", platform="solarwinds", host="orion.local",
                          username="admin", verify_ssl=False)

    class _Client:
        def request(self, method, path, **k):
            return _Resp(200, {"results": [{"NodeID": 1}]})

        def close(self):
            pass

    conn = MonitoringConnection(target, client=_Client())
    assert conn.swql("SELECT NodeID FROM Orion.Nodes")[0]["NodeID"] == 1
    # PRTG-only method against a SolarWinds target must raise
    with pytest.raises(MonitoringApiError):
        conn.prtg_get("/api/status.json")


@pytest.mark.unit
def test_swis_invoke_url_encodes_path_segments(monkeypatch):
    """An entity/verb containing '../' must never reach the URL path raw —
    path segments are percent-encoded (query params are httpx's job)."""
    from monitoring_aiops.config import TargetConfig
    from monitoring_aiops.connection import MonitoringConnection

    monkeypatch.setenv("MONITORING_SW1_SECRET", "pw")
    target = TargetConfig(name="sw1", platform="solarwinds", host="orion.local",
                          username="admin", verify_ssl=False)
    calls = []

    class _Client:
        def request(self, method, path, **k):
            calls.append((method, path))
            return _Resp(200, {})

        def close(self):
            pass

    conn = MonitoringConnection(target, client=_Client())
    conn.swis_invoke("Orion.Nodes/../../evil", "Un manage")
    _method, path = calls[0]
    assert "../" not in path
    assert "Orion.Nodes%2F..%2F..%2Fevil" in path
    assert "Un%20manage" in path


# ── flagship SWQL library + read-only validation ────────────────────────


@pytest.mark.unit
def test_swql_run_query_rejects_non_select():
    from monitoring_aiops.ops import swql as ops

    conn = MagicMock(name="conn")
    with pytest.raises(ValueError):
        ops.run_query(conn, "DELETE FROM Orion.Nodes")
    conn.swql.assert_not_called()


@pytest.mark.unit
def test_swql_canned_library_has_named_queries():
    from monitoring_aiops.ops import swql as ops

    lib = ops.list_canned()
    names = {q["name"] for q in lib}
    assert {"nodes_down", "flapping_interfaces", "muted_report"} <= names


@pytest.mark.unit
def test_swql_run_canned_executes_named_query():
    from monitoring_aiops.ops import swql as ops

    conn = MagicMock(name="conn")
    conn.swql.return_value = [{"Caption": "sw1"}]
    out = ops.run_canned(conn, "nodes_down")
    assert out["name"] == "nodes_down" and out["rowCount"] == 1
    conn.swql.assert_called_once()


# ── alert dedup/rollup + acknowledge dispatch ───────────────────────────


@pytest.mark.unit
def test_active_alerts_dedups_by_message():
    from monitoring_aiops.ops import alerts as ops

    conn = MagicMock(name="conn")
    conn.target.platform = "solarwinds"
    conn.swql.return_value = [
        {"AlertActiveID": 1, "EntityCaption": "if1", "TriggeredMessage": "interface down",
         "Acknowledged": False},
        {"AlertActiveID": 2, "EntityCaption": "if2", "TriggeredMessage": "interface down",
         "Acknowledged": False},
        {"AlertActiveID": 3, "EntityCaption": "n1", "TriggeredMessage": "node down",
         "Acknowledged": True},
    ]
    out = ops.active_alerts(conn)
    assert out["total"] == 3 and out["unacknowledged"] == 2
    top = out["rollup"][0]
    assert top["message"] == "interface down" and top["count"] == 2


@pytest.mark.unit
def test_acknowledge_alert_dispatches_solarwinds_verb():
    from monitoring_aiops.ops import alerts as ops

    conn = MagicMock(name="conn")
    conn.target.platform = "solarwinds"
    out = ops.acknowledge_alert(conn, "42")
    assert out["action"] == "acknowledge_alert" and out["platform"] == "solarwinds"
    conn.swis_invoke.assert_called_once()


@pytest.mark.unit
def test_alert_acknowledge_risk_is_low():
    from mcp_server.tools import alerts as a

    assert a.alert_acknowledge._risk_level == "low"
