"""``monitoring-aiops overview`` — one-shot fleet health."""

from __future__ import annotations

import json

from monitoring_aiops.cli._common import TargetOption, audited, cli_errors, console, get_connection


@cli_errors
@audited
def overview_cmd(target: TargetOption = None) -> None:
    """One-shot NOC summary: platform + active/unacked alert counts + top rollup."""
    from monitoring_aiops.ops import overview as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.fleet_overview(conn)))
