# Production Deployment Guide (Render / Railway / Heroku)

## 1) Prerequisites
- Domain + TLS enabled.
- Stripe live keys + `STRIPE_WEBHOOK_SECRET`.
- SMTP provider (SendGrid/Mailgun/Gmail app password).
- `SECRET_KEY` generated (64+ chars).

## 2) Environment variables
Use `.env.example` as baseline and set at minimum:
- `SECRET_KEY`
- `DATABASE_PATH`
- `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`
- `MAIL_ENABLED=1`, `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`
- `SENTRY_DSN` (recommended)

## 3) Start command
Use Gunicorn with `gunicorn.conf.py`:
```bash
gunicorn -c gunicorn.conf.py app:app
```

## 4) Platform notes
### Render
- Build: `pip install -r requirements.txt`
- Start: `gunicorn -c gunicorn.conf.py app:app`
- Add persistent disk for SQLite (or migrate to Postgres).

### Railway
- Same build/start commands.
- Ensure volume mount for SQLite persistence.

### Heroku
- Use `web: gunicorn -c gunicorn.conf.py app:app` in Procfile.
- Prefer Postgres for production; SQLite ephemeral FS is risky.

## 5) HTTPS and security
- Force HTTPS redirects at platform edge.
- `SESSION_COOKIE_SECURE=1`
- `SESSION_COOKIE_SAMESITE=Lax`
- Keep `FLASK_ENV` off development in production.

## 6) Health & metrics
- `GET /health` for uptime checks.
- `GET /metrics` for basic request/error/latency telemetry.

## 7) Stripe webhook
- Endpoint: `https://<your-domain>/stripe-webhook`
- Configure events:
  - `checkout.session.completed`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`

## 8) SMTP end-to-end verification checklist
1. Register a new account in staging.
2. Confirm verification email arrives and link works.
3. Trigger forgot-password, confirm reset email arrives.
4. Verify sender domain SPF/DKIM/DMARC configured.

## 9) Backup/restore
- Daily cron: `python scripts/backup_db.py`
- Restore with `scripts/restore_db.sh <backup.gz>`.
