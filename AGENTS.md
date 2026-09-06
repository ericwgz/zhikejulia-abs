# ABS project instructions

This repository is the maintained ABS source. Read README.md and DEPLOYMENT.md.

- Keep all demo products synthetic. Preserve fixed report snapshots and team isolation.
- Never commit credentials, environment values, SQLite files, logs or SSH private keys.
- Backend runtime uses Python standard library only. Frontend uses native JavaScript.
- Bump static asset version query strings in index.html when changing those assets.
- Run Python API/work tests and Node scoring tests for business logic changes; run
  `npm ci && npm test` when frontend behavior changes.
- Production deployment requires a clean committed checkout. Use `scripts/deploy.py`
  with the separately supplied dedicated SSH key. Inspect the change and tests first.
- Preserve `/etc/badrams/abs-api.env` and `/srv/badrams-data/abs-api/`.
- Do not change Cloudflare/DNS, other VM services, or AGIDock resources merely to ship
  application code. The cloud API key is separate from application deployment access.
- Scope deployments to ABS. The original BadRams portal shares this host.
- Email notifications are not implemented; do not describe in-app CC as email delivery.
