# Changelog

## v0.1.1

- Fix: `MONITORING_AIOPS_HOME` now also relocates `config.yaml` (was hardcoded to `~/.monitoring-aiops`).
- Fix: **CLI writes are now audited + undo-recorded** via the governance path — previously only the MCP tools recorded audit/undo; CLI `manage`/`remediate`/etc. writes now go through the same `@governed_tool` layer (they keep their dry-run + double-confirm). CLI write output is now the governed JSON result. No API/tool changes.


All notable changes to monitoring-aiops are documented here. This project adheres
to [Semantic Versioning](https://semver.org/).

## [0.1.0] — preview

Initial preview release: governed AI-ops for **network / infrastructure
monitoring** across **SolarWinds Orion** (SWIS REST + SWQL) and **Paessler PRTG**
(web API), with a bundled governance harness. One config can span both NOCs.
**Mock-validated only — not yet verified against a live NOC.**

### Added

- **31 MCP tools** (23 read, 8 write), every one wrapped with the bundled
  `@governed_tool` harness (audit, policy, token/runaway budget, undo,
  risk-tiers):
  - **SWQL (SolarWinds, read)** — `swql_library` (list the canned queries),
    `swql_canned` (run a named canned query), `swql_query` (validated read-only
    SELECT passthrough).
  - **Alerts (both platforms)** — `active_alerts` (read; dedup/rollup by
    message, collapsing flap/down storms into counted entries),
    `alert_acknowledge` (write, low).
  - **SolarWinds health (read)** — `node_status`, `nodes_list`,
    `interface_status` (top-N by utilisation), `volume_status` (by % used),
    `application_status` (SAM), `topn` (cpu/memory/latency/packetloss),
    `noc_rollup` (down/warning counts + worst CPU).
  - **SolarWinds writes** — `list_events`, `list_unmanaged`, `list_muted`
    (read); `mute_alerts` (med, time-boxed, undo→unmute), `unmute_alerts` (med),
    `schedule_maintenance` (med, requires end time), `unmanage_node` (**high**,
    dry-run, undo→remanage), `remanage_node` (med), `remove_node` (**high**,
    dry-run).
  - **PRTG (read)** — `prtg_sensors`, `prtg_sensor_details`, `prtg_devices`,
    `prtg_groups`, `prtg_history`, `prtg_system_status`, `prtg_alarms`.
  - **PRTG writes** — `pause_sensor` (med, undo→resume), `resume_sensor` (med),
    `schedule_maintenance_prtg` (med, time-boxed, requires minutes).
- **Canned-SWQL library** — the most-repeated THWACK questions as named,
  validated queries: `nodes_down`, `flapping_interfaces`, `muted_report`,
  `high_cpu_nodes`, `volumes_full`, `unmanaged_scheduled`.
- **Encrypted secret store** — the Orion account password or PRTG API token is
  stored encrypted in `~/.monitoring-aiops/secrets.enc` (Fernet + scrypt); never
  plaintext on disk. Legacy `MONITORING_<TARGET>_SECRET` env var honoured as a
  fallback.
- **CLI** (`monitoring-aiops`) — `init` platform-picking wizard, `overview`,
  `swql library/canned/query`, `alert list/ack`, `secret` management, and a
  platform-aware `doctor` (SWQL query for SolarWinds, `/api/status.json` for
  PRTG).

### Known limitations

- Preview / mock-only: SWIS REST + SWQL and PRTG web API responses are mocked and
  need live verification against a real NOC. PRTG's free Freeware edition is the
  easiest live check; SolarWinds is a 30-day trial only (largest verification
  debt).
- Zabbix and other monitoring stacks are out of scope by design.
