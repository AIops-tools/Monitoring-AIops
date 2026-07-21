"""Configuration management for Monitoring AIops.

Loads monitoring-platform connection targets from a YAML config file. Each target
names its ``platform`` — ``solarwinds`` (Orion SWIS REST), ``prtg`` (Paessler
PRTG), or ``zabbix`` (Zabbix 6.x/7.x JSON-RPC) — so one config can span all NOCs.

The secret is NEVER stored in the config file or in plaintext on disk: it lives
in the encrypted store ``~/.monitoring-aiops/secrets.enc`` (see
:mod:`monitoring_aiops.secretstore`). For SolarWinds the secret is the Orion
account **password**; for PRTG it is an **API token** (or the account passhash);
for Zabbix it is an **API token** (Administration → API tokens).
A legacy env var (``MONITORING_<TARGET>_SECRET``) is honoured as a fallback.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from monitoring_aiops.governance.paths import ops_home
from monitoring_aiops.secretstore import (
    MasterPasswordError,
    SecretStoreError,
    get_secret,
    has_store,
)

CONFIG_DIR = ops_home()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

PLATFORM_SOLARWINDS = "solarwinds"
PLATFORM_PRTG = "prtg"
PLATFORM_ZABBIX = "zabbix"
PLATFORMS = (PLATFORM_SOLARWINDS, PLATFORM_PRTG, PLATFORM_ZABBIX)

# Sensible default ports per platform (SolarWinds SWIS REST / PRTG web server /
# Zabbix frontend, which serves /api_jsonrpc.php).
#
# SolarWinds: Orion 2023.1 moved the SWIS REST endpoint to 17774 and documents
# the old 17778 as deprecated and slated for removal, so the default is the
# modern port. Pre-2023.1 Orion serves only 17778, so the connection layer
# probes it once as a fallback (see ``MonitoringConnection``) — but ONLY when
# the port was defaulted here, never when the operator set one.
SWIS_PORT = 17774
SWIS_LEGACY_PORT = 17778
DEFAULT_PORTS = {PLATFORM_SOLARWINDS: SWIS_PORT, PLATFORM_PRTG: 443, PLATFORM_ZABBIX: 443}

SECRET_ENV_PREFIX = "MONITORING_"  # nosec B105 — env-var name, not a secret
SECRET_ENV_SUFFIX = "_SECRET"  # nosec B105 — env-var name, not a secret

_log = logging.getLogger("monitoring-aiops.config")


def _secret_env_key(name: str) -> str:
    """Legacy per-target secret env var name, e.g. MONITORING_NOC1_SECRET."""
    return f"{SECRET_ENV_PREFIX}{name.upper().replace('-', '_')}{SECRET_ENV_SUFFIX}"


def _resolve_secret(name: str) -> str:
    """Return a target's secret: encrypted store first, then legacy env var."""
    if has_store():
        try:
            return get_secret(name)
        except MasterPasswordError:
            # A wrong or missing master password is NOT "this target has no
            # secret". Falling through resurfaced it as "No API key for target
            # X", sending the operator to add a credential that is already
            # there. MasterPasswordError subclasses SecretStoreError, so the
            # broad catch below would swallow it — re-raise first.
            raise
        except SecretStoreError:
            pass  # no secret stored for this target — try the legacy env var
    legacy = os.environ.get(_secret_env_key(name))
    if legacy:
        _log.warning(
            "Using plaintext env var %s. Migrate to the encrypted store with "
            "'monitoring-aiops secret migrate'.",
            _secret_env_key(name),
        )
        return legacy
    raise OSError(
        f"No secret for target '{name}'. Add one with "
        f"'monitoring-aiops secret set {name}' (stored encrypted), or run "
        f"'monitoring-aiops init'."
    )


@dataclass(frozen=True)
class TargetConfig:
    """A connection target for one monitoring platform instance.

    ``platform`` is ``solarwinds``, ``prtg``, or ``zabbix``. ``username`` (Orion
    account, or the PRTG username; unused for Zabbix token auth) lives in the
    config file; the secret (Orion password / PRTG API token / Zabbix API token)
    comes from the encrypted store.
    """

    name: str
    platform: str
    host: str
    port: int = 0
    username: str = ""
    verify_ssl: bool = True
    scheme: str = "https"
    """Transport scheme — ``https`` (default) or ``http``.

    Defaults to ``https``, so nothing changes for an existing config. It exists
    because a self-hosted Zabbix very often sits on plain HTTP behind a reverse
    proxy, and the URL was previously hardcoded to ``https://`` with no way to
    override it — which made such an instance simply unreachable, with a TLS
    record-layer error as the only clue.
    """

    port_is_explicit: bool = field(init=False, default=False)
    """True when the operator set ``port:`` themselves, rather than defaulting.

    ``__post_init__`` normalises a missing port to the platform default, which
    would otherwise erase the difference between "the operator asked for 17774"
    and "nobody said, so we picked 17774". The SolarWinds legacy-port fallback
    needs that difference: a stated port is used verbatim and never probed,
    because the operator already told us where SWIS lives.
    """

    def __post_init__(self) -> None:
        if self.platform not in PLATFORMS:
            raise ValueError(
                f"Target '{self.name}': platform must be one of {PLATFORMS}, "
                f"got '{self.platform}'."
            )
        if self.scheme not in ("https", "http"):
            raise ValueError(
                f"Target '{self.name}': scheme must be 'https' or 'http', "
                f"got '{self.scheme}'."
            )
        object.__setattr__(self, "port_is_explicit", bool(self.port))
        if not self.port:
            object.__setattr__(self, "port", DEFAULT_PORTS[self.platform])

    @property
    def secret(self) -> str:
        return _resolve_secret(self.name)

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


@dataclass(frozen=True)
class AppConfig:
    """Top-level application config."""

    targets: tuple[TargetConfig, ...] = ()

    def get_target(self, name: str) -> TargetConfig:
        for t in self.targets:
            if t.name == name:
                return t
        available = ", ".join(t.name for t in self.targets) or "(none)"
        raise KeyError(f"Target '{name}' not found. Available: {available}")

    @property
    def default_target(self) -> TargetConfig:
        if not self.targets:
            raise ValueError("No targets configured. Check config.yaml")
        return self.targets[0]


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from YAML; the secret comes from the encrypted store."""
    path = config_path or CONFIG_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Run 'monitoring-aiops init' to set up a SolarWinds or PRTG target, "
            f"or create {CONFIG_FILE} with a 'targets' list."
        )

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    targets = tuple(
        TargetConfig(
            name=t["name"],
            platform=t["platform"],
            host=t["host"],
            port=t.get("port", 0),
            username=t.get("username", ""),
            verify_ssl=t.get("verify_ssl", True),
            scheme=t.get("scheme", "https"),
        )
        for t in raw.get("targets", [])
    )

    return AppConfig(targets=targets)
