"""``monitoring-aiops alert`` — active-alert rollup + acknowledge."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from monitoring_aiops.cli._common import (
    DryRunOption,
    TargetOption,
    cli_errors,
    console,
    dry_run_print,
    get_connection,
)

alert_app = typer.Typer(
    name="alert",
    help="Active alerts: rolled-up list and acknowledge.",
    no_args_is_help=True,
)


@alert_app.command("list")
@cli_errors
def alert_list(target: TargetOption = None) -> None:
    """List active alerts with dedup/rollup by message."""
    from monitoring_aiops.ops import alerts as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.active_alerts(conn)))


@alert_app.command("ack")
@cli_errors
def alert_ack(
    alert_id: Annotated[str, typer.Argument(help="Alert id (from 'alert list')")],
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Acknowledge one active alert."""
    from mcp_server.tools import alerts as gov

    if dry_run:
        dry_run_print(operation="acknowledge_alert", api_call="Acknowledge",
                      parameters={"alert_id": alert_id})
        return
    console.print_json(json.dumps(gov.alert_acknowledge(alert_id=alert_id, target=target)))
