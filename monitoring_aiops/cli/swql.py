"""``monitoring-aiops swql`` — SolarWinds SWQL reads."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from monitoring_aiops.cli._common import TargetOption, cli_errors, console, get_connection

swql_app = typer.Typer(
    name="swql",
    help="SolarWinds SWQL: canned library + validated read-only queries.",
    no_args_is_help=True,
)


@swql_app.command("library")
@cli_errors
def swql_library(target: TargetOption = None) -> None:
    """List the canned-SWQL library."""
    from monitoring_aiops.ops import swql as ops

    console.print_json(json.dumps(ops.list_canned()))


@swql_app.command("canned")
@cli_errors
def swql_canned(
    name: Annotated[str, typer.Argument(help="Canned query name (from 'swql library')")],
    target: TargetOption = None,
) -> None:
    """Run a named canned SWQL query."""
    from monitoring_aiops.ops import swql as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.run_canned(conn, name)))


@swql_app.command("query")
@cli_errors
def swql_query(
    query: Annotated[str, typer.Argument(help="A read-only SWQL SELECT statement")],
    target: TargetOption = None,
) -> None:
    """Run a validated read-only SWQL SELECT."""
    from monitoring_aiops.ops import swql as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.run_query(conn, query)))
