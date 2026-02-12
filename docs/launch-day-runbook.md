# Launch Day Runbook

Use this checklist for a controlled production launch.

## 1) Environment and secrets

- [ ] `SECRET_KEY` is set to a long random value.
- [ ] Stripe live keys are configured (`STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`).
- [ ] `STRIPE_WEBHOOK_SECRET` is set from Stripe Dashboard.
- [ ] SMTP settings are configured and verified (`MAIL_*`, `MAIL_ENABLED=true`).
- [ ] `SENTRY_DSN` is configured for production error tracking.
- [ ] `SESSION_COOKIE_SECURE=true` and `SESSION_COOKIE_HTTPONLY=true` in production.

## 2) Startup and health

- [ ] Deploy latest commit.
- [ ] Verify app health endpoint returns 200:
  ```bash
  curl -fsS https://<your-domain>/health
  ```
- [ ] Verify metrics endpoint is reachable (internal/authorized as applicable):
  ```bash
  curl -fsS https://<your-domain>/metrics | head
  ```

## 3) Functional smoke test

- [ ] Submit one feedback entry through `/feedback`.
- [ ] Log in to `/login` and confirm dashboard updates.
- [ ] Upload a small valid CSV and verify records import.
- [ ] Generate a PDF report from admin dashboard.

## 4) Billing and email verification

- [ ] Complete one Stripe checkout in live-safe mode.
- [ ] Confirm webhook delivery to `/stripe-webhook` in Stripe events log.
- [ ] Trigger password reset and verify email delivery.
- [ ] Trigger account verification flow and verify email delivery.

## 5) Operations checks

- [ ] Confirm backup job is scheduled (`scripts/backup_db.py`).
- [ ] Perform one restore drill in non-production (`scripts/restore_db.sh`).
- [ ] Confirm on-call contact and rollback owner are assigned.

## 6) Post-launch (first 24 hours)

- [ ] Watch error rate and logs every 1-2 hours.
- [ ] Review payment failures and webhook retries.
- [ ] Review email bounce/deferral reports.
- [ ] Capture customer-reported issues in a launch bug list.

## Suggested go/no-go gate

Proceed when all sections 1-4 are complete and section 5 has backup + restore validated.
