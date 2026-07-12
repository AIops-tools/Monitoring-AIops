"""SolarWinds (Orion) health MCP tools — all read-only SWQL."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from monitoring_aiops.governance import governed_tool
from monitoring_aiops.ops import sw_health as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def node_status(name_or_ip: str, target: Optional[str] = None) -> dict:
    """[READ] One SolarWinds node's health by caption or IP (Orion.Nodes).

    Args:
        name_or_ip: Node caption or IP address to look up.
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.node_status(_get_connection(target), name_or_ip)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def nodes_list(status: Optional[int] = None, target: Optional[str] = None) -> dict:
    """[READ] List SolarWinds nodes, optionally filtered by status.

    Args:
        status: Optional Orion status filter (1=Up, 2=Down, 3=Warning).
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.nodes_list(_get_connection(target), status)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def interface_status(top: Optional[int] = None, target: Optional[str] = None) -> dict:
    """[READ] Interface status + utilization (Orion.NPM.Interfaces).

    Args:
        top: If given, return only the top-N interfaces by peak utilization.
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.interface_status(_get_connection(target), top)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def volume_status(min_percent: float = 0, target: Optional[str] = None) -> dict:
    """[READ] Volumes at/above a fill threshold (Orion.Volumes), worst first.

    Args:
        min_percent: Minimum percent-used to include (default 0 = all).
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.volume_status(_get_connection(target), min_percent)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def application_status(target: Optional[str] = None) -> dict:
    """[READ] SAM application status (Orion.APM.Application); resilient if absent.

    Args:
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.application_status(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def topn(metric: str = "cpu", n: int = 10, target: Optional[str] = None) -> list:
    """[READ] Top-N SolarWinds nodes by a health metric.

    Args:
        metric: One of cpu, memory, latency, packetloss.
        n: How many nodes to return (default 10).
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.topn(_get_connection(target), metric, n)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def noc_rollup(target: Optional[str] = None) -> dict:
    """[READ] One-shot NOC glance: down/warning counts + top-3 worst CPU nodes.

    Args:
        target: SolarWinds target name from config; omit for the default.
    """
    return ops.noc_rollup(_get_connection(target))
