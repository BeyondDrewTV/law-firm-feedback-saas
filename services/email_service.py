"""Centralized transactional email delivery with retry logic."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Optional

from flask import render_template
try:
    from flask_mail import Mail, Message
except Exception:  # noqa: BLE001
    class Message:  # simple fallback for local tests without Flask-Mail installed
        def __init__(self, subject=None, recipients=None, html=None, body=None):
            self.subject = subject
            self.recipients = recipients or []
            self.html = html
            self.body = body

    class Mail:
        def init_app(self, app):
            return None

        def send(self, msg):
            logger.info('MAIL_FALLBACK: subject=%s recipients=%s', msg.subject, msg.recipients)

mail = Mail()
logger = logging.getLogger(__name__)


@dataclass
class EmailPayload:
    to_email: str
    subject: str
    template_name: str
    context: dict


def init_mail(app):
    mail.init_app(app)


def is_valid_recipient(email: str) -> bool:
    _, parsed = parseaddr(email or "")
    return bool(parsed and "@" in parsed)


def send_templated_email(payload: EmailPayload, *, retries: int = 3, backoff_s: float = 1.5) -> bool:
    if not is_valid_recipient(payload.to_email):
        logger.warning("Skipping email; invalid recipient: %s", payload.to_email)
        return False

    html_body = render_template(f"emails/{payload.template_name}.html", **payload.context)
    text_body = render_template(f"emails/{payload.template_name}.txt", **payload.context)

    msg = Message(
        subject=payload.subject,
        recipients=[payload.to_email],
        html=html_body,
        body=text_body,
    )

    for attempt in range(1, max(1, retries) + 1):
        try:
            mail.send(msg)
            logger.info("Email sent: subject=%s to=%s", payload.subject, payload.to_email)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.exception("Email send failed on attempt %s: %s", attempt, exc)
            if attempt < retries:
                time.sleep(backoff_s * attempt)

    return False


def send_verification_email(to_email: str, verification_link: str, firm_name: str) -> bool:
    return send_templated_email(
        EmailPayload(
            to_email=to_email,
            subject="Verify your Law Firm Insights account",
            template_name="verify",
            context={"verification_link": verification_link, "firm_name": firm_name},
        )
    )


def send_password_reset_email(to_email: str, reset_link: str, firm_name: str) -> bool:
    return send_templated_email(
        EmailPayload(
            to_email=to_email,
            subject="Reset your Law Firm Insights password",
            template_name="password_reset",
            context={"reset_link": reset_link, "firm_name": firm_name},
        )
    )


def send_payment_confirmation_email(to_email: str, plan_name: str, amount: str, receipt_url: Optional[str], firm_name: str) -> bool:
    return send_templated_email(
        EmailPayload(
            to_email=to_email,
            subject="Payment confirmation - Law Firm Insights",
            template_name="payment_confirmation",
            context={
                "plan_name": plan_name,
                "amount": amount,
                "receipt_url": receipt_url,
                "firm_name": firm_name,
            },
        )
    )
