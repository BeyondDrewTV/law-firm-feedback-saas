"""
Law Firm Client Feedback Analysis - Flask Application
Main application with routes for client feedback, admin CSV upload, analysis, and PDF generation
"""

import os
import csv
import json
import re
import secrets
from io import StringIO
from datetime import datetime, timedelta, timezone
from collections import Counter
from time import perf_counter
import logging
from logging.handlers import RotatingFileHandler

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
    jsonify,
)
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from flask_wtf.csrf import CSRFProtect
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    LIMITER_AVAILABLE = True
except Exception:  # noqa: BLE001
    class Limiter:
        def __init__(self, *args, **kwargs):
            pass

        def init_app(self, app):
            return None

        def limit(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def request_filter(self, fn):
            return fn

    def get_remote_address():
        return request.remote_addr if 'request' in globals() else '127.0.0.1'

    LIMITER_AVAILABLE = False

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import RequestEntityTooLarge
import sqlite3
import stripe
try:
    import bleach
except Exception:  # noqa: BLE001
    import html

    class bleach:
        @staticmethod
        def clean(value, strip=True):
            return html.escape(value or '')
from email.utils import parseaddr

from config import Config
from pdf_generator import generate_pdf_report
from services.email_service import init_mail, send_password_reset_email, send_verification_email

try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
except Exception:  # noqa: BLE001
    sentry_sdk = None

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)
app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
app.config.setdefault('SESSION_COOKIE_SECURE', not app.config.get('DEBUG', False))
from datetime import datetime

@app.context_processor
def inject_current_year():
    return {"current_year": datetime.utcnow().year}

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Initialize basic rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=app.config.get('RATELIMIT_STORAGE_URI', 'memory://'),
    strategy='fixed-window',
    default_limits=["200 per day", "50 per hour"],
)
limiter.init_app(app)

@limiter.request_filter
def _rate_limit_exempt_for_tests():
    return app.config.get('TESTING', False)

# Initialize email service
init_mail(app)

if os.environ.get('FLASK_ENV') == 'production' and not LIMITER_AVAILABLE:
    raise RuntimeError('flask-limiter must be installed in production environments')

os.makedirs(app.config.get('LOG_DIR', 'logs'), exist_ok=True)
_file_handler = RotatingFileHandler(
    os.path.join(app.config.get('LOG_DIR', 'logs'), 'app.log'),
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
)
_file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
app.logger.setLevel(app.config.get('LOG_LEVEL', 'INFO'))
if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
    app.logger.addHandler(_file_handler)

if sentry_sdk and app.config.get('SENTRY_DSN'):
    sentry_sdk.init(
        dsn=app.config.get('SENTRY_DSN'),
        integrations=[FlaskIntegration()],
        traces_sample_rate=app.config.get('SENTRY_TRACES_SAMPLE_RATE', 0.1),
    )

# Configure Stripe
stripe.api_key = app.config.get('STRIPE_SECRET_KEY')

MAX_CSV_ROWS = 5000
MAX_REVIEW_TEXT_LENGTH = 5000
MAX_FIRM_NAME_LENGTH = 120
EMAIL_REGEX = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

REQUEST_METRICS = {
    'requests_total': 0,
    'errors_total': 0,
    'latency_ms_total': 0.0,
}


@app.before_request
def _metrics_before_request():
    request._start_ts = perf_counter()


@app.after_request
def _metrics_after_request(response):
    started = getattr(request, '_start_ts', None)
    if started is not None:
        REQUEST_METRICS['requests_total'] += 1
        elapsed = (perf_counter() - started) * 1000.0
        REQUEST_METRICS['latency_ms_total'] += elapsed
        if response.status_code >= 400:
            REQUEST_METRICS['errors_total'] += 1
    return response


def db_connect():
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def is_valid_email(email):
    if not email:
        return False
    _, parsed = parseaddr(email)
    return bool(parsed and EMAIL_REGEX.match(parsed) and len(parsed) <= 254)


def validate_password_strength(password):
    if not password or len(password) < 8:
        return False, 'Password must be at least 8 characters long.'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must include at least one uppercase letter.'
    if not re.search(r'[a-z]', password):
        return False, 'Password must include at least one lowercase letter.'
    if not re.search(r'\d', password):
        return False, 'Password must include at least one number.'
    return True, ''

# Initialize Flask-Login
login_manager = LoginManager()
@login_manager.user_loader
def load_user(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute(
        '''
        SELECT
            id,
            username,
            email,
            firm_name,
            is_admin,
            stripe_customer_id,
            stripe_subscription_id,
            subscription_status,
            trial_reviews_used,
            trial_limit,
            one_time_reports_purchased,
            one_time_reports_used,
            subscription_type,
            trial_month,
            trial_review_limit_per_report
        FROM users
        WHERE id = ?
        ''',
        (user_id,),
    )
    user_data = c.fetchone()
    conn.close()

    if user_data:
        return User(
            id=user_data[0],
            username=user_data[1],
            email=user_data[2],
            firm_name=user_data[3],
            is_admin=user_data[4],
            stripe_customer_id=user_data[5],
            stripe_subscription_id=user_data[6],
            subscription_status=user_data[7],
            trial_reviews_used=user_data[8],
            trial_limit=user_data[9],
            one_time_reports_purchased=user_data[10],
            one_time_reports_used=user_data[11],
            subscription_type=user_data[12],
            trial_month=user_data[13],
            trial_review_limit_per_report=user_data[14],
        )
    return None

login_manager.init_app(app)
login_manager.login_view = 'login'

# ===== DATABASE INITIALIZATION =====

def init_db():
    """Initialize SQLite database with reviews and users tables."""
    conn = db_connect()
    c = conn.cursor()

    # Create reviews table
    c.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            rating INTEGER NOT NULL,
            review_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create users table for admin auth + pricing / usage tracking
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            firm_name TEXT,
            is_admin INTEGER DEFAULT 1,
            trial_reports_used INTEGER DEFAULT 0,
            trial_month TEXT,
            trial_review_limit_per_report INTEGER DEFAULT 50,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            subscription_status TEXT DEFAULT 'trial',
            trial_reviews_used INTEGER DEFAULT 0,
            trial_limit INTEGER DEFAULT 3,
            one_time_reports_purchased INTEGER DEFAULT 0,
            one_time_reports_used INTEGER DEFAULT 0,
            subscription_type TEXT DEFAULT 'trial'
        )
    ''')

    # Create report snapshots table
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_reviews INTEGER NOT NULL,
            avg_rating REAL NOT NULL,
            themes TEXT,
            top_praise TEXT,
            top_complaints TEXT,
            subscription_type_at_creation TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        '''
    )

    # Ownership mapping for multi-tenant review isolation without changing reviews schema
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS review_ownership (
            review_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        '''
    )

    # Password reset tokens
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS user_email_verification (
            user_id INTEGER PRIMARY KEY,
            verified_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        '''
    )

    # Migration: ensure new pricing / Stripe columns exist on older databases
    c.execute('PRAGMA table_info(users)')
    columns = [col[1] for col in c.fetchall()]

    # Core SaaS columns
    if 'email' not in columns:
        c.execute('ALTER TABLE users ADD COLUMN email TEXT')
    if 'firm_name' not in columns:
        c.execute('ALTER TABLE users ADD COLUMN firm_name TEXT')

    # Stripe-related columns
    if 'stripe_customer_id' not in columns:
        c.execute('ALTER TABLE users ADD COLUMN stripe_customer_id TEXT')
    if 'stripe_subscription_id' not in columns:
        c.execute('ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT')
    if 'subscription_status' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN subscription_status TEXT DEFAULT 'trial'")

    # Trial and one-time report tracking
    if 'trial_reviews_used' not in columns:
        c.execute('ALTER TABLE users ADD COLUMN trial_reviews_used INTEGER DEFAULT 0')
    if 'trial_limit' not in columns:
        c.execute('ALTER TABLE users ADD COLUMN trial_limit INTEGER DEFAULT 3')
    if 'one_time_reports_purchased' not in columns:
        c.execute('ALTER TABLE users ADD COLUMN one_time_reports_purchased INTEGER DEFAULT 0')
    if 'one_time_reports_used' not in columns:
        c.execute('ALTER TABLE users ADD COLUMN one_time_reports_used INTEGER DEFAULT 0')
    if 'subscription_type' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN subscription_type TEXT DEFAULT 'trial'")

    # Align any legacy trial_limit of 10 down to 3, per instructions
    c.execute('UPDATE users SET trial_limit = 3 WHERE trial_limit = 10 OR trial_limit IS NULL')

    # Create default admin user if not exists
    c.execute('SELECT id FROM users WHERE username = ?', (app.config['ADMIN_USERNAME'],))
    admin_row = c.fetchone()
    if not admin_row:
        password_hash = generate_password_hash(app.config['ADMIN_PASSWORD'])
        c.execute(
            '''INSERT INTO users
               (email, username, password_hash, is_verified, created_at)
               VALUES (?, ?, ?, 1, ?)''',
            (
                app.config['ADMIN_EMAIL'],
                app.config['ADMIN_USERNAME'],
                password_hash,
                datetime.utcnow().isoformat(),
            ),
        )
        admin_user_id = c.lastrowid
    else:
        admin_user_id = admin_row[0]

    # Ensure default admin has reasonable SaaS fields populated
    c.execute(
        '''
        UPDATE users
        SET email = COALESCE(email, ?),
            firm_name = COALESCE(firm_name, ?),
            trial_limit = COALESCE(trial_limit, ?),
            subscription_status = COALESCE(subscription_status, 'trial'),
            subscription_type = COALESCE(subscription_type, 'trial')
        WHERE username = ?
        ''',
        (
            f"{app.config['ADMIN_USERNAME']}@example.com",
            app.config['FIRM_NAME'],
            app.config['FREE_TRIAL_LIMIT'],
            app.config['ADMIN_USERNAME'],
        ),
    )

    # Performance indexes
    c.execute('CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_reports_user_id ON reports(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_reviews_created_at ON reviews(created_at)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_ownership_user_id ON review_ownership(user_id)')

    # Backfill ownership for legacy records to default admin owner
    c.execute(
        '''
        INSERT OR IGNORE INTO review_ownership (review_id, user_id)
        SELECT id, ? FROM reviews
        ''',
        (admin_user_id,),
    )

    conn.commit()
    conn.close()

# ===== USER CLASS FOR FLASK-LOGIN =====

class User(UserMixin):
    def __init__(
        self,
        id,
        username,
        is_admin=True,
        email=None,
        firm_name=None,
        stripe_customer_id=None,
        stripe_subscription_id=None,
        subscription_status='trial',
        trial_reviews_used=0,
        trial_limit=None,
        one_time_reports_purchased=0,
        one_time_reports_used=0,
        subscription_type='trial',
        trial_month=None,
        trial_review_limit_per_report=50,
    ):
        self.id = id
        self.username = username
        self.is_admin = bool(is_admin)
        # SaaS identity fields
        self.email = email
        self.firm_name = firm_name or app.config['FIRM_NAME']

        # Stripe subscription + customer fields
        self.stripe_customer_id = stripe_customer_id
        self.stripe_subscription_id = stripe_subscription_id
        self.subscription_status = subscription_status or 'trial'
        self.subscription_type = subscription_type or 'trial'

        # Usage tracking
        self.trial_reviews_used = trial_reviews_used or 0
        self.trial_limit = trial_limit or app.config['FREE_TRIAL_LIMIT']
        self.one_time_reports_purchased = one_time_reports_purchased or 0
        self.one_time_reports_used = one_time_reports_used or 0

        # Legacy fields (kept for compatibility, not used in new logic)
        self.trial_month = trial_month
        self.trial_review_limit_per_report = trial_review_limit_per_report or 50

    # ===== PRICING / ACCOUNT HELPERS =====

    def has_active_subscription(self):
        """Return True if the user has an active Stripe subscription."""
        return self.subscription_status == 'active'

    def has_unused_one_time_reports(self):
        return self.one_time_reports_purchased > self.one_time_reports_used

    def get_remaining_one_time_reports(self):
        return max(0, self.one_time_reports_purchased - self.one_time_reports_used)

    def is_trial_expired(self):
        return self.trial_reviews_used >= self.trial_limit

    def can_generate_report(self):
        """
        Tiered logic:
        Priority: subscription → one-time → trial
        """
        return (
            self.has_active_subscription()
            or self.has_unused_one_time_reports()
            or not self.is_trial_expired()
        )

    def get_account_status(self):
        """Return a dict describing the current account status for UI."""
        if self.has_active_subscription():
            return {
                'type': self.subscription_type,
                'display': f'Unlimited ({self.subscription_type.title()} Subscription)',
                'remaining': None,
            }
        elif self.has_unused_one_time_reports():
            remaining = self.get_remaining_one_time_reports()
            return {
                'type': 'onetime',
                'display': f'One-Time Reports: {remaining} remaining',
                'remaining': remaining,
            }
        else:
            remaining = max(0, self.trial_limit - self.trial_reviews_used)
            return {
                'type': 'trial',
                'display': f'Free Trial: {remaining}/{self.trial_limit} remaining',
                'remaining': remaining,
                'trial_limit': self.trial_limit,
            }

# ===== ANALYSIS FUNCTIONS =====

def analyze_reviews():
    """
    Analyze reviews in the database.
    For free trial users: cap analysis at 50 reviews.
    For paid users: analyze all reviews.
    Returns dict with stats, themes, top praise, and top complaints.
    """
    conn = db_connect()
    c = conn.cursor()
    if not current_user.is_anonymous:
        c.execute(
            '''
            SELECT r.date, r.rating, r.review_text
            FROM reviews r
            INNER JOIN review_ownership ro ON ro.review_id = r.id
            WHERE ro.user_id = ?
            ORDER BY r.created_at DESC
            ''',
            (current_user.id,),
        )
    else:
        c.execute('SELECT date, rating, review_text FROM reviews ORDER BY created_at DESC')
    reviews = [
        {'date': row[0], 'rating': row[1], 'review_text': row[2]}
        for row in c.fetchall()
    ]
    conn.close()

    if not reviews:
        return {
            'total_reviews': 0,
            'avg_rating': 0,
            'themes': {},
            'top_praise': [],
            'top_complaints': [],
            'all_reviews': []
        }

    # Apply per-plan analysis cap: free trial = first 50 reviews only
    analysis_reviews = reviews
    if not current_user.is_anonymous:
        if not current_user.has_active_subscription() and not current_user.has_unused_one_time_reports():
            # Free trial: cap analysis at 50 reviews
            analysis_reviews = reviews[:50]

    total_reviews = len(analysis_reviews)
    avg_rating = sum(r['rating'] for r in analysis_reviews) / total_reviews

    theme_keywords = {
        'Communication': ['communication', 'responsive', 'returned calls', 'kept me informed', 'updates', 'contact'],
        'Professionalism': ['professional', 'courteous', 'respectful', 'polite', 'demeanor', 'ethical'],
        'Legal Expertise': ['knowledgeable', 'experienced', 'expert', 'skilled', 'competent', 'expertise'],
        'Case Outcome': ['won', 'successful', 'settlement', 'verdict', 'result', 'outcome', 'resolved'],
        'Cost/Value': ['expensive', 'affordable', 'fees', 'billing', 'cost', 'worth it', 'value', 'price'],
        'Responsiveness': ['quick', 'slow', 'delayed', 'waiting', 'timely', 'immediately', 'promptly'],
        'Compassion': ['caring', 'understanding', 'empathetic', 'compassionate', 'listened', 'supportive'],
        'Staff Support': ['staff', 'assistant', 'paralegal', 'secretary', 'team', 'office'],
    }

    theme_counts = Counter()
    for review in analysis_reviews:
        text_lower = review['review_text'].lower()
        for theme, keywords in theme_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                theme_counts[theme] += 1

    top_praise = [r for r in analysis_reviews if r['rating'] >= 4][:10]
    top_complaints = [r for r in analysis_reviews if r['rating'] <= 2][:10]

    return {
        'total_reviews': total_reviews,
        'avg_rating': round(avg_rating, 2),
        'themes': dict(theme_counts.most_common(8)),
        'top_praise': top_praise,
        'top_complaints': top_complaints,
        'all_reviews': reviews  # keep full set for reference
    }


def _serialize_report_data(data):
    return json.dumps(data, ensure_ascii=False)


def _deserialize_report_data(data, fallback):
    if not data:
        return fallback
    try:
        return json.loads(data)
    except (TypeError, json.JSONDecodeError):
        return fallback


def save_report_snapshot(user_id):
    """Capture the current analysis view and store as a downloadable report snapshot."""
    analysis = analyze_reviews()
    if analysis['total_reviews'] == 0:
        return None

    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT subscription_type FROM users WHERE id = ?', (user_id,))
    row = c.fetchone()
    subscription_type = row[0] if row else 'trial'

    c.execute(
        '''
        INSERT INTO reports (
            user_id,
            total_reviews,
            avg_rating,
            themes,
            top_praise,
            top_complaints,
            subscription_type_at_creation
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            user_id,
            analysis['total_reviews'],
            analysis['avg_rating'],
            _serialize_report_data(analysis['themes']),
            _serialize_report_data(analysis['top_praise']),
            _serialize_report_data(analysis['top_complaints']),
            subscription_type,
        ),
    )
    report_id = c.lastrowid
    conn.commit()
    conn.close()
    return report_id


def _plan_badge_label(plan_type):
    labels = {
        'trial': 'Trial',
        'onetime': 'One-Time',
        'monthly': 'Pro Monthly',
        'annual': 'Pro Annual',
    }
    return labels.get(plan_type or 'trial', 'Trial')


def _get_current_user_state(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute(
        '''
        SELECT subscription_status, subscription_type, one_time_reports_purchased, one_time_reports_used,
               trial_reviews_used, trial_limit, stripe_customer_id
        FROM users
        WHERE id = ?
        ''',
        (user_id,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        'subscription_status': row[0],
        'subscription_type': row[1] or 'trial',
        'one_time_reports_purchased': row[2] or 0,
        'one_time_reports_used': row[3] or 0,
        'trial_reviews_used': row[4] or 0,
        'trial_limit': row[5] or app.config['FREE_TRIAL_LIMIT'],
        'stripe_customer_id': row[6],
    }


def get_report_access_type(user_id):
    state = _get_current_user_state(user_id)
    if not state:
        return 'trial'
    if state['subscription_status'] == 'active':
        return state['subscription_type']
    if state['one_time_reports_purchased'] > state['one_time_reports_used']:
        return 'onetime'
    return 'trial'


def is_email_verified(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute('SELECT verified_at FROM user_email_verification WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0])


def create_email_verification_token(user_id):
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    conn = db_connect()
    c = conn.cursor()
    c.execute(
        'INSERT INTO email_verification_tokens (user_id, token, expires_at) VALUES (?, ?, ?)',
        (user_id, token, expires_at),
    )
    c.execute('INSERT OR IGNORE INTO user_email_verification (user_id, verified_at) VALUES (?, NULL)', (user_id,))
    conn.commit()
    conn.close()
    return token

# ===== PUBLIC / MARKETING ROUTES =====

@app.route("/")
def marketing_home():
    """Marketing landing page"""
    return render_template("marketing_home.html")

@app.route("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")

@app.route("/features")
def features():
    return render_template("features.html")

@app.route("/case-studies")
def case_studies():
    return render_template("case_studies.html")

@app.route("/pricing")
def pricing():
    return render_template(
        "pricing.html",
        trial_limit=app.config['FREE_TRIAL_LIMIT'],
        onetime_price=app.config['ONETIME_REPORT_PRICE'],
        monthly_price=app.config['MONTHLY_SUBSCRIPTION_PRICE'],
        annual_price=app.config['ANNUAL_SUBSCRIPTION_PRICE'],
    )

@app.route("/privacy")
def privacy():
    """Privacy policy page"""
    return render_template("privacy.html")

@app.route("/terms")
def terms():
    """Terms of service page"""
    return render_template("terms.html")

@app.route("/security")
def security():
    """Security page"""
    return render_template("security.html")

@app.route("/app")
def index():
    """App landing page."""
    return render_template(
        "index.html",
        trial_limit=app.config['FREE_TRIAL_LIMIT'],
        onetime_price=app.config['ONETIME_REPORT_PRICE'],
        monthly_price=app.config['MONTHLY_SUBSCRIPTION_PRICE'],
        annual_price=app.config['ANNUAL_SUBSCRIPTION_PRICE'],
    )

# ===== CLIENT FEEDBACK ROUTES =====

@app.route('/feedback', methods=['GET', 'POST'])
@limiter.limit('20 per hour')
def feedback_form():
    """Client feedback submission form"""
    if request.method == 'POST':
        date = request.form.get('date') or datetime.now().strftime('%Y-%m-%d')
        rating = request.form.get('rating')
        review_text = request.form.get('review_text')

        if not rating or not review_text:
            flash('Please provide a rating and review text.', 'danger')
            return redirect(url_for('feedback_form'))

        try:
            rating = int(rating)
            if rating < 1 or rating > 5:
                raise ValueError
        except ValueError:
            flash('Rating must be between 1 and 5.', 'danger')
            return redirect(url_for('feedback_form'))

        if len(review_text) > MAX_REVIEW_TEXT_LENGTH:
            flash(f'Review text is too long. Please keep it under {MAX_REVIEW_TEXT_LENGTH} characters.', 'danger')
            return redirect(url_for('feedback_form'))

        sanitized_review_text = bleach.clean(review_text, strip=True)

        conn = db_connect()
        c = conn.cursor()
        c.execute(
            'INSERT INTO reviews (date, rating, review_text) VALUES (?, ?, ?)',
            (date, rating, sanitized_review_text)
        )
        review_id = c.lastrowid
        owner_id = current_user.id if current_user.is_authenticated else 1
        c.execute(
            'INSERT OR IGNORE INTO review_ownership (review_id, user_id) VALUES (?, ?)',
            (review_id, owner_id),
        )
        conn.commit()
        conn.close()

        flash('Thank you for your feedback!', 'success')
        return redirect(url_for('thank_you'))

    return render_template('feedback_form.html')

@app.route('/thank-you')
def thank_you():
    """Thank you page after feedback submission"""
    return render_template('thank_you.html')

# ===== ADMIN AUTH ROUTES =====


@app.route('/register', methods=['GET', 'POST'])
@limiter.limit('5 per hour')
def register():
    """Self-service registration for new firms (free trial)."""
    if current_user.is_authenticated:
        return redirect(url_for('upload'))

    if request.method == 'POST':
        errors = {}
        full_name = (request.form.get('full_name') or '').strip()
        firm_name = (request.form.get('firm_name') or app.config['FIRM_NAME']).strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not is_valid_email(email):
            errors['email'] = 'Enter a valid business email address.'
        if len(firm_name) < 2 or len(firm_name) > MAX_FIRM_NAME_LENGTH:
            errors['firm_name'] = f'Firm name must be 2-{MAX_FIRM_NAME_LENGTH} characters.'
        if len(full_name) < 2 or len(full_name) > 120:
            errors['full_name'] = 'Enter your full name (2-120 characters).'
        ok_password, password_msg = validate_password_strength(password)
        if not ok_password:
            errors['password'] = password_msg
        if password != confirm_password:
            errors['confirm_password'] = 'Passwords do not match.'

        if errors:
            flash('Please correct the highlighted fields and submit again.', 'danger')
            return render_template('register.html', errors=errors)

        sanitized_firm_name = bleach.clean(firm_name, strip=True)

        conn = db_connect()
        c = conn.cursor()

        # Use email as username for SaaS users
        c.execute(
            'SELECT id FROM users WHERE email = ? OR username = ?',
            (email, email),
        )
        existing = c.fetchone()
        if existing:
            conn.close()
            flash('An account with that email already exists. Please log in.', 'warning')
            return redirect(url_for('login'))

        password_hash = generate_password_hash(password)

        # NEW: include created_at (and keep everything else)
        from datetime import datetime
        created_at = datetime.utcnow().isoformat()

        c.execute(
            '''
            INSERT INTO users (
                username,
                email,
                firm_name,
                password_hash,
                is_admin,
                trial_reviews_used,
                trial_limit,
                subscription_status,
                subscription_type,
                created_at
            )
            VALUES (?, ?, ?, ?, 0, 0, ?, 'trial', 'trial', ?)
            ''',
            (
                email,
                email,
                sanitized_firm_name,
                password_hash,
                app.config['FREE_TRIAL_LIMIT'],
                created_at,
            ),
        )
        user_id = c.lastrowid
        conn.commit()
        conn.close()

        user = User(
            id=user_id,
            username=email,
            email=email,
            firm_name=sanitized_firm_name,
            is_admin=False,
            subscription_status='trial',
            trial_reviews_used=0,
            trial_limit=app.config['FREE_TRIAL_LIMIT'],
            one_time_reports_purchased=0,
            one_time_reports_used=0,
            subscription_type='trial',
        )
        login_user(user)
        verify_token = create_email_verification_token(user_id)
        verification_link = url_for('verify_email', token=verify_token, _external=True)
        flash('Account created successfully. Next step: upload your CSV to generate your first report snapshot.', 'success')
        if app.config.get('MAIL_ENABLED'):
            send_verification_email(email, verification_link, sanitized_firm_name)
            flash('Verification email sent. Check your inbox to activate your account.', 'info')
        else:
            flash(f'Please verify your email address to secure your account: {verification_link}', 'info')
        return redirect(url_for('upload'))

    return render_template('register.html', errors={})

@app.route('/verify-email/<token>')
@limiter.limit('20 per hour')
def verify_email(token):
    conn = db_connect()
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, user_id, expires_at, used_at
        FROM email_verification_tokens
        WHERE token = ?
        ''',
        (token,),
    )
    row = c.fetchone()

    if not row:
        conn.close()
        flash('Invalid email verification token.', 'danger')
        return redirect(url_for('login'))

    expires_at = datetime.fromisoformat(row[2])
    if row[3] or expires_at < datetime.now(timezone.utc):
        conn.close()
        flash('This verification link is expired. Please request a new one from account settings.', 'warning')
        return redirect(url_for('login'))

    now_iso = datetime.now(timezone.utc).isoformat()
    c.execute('UPDATE email_verification_tokens SET used_at = ? WHERE id = ?', (now_iso, row[0]))
    c.execute(
        'INSERT INTO user_email_verification (user_id, verified_at) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET verified_at=excluded.verified_at',
        (row[1], now_iso),
    )
    conn.commit()
    conn.close()
    flash('Email verified successfully. Your account is now fully active.', 'success')
    return redirect(url_for('dashboard' if current_user.is_authenticated else 'login'))

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per 15 minutes')
def login():
    """Login page for firm administrators and trial accounts."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # Identifier may be email address or legacy username
        identifier = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        if not identifier or not password:
            flash('Email and password are required to sign in.', 'danger')
            return redirect(url_for('login'))

        conn = db_connect()
        c = conn.cursor()
        c.execute(
            'SELECT id, password_hash FROM users WHERE email = ? OR username = ?',
            (identifier, identifier),
        )
        user_data = c.fetchone()
        conn.close()

        if user_data and check_password_hash(user_data[1], password):
            # Load full user record via the user loader for consistency
            user = load_user(user_data[0])
            if user:
                login_user(user)
                flash('You are now signed in. Next step: upload a CSV or visit your dashboard for recent reports.', 'success')
                return redirect(url_for('dashboard'))

        flash('Sign-in failed. Check your email/password and try again. If you forgot your password, contact support.', 'danger')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit('5 per hour')
def forgot_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        generic_msg = 'If that email exists, a reset link has been generated. Contact support to deliver it securely.'
        if not is_valid_email(email):
            flash('Enter a valid email address to request a password reset.', 'danger')
            return render_template('forgot_password.html')

        conn = db_connect()
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE email = ? OR username = ?', (email, email))
        row = c.fetchone()
        if row:
            token = secrets.token_urlsafe(32)
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            c.execute(
                'INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)',
                (row[0], token, expires_at),
            )
            conn.commit()
            reset_link = url_for('reset_password', token=token, _external=True)
            if app.config.get('MAIL_ENABLED'):
                send_password_reset_email(email, reset_link, app.config.get('FIRM_NAME', 'Law Firm'))
                flash('If that email exists, a password reset link has been sent.', 'info')
            else:
                flash(f'{generic_msg} Reset link: {reset_link}', 'info')
        else:
            flash(generic_msg, 'info')
        conn.close()
        return redirect(url_for('login'))

    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
@limiter.limit('10 per hour')
def reset_password(token):
    conn = db_connect()
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, user_id, expires_at, used_at
        FROM password_reset_tokens
        WHERE token = ?
        ''',
        (token,),
    )
    token_row = c.fetchone()

    if not token_row:
        conn.close()
        flash('Invalid password reset token. Request a new one.', 'danger')
        return redirect(url_for('forgot_password'))

    expires_at = datetime.fromisoformat(token_row[2])
    if token_row[3] or expires_at < datetime.now(timezone.utc):
        conn.close()
        flash('This reset token has expired. Please request a new reset link.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        ok_password, password_msg = validate_password_strength(password)
        if not ok_password:
            conn.close()
            flash(password_msg, 'danger')
            return render_template('reset_password.html', token=token)
        if password != confirm_password:
            conn.close()
            flash('Passwords do not match. Please re-enter both fields.', 'danger')
            return render_template('reset_password.html', token=token)

        password_hash = generate_password_hash(password)
        c.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, token_row[1]))
        c.execute('UPDATE password_reset_tokens SET used_at = ? WHERE id = ?', (datetime.now(timezone.utc).isoformat(), token_row[0]))
        conn.commit()
        conn.close()
        flash('Password reset successful. You can now sign in with your new password.', 'success')
        return redirect(url_for('login'))

    conn.close()
    return render_template('reset_password.html', token=token)

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    """Admin logout"""
    logout_user()
    flash('You have been signed out.', 'info')
    return redirect(url_for('marketing_home'))


@app.route('/stripe-webhook', methods=['POST'])
@csrf.exempt
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = app.config.get('STRIPE_WEBHOOK_SECRET')

    if not webhook_secret:
        return '', 204

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception:
        return '', 400

    event_type = event.get('type', '')
    obj = event.get('data', {}).get('object', {})

    if event_type in ('customer.subscription.deleted', 'customer.subscription.updated'):
        subscription_id = obj.get('id')
        status = obj.get('status')
        if subscription_id:
            conn = db_connect()
            c = conn.cursor()
            if status in ('canceled', 'unpaid', 'incomplete_expired', 'past_due'):
                c.execute(
                    '''
                    UPDATE users
                    SET subscription_status = 'canceled'
                    WHERE stripe_subscription_id = ?
                    ''',
                    (subscription_id,),
                )
            elif status == 'active':
                c.execute(
                    '''
                    UPDATE users
                    SET subscription_status = 'active'
                    WHERE stripe_subscription_id = ?
                    ''',
                    (subscription_id,),
                )
            conn.commit()
            conn.close()

    return '', 200

# ===== ADMIN ROUTES =====

@app.route('/dashboard')
@login_required
def dashboard():
    """Admin dashboard with overview and account status."""
    analysis = analyze_reviews()
    account_status = current_user.get_account_status()

    # For backward-compatible UI hints on the dashboard template
    reports_remaining = (
        account_status.get('remaining')
        if account_status.get('type') == 'trial'
        else None
    )
    upgrade_needed = account_status.get('type') == 'trial' and account_status.get('remaining') == 0
    limited = account_status.get('type') == 'trial'

    # Convert themes dict to list of dicts for UI (name, mentions, percentage)
    themes_dict = analysis['themes']
    total_mentions = sum(themes_dict.values()) or 1
    dashboard_themes = [
        {
            'name': name,
            'mentions': int(mentions),
            'percentage': (int(mentions) / total_mentions) * 100.0,
        }
        for name, mentions in themes_dict.items()
    ]

    conn = db_connect()
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, created_at, total_reviews, subscription_type_at_creation
        FROM reports
        WHERE user_id = ?
        ORDER BY created_at DESC
        ''',
        (current_user.id,),
    )
    report_rows = c.fetchall()
    conn.close()

    reports_history = []
    for row in report_rows:
        try:
            dt = datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S')
            formatted_date = dt.strftime('%b %d, %Y at %I:%M %p')
        except Exception:
            formatted_date = row[1]

        reports_history.append(
            {
                'id': row[0],
                'created_at': formatted_date,
                'total_reviews': row[2],
                'subscription_type_at_creation': row[3],
                'plan_label': _plan_badge_label(row[3]),
            }
        )

    return render_template(
        'report_results.html',
        total_reviews=analysis['total_reviews'],
        avg_rating=analysis['avg_rating'],
        themes=dashboard_themes,
        top_praise=analysis['top_praise'],
        top_complaints=analysis['top_complaints'],
        account_status=account_status,
        reports_remaining=reports_remaining,
        upgrade_needed=upgrade_needed,
        limited=limited,
        reports_history=reports_history,
    )


@app.route('/clear-reviews', methods=['POST'])
@login_required
def clear_reviews():
    conn = db_connect()
    c = conn.cursor()
    c.execute('DELETE FROM reviews WHERE id IN (SELECT review_id FROM review_ownership WHERE user_id = ?)', (current_user.id,))
    conn.commit()
    conn.close()
    flash('All reviews were cleared successfully. Next step: upload a new CSV to generate fresh insights.', 'success')
    return redirect(url_for('dashboard'))

# ===== STRIPE PRICING ROUTES =====

@app.route('/buy-one-time')
@login_required
def buy_one_time():
    """One-time report purchase page."""
    return render_template(
        'buy-one-time.html',
        price=app.config['ONETIME_REPORT_PRICE'],
        stripe_publishable_key=app.config['STRIPE_PUBLISHABLE_KEY'],
    )

@app.route('/create-onetime-checkout', methods=['POST'])
@login_required
@limiter.limit('10 per hour')
def create_onetime_checkout():
    """Create Stripe Checkout session for one-time report purchase."""
    try:
        # Ensure Stripe customer exists
        if not current_user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_user.email or current_user.username,
                metadata={'user_id': current_user.id},
            )
            conn = db_connect()
            c = conn.cursor()
            c.execute(
                'UPDATE users SET stripe_customer_id = ? WHERE id = ?',
                (customer.id, current_user.id),
            )
            conn.commit()
            conn.close()
            customer_id = customer.id
        else:
            customer_id = current_user.stripe_customer_id

        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[
                {
                    'price': app.config['STRIPE_PRICE_ID_ONETIME'],
                    'quantity': 1,
                }
            ],
            mode='payment',  # ONE-TIME
            success_url=url_for('onetime_success', _external=True)
            + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('buy_one_time', _external=True),
        )

        return redirect(checkout_session.url, code=303)
    except Exception:
        flash('We were unable to start the payment session. Please try again or contact support.', 'danger')
        return redirect(url_for('buy_one_time'))

@app.route('/onetime-success')
@login_required
@limiter.limit('20 per hour')
def onetime_success():
    """Handle successful one-time payment and grant a report credit."""
    session_id = request.args.get('session_id')
    if not session_id:
        flash('The payment session could not be found. Please start a new payment.', 'danger')
        return redirect(url_for('buy_one_time'))

    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)

        if checkout_session.payment_status == 'paid' and str(checkout_session.customer) == str(current_user.stripe_customer_id):
            conn = db_connect()
            c = conn.cursor()
            c.execute(
                '''
                UPDATE users
                SET one_time_reports_purchased = one_time_reports_purchased + 1
                WHERE id = ?
                ''',
                (current_user.id,),
            )
            conn.commit()
            conn.close()

            flash('Payment was successful. One report credit has been added to your account.', 'success')
            return redirect(url_for('upload'))
        else:
            flash('The payment was not completed. No charges have been applied.', 'warning')
            return redirect(url_for('buy_one_time'))
    except Exception:
        flash('We were unable to confirm the payment. Please contact support if the issue persists.', 'danger')
        return redirect(url_for('buy_one_time'))

@app.route('/subscribe')
@login_required
def subscribe():
    """Subscription selection page (monthly / annual)."""
    return render_template(
        'subscribe.html',
        monthly_price=app.config['MONTHLY_SUBSCRIPTION_PRICE'],
        annual_price=app.config['ANNUAL_SUBSCRIPTION_PRICE'],
        stripe_publishable_key=app.config['STRIPE_PUBLISHABLE_KEY'],
    )

@app.route('/create-subscription-checkout', methods=['POST'])
@login_required
@limiter.limit('10 per hour')
def create_subscription_checkout():
    """Create Stripe Checkout session for recurring subscription."""
    plan = request.form.get('plan', 'monthly')  # 'monthly' or 'annual'

    # Select the correct Price ID
    if plan == 'annual':
        price_id = app.config['STRIPE_PRICE_ID_ANNUAL']
    else:
        price_id = app.config['STRIPE_PRICE_ID_MONTHLY']

    try:
        if not current_user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_user.email or current_user.username,
                metadata={'user_id': current_user.id},
            )
            conn = db_connect()
            c = conn.cursor()
            c.execute(
                'UPDATE users SET stripe_customer_id = ? WHERE id = ?',
                (customer.id, current_user.id),
            )
            conn.commit()
            conn.close()
            customer_id = customer.id
        else:
            customer_id = current_user.stripe_customer_id

        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[
                {
                    'price': price_id,
                    'quantity': 1,
                }
            ],
            mode='subscription',  # RECURRING
            success_url=url_for('subscription_success', _external=True)
            + f'?session_id={{CHECKOUT_SESSION_ID}}&plan={plan}',
            cancel_url=url_for('subscribe', _external=True),
        )

        return redirect(checkout_session.url, code=303)
    except Exception:
        flash('We were unable to start the subscription session. Please try again or contact support.', 'danger')
        return redirect(url_for('subscribe'))

@app.route('/subscription-success')
@login_required
@limiter.limit('20 per hour')
def subscription_success():
    """Handle successful subscription and mark account as active."""
    session_id = request.args.get('session_id')
    plan = request.args.get('plan', 'monthly')

    if not session_id:
        flash('The subscription session could not be found. Please start a new subscription.', 'danger')
        return redirect(url_for('subscribe'))

    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        if str(checkout_session.customer) != str(current_user.stripe_customer_id):
            flash('Subscription verification failed due to customer mismatch. Please contact support.', 'danger')
            return redirect(url_for('subscribe'))

        conn = db_connect()
        c = conn.cursor()
        c.execute(
            '''
            UPDATE users
            SET stripe_subscription_id = ?,
                subscription_status = 'active',
                subscription_type = ?
            WHERE id = ?
            ''',
            (checkout_session.subscription, plan, current_user.id),
        )
        conn.commit()
        conn.close()

        flash('Your subscription is now active. You can generate unlimited reports.', 'success')
        return redirect(url_for('upload'))
    except Exception:
        flash('We were unable to confirm the subscription. Please contact support if the issue persists.', 'danger')
        return redirect(url_for('subscribe'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
@limiter.limit('15 per hour')
def upload():
    """CSV upload page for bulk review import with tiered limits."""
    account_status = current_user.get_account_status()
    can_upload = current_user.can_generate_report()

    if request.method == 'POST':
        if not is_email_verified(current_user.id):
            flash('Please verify your email before uploading data. Check your verification link from registration.', 'warning')
            return redirect(url_for('account'))

        if not can_upload:
            flash('You have no remaining report credits. Upgrade or purchase a one-time report to generate new snapshots.', 'warning')
            return redirect(url_for('pricing'))

        if 'file' not in request.files:
            flash('No CSV file was detected in the upload request. Please choose a file and try again.', 'danger')
            return redirect(url_for('upload'))

        file = request.files['file']
        if file.filename == '':
            flash('No file selected. Choose a CSV file with date, rating, and review_text columns.', 'danger')
            return redirect(url_for('upload'))

        if not file.filename.lower().endswith('.csv'):
            flash('Unsupported file type. Please upload a .csv file and try again.', 'danger')
            return redirect(url_for('upload'))

        try:
            csv_content = file.read().decode('utf-8')
            csv_file = StringIO(csv_content)
            reader = csv.DictReader(csv_file)

            if not reader.fieldnames or not all(col in reader.fieldnames for col in ['date', 'rating', 'review_text']):
                flash('CSV header mismatch. Include exactly: date, rating, review_text. Then re-upload your file.', 'danger')
                return redirect(url_for('upload'))

            conn = db_connect()
            c = conn.cursor()

            count = 0
            row_count = 0
            for row in reader:
                row_count += 1
                if row_count > MAX_CSV_ROWS:
                    conn.close()
                    flash(f'CSV has too many rows. Maximum allowed is {MAX_CSV_ROWS}.', 'danger')
                    return redirect(url_for('upload'))
                if row['date'] and row['rating'] and row['review_text']:
                    try:
                        rating = int(row['rating'])
                        if 1 <= rating <= 5:
                            cleaned_text = bleach.clean(row['review_text'], strip=True)
                            if len(cleaned_text) > MAX_REVIEW_TEXT_LENGTH:
                                continue
                            c.execute(
                                'INSERT INTO reviews (date, rating, review_text) VALUES (?, ?, ?)',
                                (row['date'], rating, cleaned_text)
                            )
                            review_id = c.lastrowid
                            c.execute(
                                'INSERT OR IGNORE INTO review_ownership (review_id, user_id) VALUES (?, ?)',
                                (review_id, current_user.id),
                            )
                            count += 1
                    except ValueError:
                        continue

            if count == 0:
                conn.close()
                flash('No valid review rows were found. Fix the CSV values and upload again.', 'warning')
                return redirect(url_for('upload'))

            conn.commit()
            conn.close()

            snapshot_report_id = save_report_snapshot(current_user.id)

            conn = db_connect()
            c = conn.cursor()

            # Update usage counters only after report snapshot is saved
            access_type = get_report_access_type(current_user.id)
            if access_type in ('monthly', 'annual'):
                report_type = access_type
            elif access_type == 'onetime':
                report_type = 'onetime'
                c.execute(
                    '''
                    UPDATE users
                    SET one_time_reports_used = one_time_reports_used + 1
                    WHERE id = ?
                    ''',
                    (current_user.id,),
                )
            else:
                report_type = 'trial'
                c.execute(
                    '''
                    UPDATE users
                    SET trial_reviews_used = trial_reviews_used + 1
                    WHERE id = ?
                    ''',
                    (current_user.id,),
                )

            conn.commit()
            conn.close()

            if not snapshot_report_id:
                flash('Upload succeeded, but no snapshot was created because no analyzable reviews were found.', 'warning')
                return redirect(url_for('dashboard'))

            flash(
                f'Success! Imported {count} reviews and saved report snapshot #{snapshot_report_id}. '
                'Next step: open your dashboard to download this report anytime.',
                'success',
            )
            return redirect(url_for('dashboard'))

        except Exception:
            flash('We could not process that CSV upload. Please verify the file format and try again.', 'danger')
            return redirect(url_for('upload'))

    return render_template(
        'upload.html',
        account_status=account_status,
        can_upload=can_upload,
    )

@app.route('/download-pdf')
@login_required
@limiter.limit('25 per hour')
def download_pdf():
    """Generate and download PDF report based on user's plan."""
    analysis = analyze_reviews()

    if analysis['total_reviews'] == 0:
        flash('No reviews found. Upload a CSV to get started, then try generating a PDF again.', 'warning')
        return redirect(url_for('dashboard'))

    # Enrich themes with percentage values for the PDF
    themes_dict = analysis['themes']
    total_mentions = sum(themes_dict.values()) or 1

    enriched_themes = []
    for name, mentions in themes_dict.items():
        enriched_themes.append({
            'name': name,
            'mentions': int(mentions),
            'percentage': (int(mentions) / total_mentions) * 100.0,
        })

    # Determine paid status and subscription type for implementation plans
    access_type = get_report_access_type(current_user.id)
    is_paid_user = access_type in ('monthly', 'annual', 'onetime')
    subscription_type = access_type

    pdf_buffer = generate_pdf_report(
        firm_name=current_user.firm_name or app.config['FIRM_NAME'],
        total_reviews=analysis['total_reviews'],
        avg_rating=analysis['avg_rating'],
        themes=enriched_themes,
        top_praise=analysis['top_praise'],
        top_complaints=analysis['top_complaints'],
        is_paid_user=is_paid_user,
        subscription_type=subscription_type,
        analysis_period=None,
    )

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f'feedback_report_{datetime.now().strftime("%Y%m%d")}.pdf',
        mimetype='application/pdf'
    )


@app.route('/download-report/<int:report_id>')
@login_required
@limiter.limit('25 per hour')
def download_report(report_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute(
        '''
        SELECT id, user_id, created_at, total_reviews, avg_rating, themes, top_praise, top_complaints
        FROM reports
        WHERE id = ?
        ''',
        (report_id,),
    )
    report = c.fetchone()
    conn.close()

    if not report or report[1] != current_user.id:
        flash('That report was not found for your account. Please choose a report from your history list.', 'danger')
        return redirect(url_for('dashboard'))

    raw_themes = _deserialize_report_data(report[5], {})
    themes = []
    total_mentions = sum(raw_themes.values()) or 1
    for name, mentions in raw_themes.items():
        themes.append(
            {
                'name': name,
                'mentions': int(mentions),
                'percentage': (int(mentions) / total_mentions) * 100.0,
            }
        )

    top_praise = _deserialize_report_data(report[6], [])
    top_complaints = _deserialize_report_data(report[7], [])
    access_type = get_report_access_type(current_user.id)
    is_paid_user = access_type in ('monthly', 'annual', 'onetime')
    subscription_type = access_type

    pdf_buffer = generate_pdf_report(
        firm_name=current_user.firm_name or app.config['FIRM_NAME'],
        total_reviews=report[3],
        avg_rating=report[4],
        themes=themes,
        top_praise=top_praise,
        top_complaints=top_complaints,
        is_paid_user=is_paid_user,
        subscription_type=subscription_type,
        analysis_period=None,
    )

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f'feedback_report_snapshot_{report_id}.pdf',
        mimetype='application/pdf',
    )


@app.route('/account')
@login_required
def account():
    account_status = current_user.get_account_status()
    portal_url = None
    if current_user.stripe_customer_id and current_user.has_active_subscription():
        try:
            session = stripe.billing_portal.Session.create(
                customer=current_user.stripe_customer_id,
                return_url=url_for('account', _external=True),
            )
            portal_url = session.url
        except Exception:
            portal_url = None

    usage = {
        'trial_used': current_user.trial_reviews_used,
        'trial_limit': current_user.trial_limit,
        'trial_remaining': max(0, current_user.trial_limit - current_user.trial_reviews_used),
        'one_time_purchased': current_user.one_time_reports_purchased,
        'one_time_used': current_user.one_time_reports_used,
        'one_time_remaining': current_user.get_remaining_one_time_reports(),
    }

    return render_template(
        'account.html',
        account_status=account_status,
        usage=usage,
        current_plan=_plan_badge_label(current_user.subscription_type),
        portal_url=portal_url,
        email_verified=is_email_verified(current_user.id),
    )


@app.route('/export-data')
@login_required
@limiter.limit('5 per hour')
def export_data():
    conn = db_connect()
    c = conn.cursor()
    c.execute(
        '''
        SELECT r.date, r.rating, r.review_text
        FROM reviews r
        INNER JOIN review_ownership ro ON ro.review_id = r.id
        WHERE ro.user_id = ?
        ORDER BY r.created_at DESC
        ''',
        (current_user.id,),
    )
    rows = c.fetchall()
    conn.close()

    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(['date', 'rating', 'review_text'])
    for row in rows:
        writer.writerow(row)

    mem = StringIO(csv_buffer.getvalue())
    from io import BytesIO
    out = BytesIO(mem.getvalue().encode('utf-8'))
    out.seek(0)
    return send_file(
        out,
        as_attachment=True,
        download_name=f'user_data_export_{current_user.id}.csv',
        mimetype='text/csv',
    )

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'law-firm-feedback-saas'}), 200


@app.route('/metrics')
def metrics():
    total = REQUEST_METRICS['requests_total']
    avg_latency = (REQUEST_METRICS['latency_ms_total'] / total) if total else 0.0
    return jsonify({
        'requests_total': total,
        'errors_total': REQUEST_METRICS['errors_total'],
        'avg_latency_ms': round(avg_latency, 2),
    }), 200


# ===== ERROR HANDLERS =====


@app.errorhandler(429)
def rate_limited(error):
    reset_ts = int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp())
    response = render_template('errors/rate_limit.html', reset_timestamp=reset_ts, wait_minutes=15)
    resp = app.make_response((response, 429))
    resp.headers['X-RateLimit-Reset'] = str(reset_ts)
    return resp


@app.errorhandler(404)
def not_found(error):
    return render_template('marketing_home.html'), 404

@app.errorhandler(500)
def internal_error(error):
    flash('An unexpected server error occurred. Please retry in a moment. If it persists, contact support.', 'danger')
    return render_template('marketing_home.html'), 500

@app.errorhandler(RequestEntityTooLarge)
def file_too_large(error):
    flash('Upload failed: file exceeds the 10 MB limit. Compress or split the CSV and try again.', 'danger')
    return redirect(request.referrer or url_for('upload')), 413

# ===== APPLICATION ENTRY POINT =====

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=app.config['DEBUG'])
