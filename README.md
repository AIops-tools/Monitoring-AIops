<!-- mcp-name: io.github.AIops-tools/monitoring-aiops -->

# Monitoring AIops

> **Disclaimer**: Community-maintained open-source project. **Not affiliated with, endorsed by, or sponsored by SolarWinds, Paessler, Zabbix, or any monitoring vendor.** SolarWinds, Orion, SWQL, THWACK, PRTG, Paessler and Zabbix are trademarks of their respective owners. MIT licensed.

Governed AI-ops for **network / infrastructure monitoring** across three NOC
platforms in one server — **SolarWinds Orion** (SWIS REST + SWQL, port 17774
with an automatic fallback to the legacy 17778, HTTP Basic auth), **Paessler
PRTG** (web API, port 443/8080, API token), and
**Zabbix 6.x/7.x** (JSON-RPC 2.0 at `/api_jsonrpc.php`, API token) — with
a **built-in governance harness**: unified audit log, policy engine,
token/runaway budget guard, undo-token recording, and risk-tier labelling on
the audit trail. One config can span all NOCs; each target names its own
`platform`.

## What it does

Answers the questions a NOC operator actually repeats, and guards the writes
that follow:

- **Canned-SWQL library** — the most-asked THWACK questions shipped as named,
  validated queries (`nodes_down`, `flapping_interfaces`, `muted_report`,
  `high_cpu_nodes`, `volumes_full`, `unmanaged_scheduled`), plus a **validated
  read-only SWQL passthrough** (SELECT-only) for everything else.
- **Active-alert dedup / rollup** — collapses an interface-flap or node-down
  storm into a single counted entry instead of a wall of near-identical alerts,
  across SolarWinds, PRTG, and Zabbix (problems, with the 0-5 severity scale
  mapped to canonical levels).
- **Triple SolarWinds + PRTG + Zabbix coverage** — one MCP server spans all
  three NOCs; no incumbent hobby MCP does.
- **Governed writes** — mute/unmute, maintenance windows (incl. Zabbix
  `maintenance.create` with a **replayable delete-undo**), unmanage/remanage,
  node removal, and PRTG sensor pause/resume — each audited, risk-tiered, and
  the destructive ones gated with **dry-run + double-confirm**. Suppression and
  maintenance writes are **time-boxed** (they require an end time / duration).

## What this tool does, and does not, decide

It delivers NOC operations — reads and writes — accurately and efficiently, and
records every one of them. It does **not** decide whether a write is allowed to
happen. That is the agent's judgement, or the permission of the account you
connect it with: give it a SolarWinds/PRTG/Zabbix account with read-only
monitoring scope and the writes fail at the server — the place that actually
owns the permission.

So there is no read-only switch, no policy file, no approval gate to configure.
The one thing the tool guarantees is that nothing is silent: **every call, over
MCP and over the CLI alike, lands an audit row** in
`~/.monitoring-aiops/audit.db`, and destructive writes still capture their
before-state and record an inverse where one exists.

> Each tool declares a `risk_level`, kept in agreement with its `[READ]`/`[WRITE]`
> documentation tag by a test, and carried into the audit row as a descriptive
> tier — so a reviewer can see at a glance that a row was a high-risk node
> removal. It is a label, not a gate.

Running a smaller / local model? See
[agent-guardrails.md](skills/monitoring-aiops/references/agent-guardrails.md) — it lists
the guardrails this tool now enforces for you (so you don't spend prompt budget
restating them) and gives a ready-made system prompt for what's left.

## Capability matrix (42 MCP tools)

| Group | Platform | Tools | Count | R/W |
|-------|----------|-------|:-----:|:---:|
| **SWQL** | SolarWinds | `swql_library`, `swql_canned`, `swql_query` | 3 | read |
| **Alerts** | all | `active_alerts` (dedup/rollup) | 1 | read |
| | all | `alert_acknowledge` | 1 | write (low) |
| **SolarWinds health** | SolarWinds | `node_status`, `nodes_list`, `interface_status`, `volume_status`, `application_status`, `topn`, `noc_rollup` | 7 | read |
| **SolarWinds writes** | SolarWinds | `list_events`, `list_unmanaged`, `list_muted` | 3 | read |
| | SolarWinds | `mute_alerts`, `unmute_alerts`, `schedule_maintenance`, `remanage_node` | 4 | write (med) |
| | SolarWinds | `unmanage_node`, `remove_node` | 2 | write (**high**) |
| **PRTG reads** | PRTG | `prtg_sensors`, `prtg_sensor_details`, `prtg_devices`, `prtg_groups`, `prtg_history`, `prtg_system_status`, `prtg_alarms` | 7 | read |
| **PRTG writes** | PRTG | `pause_sensor`, `resume_sensor`, `schedule_maintenance_prtg` | 3 | write (med) |
| **Zabbix reads** | Zabbix | `zabbix_problems`, `zabbix_hosts`, `zabbix_hostgroups`, `zabbix_triggers`, `zabbix_events`, `zabbix_item_history`, `zabbix_maintenances` | 7 | read |
| **Zabbix writes** | Zabbix | `zabbix_create_maintenance` | 1 | write (med) |
| | Zabbix | `zabbix_delete_maintenance` | 1 | write (**high**) |
| **Undo** | all | `undo_list`, `undo_apply` | 2 | undo |

The CLI exposes a convenience subset; the full 42-tool surface is via the MCP
server.

## Quick start

```bash
uv tool install monitoring-aiops          # or: pipx install monitoring-aiops
monitoring-aiops init                     # wizard: pick platform (solarwinds/prtg/zabbix) + store the secret (encrypted)
monitoring-aiops doctor                   # verify config, secrets, connectivity
monitoring-aiops overview                 # NOC summary: platform + active/unacked alerts + top rollup
monitoring-aiops swql library             # list the canned SWQL queries
monitoring-aiops swql canned nodes_down   # run a named canned query
```

Run as an MCP server (stdio):

```bash
export MONITORING_AIOPS_MASTER_PASSWORD=...   # unlock secrets non-interactively
monitoring-aiops mcp
```

## Governance

Every MCP tool passes through the bundled `@governed_tool` harness:

- **Audit** — every call (params, result, status, duration, risk tier,
  approver, rationale) is logged to `~/.monitoring-aiops/audit.db` (relocatable
  via `MONITORING_AIOPS_HOME`).
- **Budget / runaway guard** — token and call budgets trip a circuit breaker on
  tight poll/retry loops. It is a safety backstop, not authorization.
- **Risk-tier labelling** — each tool's declared `risk_level` is carried into
  the audit row as a descriptive tier (a label, not a gate).
  `MONITORING_AUDIT_APPROVED_BY` / `MONITORING_AUDIT_RATIONALE` are optional
  audit annotations, recorded when set and never required.
- **Undo recording** — reversible writes record an inverse descriptor
  (`mute_alerts`→unmute, `unmanage_node`→remanage, `pause_sensor`→resume,
  `zabbix_create_maintenance`→delete that maintenance id).

## Supported scope & limitations

- **Platforms**: SolarWinds Orion (SWIS REST + SWQL), Paessler PRTG (web API),
  and Zabbix 6.x/7.x (JSON-RPC 2.0; API token via Bearer header on 6.4+/7.x,
  with a legacy `auth`-field fallback for 6.0).
- **Zabbix scope**: problems/triggers/hosts/host groups/events, bounded item
  history, maintenance windows (create/delete), and event acknowledge via the
  cross-platform `alert_acknowledge`. Template/discovery/user CRUD and
  `trend.get` are not covered — open an issue if you need them.
- **Validation status.** Behaviour is exercised by the test suite against mocked
  SWIS/PRTG/Zabbix responses; it has not been run against a live NOC (see
  [`docs/VERIFICATION.md`](docs/VERIFICATION.md)). **PRTG has a free perpetual 100-sensor Freeware
  edition with the API, and Zabbix is fully open source (a Docker-compose
  appliance is a 10-minute live check) — the easiest live checks.** SolarWinds
  is a 30-day trial only; past the trial this tool is **mock-only, which is
  the largest verification debt.** `monitoring-aiops doctor` is the fastest
  live check (a SWQL query for SolarWinds, `/api/status.json` for PRTG,
  unauthenticated `apiinfo.version` + an authed host count for Zabbix).

## Missing a capability?

Want another canned query, a platform dialect fixed, or a capability that isn't
here? **Open an issue or a PR — feedback and contributions are welcome.**
