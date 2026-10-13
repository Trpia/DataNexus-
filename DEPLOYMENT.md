# DataNexus Pro — backend installation and deployment

## Important architecture boundary
The existing PWA remains an offline-first, browser-local application. Its current shipment/inventory/customer records are not automatically copied into this backend. This upgrade adds a separate server-side administration API and a richer Developer Console. Until a deliberate data-sync adapter is implemented and configured, the console labels browser counts as local-only and server data as separate. Do not market browser-local accounts as production-grade multi-user authentication.

## Local installation

1. Install Python 3.11+.
2. Create and activate a virtual environment.
3. `pip install -r server/requirements.txt`
4. Copy `.env.example` to `.env`; set `DNX_SECRET_KEY` to a random value (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Never commit `.env`.
5. Set environment variables from `.env` in your shell or hosting provider. The sample app does not automatically load `.env` to avoid adding another dependency.
6. Run `flask --app server.app create-owner` and set a unique password of at least 12 characters. No default owner password is included. To reset an existing account password, run `flask --app server.app set-password`; enter the account username and new password interactively. Passwords are never stored in source code.
7. Run locally with `python server/app.py`. Open `http://127.0.0.1:5000/`; the backend serves the PWA and `/api` from the same origin. API health is `http://127.0.0.1:5000/api/health`.
8. For production use a supported WSGI server, e.g. `gunicorn --workers 2 --bind 127.0.0.1:5000 server.app:app`, behind an HTTPS reverse proxy. Set `DNX_ENV=production` and `DNX_COOKIE_SECURE=1`.

## Deployment notes
- A static GitHub Pages deployment cannot run this Python backend. Deploy the backend to a Python-capable host/container and configure the frontend/API origin plus CORS/CSRF policy before connecting them across origins. Same-origin reverse proxy is preferred.
- The backend serves only the public PWA assets from allowlisted paths, so `/api` and the app are same-origin by default. If hosting the API elsewhere, configure a reviewed reverse proxy; do not put secrets in browser configuration.
- Use HTTPS, strong random `DNX_SECRET_KEY`, firewall the database and backup directory, rotate credentials, and restrict file permissions. Configure database/backup retention and off-site encrypted backups before production.
- MFA has been removed from this edition. Existing database MFA enrollment is cleared at startup. This simplifies sign-in but reduces account protection; use a long unique password, HTTPS, limited account access, and short session expiry. MFA can be reintroduced later with a tested recovery flow.
- Sessions are HttpOnly, SameSite=Strict and expire after `DNX_SESSION_MINUTES`; secure cookies must be enabled behind HTTPS. API writes reject cross-origin `Origin` values. A same-origin deployment is recommended.

## Backups and restore
- Owner-only `POST /api/admin/backups` with `{"action":"create"}` creates a SQLite-consistent backup and records success only after the copy completes.
- Owner-only `GET /api/admin/backups` lists recorded backups. Keep backups outside public/static folders and restrict file access.
- Online restore is deliberately disabled. For a maintenance-window restore: stop all app workers, make a fresh copy of the current DB, verify the target backup file and checksum, replace the database file while workers remain stopped, run `PRAGMA integrity_check`, then restart and verify `/api/health`. Keep the pre-restore copy until verification completes. Do not upload arbitrary restore files through the browser.
- Schema migration version 1 is created idempotently at startup. Production changes should be added as numbered migrations and tested on a copy before deployment.

## API highlights
- Public: `GET /api/health`, `POST /api/auth/login`, `POST /api/auth/logout`.
- Authenticated: `GET /api/auth/me`. MFA endpoints are not available in this edition.
- Owner/Developer: overview, users list/role changes, application logs, audit, diagnostics, integrations, releases list.
- Owner-only: database diagnostics, backups, export, feature-flag changes, announcements, release metadata, operational settings.
- Roles are checked by backend decorators on every protected endpoint. Owner, Developer, Admin, Staff and Customer are distinct roles. No client-supplied role is trusted.

## Working vs external/unimplemented
Working when installed: server-side user/password storage, hashed passwords, role-checked endpoints, signed expiring sessions, MFA-disabled password authentication, audit logs, API request timing/status events, database integrity diagnostics, SQLite backup creation, metadata exports, feature flags, announcements, release metadata, protected role changes.

Not wired to an external provider: email delivery, SMS/push, maps, live GPS/carrier tracking, external webhook delivery, uptime monitor, deployment-provider rollback, cloud/off-site backups, shared shipment/inventory/customer synchronization, and automatic migration deployment pipeline. These show as unconfigured or metadata-only; no fake provider results are generated. Release metadata does not perform a deployment or rollback. The current PWA's local account system remains separate from backend accounts until a sync/auth integration is intentionally implemented.

## Security caveat
This is an implementation starter, not a completed independent security audit. Before handling real customer data, add automated tests, reverse-proxy rate limiting, operational monitoring, encrypted off-site backups, dependency scanning, and a reviewed production deployment configuration.

## Setting the Owner login non-interactively
```
export DNX_OWNER_USER='Owner'
export DNX_OWNER_PASS='your-password-here'   # 12+ chars; never put it in source files
flask --app server.app set-owner
```
Creates or updates the Owner account (usernames are case-insensitive, stored lowercase). Unset the variables afterwards.
