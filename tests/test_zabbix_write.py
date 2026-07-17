"""Unit tests for Zabbix governed writes (ack / maintenance create + delete).

Mirrors the PRTG-write test style: MagicMock connections, envelope assertions
on the JSON-RPC params, priorState capture (ack state before acknowledging; the
FULL window definition before deleting), the create→delete replayable undo
descriptor, teaching errors for unbounded/empty windows, and the risk tiers.
"""

from unittest.mock import MagicMock

import pytest


def _mock_conn(**rpc_results):
    conn = MagicMock(name="conn")
    conn.target.platform = "zabbix"

    def _rpc(method, params=None):
        return rpc_results[method]

    conn.zabbix_rpc = MagicMock(side_effect=_rpc)
    return conn


# ── acknowledge (priorState = BEFORE ack state; undo n/a) ───────────────────


@pytest.mark.unit
def test_acknowledge_event_captures_prior_ack_state():
    from monitoring_aiops.ops import zabbix_write as ops

    conn = _mock_conn(**{
        "event.get": [{"eventid": "42", "acknowledged": "1"}],  # already acked
        "event.acknowledge": {"eventids": ["42"]},
    })
    out = ops.acknowledge_event(conn, "42", message="triaged")
    assert out["priorState"] == {"acknowledged": True}
    # The BEFORE read must happen, then the acknowledge with action 6 + message.
    methods = [c[0][0] for c in conn.zabbix_rpc.call_args_list]
    assert methods == ["event.get", "event.acknowledge"]
    ack_params = conn.zabbix_rpc.call_args_list[1][0][1]
    assert ack_params["action"] == 6 and ack_params["message"] == "triaged"


# ── create_maintenance (time-boxed, replayable delete-undo) ─────────────────


@pytest.mark.unit
def test_create_maintenance_builds_one_time_period_and_returns_id():
    from monitoring_aiops.ops import zabbix_write as ops

    conn = _mock_conn(**{"maintenance.create": {"maintenanceids": ["55"]}})
    out = ops.create_maintenance(conn, "patch web01", 60, host_ids=["1"], group_ids=["2"])
    assert out["maintenanceId"] == "55" and out["minutes"] == 60
    params = conn.zabbix_rpc.call_args[0][1]
    assert params["name"] == "patch web01"
    assert params["hosts"] == [{"hostid": "1"}]
    assert params["groups"] == [{"groupid": "2"}]
    assert params["active_till"] - params["active_since"] == 3600
    period = params["timeperiods"][0]
    assert period["timeperiod_type"] == 0 and period["period"] == 3600


@pytest.mark.unit
def test_create_maintenance_rejects_non_positive_minutes():
    from monitoring_aiops.ops import zabbix_write as ops

    conn = _mock_conn()
    with pytest.raises(ValueError, match="time-boxed"):
        ops.create_maintenance(conn, "forever", 0, host_ids=["1"])
    conn.zabbix_rpc.assert_not_called()


@pytest.mark.unit
def test_create_maintenance_requires_hosts_or_groups():
    from monitoring_aiops.ops import zabbix_write as ops

    conn = _mock_conn()
    with pytest.raises(ValueError, match="at least one host_ids or group_ids"):
        ops.create_maintenance(conn, "covers nothing", 30)
    conn.zabbix_rpc.assert_not_called()


@pytest.mark.unit
def test_create_maintenance_undo_descriptor_deletes_that_id():
    """The undo must be replayable: delete exactly the created maintenance id."""
    from mcp_server.tools import zabbix_write

    descriptor = zabbix_write._create_maintenance_undo(
        {"name": "patch web01", "minutes": 60},
        {"action": "create_maintenance", "maintenanceId": "55"},
    )
    assert descriptor["tool"] == "zabbix_delete_maintenance"
    assert descriptor["params"] == {"maintenance_id": "55"}
    # No id back from the server → no undo descriptor (never guess).
    assert zabbix_write._create_maintenance_undo({}, {"maintenanceId": ""}) is None
    assert zabbix_write._create_maintenance_undo({}, "not-a-dict") is None


# ── delete_maintenance (HIGH; priorState = full definition) ─────────────────


@pytest.mark.unit
def test_delete_maintenance_captures_full_prior_definition():
    from monitoring_aiops.ops import zabbix_write as ops

    definition = {
        "maintenanceid": "55", "name": "patch web01",
        "active_since": "1700000000", "active_till": "1700003600",
        "description": "monthly patching",
        "hosts": [{"hostid": "1", "host": "web01"}],
        "hostgroups": [{"groupid": "2", "name": "Linux servers"}],
        "timeperiods": [{"timeperiod_type": "0", "start_date": "1700000000",
                         "period": "3600"}],
    }
    conn = _mock_conn(**{"maintenance.get": [definition], "maintenance.delete": ["55"]})
    out = ops.delete_maintenance(conn, "55")
    prior = out["priorState"]
    assert prior["name"] == "patch web01"
    assert prior["hosts"] == [{"hostId": "1", "host": "web01"}]
    assert prior["groups"] == [{"groupId": "2", "name": "Linux servers"}]
    assert prior["timeperiods"][0]["period"] == "3600"
    # Read-before-delete ordering, and the delete carries the id list.
    methods = [c[0][0] for c in conn.zabbix_rpc.call_args_list]
    assert methods == ["maintenance.get", "maintenance.delete"]
    assert conn.zabbix_rpc.call_args_list[1][0][1] == ["55"]


@pytest.mark.unit
def test_delete_maintenance_missing_id_teaches_instead_of_deleting():
    from monitoring_aiops.ops import zabbix_write as ops

    conn = _mock_conn(**{"maintenance.get": []})
    with pytest.raises(ValueError, match="not found"):
        ops.delete_maintenance(conn, "404")
    methods = [c[0][0] for c in conn.zabbix_rpc.call_args_list]
    assert "maintenance.delete" not in methods


@pytest.mark.unit
def test_zabbix_delete_maintenance_dry_run_previews_without_deleting(monkeypatch):
    from mcp_server.tools import zabbix_write as gov

    conn = _mock_conn(**{"maintenance.get": [{"maintenanceid": "55", "name": "w"}]})
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    out = gov.zabbix_delete_maintenance(maintenance_id="55", dry_run=True)
    assert out["dryRun"] is True and out["wouldDelete"]["name"] == "w"
    methods = [c[0][0] for c in conn.zabbix_rpc.call_args_list]
    assert "maintenance.delete" not in methods


@pytest.mark.unit
def test_zabbix_write_risk_tiers():
    from mcp_server.tools import zabbix_write

    assert zabbix_write.zabbix_create_maintenance._risk_level == "medium"
    assert zabbix_write.zabbix_delete_maintenance._risk_level == "high"
    for tool in (zabbix_write.zabbix_create_maintenance,
                 zabbix_write.zabbix_delete_maintenance):
        assert getattr(tool, "_is_governed_tool", False)
