import os
import tempfile
from io import BytesIO

import pytest

os.environ.setdefault('SECRET_KEY', 'test-secret')

from app import app, db_connect, init_db


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp()
    app.config.update(
        DATABASE_PATH=db_path,
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        MAIL_ENABLED=False,
    )
    with app.app_context():
        init_db()
    with app.test_client() as c:
        yield c
    os.close(db_fd)
    os.unlink(db_path)


def login_admin(client):
    return client.post('/login', data={'username': 'admin', 'password': 'change-this-admin-password'}, follow_redirects=True)


def test_upload_requires_login(client):
    resp = client.get('/upload')
    assert resp.status_code == 302


def test_upload_blocked_until_verified(client):
    client.post('/register', data={
        'full_name': 'Lawyer Name',
        'firm_name': 'Firm Name',
        'email': 'lawyer@example.com',
        'password': 'StrongPass1',
        'confirm_password': 'StrongPass1',
    }, follow_redirects=True)
    client.post('/login', data={'username': 'lawyer@example.com', 'password': 'StrongPass1'}, follow_redirects=True)

    payload = b"date,rating,review_text\n2024-01-01,5,Great"
    resp = client.post('/upload', data={'file': (BytesIO(payload), 'reviews.csv')}, content_type='multipart/form-data', follow_redirects=True)
    assert b'Please verify your email before uploading data' in resp.data


def test_upload_success_after_verification(client):
    login_admin(client)
    conn = db_connect()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO user_email_verification (user_id, verified_at) VALUES (1, '2024-01-01T00:00:00+00:00')")
    conn.commit(); conn.close()

    payload = b"date,rating,review_text\n2024-01-01,5,Great service"
    resp = client.post('/upload', data={'file': (BytesIO(payload), 'reviews.csv')}, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
