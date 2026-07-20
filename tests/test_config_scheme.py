"""A self-hosted Zabbix is very often plain HTTP; the URL must not be hardcoded.

Regression from live verification against Zabbix 7.0.28: base_url was built as
`https://{host}:{port}` with no override, so an http-only instance was simply
unreachable — the only clue being a TLS record-layer error.
"""

from __future__ import annotations

import pytest

from monitoring_aiops.config import TargetConfig


@pytest.mark.unit
def test_scheme_defaults_to_https_so_existing_configs_are_unchanged():
    t = TargetConfig(name="n", platform="zabbix", host="h", port=443)
    assert t.scheme == "https"
    assert t.base_url == "https://h:443"


@pytest.mark.unit
def test_scheme_http_is_honoured():
    t = TargetConfig(name="n", platform="zabbix", host="h", port=8080, scheme="http")
    assert t.base_url == "http://h:8080"


@pytest.mark.unit
def test_invalid_scheme_is_rejected_at_construction():
    with pytest.raises(ValueError, match="scheme must be"):
        TargetConfig(name="n", platform="zabbix", host="h", scheme="ftp")
