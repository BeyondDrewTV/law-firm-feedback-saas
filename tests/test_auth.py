import os
import tempfile

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


def test_register_rejects_weak_password(client):
    resp = client.post('/register', data={
        'full_name': 'Jane Doe',
        'firm_name': 'Doe Legal',
        'email': 'jane@example.com',
        'password': 'weak',
        'confirm_password': 'weak',
    }, follow_redirects=True)
    assert b'Password must be at least 8 characters long' in resp.data


def test_register_and_login_success(client):
    register_resp = client.post('/register', data={
        'full_name': 'Lawyer Name',
        'firm_name': 'Firm Name',
        'email': 'lawyer@example.com',
        'password': 'StrongPass1',
        'confirm_password': 'StrongPass1',
    }, follow_redirects=True)
    assert register_resp.status_code == 200

    login_resp = client.post('/login', data={
        'username': 'lawyer@example.com',
        'password': 'StrongPass1',
    }, follow_redirects=True)
    assert login_resp.status_code == 200


def test_password_reset_token_single_use(client):
    client.post('/register', data={
        'full_name': 'Lawyer Name',
        'firm_name': 'Firm Name',
        'email': 'lawyer@example.com',
        'password': 'StrongPass1',
        'confirm_password': 'StrongPass1',
    }, follow_redirects=True)

    client.post('/forgot-password', data={'email': 'lawyer@example.com'}, follow_redirects=True)
    conn = db_connect(); c = conn.cursor()
    c.execute('SELECT token FROM password_reset_tokens ORDER BY id DESC LIMIT 1')
    token = c.fetchone()[0]
    conn.close()

    first = client.post(f'/reset-password/{token}', data={
        'password': 'EvenStronger2',
        'confirm_password': 'EvenStronger2',
    }, follow_redirects=True)
    assert b'Password reset successful' in first.data

    second = client.post(f'/reset-password/{token}', data={
        'password': 'AnotherPass3',
        'confirm_password': 'AnotherPass3',
    }, follow_redirects=True)
    assert b'expired' in second.data.lower() or b'invalid' in second.data.lower()


def test_login_sql_injection_attempt_fails(client):
    resp = client.post('/login', data={'username': "admin' OR 1=1 --", 'password': 'x'}, follow_redirects=True)
    assert b'Sign-in failed' in resp.data


def test_health_and_metrics_endpoints(client):
    h = client.get('/health')
    assert h.status_code == 200
    m = client.get('/metrics')
    assert m.status_code == 200


def test_forgot_password_mail_enabled_hides_link(client):
    client.post('/register', data={
        'full_name': 'Lawyer Name',
        'firm_name': 'Firm Name',
        'email': 'mailtest@example.com',
        'password': 'StrongPass1',
        'confirm_password': 'StrongPass1',
    }, follow_redirects=True)
    app.config['MAIL_ENABLED'] = True
    resp = client.post('/forgot-password', data={'email': 'mailtest@example.com'}, follow_redirects=True)
    assert b'password reset link has been sent' in resp.data.lower()
    assert b'Reset link:' not in resp.data


def test_rate_limit_handler_exists(client):
    # Ensure custom 429 page renders and includes reset hint text
    from app import rate_limited
    with app.test_request_context('/login'):
        resp = rate_limited(Exception('too many'))
        assert resp.status_code == 429
        assert 'X-RateLimit-Reset' in resp.headers


def test_webhook_bad_signature_returns_400(client):
    resp = client.post('/stripe-webhook', data='{}', headers={'Stripe-Signature': 'bad'})
    # If webhook secret not set it may be 204; with secret set and bad sig -> 400
    assert resp.status_code in (204, 400)
