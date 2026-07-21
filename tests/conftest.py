"""Shared test fixtures (no live SolarWinds Orion / PRTG server needed)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _default_approver(monkeypatch: pytest.MonkeyPatch) -> None:
    """MONITORING_AUDIT_APPROVED_BY is an optional audit annotation now, not a
    gate — recorded on the row when set, never required. Set a synthetic value
    globally so audit rows carry a stable approver; the persistence tests clear
    it to prove a write still runs without one."""
    monkeypatch.setenv("MONITORING_AUDIT_APPROVED_BY", "pytest")


MASTER_PW = "test-master-pw"


@pytest.fixture
def isolated_home(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Redirect every config/secret/governance path to a throwaway home.

    The path constants are bound at import time in each module, so patch the
    names where they are *used* (config, secretstore, doctor, cli.init), plus
    the env vars for call-time resolution (governance ``ops_path`` and the
    secret-store master password).
    """
    import monitoring_aiops.cli.init as init_mod
    import monitoring_aiops.config as cfg
    import monitoring_aiops.doctor as doc
    import monitoring_aiops.secretstore as ss

    monkeypatch.setenv("MONITORING_AIOPS_HOME", str(tmp_path))
    monkeypatch.setenv("MONITORING_AIOPS_MASTER_PASSWORD", MASTER_PW)
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ss, "_cached", None)
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(doc, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(doc, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(doc, "SECRETS_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(init_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(init_mod, "CONFIG_FILE", tmp_path / "config.yaml")
    return tmp_path
