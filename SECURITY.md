# Security Policy

## Supported Versions

Security fixes are accepted for the current `main` branch until formal release branches exist.

## Reporting a Vulnerability

Please do not open a public issue for a suspected vulnerability. Email
`hello@your-domain.example` with:

- affected version or commit,
- a short reproduction,
- impact and any known workaround,
- whether credentials, project data, or publishing access may be exposed.

We will acknowledge reports as quickly as possible and coordinate a fix before public disclosure.

## Operator Responsibilities

- Set a strong `DRAPER_DASHBOARD_TOKEN` in production.
- Keep `.env`, `data/*.sqlite3`, `data/projects/**/secrets.json`, and backups out of Git.
- Bind the dashboard to `127.0.0.1` behind a same-host reverse proxy, or — for the split-host
  proxy deployment the unit file targets — bind `0.0.0.0` but restrict port 8765 to the proxy's IP
  at the firewall. Either way, terminate TLS at the proxy and keep `DRAPER_REQUIRE_AUTH=1` and
  `DASHBOARD_SECURE_COOKIE=1` set.
- Failed dashboard logins are throttled per source IP (10 failures / 5 minutes by default) and
  audited as `auth` events in the system event log (`/api/events?category=auth`). Behind a reverse
  proxy the proxy's address is the throttle key; do not forward spoofable client IP headers to the
  app for this purpose.
- Rotate provider API keys if logs, backups, or local disks may have been exposed.
