"""
Configuration classes for Law Firm Feedback Analysis application
Loads settings from environment variables
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Application configuration"""
    
    # Flask
    # SECRET_KEY must be provided via environment for production security
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY environment variable must be set")
    DEBUG = os.environ.get('FLASK_ENV') == 'development'
    
    # Database
    DATABASE_PATH = os.environ.get('DATABASE_PATH') or 'feedback.db'
    
    # Admin credentials
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME') or 'admin'
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or 'changeme123'
    
    # Firm information
    FIRM_NAME = os.environ.get('FIRM_NAME') or 'Law Firm'
    
    # File upload
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB max file size

    # Stripe configuration
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')

    # Stripe Price IDs
    STRIPE_PRICE_ID_ONETIME = os.environ.get('STRIPE_PRICE_ID_ONETIME')
    STRIPE_PRICE_ID_MONTHLY = os.environ.get('STRIPE_PRICE_ID_MONTHLY')
    STRIPE_PRICE_ID_ANNUAL = os.environ.get('STRIPE_PRICE_ID_ANNUAL')

    # Pricing - UPDATED TO MATCH NEW SELF-SERVICE MODEL
    FREE_TRIAL_LIMIT = int(os.environ.get('FREE_TRIAL_LIMIT', 3))
    ONETIME_REPORT_PRICE = int(os.environ.get('ONETIME_REPORT_PRICE', 49))
    MONTHLY_SUBSCRIPTION_PRICE = int(os.environ.get('MONTHLY_SUBSCRIPTION_PRICE', 129))
    ANNUAL_SUBSCRIPTION_PRICE = int(os.environ.get('ANNUAL_SUBSCRIPTION_PRICE', 1290))
