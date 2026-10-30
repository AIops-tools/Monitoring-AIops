# Live verification status

This document records what has and has not been validated against real
monitoring servers, so the maturity claim is auditable rather than a vibe.

## Already live-verified ✅ — Zabbix 7.0.28 (2026-07-20)

- `doctor` against a live server, including the API-token validity probe.
- All six Zabbix read tools returned well-shaped data: `problems`, `hosts`,
  `hostgroups`, `triggers`, `events` (with truncation envelope), `maintenances`.
  The unbounded reads count the rows returned by the API; `events` reports
  measured truncation when its explicit limit is reached.
- Governance loop end-to-end: `zabbix_create_maintenance` really created a
  maintenance window (confirmed via `maintenance.get`), and `undo_apply` deleted
  it — all three calls landed audit rows.
- Confirmed the auth model: Zabbix needs an **API token**, not a user password.

**A real bug was found and fixed by this run**: the target URL was hardcoded to
`https://`, so a plain-HTTP Zabbix — very common self-hosted, behind a reverse
proxy — was unreachable with no config knob to fix it. Targets now take an
optional `scheme:`.

## Not yet live-verified ⚠️

- **SolarWinds Orion** and **PRTG** — both platform branches, including all the
  SWQL machinery. Both need licensed servers; this is the largest gap here.
- **The SWIS port default and its fallback.** The default moved to **17774**
  (the SWIS REST port from Orion 2023.1 on, with 17778 documented as deprecated
  and slated for removal); a defaulted port that refuses the connection retries
  **once** on 17778 and then remembers which one answered. An operator-set
  `port:` is used verbatim and never probed. All of that is modelled from
  SolarWinds' documentation and exercised only against a simulated client —
  **no real Orion has answered on either port here**. Status: **UNKNOWN —
  pending live**. What a live run must distinguish: a 2023.1+ Orion should
  answer on 17774 with **no** fallback attempt (the probe costs a round trip),
  and a pre-2023.1 Orion should end up on 17778 and stay there for the rest of
  the session.
- ~~Zabbix with a real estate, and `alert ack` against real alerts.~~
  **Closed 2026-08-10 against a live Zabbix 7.0.29** carrying three hosts, four
  trapper items with triggers, and six genuine problems raised by pushing real
  values (plus the server's own agent-unavailable problem).
  - `alert list` / `overview`: `total` and `unacknowledged` matched
    `problem.get` exactly, and the dedup/rollup grouped by message as designed.
  - `alert ack`: the dry-run changed nothing; the real call acknowledged
    **exactly** the named event on the server (`acknowledged: 1`) and left the
    other five alone, with `priorState.acknowledged: false` captured. No undo
    token is recorded, which matches the tool's contract — `acknowledge_alert`
    does not advertise reversibility.
  - That run found a real defect: **`entity` carried the numeric trigger id**
    instead of the host, so an alert list answered "which host is alerting?"
    with `25224` — while the same field is a readable name on SolarWinds
    (`EntityCaption`) and PRTG (`device`). Now resolved to the host name through
    one batched `event.get`; `problem.get` cannot do it (it rejects
    `selectHosts` outright — measured, not assumed).
  - **Corrected 2026-10-30:** the earlier fleet-scale warning attributed a
    1000-row API cap to Zabbix `search_limit` without evidence. In the official
    7.0.29 implementation, `problem.get` and `host.get` default `limit` to
    `null` and pass that value to `DBselect`; the other read services used here
    likewise default to `null`. `search_limit` is a frontend search/filter
    setting, not an implicit cap in these API methods. Sources:
    [CProblem.php](https://github.com/zabbix/zabbix/blob/7.0.29/ui/include/classes/api/services/CProblem.php),
    [CHost.php](https://github.com/zabbix/zabbix/blob/7.0.29/ui/include/classes/api/services/CHost.php),
    [Zabbix API `problem.get`](https://www.zabbix.com/documentation/7.0/en/manual/api/reference/problem/get),
    and [frontend GUI settings](https://www.zabbix.com/documentation/7.0/en/manual/web_interface/frontend_sections/administration/general).
    A live fleet with more than 1000 rows has still not been exercised; memory
    use and response time at that scale remain unmeasured. `events` and item
    history use explicit `limit + 1` probes and report truncation separately.

## MCP protocol compatibility — local stdio (2026-10-30)

- With Python MCP SDK 2.0.0, the real `monitoring-aiops-mcp` process completed
  legacy `initialize` (2025-11-25) and modern `server/discover` (2026-07-28).
  Both paths listed all 42 tools with the expected `undo_list` read-only hint
  and `zabbix_problems` risk metadata; `undo_list` returned a successful result.
- The same wire test exposed a protocol error: a missing Zabbix config produced
  a sanitized `{"error": ...}` result and an `error` audit row, while MCP
  marked the call `isError: false`. The server now marks such tool results
  `isError: true` **after** the governance wrapper records the failure. The
  legacy and modern stdio regression tests pass. This matches the
  [MCP 2026-07-28 tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
  for tool execution failures.
- This is a local transport and missing-config test. No live SolarWinds, PRTG,
  or Zabbix server was contacted in this protocol check; HTTP transport and
  client-specific behavior were not tested.

## Governance hardening — local synthetic verification (2026-10-30)

The shared governance tests exercise a durable `pending` row before a write, refusal when the audit DB cannot persist that row, a visible pending row after finalization failure, explicit reconciliation to `unknown`, async/preview parity, result minimization, and metadata-only telemetry with `AIOPS_WORKFLOW_ID`. The tests use a temporary SQLite DB and synthetic tools; they do not claim a new live upstream write was performed. Existing audit rows and rotated archives from earlier releases are not automatically scrubbed. A pending intent from another process is never auto-reconciled. On POSIX the rotation/intent lock spans processes; on Windows it currently protects only threads in this process.
