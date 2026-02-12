"""
Configuration classes for Law Firm Feedback Analysis application
Loads settings from environment variables
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration"""

    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY environment variable must be set")

    APP_ENV = os.environ.get('APP_ENV', 'production')
    DEBUG = os.environ.get('FLASK_ENV') == 'development' or os.environ.get('FLASK_DEBUG') == '1'

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '1') == '1'

    # Database
    DATABASE_PATH = os.environ.get('DATABASE_PATH') or 'feedback.db'

    # Admin credentials
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME') or 'admin'
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or 'changeme123'

    # Firm information
    FIRM_NAME = os.environ.get('FIRM_NAME') or 'Law Firm'

    # File upload
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', str(10 * 1024 * 1024)))

    # Stripe configuration
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')

    # Stripe Price IDs
    STRIPE_PRICE_ID_ONETIME = os.environ.get('STRIPE_PRICE_ID_ONETIME')
    STRIPE_PRICE_ID_MONTHLY = os.environ.get('STRIPE_PRICE_ID_MONTHLY')
    STRIPE_PRICE_ID_ANNUAL = os.environ.get('STRIPE_PRICE_ID_ANNUAL')

    # Pricing
    FREE_TRIAL_LIMIT = int(os.environ.get('FREE_TRIAL_LIMIT', 3))
    ONETIME_REPORT_PRICE = int(os.environ.get('ONETIME_REPORT_PRICE', 49))
    MONTHLY_SUBSCRIPTION_PRICE = int(os.environ.get('MONTHLY_SUBSCRIPTION_PRICE', 129))
    ANNUAL_SUBSCRIPTION_PRICE = int(os.environ.get('ANNUAL_SUBSCRIPTION_PRICE', 1290))

    # Mail configuration
    MAIL_ENABLED = os.environ.get('MAIL_ENABLED', '0') == '1'
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.sendgrid.net')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', '587'))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', '1') == '1'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', '0') == '1'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'no-reply@example.com')
    MAIL_MAX_RETRIES = int(os.environ.get('MAIL_MAX_RETRIES', '3'))

    # Monitoring / logging
    SENTRY_DSN = os.environ.get('SENTRY_DSN')
    SENTRY_TRACES_SAMPLE_RATE = float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.1'))
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_DIR = os.environ.get('LOG_DIR', 'logs')
