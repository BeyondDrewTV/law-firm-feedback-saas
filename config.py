import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Application configuration"""
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database
    DATABASE_URL = os.environ.get('DATABASE_URL') or 'sqlite:///lawfirm_feedback.db'
    
    # Stripe Configuration
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
    STRIPE_MONTHLY_PRICE_ID = os.environ.get('STRIPE_MONTHLY_PRICE_ID')
    STRIPE_ONETIME_PRICE_ID = os.environ.get('STRIPE_ONETIME_PRICE_ID')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')
    
    # Pricing
    FREE_TRIAL_LIMIT = int(os.environ.get('FREE_TRIAL_LIMIT', 10))
    ONETIME_REPORT_PRICE = int(os.environ.get('ONETIME_REPORT_PRICE', 39))
    MONTHLY_SUBSCRIPTION_PRICE = int(os.environ.get('MONTHLY_SUBSCRIPTION_PRICE', 99))
    
    # File Upload
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB max file size
