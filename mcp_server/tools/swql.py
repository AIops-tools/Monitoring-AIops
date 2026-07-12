"""SWQL query MCP tools (SolarWinds, read-only)."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from monitoring_aiops.governance import governed_tool
from monitoring_aiops.ops import swql as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def swql_library(target: Optional[str] = None) -> list:
    """[READ] List the canned-SWQL library (name + description).

    These answer the most-repeated SolarWinds SWQL questions directly — run one
    with swql_canned instead of hand-writing the query.

    Args:
        target: Monitoring target name from config; omit for the default.
    """
    return ops.list_canned()


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def swql_canned(name: str, params: Optional[dict] = None, target: Optional[str] = None) -> dict:
    """[READ] Run a named canned SWQL query (e.g. nodes_down, flapping_interfaces).

    Args:
        name: Canned query name (from swql_library).
        params: Optional query params (e.g. {"min": 90} for a threshold).
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.run_canned(_get_connection(target), name, params)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def swql_query(query: str, params: Optional[dict] = None, target: Optional[str] = None) -> dict:
    """[READ] Run a validated read-only SWQL SELECT (row-capped).

    Only SELECT is permitted — state changes go through the governed write tools.

    Args:
        query: A SWQL SELECT statement.
        params: Optional named parameters referenced as @name in the query.
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.run_query(_get_connection(target), query, params)
