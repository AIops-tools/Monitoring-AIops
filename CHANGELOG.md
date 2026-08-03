# Changelog

## Unreleased

### Fixed
- **`undo apply` replays against the target the original write ran on.** It dispatched the inverse against whatever target the *caller* named — in practice the config's first entry — while the write's own target sat unused in the undo record. On a multi-target config the inverse therefore ran against the wrong host; it only looks harmless because the resource usually is not there, but two hosts holding the same name and the inverse **succeeds on the wrong one, silently**. An explicitly named target still wins. Line-wide: all 24 copies had the identical defect. Caught live in container-host-aiops, where a stop recorded against a Podman target replayed against a Portainer one.

## v0.7.0 — 2026-08-02

### Changed (BREAKING)
- **Requires MCP SDK 2.0** (`mcp[cli]>=2.0,<3.0`). `mcp.server.fastmcp` no longer exists in 2.0; the server is now built with `MCPServer` and reports its package version in the stdio handshake.

### Fixed
- **`undo apply` works from the CLI.** Every write tool is imported lazily inside its own CLI command, so a CLI-driven undo ran in a process where the inverse tool was never registered and failed with "inverse tool is not registered" — for every write tool. Only the MCP entry point, which imports the whole server, worked. Found while live-verifying against a real cluster.
- **An undetermined outcome is audited `unknown`, not `ok`.** The harness only classified a result as undetermined when the payload *also* carried an `error` key, so a write that looked successful but had not been confirmed was recorded as a success.


## v0.6.0 — 2026-07-21

### Changed (BREAKING)
- **Removed the authorization layer** — read-only mode, the approver gate, and rules.yaml deny are gone. The skill no longer decides read vs write; that is the agent's judgement or the connecting account's permissions. `<PREFIX>_READ_ONLY` now has no effect (a startup warning is logged); `<PREFIX>_AUDIT_APPROVED_BY`/`_RATIONALE` are optional audit annotations.
- The retained guarantee is **unbypassable audit over MCP and CLI alike** — no unaudited entry point. Harness = audit + runaway safety guard + undo + sanitize; `risk_level` is a descriptive audit label, not a gate.

See RELEASE_NOTES.md for tool-specific changes.


## v0.5.0 — 2026-07-20

### Fixed
- **The SolarWinds SWIS port default moves to 17774.** Port 17778 was deprecated in Orion 2023.1 and is slated for removal.
- Harness: a write whose response is lost is audited `status=unknown`, not `error` — it may have taken effect. Undo tokens gain `effectVerified` (undo.db migrated in place).
- Harness: a dry-run no longer records an undo token, and no longer requires a named approver. Guards now run on the preview path.
- Truncated strings end in an ellipsis instead of being cut silently; error messages are capped at 800 chars, not 300.

See RELEASE_NOTES.md for the full detail.

## v0.3.0 — 2026-07-17

### Added
- **New:** Zabbix platform (3rd: SolarWinds/PRTG/Zabbix).
- **Undo executor**: `undo list` / `undo apply <id>` (CLI + MCP) — apply a recorded replayable inverse; the dispatched inverse is re-gated by its own risk tier; single-use, dry-run, double-confirm, both wrapper + inverse audited.

## v0.2.1 — 2026-07-16

### Fixed
- **`secrets.enc` now follows `MONITORING_AIOPS_HOME`** (secretstore hardcoded the real
  home directory; config/audit/undo already relocated — found in live verification).
- **Audit fidelity**: failures sanitized into `{"error": ...}` results by the MCP error
  layer are now audited as `status=error` (they previously read as `ok`, hiding failed
  attempts from exception reports), and no undo is recorded for a call that failed.

### Tests
- `doctor` and the `init` wizard are now fully covered (previously ~10–20%); plus a
  regression test for the sanitized-failure audit status.

## v0.2.0 — 2026-07-13

Security-hardening release from a line-wide code review.

### Changed (behavior)
- **Secure by default**: with no `rules.yaml`, high/critical operations now require a
  named approver (`MONITORING_AUDIT_APPROVED_BY`). A fresh install no longer allows
  destructive writes unattended; `init` seeds a starter `rules.yaml` you can edit,
  and an operator-authored rules file is honoured as-is.
- `__version__` is now single-sourced from package metadata (the previous release
  self-reported a stale version string).
- Sanitize docs no longer overstate scope: it strips control/format characters and
  truncates; semantic prompt-injection resistance must come from the consuming agent.

### Fixed
- `alert ack` CLI now double-confirms before acknowledging (line convention).
- SWIS invoke paths percent-encode agent-supplied segments.
- `init` TLS verification prompt now defaults to ON.

### Tests
- Governance persistence is now tested against REAL `audit.db`/`undo.db` files
  (write → audit row + inverse undo row with captured prior state).
- The CLI confirmed-write path (dry-run / double-confirm / governed execution) is
  covered end-to-end.
- `pytest-cov` added to the dev dependencies.

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
