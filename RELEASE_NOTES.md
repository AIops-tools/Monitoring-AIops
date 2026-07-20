# Release notes — monitoring-aiops 0.4.2

Previous release: 0.4.1.

## Fixed: a plain-HTTP Zabbix was unreachable, with no way to configure it

The target URL was built as `https://{host}:{port}` with no override. A
self-hosted Zabbix very often sits on plain HTTP behind a reverse proxy — and
against one, this tool simply could not connect, offering a TLS record-layer
error as the only clue.

Targets now accept an optional `scheme:` of `https` (default, so nothing changes
for an existing config) or `http`, validated at construction:

```yaml
targets:
  - name: zbx
    platform: zabbix
    host: 127.0.0.1
    port: 8080
    scheme: http
```

## Live-verified: Zabbix

The Zabbix branch had never been run against a live server. It has now been
exercised against **Zabbix 7.0.28**: `doctor` (token validity probe), all six
read tools (`problems`, `hosts`, `hostgroups`, `triggers`, `events`,
`maintenances`), and the governance loop — `zabbix_create_maintenance` really
created a maintenance window on the server, and `undo_apply` deleted it, with
all three calls audited.

Confirmed the auth model too: Zabbix wants an **API token**
(Administration → API tokens), not a user password, and the error when you pass
the wrong thing says so.

See [docs/VERIFICATION.md](docs/VERIFICATION.md) — **SolarWinds and PRTG remain
mock-only** (both need licensed servers) and are now the largest gap here.
