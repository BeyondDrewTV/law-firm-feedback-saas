import os
import csv
from io import StringIO, BytesIO
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
import stripe
from config import Config

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Initialize Stripe
stripe.api_key = app.config['STRIPE_SECRET_KEY']

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ===== DATABASE INITIALIZATION =====
def init_db():
    """Initialize database with support for 3-tier pricing model"""
    conn = sqlite3.connect('lawfirm_feedback.db')
    c = conn.cursor()
    
    # Check existing columns
    c.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in c.fetchall()]
    
    # Create users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            firm_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            subscription_status TEXT DEFAULT 'trial',
            trial_reviews_used INTEGER DEFAULT 0,
            trial_limit INTEGER DEFAULT 10,
            one_time_reports_purchased INTEGER DEFAULT 0,
            one_time_reports_used INTEGER DEFAULT 0
        )
    ''')
    
    # Add new columns if upgrading existing database
    if 'one_time_reports_purchased' not in columns:
        try:
            c.execute('ALTER TABLE users ADD COLUMN one_time_reports_purchased INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
    
    if 'one_time_reports_used' not in columns:
        try:
            c.execute('ALTER TABLE users ADD COLUMN one_time_reports_used INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
    
    # Create reports table
    c.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            review_count INTEGER,
            avg_rating REAL,
            report_type TEXT DEFAULT 'trial',
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

# ===== USER CLASS WITH 3-TIER PRICING LOGIC =====
class User(UserMixin):
    """User model with 3-tier pricing support"""
    def __init__(self, id, email, firm_name, stripe_customer_id=None, 
                 stripe_subscription_id=None, subscription_status='trial',
                 trial_reviews_used=0, trial_limit=10,
                 one_time_reports_purchased=0, one_time_reports_used=0):
        self.id = id
        self.email = email
        self.firm_name = firm_name
        self.stripe_customer_id = stripe_customer_id
        self.stripe_subscription_id = stripe_subscription_id
        self.subscription_status = subscription_status
        self.trial_reviews_used = trial_reviews_used
        self.trial_limit = trial_limit
        self.one_time_reports_purchased = one_time_reports_purchased
        self.one_time_reports_used = one_time_reports_used
    
    def has_active_subscription(self):
        """Check if user has active $99/month subscription"""
        return self.subscription_status == 'active'
    
    def has_unused_one_time_reports(self):
        """Check if user has unused $39 one-time reports"""
        return self.one_time_reports_purchased > self.one_time_reports_used
    
    def get_remaining_one_time_reports(self):
        """Get number of remaining one-time reports"""
        return max(0, self.one_time_reports_purchased - self.one_time_reports_used)
    
    def is_trial_expired(self):
        """Check if free trial is expired"""
        return self.trial_reviews_used >= self.trial_limit
    
    def get_remaining_trial_reports(self):
        """Get number of remaining trial reports"""
        return max(0, self.trial_limit - self.trial_reviews_used)
    
    def can_generate_report(self):
        """
        Check if user can generate a report (3-tier logic):
        1. Active subscription ($99/month) → unlimited
        2. Unused one-time reports ($39 each) → use one
        3. Trial not expired (10 free) → use one
        """
        return (self.has_active_subscription() or 
                self.has_unused_one_time_reports() or 
                not self.is_trial_expired())
    
    def get_account_status(self):
        """Get user's current account status for display"""
        if self.has_active_subscription():
            return {
                'type': 'subscription',
                'display': 'Unlimited Reports (Monthly Subscription)',
                'remaining': None,
                'badge_color': 'success'
            }
        elif self.has_unused_one_time_reports():
            remaining = self.get_remaining_one_time_reports()
            return {
                'type': 'one_time',
                'display': f'One-Time Reports: {remaining} remaining',
                'remaining': remaining,
                'badge_color': 'primary'
            }
        else:
            remaining = self.get_remaining_trial_reports()
            return {
                'type': 'trial',
                'display': f'Free Trial: {remaining}/{self.trial_limit} remaining',
                'remaining': remaining,
                'badge_color': 'warning' if remaining > 0 else 'danger'
            }

@login_manager.user_loader
def load_user(user_id):
    """Load user from database"""
    conn = sqlite3.connect('lawfirm_feedback.db')
    c = conn.cursor()
    c.execute('''SELECT id, email, firm_name, stripe_customer_id, stripe_subscription_id, 
                 subscription_status, trial_reviews_used, trial_limit,
                 one_time_reports_purchased, one_time_reports_used 
                 FROM users WHERE id = ?''', (user_id,))
    user_data = c.fetchone()
    conn.close()
    
    if user_data:
        return User(*user_data)
    return None

# ===== THEME ANALYSIS (Unchanged) =====
THEMES = {
    'Communication': ['communication', 'responsive', 'returned calls', 'kept me informed', 'updates', 
                     'contact', 'reachable', 'available', 'prompt', 'timely'],
    'Professionalism': ['professional', 'courteous', 'respectful', 'polite', 'demeanor', 
                       'conduct', 'manner', 'appropriate', 'ethical'],
    'Legal Expertise': ['knowledgeable', 'experienced', 'expert', 'skilled', 'competent', 
                       'qualified', 'expertise', 'understanding of law', 'legal knowledge'],
    'Case Outcome': ['won', 'successful', 'settlement', 'verdict', 'result', 'outcome', 
                    'resolved', 'dismissed', 'favorable'],
    'Cost/Value': ['expensive', 'affordable', 'fees', 'billing', 'cost', 'worth it', 
                  'value', 'money', 'price', 'rates'],
    'Staff/Support': ['staff', 'assistant', 'paralegal', 'secretary', 'team', 'office', 
                     'support staff', 'helpful staff'],
    'Responsiveness': ['quick', 'slow', 'delayed', 'waiting', 'took forever', 'immediately', 
                      'right away', 'promptly'],
    'Compassion': ['caring', 'understanding', 'empathetic', 'compassionate', 'listened', 
                  'sympathetic', 'supportive'],
    'Clarity': ['explained', 'clear', 'confusing', 'understood', 'guidance', 'direction', 
               'straightforward', 'complicated'],
    'Recommendation': ['recommend', 'refer', 'hire again', 'use again', 'best lawyer', 
                      'highly recommend', 'would not recommend']
}

def analyze_reviews(reviews):
    """Analyze reviews and extract themes"""
    total_reviews = len(reviews)
    ratings = [float(r['rating']) for r in reviews if r['rating']]
    avg_rating = sum(ratings) / len(ratings) if ratings else 0
    
    theme_counts = {theme: 0 for theme in THEMES}
    theme_examples = {theme: [] for theme in THEMES}
    
    for review in reviews:
        text = review['review_text'].lower()
        for theme, keywords in THEMES.items():
            for keyword in keywords:
                if keyword in text:
                    theme_counts[theme] += 1
                    if len(theme_examples[theme]) < 3:
                        theme_examples[theme].append(review['review_text'][:200])
                    break
    
    sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
    low_rating_reviews = [r for r in reviews if float(r['rating']) <= 3]
    high_rating_reviews = [r for r in reviews if float(r['rating']) >= 4]
    
    return {
        'total_reviews': total_reviews,
        'avg_rating': round(avg_rating, 2),
        'theme_counts': dict(sorted_themes),
        'theme_examples': theme_examples,
        'top_complaints': low_rating_reviews[:5],
        'top_praise': high_rating_reviews[:5],
        'sorted_themes': sorted_themes[:5]
    }

def generate_pdf_report(results, firm_name):
    """Generate PDF report"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a365d'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#2c5282'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    story.append(Paragraph(f"Client Feedback Report - {firm_name}", title_style))
    story.append(Spacer(1, 0.3*inch))
    
    story.append(Paragraph("Executive Summary", heading_style))
    overview_data = [
        ['Total Reviews', str(results['total_reviews'])],
        ['Average Rating', f"{results['avg_rating']}/5.0"],
        ['Report Generated', datetime.now().strftime('%B %d, %Y')]
    ]
    overview_table = Table(overview_data, colWidths=[3*inch, 3*inch])
    overview_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f7fafc')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2d3748')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0'))
    ]))
    story.append(overview_table)
    story.append(Spacer(1, 0.3*inch))
    
    story.append(Paragraph("Top Discussion Themes", heading_style))
    theme_data = [['Theme', 'Mentions']]
    for theme, count in results['sorted_themes']:
        theme_data.append([theme, str(count)])
    
    theme_table = Table(theme_data, colWidths=[4*inch, 2*inch])
    theme_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f7fafc')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0'))
    ]))
    story.append(theme_table)
    story.append(Spacer(1, 0.3*inch))
    
    if results['top_praise']:
        story.append(Paragraph("Top Positive Feedback", heading_style))
        for i, review in enumerate(results['top_praise'][:3], 1):
            story.append(Paragraph(f"<b>Review {i}:</b> {review['review_text'][:300]}...", styles['Normal']))
            story.append(Spacer(1, 0.1*inch))
    
    if results['top_complaints']:
        story.append(PageBreak())
        story.append(Paragraph("Areas for Improvement", heading_style))
        for i, review in enumerate(results['top_complaints'][:3], 1):
            story.append(Paragraph(f"<b>Review {i}:</b> {review['review_text'][:300]}...", styles['Normal']))
            story.append(Spacer(1, 0.1*inch))
    
    doc.build(story)
    buffer.seek(0)
    return buffer

# ===== ROUTES =====

@app.route('/')
def index():
    """Homepage with 3-tier pricing"""
    return render_template('index.html',
                         trial_limit=app.config['FREE_TRIAL_LIMIT'],
                         onetime_price=app.config['ONETIME_REPORT_PRICE'],
                         monthly_price=app.config['MONTHLY_SUBSCRIPTION_PRICE'])

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        firm_name = request.form.get('firm_name')
        
        if not all([email, password, firm_name]):
            flash('All fields are required', 'danger')
            return redirect(url_for('register'))
        
        conn = sqlite3.connect('lawfirm_feedback.db')
        c = conn.cursor()
        
        c.execute('SELECT id FROM users WHERE email = ?', (email,))
        if c.fetchone():
            flash('Email already registered', 'danger')
            conn.close()
            return redirect(url_for('login'))
        
        password_hash = generate_password_hash(password)
        c.execute('''INSERT INTO users (email, password_hash, firm_name) 
                    VALUES (?, ?, ?)''', (email, password_hash, firm_name))
        conn.commit()
        conn.close()
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = sqlite3.connect('lawfirm_feedback.db')
        c = conn.cursor()
        c.execute('''SELECT id, email, firm_name, stripe_customer_id, 
                     stripe_subscription_id, subscription_status, trial_reviews_used, trial_limit,
                     one_time_reports_purchased, one_time_reports_used
                     FROM users WHERE email = ?''', (email,))
        user_data = c.fetchone()
        conn.close()
        
        if user_data:
            # Get password hash separately
            conn = sqlite3.connect('lawfirm_feedback.db')
            c = conn.cursor()
            c.execute('SELECT password_hash FROM users WHERE email = ?', (email,))
            password_hash = c.fetchone()[0]
            conn.close()
            
            if check_password_hash(password_hash, password):
                user = User(*user_data)
                login_user(user)
                flash(f'Welcome back, {user.firm_name}!', 'success')
                return redirect(url_for('upload'))
        
        flash('Invalid email or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """User logout"""
    logout_user()
    flash('Logged out successfully', 'info')
    return redirect(url_for('index'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    """
    CSV upload with 3-tier usage logic:
    1. Check if user can generate report
    2. Process CSV
    3. Decrement appropriate counter
    """
    if request.method == 'POST':
        # Check if user can generate report
        if not current_user.can_generate_report():
            flash('You have no reports remaining. Please purchase more.', 'warning')
            return redirect(url_for('index'))
        
        if 'file' not in request.files:
            flash('No file uploaded', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(request.url)
        
        if not file.filename.endswith('.csv'):
            flash('Please upload a CSV file', 'danger')
            return redirect(request.url)
        
        try:
            csv_content = file.read().decode('utf-8')
            csv_file = StringIO(csv_content)
            reader = csv.DictReader(csv_file)
            
            reviews = []
            for row in reader:
                if 'date' in row and 'rating' in row and 'review_text' in row:
                    reviews.append(row)
            
            if not reviews:
                flash('CSV must contain columns: date, rating, review_text', 'danger')
                return redirect(request.url)
            
            # Analyze reviews
            results = analyze_reviews(reviews)
            
            # Determine report type and update counters
            conn = sqlite3.connect('lawfirm_feedback.db')
            c = conn.cursor()
            
            if current_user.has_active_subscription():
                report_type = 'subscription'
            elif current_user.has_unused_one_time_reports():
                report_type = 'one_time'
                c.execute('''UPDATE users SET one_time_reports_used = one_time_reports_used + 1 
                            WHERE id = ?''', (current_user.id,))
                current_user.one_time_reports_used += 1
            else:
                report_type = 'trial'
                c.execute('''UPDATE users SET trial_reviews_used = trial_reviews_used + 1 
                            WHERE id = ?''', (current_user.id,))
                current_user.trial_reviews_used += 1
            
            # Save report
            c.execute('''INSERT INTO reports (user_id, review_count, avg_rating, report_type)
                        VALUES (?, ?, ?, ?)''',
                     (current_user.id, results['total_reviews'], results['avg_rating'], report_type))
            
            conn.commit()
            conn.close()
            
            session['report_data'] = results
            flash(f'Report generated successfully!', 'success')
            return redirect(url_for('report'))
            
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'danger')
            return redirect(request.url)
    
    # GET - show upload form with status
    status = current_user.get_account_status()
    return render_template('upload.html', 
                         account_status=status,
                         can_upload=current_user.can_generate_report())

@app.route('/report')
@login_required
def report():
    """Display generated report"""
    results = session.get('report_data')
    if not results:
        flash('No report data available', 'warning')
        return redirect(url_for('upload'))
    
    return render_template('report.html', results=results)

@app.route('/download_pdf')
@login_required
def download_pdf():
    """Download PDF report"""
    results = session.get('report_data')
    if not results:
        flash('No report data available', 'warning')
        return redirect(url_for('upload'))
    
    pdf_file = generate_pdf_report(results, current_user.firm_name)
    return send_file(pdf_file, as_attachment=True, download_name='feedback_report.pdf')

# ===== ONE-TIME PURCHASE ($39) =====

@app.route('/buy-one-time')
@login_required
def buy_one_time():
    """Purchase $39 one-time report"""
    return render_template('buy-one-time.html',
                         price=app.config['ONETIME_REPORT_PRICE'],
                         stripe_publishable_key=app.config['STRIPE_PUBLISHABLE_KEY'])

@app.route('/create-onetime-checkout', methods=['POST'])
@login_required
def create_onetime_checkout():
    """Create Stripe Checkout for $39 one-time payment"""
    try:
        # Create/get Stripe customer
        if not current_user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                metadata={'user_id': current_user.id, 'firm_name': current_user.firm_name}
            )
            
            conn = sqlite3.connect('lawfirm_feedback.db')
            c = conn.cursor()
            c.execute('UPDATE users SET stripe_customer_id = ? WHERE id = ?',
                     (customer.id, current_user.id))
            conn.commit()
            conn.close()
            customer_id = customer.id
        else:
            customer_id = current_user.stripe_customer_id
        
        # Get or create one-time price
        price_id = app.config.get('STRIPE_ONETIME_PRICE_ID')
        
        if not price_id:
            # Create product and price dynamically
            products = stripe.Product.list(limit=100)
            onetime_product = None
            for product in products.data:
                if product.name == 'Law Firm Feedback - One-Time Report':
                    onetime_product = product
                    break
            
            if not onetime_product:
                onetime_product = stripe.Product.create(
                    name='Law Firm Feedback - One-Time Report',
                    description='Single client feedback analysis report'
                )
            
            price = stripe.Price.create(
                product=onetime_product.id,
                unit_amount=app.config['ONETIME_REPORT_PRICE'] * 100,
                currency='usd'
            )
            price_id = price.id
        
        # Create checkout session (ONE-TIME payment)
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='payment',  # ONE-TIME
            success_url=url_for('onetime_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('buy_one_time', _external=True),
        )
        
        return redirect(checkout_session.url, code=303)
    
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('buy_one_time'))

@app.route('/onetime-success')
@login_required
def onetime_success():
    """Handle successful one-time purchase"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        flash('Invalid session', 'danger')
        return redirect(url_for('buy_one_time'))
    
    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        if checkout_session.payment_status == 'paid':
            conn = sqlite3.connect('lawfirm_feedback.db')
            c = conn.cursor()
            c.execute('''UPDATE users 
                        SET one_time_reports_purchased = one_time_reports_purchased + 1
                        WHERE id = ?''', (current_user.id,))
            conn.commit()
            conn.close()
            
            current_user.one_time_reports_purchased += 1
            
            flash(f'Payment successful! You have {current_user.get_remaining_one_time_reports()} report(s) available.', 'success')
            return redirect(url_for('upload'))
        else:
            flash('Payment not completed', 'warning')
            return redirect(url_for('buy_one_time'))
    
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('buy_one_time'))

# ===== MONTHLY SUBSCRIPTION ($99) =====

@app.route('/subscribe')
@login_required
def subscribe():
    """Subscribe to $99/month plan"""
    if current_user.has_active_subscription():
        flash('You already have an active subscription', 'info')
        return redirect(url_for('upload'))
    
    return render_template('subscribe.html', 
                         price=app.config['MONTHLY_SUBSCRIPTION_PRICE'],
                         stripe_publishable_key=app.config['STRIPE_PUBLISHABLE_KEY'])

@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    """Create Stripe Checkout for monthly subscription"""
    try:
        # Create/get Stripe customer
        if not current_user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                metadata={'user_id': current_user.id, 'firm_name': current_user.firm_name}
            )
            
            conn = sqlite3.connect('lawfirm_feedback.db')
            c = conn.cursor()
            c.execute('UPDATE users SET stripe_customer_id = ? WHERE id = ?',
                     (customer.id, current_user.id))
            conn.commit()
            conn.close()
            customer_id = customer.id
        else:
            customer_id = current_user.stripe_customer_id
        
        # Create checkout session (SUBSCRIPTION)
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': app.config['STRIPE_MONTHLY_PRICE_ID'],
                'quantity': 1,
            }],
            mode='subscription',  # RECURRING
            success_url=url_for('subscription_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('subscribe', _external=True),
        )
        
        return redirect(checkout_session.url, code=303)
    
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('subscribe'))

@app.route('/subscription-success')
@login_required
def subscription_success():
    """Handle successful subscription"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        flash('Invalid session', 'danger')
        return redirect(url_for('subscribe'))
    
    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        conn = sqlite3.connect('lawfirm_feedback.db')
        c = conn.cursor()
        c.execute('''UPDATE users 
                    SET stripe_subscription_id = ?, subscription_status = 'active'
                    WHERE id = ?''',
                 (checkout_session.subscription, current_user.id))
        conn.commit()
        conn.close()
        
        current_user.stripe_subscription_id = checkout_session.subscription
        current_user.subscription_status = 'active'
        
        flash('Subscription successful! Unlimited reports now available.', 'success')
        return redirect(url_for('upload'))
    
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('subscribe'))

@app.route('/cancel-subscription', methods=['POST'])
@login_required
def cancel_subscription():
    """Cancel subscription"""
    if not current_user.stripe_subscription_id:
        flash('No active subscription', 'warning')
        return redirect(url_for('upload'))
    
    try:
        stripe.Subscription.delete(current_user.stripe_subscription_id)
        
        conn = sqlite3.connect('lawfirm_feedback.db')
        c = conn.cursor()
        c.execute('''UPDATE users 
                    SET subscription_status = 'trial', stripe_subscription_id = NULL
                    WHERE id = ?''', (current_user.id,))
        conn.commit()
        conn.close()
        
        current_user.subscription_status = 'trial'
        current_user.stripe_subscription_id = None
        
        flash('Subscription cancelled', 'info')
        return redirect(url_for('upload'))
    
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('upload'))

# ===== STRIPE WEBHOOK =====

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle Stripe webhooks"""
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = app.config.get('STRIPE_WEBHOOK_SECRET')
    
    if not webhook_secret:
        return 'Webhook secret not configured', 500
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError:
        return 'Invalid signature', 400
    
    # Handle events
    if event['type'] == 'payment_intent.succeeded':
        print(f"One-time payment succeeded")
    
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        conn = sqlite3.connect('lawfirm_feedback.db')
        c = conn.cursor()
        c.execute('''UPDATE users 
                    SET subscription_status = 'trial', stripe_subscription_id = NULL
                    WHERE stripe_subscription_id = ?''', (subscription['id'],))
        conn.commit()
        conn.close()
    
    elif event['type'] == 'customer.subscription.updated':
        subscription = event['data']['object']
        status = 'active' if subscription['status'] == 'active' else 'trial'
        conn = sqlite3.connect('lawfirm_feedback.db')
        c = conn.cursor()
        c.execute('''UPDATE users 
                    SET subscription_status = ?
                    WHERE stripe_subscription_id = ?''', (status, subscription['id']))
        conn.commit()
        conn.close()
    
    return 'Success', 200

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
