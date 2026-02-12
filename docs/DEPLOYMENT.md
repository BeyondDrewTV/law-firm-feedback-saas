# Production Deployment Guide

## Architecture baseline
- Flask app served by Gunicorn behind an HTTPS reverse proxy (Nginx/Cloudflare/Render edge).
- Persistent database volume mounted at `DATABASE_PATH` (SQLite minimum) or migrate to managed Postgres for scale.
- Background operational jobs via cron: backups + lifecycle reminder emails.

## 1) Provision infrastructure
1. Create production host (Render/Fly/EC2) with at least 2 vCPU / 2 GB RAM.
2. Create DNS records:
   - `A` record: `app.yourdomain.com -> host public IP`
   - Optional `CNAME`: `www.app.yourdomain.com -> app.yourdomain.com`
3. Configure TLS certificate (Let's Encrypt or managed cert).
4. Restrict firewall ingress to `80/443`; SSH only from trusted office IPs.

## 2) App bootstrap
1. Clone repository and create virtualenv.
2. Copy `.env.example` to `.env` and set all secrets.
3. Install dependencies and run tests.
4. Initialize database schema: `python -c "from app import init_db; init_db()"`.
5. Start app: `gunicorn -c gunicorn.conf.py app:app`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
python -c "from app import init_db; init_db()"
gunicorn -c gunicorn.conf.py app:app
```

## 3) HTTPS and security checklist
- [ ] `SESSION_COOKIE_SECURE=1` and `REMEMBER_COOKIE_SECURE=1`
- [ ] `ENABLE_HSTS=1`
- [ ] Reverse proxy redirects HTTP -> HTTPS
- [ ] Stripe webhook endpoint uses HTTPS and validates signatures
- [ ] `SECRET_KEY` rotated and stored in secret manager
- [ ] Access logs and application logs retained for at least 30 days

## 4) Static asset strategy
- Serve `/static` through CDN (Cloudflare/Fastly/CloudFront).
- Add fingerprinted filenames during build for long TTL caching.
- Recommended headers:
  - `Cache-Control: public, max-age=31536000, immutable` for versioned assets
  - `Cache-Control: no-cache` for HTML documents

## 5) Database migrations and rollback
- **Before deploy:** run `scripts/backup_db.sh` and verify artifact in S3/local backup dir.
- **Deploy strategy:** additive migration only (new tables/indexes/columns) via `init_db()`.
- **Rollback strategy:**
  1. Stop app process.
  2. Restore latest known-good backup with `scripts/restore_db.sh backups/file.sqlite3.gz`.
  3. Redeploy previous application image/commit.
  4. Run smoke tests.

## 6) Monitoring and alerts
- UptimeRobot HTTP checks:
  - `/health` every 60 seconds
  - alert after 2 failures
- Sentry DSN configured in production.
- Capture dashboards from `/metrics` (request volume, error rate, avg latency).

## 7) Stripe production configuration
- Webhook endpoint: `https://app.yourdomain.com/stripe-webhook`
- Subscribe events:
  - `checkout.session.completed`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.payment_failed`
- Rotate webhook secret when team roles change.

## 8) Smoke test plan (post deploy)
1. Register account with valid email.
2. Verify email link.
3. Upload sample CSV and ensure dashboard renders.
4. Generate/download PDF.
5. Execute Stripe test checkout and verify confirmation email.
6. Run forgot-password flow end-to-end.
