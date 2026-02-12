"""Legacy smoke tests kept compatible with current UX copy and CSRF settings."""

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
    return client.post('/login', data={'username': 'admin', 'password': 'changeme123'}, follow_redirects=True)


def test_home_page_loads(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'Law Firm Insights' in response.data


def test_feedback_form_loads(client):
    response = client.get('/feedback')
    assert response.status_code == 200


def test_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200


def test_invalid_login(client):
    response = client.post('/login', data={'username': 'wronguser', 'password': 'wrongpass'}, follow_redirects=True)
    assert b'Sign-in failed' in response.data


def test_csv_upload_requires_auth(client):
    response = client.get('/upload')
    assert response.status_code == 302


def test_invalid_csv_upload(client):
    login_admin(client)
    conn = db_connect(); cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO user_email_verification (user_id, verified_at) VALUES (1, '2024-01-01T00:00:00+00:00')")
    conn.commit(); conn.close()
    response = client.post('/upload', data={'file': (BytesIO(b'test'), 'test.txt')}, content_type='multipart/form-data', follow_redirects=True)
    assert b'Unsupported file type' in response.data


def test_csv_upload_with_valid_data(client):
    login_admin(client)
    conn = db_connect(); cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO user_email_verification (user_id, verified_at) VALUES (1, '2024-01-01T00:00:00+00:00')")
    conn.commit(); conn.close()
    csv_data = b'date,rating,review_text\n2024-01-15,5,Great legal services'
    response = client.post('/upload', data={'file': (BytesIO(csv_data), 'reviews.csv')}, content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200


def test_pdf_download_without_reviews(client):
    login_admin(client)
    response = client.get('/download-pdf', follow_redirects=True)
    assert b'No reviews found' in response.data
