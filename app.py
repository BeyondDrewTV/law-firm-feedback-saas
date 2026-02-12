"""
Law Firm Client Feedback Analysis - Flask Application
Main application with routes for client feedback, admin CSV upload, analysis, and PDF generation
"""

import os
import csv
import json
from io import StringIO
from datetime import datetime
from collections import Counter

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
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
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import RequestEntityTooLarge
import sqlite3
import stripe
import bleach

from config import Config
from pdf_generator import generate_pdf_report

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Initialize basic rate limiting
limiter = Limiter(get_remote_address, app=app, default_limits=[])

# Configure Stripe
stripe.api_key = app.config.get('STRIPE_SECRET_KEY')

# Initialize Flask-Login
login_manager = LoginManager()
@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
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
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
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
            username TEXT UNIQUE,
            email TEXT UNIQUE,
            firm_name TEXT,
            password_hash TEXT NOT NULL,
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
    if not c.fetchone():
        password_hash = generate_password_hash(app.config['ADMIN_PASSWORD'])
        c.execute(
            'INSERT INTO users (username, password_hash) VALUES (?, ?)',
            (app.config['ADMIN_USERNAME'], password_hash)
        )

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
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    c = conn.cursor()
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

    conn = sqlite3.connect(app.config['DATABASE_PATH'])
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

        sanitized_review_text = bleach.clean(review_text, strip=True)

        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        c = conn.cursor()
        c.execute(
            'INSERT INTO reviews (date, rating, review_text) VALUES (?, ?, ?)',
            (date, rating, sanitized_review_text)
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
def register():
    """Self-service registration for new firms (free trial)."""
    if current_user.is_authenticated:
        return redirect(url_for('upload'))

    if request.method == 'POST':
        firm_name = request.form.get('firm_name') or app.config['FIRM_NAME']
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            flash('Email and password are required.', 'danger')
            return redirect(url_for('register'))

        conn = sqlite3.connect(app.config['DATABASE_PATH'])
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
                subscription_type
            )
            VALUES (?, ?, ?, ?, 0, 0, ?, 'trial', 'trial')
            ''',
            (
                email,
                email,
                firm_name,
                password_hash,
                app.config['FREE_TRIAL_LIMIT'],
            ),
        )
        user_id = c.lastrowid
        conn.commit()
        conn.close()

        user = User(
            id=user_id,
            username=email,
            email=email,
            firm_name=firm_name,
            is_admin=False,
            subscription_status='trial',
            trial_reviews_used=0,
            trial_limit=app.config['FREE_TRIAL_LIMIT'],
            one_time_reports_purchased=0,
            one_time_reports_used=0,
            subscription_type='trial',
        )
        login_user(user)
        flash('Account created. Welcome to your free trial!', 'success')
        return redirect(url_for('upload'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per 15 minutes')
def login():
    """Login page for firm administrators and trial accounts."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # Identifier may be email address or legacy username
        identifier = request.form.get('username')
        password = request.form.get('password')

        conn = sqlite3.connect(app.config['DATABASE_PATH'])
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

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    """Admin logout"""
    logout_user()
    flash('You have been signed out.', 'info')
    return redirect(url_for('marketing_home'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Password reset request page."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if email:
            conn = sqlite3.connect(app.config['DATABASE_PATH'])
            c = conn.cursor()
            c.execute('SELECT id FROM users WHERE email = ? OR username = ?', (email, email))
            user_row = c.fetchone()
            conn.close()
            # Always show the same message to prevent email enumeration
            if user_row:
                import secrets as _secrets
                token = _secrets.token_urlsafe(32)
                conn = sqlite3.connect(app.config['DATABASE_PATH'])
                c = conn.cursor()
                # Store token — add column if not present
                try:
                    c.execute('ALTER TABLE users ADD COLUMN reset_token TEXT')
                    c.execute('ALTER TABLE users ADD COLUMN reset_token_expiry TEXT')
                except Exception:
                    pass
                from datetime import timedelta
                expiry = (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
                c.execute(
                    'UPDATE users SET reset_token = ?, reset_token_expiry = ? WHERE id = ?',
                    (token, expiry, user_row[0]),
                )
                conn.commit()
                conn.close()
                # In production, email the link. For now, flash it for development.
                reset_link = url_for('reset_password', token=token, _external=True)
                flash(
                    f'If that email exists, a reset link has been sent. '
                    f'(Dev mode: <a href="{reset_link}">click here</a>)',
                    'info',
                )
            else:
                flash('If that email exists, a reset link has been sent.', 'info')
        return redirect(url_for('login'))

    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Password reset form (linked from email)."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    c = conn.cursor()
    try:
        c.execute(
            'SELECT id, reset_token_expiry FROM users WHERE reset_token = ?',
            (token,),
        )
    except Exception:
        conn.close()
        flash('This reset link is invalid or has expired.', 'danger')
        return redirect(url_for('forgot_password'))

    row = c.fetchone()
    conn.close()

    if not row:
        flash('This reset link is invalid or has expired.', 'danger')
        return redirect(url_for('forgot_password'))

    user_id, expiry_str = row
    try:
        expiry = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
        if datetime.now() > expiry:
            flash('This reset link has expired. Please request a new one.', 'danger')
            return redirect(url_for('forgot_password'))
    except Exception:
        flash('This reset link is invalid.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return render_template('reset_password.html', token=token)

        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token)

        new_hash = generate_password_hash(password)
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        c = conn.cursor()
        c.execute(
            'UPDATE users SET password_hash = ?, reset_token = NULL, reset_token_expiry = NULL WHERE id = ?',
            (new_hash, user_id),
        )
        conn.commit()
        conn.close()
        flash('Password updated successfully. Please sign in.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)


@app.route('/export-data')
@login_required
def export_data():
    """Export the current user's review data as a CSV download."""
    import io as _io
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    c = conn.cursor()
    c.execute('SELECT date, rating, review_text, created_at FROM reviews ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()

    output = _io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['date', 'rating', 'review_text', 'created_at'])
    for row in rows:
        writer.writerow(row)
    output.seek(0)

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=my_reviews_{datetime.now().strftime("%Y%m%d")}.csv'
        },
    )

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

    conn = sqlite3.connect(app.config['DATABASE_PATH'])
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
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    c = conn.cursor()
    c.execute('DELETE FROM reviews')
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
def create_onetime_checkout():
    """Create Stripe Checkout session for one-time report purchase."""
    try:
        # Ensure Stripe customer exists
        if not current_user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_user.email or current_user.username,
                metadata={'user_id': current_user.id},
            )
            conn = sqlite3.connect(app.config['DATABASE_PATH'])
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
def onetime_success():
    """Handle successful one-time payment and grant a report credit."""
    session_id = request.args.get('session_id')
    if not session_id:
        flash('The payment session could not be found. Please start a new payment.', 'danger')
        return redirect(url_for('buy_one_time'))

    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)

        if checkout_session.payment_status == 'paid':
            conn = sqlite3.connect(app.config['DATABASE_PATH'])
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
            conn = sqlite3.connect(app.config['DATABASE_PATH'])
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
def subscription_success():
    """Handle successful subscription and mark account as active."""
    session_id = request.args.get('session_id')
    plan = request.args.get('plan', 'monthly')

    if not session_id:
        flash('The subscription session could not be found. Please start a new subscription.', 'danger')
        return redirect(url_for('subscribe'))

    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)

        conn = sqlite3.connect(app.config['DATABASE_PATH'])
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
def upload():
    """CSV upload page for bulk review import with tiered limits."""
    account_status = current_user.get_account_status()
    can_upload = current_user.can_generate_report()

    if request.method == 'POST':
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

            conn = sqlite3.connect(app.config['DATABASE_PATH'])
            c = conn.cursor()

            count = 0
            for row in reader:
                if row['date'] and row['rating'] and row['review_text']:
                    try:
                        rating = int(row['rating'])
                        if 1 <= rating <= 5:
                            c.execute(
                                'INSERT INTO reviews (date, rating, review_text) VALUES (?, ?, ?)',
                                (row['date'], rating, bleach.clean(row['review_text'], strip=True))
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

            conn = sqlite3.connect(app.config['DATABASE_PATH'])
            c = conn.cursor()

            # Update usage counters only after report snapshot is saved
            if current_user.has_active_subscription():
                report_type = current_user.subscription_type
            elif current_user.has_unused_one_time_reports():
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
    is_paid_user = current_user.has_active_subscription() or current_user.has_unused_one_time_reports()
    subscription_type = (
        current_user.subscription_type
        if current_user.has_active_subscription()
        else ('onetime' if current_user.has_unused_one_time_reports() else 'trial')
    )

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
def download_report(report_id):
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
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
    is_paid_user = current_user.has_active_subscription() or current_user.has_unused_one_time_reports()
    subscription_type = (
        current_user.subscription_type
        if current_user.has_active_subscription()
        else ('onetime' if current_user.has_unused_one_time_reports() else 'trial')
    )

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
    )

# ===== ERROR HANDLERS =====

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
