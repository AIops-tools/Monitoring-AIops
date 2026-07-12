<!-- mcp-name: io.github.AIops-tools/monitoring-aiops -->

# Monitoring AIops (preview)

> **Disclaimer**: Community-maintained open-source project. **Not affiliated with, endorsed by, or sponsored by SolarWinds, Paessler, or any monitoring vendor.** SolarWinds, Orion, SWQL, THWACK, PRTG and Paessler are trademarks of their respective owners. MIT licensed.

Governed AI-ops for **network / infrastructure monitoring** across two NOC
platforms in one server — **SolarWinds Orion** (SWIS REST + SWQL, port 17778,
HTTP Basic auth) and **Paessler PRTG** (web API, port 443/8080, API token) — with
a **built-in governance harness**: unified audit log, policy engine,
token/runaway budget guard, undo-token recording, and graduated-autonomy risk
tiers. One config can span both NOCs; each target names its own `platform`.
**Preview — mock-validated only, not yet verified against a live NOC.**

## What it does

Answers the questions a NOC operator actually repeats, and guards the writes
that follow:

- **Canned-SWQL library** — the most-asked THWACK questions shipped as named,
  validated queries (`nodes_down`, `flapping_interfaces`, `muted_report`,
  `high_cpu_nodes`, `volumes_full`, `unmanaged_scheduled`), plus a **validated
  read-only SWQL passthrough** (SELECT-only) for everything else.
- **Active-alert dedup / rollup** — collapses an interface-flap or node-down
  storm into a single counted entry instead of a wall of near-identical alerts,
  across both SolarWinds and PRTG.
- **Dual SolarWinds + PRTG coverage** — one MCP server spans both NOCs; no
  incumbent hobby MCP does.
- **Governed writes** — mute/unmute, maintenance windows, unmanage/remanage,
  node removal, and PRTG sensor pause/resume — each audited, risk-tiered, and
  the destructive ones gated with **dry-run + double-confirm**. Suppression and
  maintenance writes are **time-boxed** (they require an end time / duration).

## Capability matrix (31 MCP tools)

| Group | Platform | Tools | Count | R/W |
|-------|----------|-------|:-----:|:---:|
| **SWQL** | SolarWinds | `swql_library`, `swql_canned`, `swql_query` | 3 | read |
| **Alerts** | both | `active_alerts` (dedup/rollup) | 1 | read |
| | both | `alert_acknowledge` | 1 | write (low) |
| **SolarWinds health** | SolarWinds | `node_status`, `nodes_list`, `interface_status`, `volume_status`, `application_status`, `topn`, `noc_rollup` | 7 | read |
| **SolarWinds writes** | SolarWinds | `list_events`, `list_unmanaged`, `list_muted` | 3 | read |
| | SolarWinds | `mute_alerts`, `unmute_alerts`, `schedule_maintenance`, `remanage_node` | 4 | write (med) |
| | SolarWinds | `unmanage_node`, `remove_node` | 2 | write (**high**) |
| **PRTG reads** | PRTG | `prtg_sensors`, `prtg_sensor_details`, `prtg_devices`, `prtg_groups`, `prtg_history`, `prtg_system_status`, `prtg_alarms` | 7 | read |
| **PRTG writes** | PRTG | `pause_sensor`, `resume_sensor`, `schedule_maintenance_prtg` | 3 | write (med) |

The CLI exposes a convenience subset; the full 31-tool surface is via the MCP
server.

## Quick start

```bash
uv tool install monitoring-aiops          # or: pipx install monitoring-aiops
monitoring-aiops init                     # wizard: pick platform (solarwinds/prtg) + store the secret (encrypted)
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
  tight poll/retry loops.
- **Risk tiers** — graduated autonomy; high-risk ops (`unmanage_node`,
  `remove_node`) can require a named approver (`MONITORING_AUDIT_APPROVED_BY` /
  `MONITORING_AUDIT_RATIONALE`).
- **Undo recording** — reversible writes record an inverse descriptor
  (`mute_alerts`→unmute, `unmanage_node`→remanage, `pause_sensor`→resume).

## Supported scope & limitations

- **Platforms**: SolarWinds Orion (SWIS REST + SWQL) and Paessler PRTG (web API).
  Zabbix is deliberately **out of scope** for this tool.
- **Preview / mock-only.** All behaviour is validated against mocked SWIS/PRTG
  responses. **PRTG has a free perpetual 100-sensor Freeware edition with the
  API — the easiest live check.** SolarWinds is a 30-day trial only; past the
  trial this tool is **mock-only, which is the largest verification debt.**
  `monitoring-aiops doctor` is the fastest live check (a SWQL query for
  SolarWinds, `/api/status.json` for PRTG).

## Missing a capability?

Want another canned query, a platform dialect fixed, or a capability that isn't
here? **Open an issue or a PR — feedback and contributions are welcome.**
