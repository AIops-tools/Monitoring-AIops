"""Connection management for SolarWinds Orion (SWIS), Paessler PRTG, and Zabbix.

One :class:`MonitoringConnection` speaks the protocol of its target's platform:

  * **SolarWinds** — the SWIS REST endpoint. ``swql(query)`` runs a read-only
    SWQL query (``POST .../Query``); ``swis_invoke(entity, verb, args)`` calls a
    verb (``POST .../Invoke/{entity}/{verb}``) for governed writes like
    ``Orion.Nodes.Unmanage`` / ``Orion.AlertActive.Acknowledge``. HTTP Basic auth.
  * **PRTG** — the PRTG web API. ``prtg_get`` / ``prtg_post`` hit ``/api/...``
    with the API token appended as ``apitoken`` (so it never lands in a log line
    the way a URL-embedded passhash would be more likely to).
  * **Zabbix** — JSON-RPC 2.0 at the single ``/api_jsonrpc.php`` endpoint.
    ``zabbix_rpc(method, params)`` posts the standard envelope with the API
    token as a ``Authorization: Bearer`` header (6.4+/7.x); on a 6.0 server
    that rejects Bearer, one retry falls back to the legacy ``auth`` body
    field. ``apiinfo.version`` is sent unauthenticated (Zabbix requires that).

Platform-specific methods guard on ``platform`` and raise a clear
``MonitoringApiError`` if called against the wrong platform, so a SolarWinds-only
tool can't silently misfire at a PRTG or Zabbix target.

The httpx client is injectable for tests (``client=``); mock responses expose
``status_code``, ``content``, ``text``, and ``json()``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from monitoring_aiops.config import (
    PLATFORM_PRTG,
    PLATFORM_SOLARWINDS,
    PLATFORM_ZABBIX,
    AppConfig,
    TargetConfig,
    load_config,
)

_TIMEOUT = 60.0
_SWIS_BASE = "/SolarWinds/InformationService/v3/Json"
_ZABBIX_RPC = "/api_jsonrpc.php"
# Zabbix methods that must be called WITHOUT auth (the server rejects a token).
_ZABBIX_NO_AUTH = frozenset({"apiinfo.version"})


def _seg(value: Any) -> str:
    """URL-encode one path segment so an identifier can never smuggle
    ``../`` / ``?`` / ``#`` into the request path (query params passed via
    httpx ``params=`` are already encoded and must NOT go through this)."""
    return quote(str(value), safe="")


class MonitoringApiError(Exception):
    """A SolarWinds/PRTG call failed; carries a teaching message + status code."""

    def __init__(self, message: str, *, status_code: int | None = None, path: str = "") -> None:
        self.status_code = status_code
        self.path = path
        super().__init__(message)


def _teaching_message(status: int, path: str, body: str, platform: str) -> str:
    snippet = body[:200].strip()
    if status in (401, 403):
        return (
            f"Authentication failed ({status}) on {platform} {path}. Check the "
            f"credentials (SolarWinds Orion account / PRTG API token / Zabbix "
            f"API token) and the account's role. {snippet}"
        )
    if status == 404:
        return f"Not found (404) on {platform} {path}. Check the id/name. {snippet}"
    if status == 400:
        return (
            f"Bad request (400) on {platform} {path}. For SolarWinds this is often a "
            f"SWQL syntax error; check the query. {snippet}"
        )
    if status in (500, 502, 503, 504):
        return (
            f"{platform} server error ({status}) on {path}. The service may be busy; "
            f"retry shortly. {snippet}"
        )
    return f"{platform} API error ({status}) on {path}. {snippet}"


class MonitoringConnection:
    """A session against one SolarWinds, PRTG, or Zabbix target."""

    def __init__(self, target: TargetConfig, client: Any | None = None) -> None:
        self._target = target
        self._zbx_rpc_id = 0
        self._zbx_legacy_auth = False  # flips after a 6.0 server rejects Bearer
        auth = None
        if target.platform == PLATFORM_SOLARWINDS:
            auth = httpx.BasicAuth(target.username, target.secret)
        self._client = client or httpx.Client(
            base_url=target.base_url, verify=target.verify_ssl, timeout=_TIMEOUT,
            auth=auth, headers={"Content-Type": "application/json"},
        )

    @property
    def target(self) -> TargetConfig:
        return self._target

    def _require(self, platform: str, tool: str) -> None:
        if self._target.platform != platform:
            raise MonitoringApiError(
                f"'{tool}' requires a {platform} target, but '{self._target.name}' "
                f"is a {self._target.platform} target.",
            )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise MonitoringApiError(
                f"Could not reach {self._target.platform} at {self._target.base_url} "
                f"({method} {path}): {exc}. Check host/port and reachability.",
                path=path,
            ) from exc
        if not (200 <= resp.status_code < 300):
            raise MonitoringApiError(
                _teaching_message(resp.status_code, path, resp.text, self._target.platform),
                status_code=resp.status_code, path=path,
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    # ── SolarWinds (SWIS) ────────────────────────────────────────────────
    def swql(self, query: str, params: dict | None = None) -> list[dict]:
        """Run a read-only SWQL query; returns the ``results`` rows."""
        self._require(PLATFORM_SOLARWINDS, "swql")
        body = {"query": query, "parameters": params or {}}
        data = self._request("POST", f"{_SWIS_BASE}/Query", json=body)
        rows = data.get("results", []) if isinstance(data, dict) else []
        return [r for r in rows if isinstance(r, dict)]

    def swis_invoke(self, entity: str, verb: str, args: list | None = None) -> Any:
        """Invoke a SWIS verb (e.g. Orion.Nodes.Unmanage) — governed writes."""
        self._require(PLATFORM_SOLARWINDS, verb)
        return self._request(
            "POST", f"{_SWIS_BASE}/Invoke/{_seg(entity)}/{_seg(verb)}", json=args or []
        )

    # ── PRTG ─────────────────────────────────────────────────────────────
    def _prtg_params(self, params: dict | None) -> dict:
        merged = dict(params or {})
        merged["apitoken"] = self._target.secret
        return merged

    def prtg_get(self, path: str, params: dict | None = None) -> Any:
        """GET a PRTG API path with the API token appended."""
        self._require(PLATFORM_PRTG, "prtg_get")
        return self._request("GET", path, params=self._prtg_params(params))

    def prtg_post(self, path: str, params: dict | None = None) -> Any:
        """POST a PRTG API path (acknowledge/pause/resume) with the token appended."""
        self._require(PLATFORM_PRTG, "prtg_post")
        return self._request("POST", path, params=self._prtg_params(params))

    # ── Zabbix (JSON-RPC 2.0) ────────────────────────────────────────────
    @staticmethod
    def _zbx_auth_error(err: dict) -> bool:
        """True when a JSON-RPC error looks like an auth failure (token/session)."""
        text = f"{err.get('message', '')} {err.get('data', '')}".lower()
        return any(m in text for m in ("not authorised", "not authorized", "re-login"))

    def zabbix_rpc(self, method: str, params: Any = None) -> Any:
        """Call one Zabbix JSON-RPC 2.0 method; returns the ``result`` payload.

        The API token rides in an ``Authorization: Bearer`` header (Zabbix
        6.4+/7.x). If a 6.0 server rejects it with an auth error, ONE retry
        resends the token as the legacy ``auth`` body field and the connection
        remembers that mode. ``apiinfo.version`` is always sent without auth.
        """
        self._require(PLATFORM_ZABBIX, "zabbix_rpc")
        self._zbx_rpc_id += 1
        body: dict = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params if params is not None else {},
            "id": self._zbx_rpc_id,
        }
        headers: dict = {}
        authed = method not in _ZABBIX_NO_AUTH
        if authed:
            if self._zbx_legacy_auth:
                body["auth"] = self._target.secret
            else:
                headers["Authorization"] = f"Bearer {self._target.secret}"
        data = self._request("POST", _ZABBIX_RPC, json=body, headers=headers)
        if not isinstance(data, dict):
            return data
        err = data.get("error")
        if isinstance(err, dict):
            if authed and not self._zbx_legacy_auth and self._zbx_auth_error(err):
                # Bearer not accepted (Zabbix 6.0) — retry once with the
                # legacy ``auth`` body field, then remember that mode.
                self._zbx_legacy_auth = True
                return self.zabbix_rpc(method, params)
            raise MonitoringApiError(
                f"Zabbix API error on '{method}': {err.get('message', '')} "
                f"{str(err.get('data', ''))[:200]}".strip()
                + ". For auth errors check the API token "
                "(Administration → API tokens) and its expiry.",
                path=_ZABBIX_RPC,
            )
        return data.get("result")

    def close(self) -> None:
        self._client.close()


class ConnectionManager:
    """Manages connections to multiple monitoring targets with session reuse."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._connections: dict[str, MonitoringConnection] = {}

    @classmethod
    def from_config(cls, config: AppConfig | None = None) -> ConnectionManager:
        cfg = config or load_config()
        return cls(cfg)

    def connect(self, target_name: str | None = None) -> MonitoringConnection:
        target = (
            self._config.get_target(target_name)
            if target_name
            else self._config.default_target
        )
        cached = self._connections.get(target.name)
        if cached is not None:
            return cached
        conn = MonitoringConnection(target)
        self._connections[target.name] = conn
        return conn

    def disconnect(self, target_name: str) -> None:
        conn = self._connections.pop(target_name, None)
        if conn is not None:
            conn.close()

    def disconnect_all(self) -> None:
        for name in list(self._connections):
            self.disconnect(name)

    def list_targets(self) -> list[str]:
        return [t.name for t in self._config.targets]

    def list_connected(self) -> list[str]:
        return list(self._connections.keys())
