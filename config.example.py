import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    
    # Stripe Configuration
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')
    
    # Stripe Price IDs
    STRIPE_PRICE_ID_ONETIME = os.environ.get('STRIPE_PRICE_ID_ONETIME')
    STRIPE_PRICE_ID_MONTHLY = os.environ.get('STRIPE_PRICE_ID_MONTHLY')
    STRIPE_PRICE_ID_ANNUAL = os.environ.get('STRIPE_PRICE_ID_ANNUAL')
    
    # Pricing
    FREE_TRIAL_LIMIT = 3
    ONETIME_REPORT_PRICE = 49
    MONTHLY_SUBSCRIPTION_PRICE = 129
    ANNUAL_SUBSCRIPTION_PRICE = 1290
