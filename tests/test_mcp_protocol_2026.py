"""Exercise both MCP protocol eras through the real stdio entry point."""

import asyncio
import json
import os
import sqlite3
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def _exercise_stdio(home, modern: bool):
    env = dict(os.environ)
    env["MONITORING_AIOPS_HOME"] = str(home)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from monitoring_aiops.mcp_server.server import main; main()"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            if modern:
                discovery = await client.discover()
                assert "2026-07-28" in discovery.supported_versions
            else:
                initialized = await client.initialize()
                assert initialized.protocol_version == "2025-11-25"

            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            assert len(tools) == 42
            assert tools["undo_list"].annotations.read_only_hint is True
            assert tools["zabbix_problems"].meta["io.github.AIops-tools/riskLevel"] == "low"

            success = await client.call_tool("undo_list", {"limit": 1})
            assert success.is_error is False
            assert json.loads(success.content[0].text)["truncated"] is False

            failure = await client.call_tool("zabbix_problems", {})
            assert "error" in json.loads(failure.content[0].text)
            assert failure.is_error is True

    with sqlite3.connect(home / "audit.db") as db:
        status = db.execute(
            "SELECT status FROM audit_log WHERE tool = 'zabbix_problems' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert status == ("error",)


def test_legacy_mcp_stdio(tmp_path):
    asyncio.run(_exercise_stdio(tmp_path, modern=False))


def test_mcp_2026_discovery_stdio(tmp_path):
    asyncio.run(_exercise_stdio(tmp_path, modern=True))
