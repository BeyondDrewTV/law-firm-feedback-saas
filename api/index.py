"""
Vercel serverless entry point for Law Firm Insights.

NOTE ON SQLITE + VERCEL:
Vercel's serverless functions use an ephemeral (read-only) filesystem except
for /tmp. This means SQLite writes WILL NOT persist between function invocations
on Vercel's free tier. For production use on Vercel you have two options:

  Option A (recommended): Migrate to Supabase Postgres
    - Create a Supabase project at supabase.com (free tier: 500 MB)
    - Replace sqlite3 calls in app.py with psycopg2 / SQLAlchemy
    - Set DATABASE_URL env var in Vercel dashboard
    - See: https://supabase.com/docs/guides/database/connecting-to-postgres

  Option B (quick test only): Use /tmp for SQLite
    - Set DATABASE_PATH=/tmp/feedback.db in Vercel env vars
    - Data is lost on cold starts — NOT suitable for production
    - Fine for evaluating the UI / flow during development

For non-serverless deploys (Railway, Render, Fly.io, VPS):
  - SQLite works fine with persistent disk
  - Just deploy as a standard Flask app with gunicorn
  - See DEPLOYMENT.md for Railway 3-step instructions
"""

import sys
import os

# Make the project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the Flask app object
from app import app

# Vercel expects a handler named `app` at module level
# The @vercel/python runtime calls app(environ, start_response) directly
