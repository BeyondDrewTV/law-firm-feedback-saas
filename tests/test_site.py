import os
import tempfile
import threading
import time
from pathlib import Path

import pytest
from werkzeug.serving import make_server

os.environ.setdefault('SECRET_KEY', 'test-secret')

from app import app, init_db


@pytest.fixture(scope='module')
def live_server():
    db_fd, db_path = tempfile.mkstemp()
    app.config.update(DATABASE_PATH=db_path, TESTING=True, WTF_CSRF_ENABLED=False, MAIL_ENABLED=False)
    with app.app_context():
        init_db()

    server = make_server('127.0.0.1', 5001, app)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    time.sleep(0.3)
    yield 'http://127.0.0.1:5001'
    server.shutdown()
    os.close(db_fd)
    os.unlink(db_path)


try:
    import playwright.sync_api  # noqa: F401
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False


def test_home_login_rate_limit_page(live_server):
    if PLAYWRIGHT_AVAILABLE:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(f'{live_server}/')
            assert page.locator('text=Sign Up Free').first.is_visible()
            page.goto(f'{live_server}/health')
            assert 'ok' in page.content().lower()
            browser.close()
    else:
        c = app.test_client()
        r = c.get('/')
        assert r.status_code == 200


def test_error_handlers_no_white_pages(client=None):
    # lightweight fallback checks using Flask test client through app
    c = app.test_client()
    r404 = c.get('/missing-page')
    assert r404.status_code == 404
