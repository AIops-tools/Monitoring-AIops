"""Shared MCP server primitives: the FastMCP instance, connection helper,
error sanitisation, and the ``@tool_errors`` decorator.

Tool modules under ``mcp_server/tools/`` import ``mcp`` from here and register
their ``@mcp.tool()`` functions onto it. ``mcp_server/server.py`` then imports
those modules and runs the server.

Keep ``Optional[X]`` (never PEP 604 ``X | None``) in any FastMCP-reflected
tool signature — on older mcp/pydantic the union eval'd to ``types.UnionType``
crashes FastMCP's ``issubclass`` check.
"""

import functools
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from monitoring_aiops.config import load_config
from monitoring_aiops.connection import ConnectionManager, MonitoringApiError
from monitoring_aiops.governance import sanitize

logger = logging.getLogger(__name__)

_DOCTOR_HINT = "Run 'monitoring-aiops doctor' to verify connectivity and credentials."


def _safe_error(exc: Exception, tool: str) -> str:
    """Return an agent-safe error string; log full detail server-side only."""
    logger.error("Tool %s failed", tool, exc_info=True)
    _passthrough = (
        ValueError,
        FileNotFoundError,
        KeyError,
        PermissionError,
        TimeoutError,
        ConnectionError,
        MonitoringApiError,
    )
    if isinstance(exc, _passthrough):
        return sanitize(str(exc), 300)
    return f"{type(exc).__name__}: operation failed."


def tool_errors(shape: str = "dict") -> Callable:
    """Wrap a tool body in the canonical try/except → ``_safe_error`` pattern.

    Place this *between* ``@governed_tool`` and the function so the audit
    decorator and FastMCP still see the original signature.
    """

    def decorator(func: Callable) -> Callable:
        name = func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — sanitised below
                msg = _safe_error(e, name)
                if shape == "list":
                    return [{"error": msg, "hint": _DOCTOR_HINT}]
                if shape == "str":
                    return f"Error: {msg} {_DOCTOR_HINT}"
                return {"error": msg, "hint": _DOCTOR_HINT}

        return wrapper

    return decorator


mcp = FastMCP(
    "monitoring-aiops",
    instructions=(
        "Network/infra monitoring operations over SolarWinds Orion "
        "(SWIS/SWQL), Paessler PRTG, and Zabbix 6.x/7.x (JSON-RPC): a canned-SWQL "
        "library + validated read-only SWQL passthrough; "
        "node/interface/volume/application health and top-N; active alerts with "
        "dedup/rollup; events and historical metrics; PRTG sensors/alarms/history; "
        "Zabbix problems/hosts/triggers/item-history/maintenances; and governed "
        "light writes — acknowledge alerts, mute/pause (time-boxed), schedule "
        "maintenance (incl. Zabbix maintenance windows with a replayable "
        "delete-undo), and unmanage/add/remove a node. Destructive writes "
        "(unmanage / remove node / delete maintenance) are risk=high with a "
        "dry_run preview and require an approver. Every tool runs through the "
        "monitoring-aiops governance harness (audit / budget / risk-tier / undo)."
    ),
)

_conn_mgr: Optional[ConnectionManager] = None


def _get_connection(target: Optional[str] = None) -> Any:
    """Return a Monitoring connection, lazily initialising the manager."""
    global _conn_mgr  # noqa: PLW0603
    if _conn_mgr is None:
        config_path_str = os.environ.get("MONITORING_AIOPS_CONFIG")
        config_path = Path(config_path_str) if config_path_str else None
        _conn_mgr = ConnectionManager(load_config(config_path))
    return _conn_mgr.connect(target)
