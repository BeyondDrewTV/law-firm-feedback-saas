#!/usr/bin/env python3
"""Admin maintenance CLI for safe account operations."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone

from config import Config


def db_connect():
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def grant_credits(email: str, count: int):
    conn = db_connect(); cur = conn.cursor()
    cur.execute(
        """
        UPDATE users
        SET one_time_reports_purchased = COALESCE(one_time_reports_purchased, 0) + ?
        WHERE email = ?
        """,
        (count, email),
    )
    conn.commit(); changed = cur.rowcount; conn.close()
    print(f"updated_rows={changed}")


def set_subscription(email: str, sub_type: str, status: str):
    conn = db_connect(); cur = conn.cursor()
    cur.execute(
        "UPDATE users SET subscription_type = ?, subscription_status = ? WHERE email = ?",
        (sub_type, status, email),
    )
    conn.commit(); changed = cur.rowcount; conn.close()
    print(f"updated_rows={changed}")


def verify_email(email: str):
    conn = db_connect(); cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    if not row:
        conn.close()
        print("user_not_found")
        return
    user_id = row[0]
    cur.execute(
        "INSERT OR REPLACE INTO user_email_verification (user_id, verified_at) VALUES (?, ?)",
        (user_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit(); conn.close()
    print("verified")


def main():
    parser = argparse.ArgumentParser(description='Law Firm Insights admin utility')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p1 = sub.add_parser('grant-credits')
    p1.add_argument('--email', required=True)
    p1.add_argument('--count', type=int, required=True)

    p2 = sub.add_parser('set-subscription')
    p2.add_argument('--email', required=True)
    p2.add_argument('--type', required=True, choices=['trial', 'one-time', 'monthly', 'annual'])
    p2.add_argument('--status', required=True, choices=['trial', 'active', 'inactive', 'canceled', 'past_due'])

    p3 = sub.add_parser('verify-email')
    p3.add_argument('--email', required=True)

    args = parser.parse_args()

    if args.cmd == 'grant-credits':
        grant_credits(args.email, args.count)
    elif args.cmd == 'set-subscription':
        set_subscription(args.email, args.type, args.status)
    elif args.cmd == 'verify-email':
        verify_email(args.email)


if __name__ == '__main__':
    main()
