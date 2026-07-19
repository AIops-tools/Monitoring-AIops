# Live verification — monitoring-aiops

`monitoring-aiops` is published on PyPI, the MCP Registry, and ClawHub. What it
has **not** had is an end-to-end run against a live NOC:

> The code is exercised by a mock-only test suite (`uv run pytest`, no real
> SolarWinds, PRTG, or Zabbix). It has not yet been validated end-to-end against
> a live monitoring platform. Until it has, we do not claim it works against a
> real SWIS / PRTG / Zabbix API.

This document defines exactly what a live verification run must cover, and the
criteria for recording this tool as live-verified. It is deliberately
checklist-shaped so the result is reproducible and auditable — not a subjective
"seems fine". Because this tool spans **three platforms**, verification is
tracked **per platform** — a green Zabbix run says nothing about SolarWinds.

## What the mock suite already guarantees

- Every module imports; the CLI builds; every MCP tool carries the
  `@governed_tool` harness marker (`tests/test_smoke.py`).
- The SWQL passthrough validator accepts `SELECT` and refuses everything else,
  including comment-smuggled and multi-statement write attempts.
- Alert dedup / rollup collapses a synthetic flap storm into the expected
  rolled-up entries with the right counts.
- Zabbix item history is bounded (capped window and point count) and the
  JSON-RPC auth shape switches correctly between the 6.4+/7.x Bearer header and
  the legacy 6.0 `auth` field.
- Write tools carry the correct risk tier and record the correct inverse undo
  descriptor (mute→unmute, unmanage→remanage, pause→resume,
  create-maintenance→delete-that-id); `zabbix_delete_maintenance` captures the
  window's full definition into priorState first.
- Governance genuinely persists: audit rows and undo tokens land in a real
  SQLite DB.

What it does **not** guarantee: that real SWIS entity/field names, PRTG web-API
response dialects, and Zabbix JSON-RPC shapes match what these tools assume.

## Prerequisites for a live run

Verification cost differs sharply per platform:

- **Zabbix — cheapest.** Fully open source; a Docker-compose appliance is a
  ~10-minute live check. Do this one first.
- **PRTG — cheap.** Free perpetual **100-sensor Freeware** edition, with the
  web API enabled. Create an API token for a least-privilege user.
- **SolarWinds Orion — expensive.** 30-day trial only; past the trial this tool
  is mock-only. **This is the largest verification debt in this repo.**

For each platform create a **throwaway test node/host/sensor** you are willing
to mute, unmanage, pause, and (on SolarWinds) remove. Never verify against a
node someone is actually on call for — suppression writes make real alerts
disappear.

```bash
uv tool install monitoring-aiops
monitoring-aiops init            # asks for the platform; encrypted secret store
```

## Verification checklist

Tick every box **per platform you are verifying**. A box that cannot be ticked
is a verification gap — record it, do not silently pass.

### 1. Connectivity (the fastest live gate)
- [ ] `monitoring-aiops doctor` → green: a SWQL query for SolarWinds,
      `/api/status.json` for PRTG, unauthenticated `apiinfo.version` plus an
      authed host count for Zabbix.

### 2. Reads return real, well-shaped data
- [ ] `monitoring-aiops overview` / `noc_rollup` → down and warning counts match
      the platform's own dashboard at the same moment.
- [ ] `nodes_list` / `prtg_devices` / `zabbix_hosts` → the real inventory, with
      populated ids and names.
- [ ] `active_alerts` → the currently firing alerts, and the rollup collapses a
      real flap storm rather than a synthetic one (induce one by bouncing a test
      interface or a test sensor).
- [ ] `topn cpu` / `topn latency` → ordering and values match the platform UI.
- [ ] `node_status`, `interface_status`, `volume_status`, `application_status`
      (SolarWinds) → no crash on a node missing that sub-entity.
- [ ] `prtg_sensors`, `prtg_sensor_details`, `prtg_groups`, `prtg_history`,
      `prtg_system_status`, `prtg_alarms` (PRTG) → populated and correctly typed.
- [ ] `zabbix_problems`, `zabbix_triggers`, `zabbix_events`, `zabbix_hostgroups`,
      `zabbix_maintenances` (Zabbix) → match the Zabbix frontend.
- [ ] `zabbix_item_history` → respects the bounded window/point cap against a
      real high-frequency item (this is where an unbounded read would hurt).

### 3. SWQL passthrough (SolarWinds only)
- [ ] `monitoring-aiops swql library` → the canned queries list.
- [ ] `monitoring-aiops swql canned nodes_down` → results match a hand-run SWQL
      query in the SolarWinds SWQL Studio.
- [ ] Every canned query in the library runs without a dialect error against a
      real Orion — a canned query that 500s is a **blocking** finding.
- [ ] `monitoring-aiops swql query "UPDATE ..."` → refused by the validator, and
      the refusal happens **before** anything is sent to the server.

### 4. A reversible write + its undo (governance closes the loop)
- [ ] `monitoring-aiops alert ack <id>` → the alert is genuinely acknowledged in
      the platform UI; the result carries an `_undo_id`; a row lands in
      `~/.monitoring-aiops/audit.db`.
- [ ] `mute_alerts` on the test node (time-boxed) → alerts really are suppressed;
      `monitoring-aiops undo apply <id>` unmutes and the prior state returns.
- [ ] `unmanage_node --dry-run` → prints the call, changes nothing; then for real
      → the node shows unmanaged, and `undo apply` remanages it.
- [ ] `pause_sensor` (PRTG) then `undo apply` → the sensor resumes.
- [ ] `zabbix_create_maintenance` then `undo apply` → the window is created then
      deleted by **id**, leaving no orphan window.
- [ ] `zabbix_delete_maintenance` on a throwaway window → priorState contains the
      window's **full definition** (timeperiods, groups, hosts), not just its id.

### 5. Time-boxing is real, not nominal
- [ ] A `mute_alerts` / `schedule_maintenance` window with a short end time
      actually **expires on its own** and alerting resumes without operator
      action. (This is the safety property the tool leans on — verify it.)

### 6. Governance actually gates
- [ ] With no `~/.monitoring-aiops/rules.yaml`, a `high`-risk op
      (`unmanage_node`, `remove_node`, `zabbix_delete_maintenance`) is **refused**
      unless `MONITORING_AUDIT_APPROVED_BY` names an approver
      (secure-by-default).
- [ ] With the approver set, the op proceeds and the audit row records the
      approver and `MONITORING_AUDIT_RATIONALE`.
- [ ] A failed write is audited with `status=error` and records **no** undo token.
- [ ] A tight alert-poll loop trips the runaway budget guard rather than
      hammering the NOC API.

### 7. Cleanup
- [ ] `list_muted` and `list_unmanaged` are **empty** of your test artefacts —
      nothing left silently unmonitored.
- [ ] `zabbix_maintenances` contains no leftover test windows.
- [ ] On SolarWinds, `remove_node` the throwaway node; confirm it is audited and
      tagged `high`.

## Criteria to consider this tool live-verified

Record `monitoring-aiops` as live-verified **per platform**, and only when all
of the following hold for that platform:

1. Every applicable box above is ticked against a real instance, and the version
   is recorded (e.g. "verified on Zabbix 7.0", "verified on PRTG 24.x",
   "verified on Orion 2024.2"). **Never write a bare "live-verified"** — this
   tool spans three platforms and a partial run must be recorded as partial.
2. Any entity-name, field-shape, or API-dialect mismatch found during the run is
   fixed **and covered by a test**, so the mock suite cannot regress it.
3. Section 5 (time-boxing) passed by **observing an actual expiry**, not by
   reading the parameter back.
4. The run is written up in this repo's release notes with the date, the tool
   version, and the platform version, matching how the line records its other
   live-verified tools.

Until then this document is the accurate statement of status — and no positive
claim about real-NOC behaviour should appear in the README or SKILL.md.

## Notes for maintainers

- `monitoring-aiops doctor` is the single fastest live entry point; start there.
- Verify in cost order: **Zabbix → PRTG → SolarWinds**. Two-thirds of the
  verification debt clears for free.
- SolarWinds past the 30-day trial is the known blocker; if it stays unverified,
  say so plainly rather than letting a Zabbix-only run imply full coverage.
- The verification story for the whole product line is tracked centrally; add
  this tool's per-platform result there so the verification-debt ledger stays
  accurate.
