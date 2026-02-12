#!/usr/bin/env python3
"""Send subscription/trial lifecycle reminders.
Run daily from cron after exporting env vars.
"""

from __future__ import annotations

from app import app, db_connect
from services.email_service import send_templated_email, EmailPayload


def send_trial_reminders():
    conn = db_connect(); cur = conn.cursor()
    cur.execute(
        """
        SELECT email, firm_name, trial_reviews_used, trial_limit
        FROM users
        WHERE subscription_type = 'trial'
        """
    )
    rows = cur.fetchall(); conn.close()
    for email, firm_name, used, limit_ in rows:
        remaining = max(0, (limit_ or 0) - (used or 0))
        if remaining <= 1:
            send_templated_email(
                EmailPayload(
                    to_email=email,
                    subject='Your Law Firm Insights trial is almost over',
                    template_name='trial_reminder',
                    context={'firm_name': firm_name or 'Law Firm', 'remaining_reports': remaining},
                ),
                retries=app.config.get('MAIL_MAX_RETRIES', 3),
            )


def send_subscription_warnings():
    conn = db_connect(); cur = conn.cursor()
    cur.execute(
        """
        SELECT email, firm_name, subscription_type, subscription_status
        FROM users
        WHERE subscription_type IN ('monthly', 'annual')
          AND subscription_status IN ('past_due', 'canceled', 'inactive')
        """
    )
    rows = cur.fetchall(); conn.close()
    for email, firm_name, sub_type, status in rows:
        send_templated_email(
            EmailPayload(
                to_email=email,
                subject='Action needed: your Law Firm Insights subscription',
                template_name='subscription_warning',
                context={
                    'firm_name': firm_name or 'Law Firm',
                    'subscription_type': sub_type,
                    'subscription_status': status,
                },
            ),
            retries=app.config.get('MAIL_MAX_RETRIES', 3),
        )


if __name__ == '__main__':
    with app.app_context():
        send_trial_reminders()
        send_subscription_warnings()
        print('Lifecycle emails processed')
