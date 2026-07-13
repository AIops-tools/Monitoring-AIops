---
name: monitoring-aiops
description: >
  Use this skill whenever the user needs to operate a network / infrastructure monitoring NOC on SolarWinds Orion (SWIS REST + SWQL) or Paessler PRTG (web API) — a one-shot NOC overview, canned SWQL answers (nodes down, flapping interfaces, muted, high-CPU nodes, full volumes, unmanaged/scheduled), a validated read-only SWQL passthrough, deduped/rolled-up active alerts, SolarWinds node/interface/volume/application health and top-N, PRTG sensors/devices/groups/history/alarms, and guarded writes (acknowledge, mute/unmute, schedule maintenance, unmanage/remanage, remove node, pause/resume sensor).
  Always use this skill for "SolarWinds", "Orion", "SWQL", "THWACK question", "PRTG", "Paessler", "NOC overview", "which nodes are down", "flapping interfaces", "interface flap storm", "alert storm", "acknowledge this alert", "worst CPU nodes", "top-N by latency/packet loss", "which volumes are full", "muted alerts report", "unmanaged nodes", "schedule a maintenance window", "unmanage / remanage a node", "pause a PRTG sensor" when the context is monitoring.
  Do NOT use when the target is something other than a SolarWinds/PRTG monitoring platform (a hypervisor, storage appliance, backup product, Kubernetes cluster, network device config, or OT/industrial equipment) — route those to the appropriate other AIops-tools skill. Zabbix is out of scope.
  Preview — governed monitoring operations with a built-in governance harness (audit, policy, token budget, undo, risk-tiers). Mock-validated only; PRTG's free Freeware edition is the easiest live check, SolarWinds is trial-only past 30 days.
installer:
  kind: uv
  package: monitoring-aiops
argument-hint: "[node/sensor id, a SWQL question, or describe your NOC task]"
allowed-tools:
  - Bash
metadata: {"openclaw":{"requires":{"env":["MONITORING_AIOPS_CONFIG"],"bins":["monitoring-aiops"],"config":["~/.monitoring-aiops/config.yaml","~/.monitoring-aiops/secrets.enc"]},"optional":{"env":["MONITORING_AIOPS_MASTER_PASSWORD"]},"primaryEnv":"MONITORING_AIOPS_CONFIG","homepage":"https://github.com/AIops-tools/Monitoring-AIops","emoji":"📡","os":["macos","linux"]}}
compatibility: >
  Standalone, self-governed monitoring operations across SolarWinds Orion (SWIS REST + SWQL, port 17778, HTTP Basic auth) and Paessler PRTG (web API, port 443/8080, API token) — preview. Each target in the config names its own platform, so one config can span both NOCs. The governance harness (audit, policy, token/runaway budget, undo, risk-tiers) is bundled in the package — no external skill-family dependency.
  All write operations are audited to a local SQLite DB under ~/.monitoring-aiops/ (relocatable via MONITORING_AIOPS_HOME).
  Credentials: the Orion account password (SolarWinds) or the PRTG API token is stored ENCRYPTED in ~/.monitoring-aiops/secrets.enc (Fernet/AES-128 + scrypt-derived key) — never plaintext on disk. Run 'monitoring-aiops init' to onboard (it asks for the platform), or 'monitoring-aiops secret set <target>' to add one. The store is unlocked by a master password from MONITORING_AIOPS_MASTER_PASSWORD (non-interactive/MCP/CI) or an interactive prompt (CLI on a TTY). A legacy plaintext env var MONITORING_<TARGET_NAME_UPPER>_SECRET is still honoured as a fallback with a deprecation warning (migrate with 'monitoring-aiops secret migrate'). The secret is used for HTTP Basic auth (SolarWinds) or as the PRTG API token at request time and held only in memory; secrets are never logged or echoed.
  Read-only SWQL passthrough (swql_query) is validated to accept SELECT statements only. State-changing operations pass through the @governed_tool decorator (pre-check + budget guard + audit + risk-tier gate). Destructive writes (unmanage_node, remove_node) are high-risk with dry_run + double confirmation; unmanage_node records an inverse remanage undo descriptor. Suppression/maintenance writes are TIME-BOXED (mute_alerts, schedule_maintenance, schedule_maintenance_prtg require an end time / duration). mute_alerts→unmute, pause_sensor→resume record inverse undo descriptors.
  Webhooks: none — no outbound network calls beyond the configured SolarWinds SWIS / PRTG web API.
  SSL: verify_ssl defaults to false-friendly for self-signed lab certs; enable for production.
  Transitive dependencies: httpx (HTTP client) and the MCP SDK. No post-install scripts or background services.
  PREVIEW: mock-validated only. PRTG has a free perpetual 100-sensor Freeware edition with the API (easiest live check); SolarWinds is a 30-day trial (mock-only past that — largest verification debt).
---

# Monitoring AIops (preview)

> **Disclaimer**: Community-maintained open-source project, **not affiliated with, endorsed by, or sponsored by SolarWinds, Paessler, or any monitoring vendor.** SolarWinds, Orion, SWQL, THWACK, PRTG and Paessler are trademarks of their respective owners. Source at [github.com/AIops-tools/Monitoring-AIops](https://github.com/AIops-tools/Monitoring-AIops) under the MIT license.

Governed network / infrastructure monitoring operations — **31 MCP tools**
across **SolarWinds Orion** (SWIS REST + SWQL) and **Paessler PRTG** (web API),
every one wrapped with the bundled `@governed_tool` harness: a local unified
audit log under `~/.monitoring-aiops/`, policy engine, token/runaway budget
guard, undo-token recording, and graduated-autonomy risk tiers. One config can
span both NOCs. The Orion password / PRTG API token is stored **encrypted**
(`~/.monitoring-aiops/secrets.enc`, Fernet + scrypt) — never plaintext on disk.

> **Standalone**: the governance harness is bundled in the package
> (`monitoring_aiops.governance`) — no external skill-family dependency.
> **Preview / mock-only**: PRTG's free Freeware edition is the easiest live
> check; SolarWinds is trial-only past 30 days (largest verification debt).

## What This Skill Does

| Group | Platform | Tools | Count | R/W |
|-------|----------|-------|:-----:|:---:|
| **SWQL** | SolarWinds | library, canned, query (SELECT-only passthrough) | 3 | read |
| **Alerts** | both | active_alerts (dedup/rollup), alert_acknowledge | 2 | 1 read, 1 write |
| **SolarWinds health** | SolarWinds | node/nodes/interface/volume/application status, topn, noc_rollup | 7 | read |
| **SolarWinds writes** | SolarWinds | list_events/unmanaged/muted | 3 | read |
| | SolarWinds | mute/unmute, schedule_maintenance, remanage_node | 4 | write (med) |
| | SolarWinds | unmanage_node, remove_node | 2 | write (**high**) |
| **PRTG** | PRTG | sensors/sensor_details/devices/groups/history/system_status/alarms | 7 | read |
| **PRTG writes** | PRTG | pause_sensor, resume_sensor, schedule_maintenance_prtg | 3 | write (med) |

The canned SWQL library (`swql_library` lists them) answers the most-repeated
THWACK questions directly: `nodes_down`, `flapping_interfaces`, `muted_report`,
`high_cpu_nodes`, `volumes_full`, `unmanaged_scheduled`. For anything else,
`swql_query` is a validated read-only (SELECT-only) SWQL passthrough.

## Quick Install

```bash
uv tool install monitoring-aiops
monitoring-aiops init       # wizard: pick platform (solarwinds/prtg) + encrypted secret
monitoring-aiops doctor
```

## When to Use This Skill

- Get a NOC snapshot (`overview` / `noc_rollup`): active/unacked alert counts,
  down/warning nodes, worst CPU
- Answer a repeated SWQL question (`swql_library` → `swql_canned nodes_down`), or
  run an ad-hoc read-only SWQL SELECT (`swql_query`)
- Triage an alert storm (`active_alerts` dedup/rollup collapses flap/down
  storms), then `alert_acknowledge`
- SolarWinds health: `node_status`, `interface_status` (top-N by util),
  `volume_status`, `application_status` (SAM), `topn` (cpu/mem/latency/loss)
- PRTG: list `prtg_sensors` / `prtg_devices` / `prtg_groups`, drill with
  `prtg_sensor_details` / `prtg_history`, check `prtg_alarms` / `prtg_system_status`
- Safely take a node out for maintenance (`schedule_maintenance` /
  `unmanage_node` with dry_run + approver), or pause a PRTG sensor (`pause_sensor`)

**Do NOT use when** the target is not a SolarWinds/PRTG monitoring platform —
route hypervisor, storage, backup, cluster, network-device-config, or
OT/industrial work to the appropriate other AIops-tools skill. Zabbix is out of
scope.

## Related Skills — Skill Routing

| If the user wants… | Use |
|--------------------|-----|
| SolarWinds Orion / SWQL or PRTG monitoring ops | **monitoring-aiops** (this skill) |
| A non-monitoring platform (hypervisor, storage, backup, cluster, network config, OT edge) | the appropriate **other AIops-tools** skill |
| Zabbix / other monitoring stacks | out of scope for this tool |

## Common Workflows

### Answer a SWQL / THWACK question

1. `monitoring-aiops swql library` (or `swql_library`) → list the canned queries
2. `monitoring-aiops swql canned nodes_down` (or `swql_canned`) → run it directly
3. Need something not canned? `monitoring-aiops swql query "SELECT ..."` — the
   passthrough validates it is a read-only SELECT before running

### Triage an alert storm

1. `active_alerts` → deduped/rolled-up entries; an interface-flap or node-down
   storm collapses into one entry with a count instead of a wall of alerts
2. Pick the rolled-up entry that matters, then `alert_acknowledge` (SW
   `AlertActive.Acknowledge` / PRTG `acknowledgealarm`)

### Which nodes are down / worst CPU

1. `noc_rollup` → down/warning counts + the worst-CPU nodes in one call
2. Drill with `topn` (cpu/memory/latency/packetloss) or `swql_canned high_cpu_nodes`

### Safely unmanage a node for maintenance (reversible)

1. `swql_canned nodes_down` / `node_status` → confirm the node
2. `schedule_maintenance <node> --end ...` (time-boxed) **or**
   `unmanage_node <node> --dry-run` → preview the call
3. Re-run without `--dry-run` (double-confirm; set `MONITORING_AUDIT_APPROVED_BY`
- **Secure by default (v0.2.0+)**: with no `~/.monitoring-aiops/rules.yaml`, high/critical operations are denied unless `MONITORING_AUDIT_APPROVED_BY` names an approver (set `MONITORING_AUDIT_RATIONALE` too). `monitoring-aiops init` seeds a starter rules.yaml; an operator-authored rules file is honoured as-is.
   + `MONITORING_AUDIT_RATIONALE` for the high-risk gate) — it records an inverse
   remanage undo descriptor
4. When maintenance ends, `remanage_node <node>` (or replay the recorded undo)

## Governance & Safety

- Every tool is audited to `~/.monitoring-aiops/audit.db` (relocatable via
  `MONITORING_AIOPS_HOME`).
- High-risk ops (`unmanage_node`, `remove_node`) can require a named approver:
  set `MONITORING_AUDIT_APPROVED_BY` and `MONITORING_AUDIT_RATIONALE`.
- Destructive writes support `--dry-run` and double confirmation at the CLI.
- Suppression / maintenance writes are **time-boxed** (require an end time /
  duration). Reversible writes record an inverse descriptor (mute→unmute,
  unmanage→remanage, pause→resume).

## References

- `references/capabilities.md` — full tool + platform + SWQL/API-path reference
- `references/cli-reference.md` — CLI command reference
- `references/setup-guide.md` — onboarding, credentials, and connectivity
