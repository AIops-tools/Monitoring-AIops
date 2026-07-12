"""Unit tests for PRTG governed writes (pause / resume / maintenance)."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
def test_pause_sensor_with_minutes_uses_pauseobjectfor():
    from monitoring_aiops.ops import prtg_write as ops

    conn = MagicMock(name="conn")
    conn.target.platform = "prtg"
    out = ops.pause_sensor(conn, "2010", minutes=30, message="patching")
    conn.prtg_post.assert_called_once()
    path, params = conn.prtg_post.call_args[0]
    assert path == "/api/pauseobjectfor.htm"
    assert params["duration"] == 30 and params["id"] == "2010"
    assert out["action"] == "pause_sensor" and out["priorState"] == {"paused": False}


@pytest.mark.unit
def test_schedule_maintenance_rejects_non_positive_minutes():
    from monitoring_aiops.ops import prtg_write as ops

    conn = MagicMock(name="conn")
    conn.target.platform = "prtg"
    with pytest.raises(ValueError):
        ops.schedule_maintenance(conn, "2010", 0)
    conn.prtg_post.assert_not_called()


@pytest.mark.unit
def test_prtg_write_risk_tiers_all_medium():
    from mcp_server.tools import prtg_write

    assert prtg_write.pause_sensor._risk_level == "medium"
    assert prtg_write.resume_sensor._risk_level == "medium"
    assert prtg_write.schedule_maintenance_prtg._risk_level == "medium"


@pytest.mark.unit
def test_pause_sensor_undo_descriptor_targets_resume_same_object():
    from mcp_server.tools import prtg_write

    descriptor = prtg_write._pause_undo(
        {"object_id": "2010"}, {"priorState": {"paused": False}}
    )
    assert descriptor["tool"] == "resume_sensor"
    assert descriptor["params"]["object_id"] == "2010"
