# GDPR + Legal Compliance Checklist

## Data handling
- [ ] Document legal basis for data processing (contract/legitimate interest/consent).
- [ ] Maintain data inventory: user profile, reviews, billing metadata, logs.
- [ ] Publish retention policy and deletion policy.

## User rights
- [ ] Right of access (`/export-data` available).
- [ ] Right to deletion (implement account deletion workflow with irreversible purge).
- [ ] Right to rectification (support process to update user profile metadata).
- [ ] Right to portability (CSV export from `/export-data`).

## Security controls
- [ ] TLS in transit and encrypted backups at rest.
- [ ] Least-privilege access for production secrets.
- [ ] Audit log for manual admin changes.
- [ ] Incident response policy with customer notification timeline.

## Third-party processors
- [ ] Stripe listed in Privacy Policy.
- [ ] Email provider (SendGrid/Mailgun) listed.
- [ ] Hosting/CDN providers listed.

## Required legal pages
- [ ] Privacy Policy published and linked from footer.
- [ ] Terms of Service published and linked from footer.
- [ ] Cookie consent banner enabled when analytics cookies are used.

## Data retention policy
- Billing and subscription records: 7 years.
- Operational logs: 30-90 days.
- User-generated review text: retained until account deletion or policy cutoff.
