"""CLI write path — dry-run previews and confirmed writes, both governed.

The CLI write commands delegate execution to the ``@governed_tool`` functions
in ``mcp_server.tools``. These tests drive ``alert ack`` PAST the double-confirm
prompts and assert the call really went through the governed path (audit row on
disk) — the regression test for the "CLI writes were unaudited" line-wide fix.

``--dry-run`` routes through the same governed twin with ``dry_run=True``. The
invariant it holds is **a dry_run MAY read; it must never write**: no acknowledge
reaches the platform, while the audit row IS written. The older rule — that a
preview reached no governed call at all — made every guard unreachable from a
preview, so a preview could green-light a call the real write then refused.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import monitoring_aiops.governance.audit as audit_mod
import monitoring_aiops.governance.policy as policy_mod
import monitoring_aiops.governance.undo as undo_mod


@pytest.fixture
def gov_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITORING_AIOPS_HOME", str(tmp_path))
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()
    yield tmp_path
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()


def _audit_tools(db_path: Path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT tool FROM audit_log ORDER BY id")]
    finally:
        conn.close()


def _sw_conn() -> MagicMock:
    conn = MagicMock(name="conn")
    conn.target.platform = "solarwinds"
    return conn


@pytest.mark.unit
def test_cli_alert_ack_dry_run_reads_and_audits_but_never_writes(gov_home, monkeypatch):
    """The invariant: a dry_run MAY read; it must never write.

    The preview routes through the governed twin, so it is policy-checked and
    audited, but no acknowledge reaches the platform. It also now reports the
    RESOLVED platform rather than a hand-written string — the three platforms
    take different endpoints and id shapes, so that is the part worth seeing
    before committing.
    """
    from monitoring_aiops.cli import app

    conn = _sw_conn()
    import mcp_server.tools.alerts as gov_alerts

    monkeypatch.setattr(gov_alerts, "_get_connection", lambda target=None: conn)
    result = CliRunner().invoke(app, ["alert", "ack", "42", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    assert "platform = solarwinds" in result.output
    conn.swis_invoke.assert_not_called()
    conn.prtg_post.assert_not_called()
    assert _audit_tools(gov_home / "audit.db") == ["alert_acknowledge"]


@pytest.mark.unit
def test_cli_alert_ack_dry_run_resolves_the_prtg_platform(gov_home, monkeypatch):
    """Exactness on the other branch: the preview is not hardcoded to SolarWinds."""
    from monitoring_aiops.cli import app

    conn = MagicMock(name="conn")
    conn.target.platform = "prtg"
    import mcp_server.tools.alerts as gov_alerts

    monkeypatch.setattr(gov_alerts, "_get_connection", lambda target=None: conn)
    result = CliRunner().invoke(app, ["alert", "ack", "9001", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "platform = prtg" in result.output
    conn.prtg_post.assert_not_called()


@pytest.mark.unit
def test_cli_alert_ack_dry_run_refusal_prints_the_teaching_message_nonzero(
    gov_home, monkeypatch
):
    """A refused preview must print the refusal and exit non-zero.

    The refusal arrives as ``{"error": ...}`` — ``tool_errors`` flattens
    whatever the tool body raised — and the banner is never printed. Previously
    the preview could not fail at all: it was a hand-written string, so it
    green-lit a call that the real write would then reject.
    """
    import mcp_server.tools.alerts as gov_alerts
    from monitoring_aiops.cli import app
    from monitoring_aiops.connection import MonitoringApiError

    def _boom(target=None):
        raise MonitoringApiError("no such target 'ghost'")

    monkeypatch.setattr(gov_alerts, "_get_connection", _boom)
    result = CliRunner().invoke(app, ["alert", "ack", "42", "--dry-run", "-t", "ghost"])

    assert result.exit_code == 1
    assert "DRY-RUN" not in result.output
    assert "no such target" in result.output


@pytest.mark.unit
def test_cli_alert_ack_confirmed_goes_through_governance(gov_home, monkeypatch):
    """Confirmed CLI write must execute via the governed twin: the API call runs
    AND an audit row lands in audit.db (this is what the reroute fix bought)."""
    from monitoring_aiops.cli import app

    conn = _sw_conn()
    import mcp_server.tools.alerts as gov_alerts

    monkeypatch.setattr(gov_alerts, "_get_connection", lambda target=None: conn)
    result = CliRunner().invoke(app, ["alert", "ack", "42"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    conn.swis_invoke.assert_called_once()
    assert _audit_tools(gov_home / "audit.db") == ["alert_acknowledge"]


@pytest.mark.unit
def test_cli_alert_ack_aborts_without_double_confirm(gov_home, monkeypatch):
    from monitoring_aiops.cli import app

    conn = _sw_conn()
    import mcp_server.tools.alerts as gov_alerts

    monkeypatch.setattr(gov_alerts, "_get_connection", lambda target=None: conn)
    result = CliRunner().invoke(app, ["alert", "ack", "42"], input="y\nn\n")
    assert result.exit_code != 0
    conn.swis_invoke.assert_not_called()
    assert not (gov_home / "audit.db").exists()
