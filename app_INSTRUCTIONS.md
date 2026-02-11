# APP.PY UPDATES REQUIRED

Your current app.py needs these updates to support all 4 pricing tiers:

## 1. Update Database Schema (init_db function)

Change trial_limit from 10 to 3:
```python
trial_limit INTEGER DEFAULT 3
```

Add new columns:
```python
one_time_reports_purchased INTEGER DEFAULT 0,
one_time_reports_used INTEGER DEFAULT 0,
subscription_type TEXT DEFAULT 'trial'
```

Add migration code to update existing database:
```python
c.execute("PRAGMA table_info(users)")
columns = [col[1] for col in c.fetchall()]

if 'one_time_reports_purchased' not in columns:
    c.execute('ALTER TABLE users ADD COLUMN one_time_reports_purchased INTEGER DEFAULT 0')
if 'one_time_reports_used' not in columns:
    c.execute('ALTER TABLE users ADD COLUMN one_time_reports_used INTEGER DEFAULT 0')
if 'subscription_type' not in columns:
    c.execute('ALTER TABLE users ADD COLUMN subscription_type TEXT DEFAULT "trial"')

# Update existing users
c.execute('UPDATE users SET trial_limit = 3 WHERE trial_limit = 10')
```

## 2. Update User Class

Add new attributes to __init__:
```python
def __init__(self, id, email, firm_name, stripe_customer_id=None, 
             stripe_subscription_id=None, subscription_status='trial',
             trial_reviews_used=0, trial_limit=3,
             one_time_reports_purchased=0, one_time_reports_used=0,
             subscription_type='trial'):
    # ... existing code ...
    self.one_time_reports_purchased = one_time_reports_purchased
    self.one_time_reports_used = one_time_reports_used
    self.subscription_type = subscription_type
```

Add new methods:
```python
def has_unused_one_time_reports(self):
    return self.one_time_reports_purchased > self.one_time_reports_used

def get_remaining_one_time_reports(self):
    return max(0, self.one_time_reports_purchased - self.one_time_reports_used)

def can_generate_report(self):
    # Priority: subscription → one-time → trial
    return (self.has_active_subscription() or 
            self.has_unused_one_time_reports() or 
            not self.is_trial_expired())

def get_account_status(self):
    if self.has_active_subscription():
        return {
            'type': self.subscription_type,
            'display': f'Unlimited ({self.subscription_type.title()} Subscription)',
            'remaining': None
        }
    elif self.has_unused_one_time_reports():
        remaining = self.get_remaining_one_time_reports()
        return {
            'type': 'onetime',
            'display': f'One-Time Reports: {remaining} remaining',
            'remaining': remaining
        }
    else:
        remaining = self.trial_limit - self.trial_reviews_used
        return {
            'type': 'trial',
            'display': f'Free Trial: {remaining}/{self.trial_limit} remaining',
            'remaining': remaining
        }
```

## 3. Update load_user function

Add new columns to SELECT:
```python
c.execute('''SELECT id, email, firm_name, stripe_customer_id, stripe_subscription_id, 
             subscription_status, trial_reviews_used, trial_limit,
             one_time_reports_purchased, one_time_reports_used, subscription_type 
             FROM users WHERE id = ?''', (user_id,))
```

## 4. Add New Routes

### /buy-one-time
```python
@app.route('/buy-one-time')
@login_required
def buy_one_time():
    return render_template('buy-one-time.html',
                         price=app.config['ONETIME_REPORT_PRICE'],
                         stripe_publishable_key=app.config['STRIPE_PUBLISHABLE_KEY'])
```

### /create-onetime-checkout
```python
@app.route('/create-onetime-checkout', methods=['POST'])
@login_required
def create_onetime_checkout():
    try:
        if not current_user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                metadata={'user_id': current_user.id}
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
        
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': app.config['STRIPE_PRICE_ID_ONETIME'],
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
```

### /onetime-success
```python
@app.route('/onetime-success')
@login_required
def onetime_success():
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
            
            flash('Payment successful! You have 1 report available.', 'success')
            return redirect(url_for('upload'))
        else:
            flash('Payment not completed', 'warning')
            return redirect(url_for('buy_one_time'))
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('buy_one_time'))
```

### /create-subscription-checkout (UPDATE EXISTING)
```python
@app.route('/create-subscription-checkout', methods=['POST'])
@login_required
def create_subscription_checkout():
    plan = request.form.get('plan', 'monthly')  # 'monthly' or 'annual'
    
    # Select the correct Price ID
    if plan == 'annual':
        price_id = app.config['STRIPE_PRICE_ID_ANNUAL']
    else:
        price_id = app.config['STRIPE_PRICE_ID_MONTHLY']
    
    try:
        if not current_user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                metadata={'user_id': current_user.id}
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
        
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',  # RECURRING
            success_url=url_for('subscription_success', _external=True) + f'?session_id={{CHECKOUT_SESSION_ID}}&plan={plan}',
            cancel_url=url_for('subscribe', _external=True),
        )
        
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('subscribe'))
```

### /subscription-success (UPDATE)
```python
@app.route('/subscription-success')
@login_required
def subscription_success():
    session_id = request.args.get('session_id')
    plan = request.args.get('plan', 'monthly')
    
    if not session_id:
        flash('Invalid session', 'danger')
        return redirect(url_for('subscribe'))
    
    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        conn = sqlite3.connect('lawfirm_feedback.db')
        c = conn.cursor()
        c.execute('''UPDATE users 
                    SET stripe_subscription_id = ?, 
                        subscription_status = 'active',
                        subscription_type = ?
                    WHERE id = ?''',
                 (checkout_session.subscription, plan, current_user.id))
        conn.commit()
        conn.close()
        
        flash(f'Subscription successful! Unlimited reports now available.', 'success')
        return redirect(url_for('upload'))
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('subscribe'))
```

## 5. Update /upload route

Update logic to handle all tiers:
```python
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if not current_user.can_generate_report():
            flash('No reports remaining. Please purchase more.', 'warning')
            return redirect(url_for('index'))
        
        # ... CSV processing ...
        
        # Determine which tier to use
        conn = sqlite3.connect('lawfirm_feedback.db')
        c = conn.cursor()
        
        if current_user.has_active_subscription():
            report_type = current_user.subscription_type
        elif current_user.has_unused_one_time_reports():
            report_type = 'onetime'
            c.execute('UPDATE users SET one_time_reports_used = one_time_reports_used + 1 WHERE id = ?',
                     (current_user.id,))
        else:
            report_type = 'trial'
            c.execute('UPDATE users SET trial_reviews_used = trial_reviews_used + 1 WHERE id = ?',
                     (current_user.id,))
        
        conn.commit()
        conn.close()
        
        # ... save report and redirect ...
    
    status = current_user.get_account_status()
    return render_template('upload.html',
                         account_status=status,
                         can_upload=current_user.can_generate_report())
```

## 6. Update index route

Pass pricing to template:
```python
@app.route('/')
def index():
    return render_template('index.html',
                         trial_limit=app.config['FREE_TRIAL_LIMIT'],
                         onetime_price=app.config['ONETIME_REPORT_PRICE'],
                         monthly_price=app.config['MONTHLY_SUBSCRIPTION_PRICE'],
                         annual_price=app.config['ANNUAL_SUBSCRIPTION_PRICE'])
```

## Implementation Steps

1. Backup your current database: `cp lawfirm_feedback.db lawfirm_feedback.db.backup`
2. Update app.py with all changes above
3. Restart app - database will auto-migrate
4. Test each pricing tier with Stripe test card: 4242 4242 4242 4242

