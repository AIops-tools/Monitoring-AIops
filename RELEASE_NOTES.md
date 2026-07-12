# Monitoring AIops v0.1.0 — preview

Governed AI-ops for **network / infrastructure monitoring** across **SolarWinds
Orion** (SWIS REST + SWQL) and **Paessler PRTG** (web API) for AI agents, with a
built-in governance harness (audit, policy, token/runaway budget, undo-token
recording, graduated risk tiers) and an encrypted credential store. Standalone —
no external skill-family dependency. One config can span both NOCs.

> **Preview / mock-only.** All behaviour is validated against mocked SWIS/PRTG
> responses; it has not been run against a live NOC. **PRTG's free perpetual
> 100-sensor Freeware edition (with the API) is the easiest live check;
> SolarWinds is a 30-day trial only — mock-only past that, the largest
> verification debt.** The fastest live check is `monitoring-aiops doctor`.

## Highlights

- **31 MCP tools** (23 read, 8 write), every one wrapped with `@governed_tool`.
  - **SWQL (SolarWinds)** — `swql_library`, `swql_canned`, `swql_query`
    (validated read-only SELECT passthrough).
  - **Alerts (both platforms)** — `active_alerts` (dedup/rollup by message),
    `alert_acknowledge`.
  - **SolarWinds health** — `node_status`, `nodes_list`, `interface_status`,
    `volume_status`, `application_status`, `topn`, `noc_rollup`.
  - **SolarWinds writes** — `list_events`, `list_unmanaged`, `list_muted`;
    `mute_alerts`/`unmute_alerts`, `schedule_maintenance`,
    `unmanage_node`/`remanage_node`, `remove_node`.
  - **PRTG** — `prtg_sensors`, `prtg_sensor_details`, `prtg_devices`,
    `prtg_groups`, `prtg_history`, `prtg_system_status`, `prtg_alarms`;
    `pause_sensor`/`resume_sensor`, `schedule_maintenance_prtg`.
- **Canned-SWQL library** — the most-repeated THWACK questions shipped as named,
  validated queries (`nodes_down`, `flapping_interfaces`, `muted_report`,
  `high_cpu_nodes`, `volumes_full`, `unmanaged_scheduled`).
- **Active-alert rollup** — collapses interface-flap / node-down storms into one
  counted entry, across SolarWinds and PRTG.
- **Encrypted secret store** (`~/.monitoring-aiops/secrets.enc`, Fernet + scrypt)
  — the Orion account password or PRTG API token, never plaintext on disk;
  legacy `MONITORING_<TARGET>_SECRET` env fallback.
- **Guarded writes** — destructive ops (`unmanage_node`, `remove_node`) require
  dry-run + double-confirm; suppression/maintenance writes are time-boxed
  (require an end time / duration).
- **CLI** with an `init` platform-picking wizard, `secret` management, and a
  platform-aware `doctor`.

## Install

```bash
uv tool install monitoring-aiops
monitoring-aiops init       # pick platform (solarwinds/prtg) + store the secret
monitoring-aiops doctor
```

## Caveats

- Preview / mock-only: SWIS REST + SWQL and the PRTG web API responses are
  mocked and need live verification (SolarWinds especially, past the trial).
- Zabbix and other monitoring stacks are out of scope by design.
