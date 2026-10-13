# DataNexus Pro Developer Console upgrade

See `DEPLOYMENT.md` for installation, environment configuration, deployment, backups and restore procedures.

- `server/app.py`: Flask API, server-enforced roles, auth sessions, MFA-disabled password authentication, audit/API logs, database diagnostics, backups, flags, announcements and release metadata.
- `server/requirements.txt`: Python dependencies.
- `server/migrations/001_initial.sql`: migration marker/reference.
- `.env.example`: safe environment variable template (placeholder values only).
- `js/views/dev.js` and `css/styles.css`: responsive Developer Console with searchable local users, configurable widgets, five themes, diagnostics, and clearly marked unavailable integrations.

The PWA and backend do not share business data automatically yet. Static-host deployments need a separate Python backend. UI modules do not claim live data unless the backend confirms it.
