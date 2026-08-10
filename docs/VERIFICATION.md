# Live verification status

This document records what has and has not been validated against real
monitoring servers, so the maturity claim is auditable rather than a vibe.

## Already live-verified ✅ — Zabbix 7.0.28 (2026-07-20)

- `doctor` against a live server, including the API-token validity probe.
- All six Zabbix read tools returned well-shaped data: `problems`, `hosts`,
  `hostgroups`, `triggers`, `events` (with truncation envelope), `maintenances`.
  These fetch everything the API returns, so their `total` is a true count.
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
  - Still open at **fleet** scale: Zabbix applies a server-side `search_limit`
    (default 1000) that the reads do not detect, so on a large install a `total`
    could silently be the capped value. Three hosts cannot exercise that.
