# Backup & Disaster Recovery

## Automated backup job
Run daily at 02:15 UTC:

```cron
15 2 * * * cd /path/to/repo && /usr/bin/env bash scripts/backup_db.sh >> logs/backup.log 2>&1
```

## S3 backup configuration
- Set `S3_BACKUP_BUCKET` in `.env`.
- Ensure IAM user has `s3:PutObject` and `s3:ListBucket` on the backup bucket.
- Enable bucket versioning and lifecycle retention.

## One-click restore procedure
```bash
scripts/restore_db.sh backups/feedback_YYYYMMDDTHHMMSSZ.sqlite3.gz
```
Then restart Gunicorn and run smoke tests.

## Stripe webhook outage recovery
1. Confirm `/stripe-webhook` health.
2. Re-send failed events from Stripe dashboard.
3. Reconcile local subscription state with Stripe API for impacted users.

## Payment disputes playbook
- Freeze premium access for disputed invoices.
- Capture audit data (webhook logs, Stripe event IDs, account history).
- Coordinate with support/legal for response.

## Emergency rollback
1. Deploy previous release artifact.
2. Restore pre-deploy DB backup.
3. Validate auth, upload, report download, and billing flows.
4. Post incident note and corrective actions.
