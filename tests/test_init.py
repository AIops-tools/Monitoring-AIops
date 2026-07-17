"""Tests for the ``monitoring-aiops init`` wizard.

Driven through typer's CliRunner against an ``isolated_home`` (see conftest);
the master password comes from ``MONITORING_AIOPS_MASTER_PASSWORD`` and the
hidden secret prompt is fed by patching ``getpass``. The trailing doctor run
is either declined via stdin or patched out.

Monitoring specifics: a platform prompt (solarwinds default / prtg / zabbix),
a per-platform port default (17778 / 443 / 443), and an Orion-username prompt
that only appears for solarwinds targets.
"""

from __future__ import annotations

import pytest
import yaml
from typer.testing import CliRunner

import monitoring_aiops.cli.init as init_mod
import monitoring_aiops.secretstore as ss
from monitoring_aiops.cli._root import app
from tests.conftest import MASTER_PW

pytestmark = pytest.mark.unit

runner = CliRunner()

NOC_SECRET = "orion-secret-123"  # noqa: S105 — test fixture value

# Prompt order (solarwinds): name, platform(default=solarwinds), host,
# port(default), Orion username(default), TLS confirm(default=True),
# [getpass patched], add-another(No), doctor(No).
WIZARD_INPUT_SW = "noc1\n\norion.example.com\n\n\n\n\nn\n"
# prtg: no username prompt; port default becomes 443.
WIZARD_INPUT_PRTG = "prtg1\nprtg\nprtg.example.com\n\n\n\nn\n"
# zabbix: no username prompt (API token auth); port default 443.
WIZARD_INPUT_ZABBIX = "zbx1\nzabbix\nzabbix.example.com\n\n\n\nn\n"


@pytest.fixture
def hidden_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """getpass reads the TTY, not CliRunner stdin — patch it."""
    monkeypatch.setattr(init_mod.getpass, "getpass", lambda prompt="": NOC_SECRET)


def test_init_solarwinds_writes_config_and_encrypted_secret(isolated_home, hidden_secret):
    result = runner.invoke(app, ["init"], input=WIZARD_INPUT_SW)
    assert result.exit_code == 0, result.output

    config_text = (isolated_home / "config.yaml").read_text("utf-8")
    raw = yaml.safe_load(config_text)
    assert raw["targets"] == [
        {
            "name": "noc1",
            "platform": "solarwinds",
            "host": "orion.example.com",
            "port": 17778,
            "username": "admin",
            "verify_ssl": True,  # TLS confirm default=True accepted as-is
        }
    ]

    # The secret lands encrypted in secrets.enc, never in config.yaml.
    secrets_blob = (isolated_home / "secrets.enc").read_text("utf-8")
    assert NOC_SECRET not in config_text
    assert NOC_SECRET not in secrets_blob
    assert ss.SecretStore.unlock(MASTER_PW).get("noc1") == NOC_SECRET


def test_init_prtg_skips_username_and_defaults_port(isolated_home, hidden_secret):
    result = runner.invoke(app, ["init"], input=WIZARD_INPUT_PRTG)
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"] == [
        {
            "name": "prtg1",
            "platform": "prtg",
            "host": "prtg.example.com",
            "port": 443,
            "username": "",
            "verify_ssl": True,
        }
    ]
    assert ss.SecretStore.unlock(MASTER_PW).get("prtg1") == NOC_SECRET


def test_init_rejects_unknown_platform_then_recovers(isolated_home, hidden_secret):
    # 'nagios' is refused (error + loop restarts at the name prompt).
    bad_then_good = "noc1\nnagios\nnoc1\nprtg\nprtg.example.com\n\n\n\nn\n"
    result = runner.invoke(app, ["init"], input=bad_then_good)
    assert result.exit_code == 0, result.output
    assert "Platform must be 'solarwinds', 'prtg' or 'zabbix'." in result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"][0]["platform"] == "prtg"


def test_init_zabbix_skips_username_and_defaults_port(isolated_home, hidden_secret):
    result = runner.invoke(app, ["init"], input=WIZARD_INPUT_ZABBIX)
    assert result.exit_code == 0, result.output
    assert "Zabbix API token" not in result.output  # getpass is patched (hidden)
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"] == [
        {
            "name": "zbx1",
            "platform": "zabbix",
            "host": "zabbix.example.com",
            "port": 443,
            "username": "",
            "verify_ssl": True,
        }
    ]
    assert ss.SecretStore.unlock(MASTER_PW).get("zbx1") == NOC_SECRET


def test_init_seeds_default_policy_rules(isolated_home, hidden_secret):
    result = runner.invoke(app, ["init"], input=WIZARD_INPUT_SW)
    assert result.exit_code == 0, result.output
    rules = (isolated_home / "rules.yaml").read_text("utf-8")
    assert "high-risk-requires-approver" in rules
    assert "tier: dual" in rules


def test_init_does_not_clobber_existing_rules(isolated_home, hidden_secret):
    sentinel = "# operator-authored rules — do not touch\nrisk_tiers: []\n"
    (isolated_home / "rules.yaml").write_text(sentinel, "utf-8")
    result = runner.invoke(app, ["init"], input=WIZARD_INPUT_SW)
    assert result.exit_code == 0, result.output
    assert (isolated_home / "rules.yaml").read_text("utf-8") == sentinel


def test_init_declines_tls_verification(isolated_home, hidden_secret):
    # Same solarwinds script but answer No at the TLS confirm.
    result = runner.invoke(app, ["init"], input="noc1\n\norion.example.com\n\n\nn\n\nn\n")
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"][0]["verify_ssl"] is False


def test_init_appends_to_existing_targets(isolated_home, hidden_secret):
    assert runner.invoke(app, ["init"], input=WIZARD_INPUT_SW).exit_code == 0
    result = runner.invoke(app, ["init"], input=WIZARD_INPUT_PRTG)
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert [t["name"] for t in raw["targets"]] == ["noc1", "prtg1"]


def test_init_overwrites_target_on_confirm(isolated_home, hidden_secret):
    assert runner.invoke(app, ["init"], input=WIZARD_INPUT_SW).exit_code == 0
    # Re-add 'noc1': confirm the overwrite, change the host.
    result = runner.invoke(
        app, ["init"], input="noc1\ny\n\nnew-orion.example.com\n\n\n\n\nn\n"
    )
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((isolated_home / "config.yaml").read_text("utf-8"))
    assert len(raw["targets"]) == 1
    assert raw["targets"][0]["host"] == "new-orion.example.com"


def test_init_runs_doctor_when_accepted(isolated_home, hidden_secret, monkeypatch):
    import monitoring_aiops.doctor as doc

    calls: list[bool] = []

    def fake_doctor(skip_auth: bool = False) -> int:
        calls.append(True)
        return 0

    monkeypatch.setattr(doc, "run_doctor", fake_doctor)
    # Accept the trailing doctor confirm (default=True) with a blank line.
    result = runner.invoke(app, ["init"], input="noc1\n\norion.example.com\n\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert calls == [True]
