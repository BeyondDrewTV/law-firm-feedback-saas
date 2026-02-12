#!/usr/bin/env python3
"""Backup SQLite DB locally and optionally upload to S3."""

from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

try:
    import boto3
except Exception:  # noqa: BLE001
    boto3 = None


def backup_database():
    db_path = Path(os.environ.get('DATABASE_PATH', 'feedback.db'))
    backup_dir = Path(os.environ.get('BACKUP_DIR', 'backups'))
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    raw_backup = backup_dir / f'feedback_{ts}.sqlite3'
    gz_backup = Path(str(raw_backup) + '.gz')

    conn = sqlite3.connect(str(db_path))
    out = sqlite3.connect(str(raw_backup))
    with out:
        conn.backup(out)
    out.close()
    conn.close()

    with open(raw_backup, 'rb') as src, gzip.open(gz_backup, 'wb') as dst:
        shutil.copyfileobj(src, dst)
    raw_backup.unlink(missing_ok=True)

    bucket = os.environ.get('S3_BACKUP_BUCKET')
    if bucket and boto3:
        s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION'))
        s3.upload_file(str(gz_backup), bucket, gz_backup.name)

    print(f'backup_created={gz_backup}')


if __name__ == '__main__':
    backup_database()
