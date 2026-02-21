# Deployment Guide — Law Firm Insights

## Option 1 — Railway (Recommended — Persistent SQLite, 3 steps)

Railway gives you a persistent disk, so SQLite works out of the box.

```bash
# 1. Install Railway CLI and login
npm install -g @railway/cli && railway login

# 2. Create project and deploy
railway init
railway up

# 3. Set environment variables in Railway dashboard
#    (Project → Variables → Add All)
SECRET_KEY=<64-char-random-string>
STRIPE_SECRET_KEY=sk_live_xxx
STRIPE_PUBLISHABLE_KEY=pk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_PRICE_ID_MONTHLY=price_xxx
STRIPE_PRICE_ID_ANNUAL=price_xxx
STRIPE_PRICE_ID_ONETIME=price_xxx
ADMIN_EMAIL=you@yourdomain.com
ADMIN_PASSWORD=<strong-password>
SESSION_COOKIE_SECURE=1
```

Railway auto-detects the `gunicorn.conf.py` and starts with Gunicorn.
Your app will be live at `https://your-project.up.railway.app` in ~2 minutes.

---

## Option 2 — Vercel (Serverless — requires Postgres migration for persistence)

⚠️ Vercel's filesystem is read-only. SQLite writes won't persist.
For a quick UI preview it works. For production, set up Supabase first.

```bash
# Prerequisites: Supabase project created, DATABASE_URL ready

# 1. Install Vercel CLI
npm install -g vercel

# 2. Deploy
vercel --prod

# 3. Set env vars in Vercel dashboard (Settings → Environment Variables)
#    Add the same variables as Railway above, plus:
DATABASE_PATH=/tmp/feedback.db   # temp only — use Supabase for real persistence
```

---

## Option 3 — Render (Original host — reduce cold starts)

Cold starts happen on Render's free tier because containers spin down after 15min.
Upgrade to Render's $7/month "Starter" plan to keep the container warm.

Or set a health check ping (e.g., UptimeRobot → ping /health every 10 min).

---

## Stripe Webhook Setup

After deploying, update your Stripe webhook endpoint:

1. Go to Stripe Dashboard → Developers → Webhooks
2. Click "Add endpoint"
3. URL: `https://your-domain.com/stripe-webhook`
4. Events to listen for:
   - `customer.subscription.deleted`
   - `customer.subscription.updated`
   - `checkout.session.completed`
5. Copy the webhook signing secret → set as `STRIPE_WEBHOOK_SECRET`

---

## Environment Variables Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `SECRET_KEY` | Flask session secret (64+ chars, random) | `openssl rand -hex 32` |
| `STRIPE_SECRET_KEY` | Stripe live secret key | `sk_live_...` |
| `STRIPE_PUBLISHABLE_KEY` | Stripe publishable key | `pk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret | `whsec_...` |
| `STRIPE_PRICE_ID_MONTHLY` | Monthly plan price ID | `price_...` |
| `STRIPE_PRICE_ID_ANNUAL` | Annual plan price ID | `price_...` |
| `STRIPE_PRICE_ID_ONETIME` | One-time report price ID | `price_...` |
| `ADMIN_EMAIL` | Admin account email | `admin@yourdomain.com` |
| `ADMIN_PASSWORD` | Admin account password | strong password |
| `DATABASE_PATH` | SQLite file path | `feedback.db` |
| `SESSION_COOKIE_SECURE` | Enforce HTTPS cookies | `1` |
| `MAIL_ENABLED` | Enable email sending | `1` |
| `MAIL_SERVER` | SMTP server | `smtp.sendgrid.net` |
| `MAIL_PASSWORD` | SMTP password / API key | SendGrid API key |
