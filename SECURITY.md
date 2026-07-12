# Security Policy

## Disclaimer

Community-maintained open-source project. **Not affiliated with, endorsed by, or
sponsored by SolarWinds or Paessler.** Product and trademark names (SolarWinds,
Orion, PRTG) belong to their owners. Source is auditable under the MIT license.

## Reporting Vulnerabilities

Report privately via a GitHub Security Advisory on
[github.com/AIops-tools/Monitoring-AIops](https://github.com/AIops-tools/Monitoring-AIops/security/advisories)
or email zhouwei008@gmail.com. Please do not open public issues for security
reports.

## Security Design

### Credential Management
- Per-target secrets — the SolarWinds Orion account password (used for SWIS HTTP
  Basic auth) or the PRTG API token — live **encrypted** in
  `~/.monitoring-aiops/secrets.enc` (Fernet/AES-128 + scrypt-derived key; chmod
  600), never in `config.yaml` and never in source. The master password is never
  stored — only a per-store random salt and the ciphertext are on disk.
- A legacy plaintext env var `MONITORING_<TARGET_NAME_UPPER>_SECRET` is still
  honoured as a fallback with a deprecation warning (migrate with
  `monitoring-aiops secret migrate`).
- The secret is held only in memory and never logged or echoed. For PRTG the API
  token is passed as the `apitoken` request parameter (not embedded in a stored
  URL); the config file holds only platform, host, port, username, and TLS
  settings. SWQL passthrough is validated read-only (SELECT only) to keep the
  query surface from being used for writes.

### Governed Operations
Every MCP tool runs through the bundled `@governed_tool` harness
(`monitoring_aiops.governance`):
- **Audit** — every call logged to a local SQLite DB under `~/.monitoring-aiops/`
  (relocatable via `MONITORING_AIOPS_HOME`), agent-attributed, secret-redacted.
- **Token/runaway budget** — hard ceilings (`MONITORING_MAX_TOOL_CALLS` /
  `MONITORING_MAX_TOOL_SECONDS`) plus an on-by-default guard that trips a tight
  poll/retry loop, preventing unbounded API consumption (e.g. polling a slow
  session).
- **Graduated risk tiers** — `~/.monitoring-aiops/rules.yaml` `risk_tiers` gate
  writes by environment/tag; the highest tiers require a recorded approver.
- **Undo-token recording** — reversible writes capture the BEFORE state and
  record an inverse descriptor (e.g. `mute_alerts`→`unmute_alerts`,
  `unmanage_node`→`remanage_node`, `pause_sensor`→`resume_sensor`) so the change
  can be rolled back.

### State-Changing Operations
Destructive writes — `unmanage_node`, `remove_node` — are `risk_level=high`,
accept a `dry_run` preview, and (under `risk_tiers`) require a recorded approver
(`MONITORING_AUDIT_APPROVED_BY` + `MONITORING_AUDIT_RATIONALE`). Suppression and
maintenance writes (`mute_alerts`, `schedule_maintenance`, `pause_sensor`,
`schedule_maintenance_prtg`) are `risk_level=medium` and **time-boxed** — they
require an end time / duration (no open-ended suppression). Acknowledge is
`risk_level=low`. Reversible writes capture before-state and record an undo token.

### SSL/TLS Verification
`verify_ssl` defaults to true; disable only for self-signed lab certificates.

### Prompt-Injection Protection
All server-returned text (node/interface captions, alert messages, sensor names,
event text) is passed through a `sanitize()` truncate + control-character strip
before reaching the agent.

### Network Scope
No webhooks, no telemetry, no outbound calls beyond the configured SolarWinds
SWIS and PRTG API endpoints. No post-install scripts or background services.

## Static Analysis

```bash
uvx bandit -r monitoring_aiops/ mcp_server/
uv run ruff check .
```

## Supported Versions

The latest released version receives security fixes. This is a preview (0.x);
pin a version in production.
